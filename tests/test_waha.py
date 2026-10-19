import base64
from copy import deepcopy
import unittest
from unittest.mock import AsyncMock, Mock, patch

import httpx
from fastapi import FastAPI

from api.routes.webhook.waha.normalize import normalize_webhook
from api.routes.webhook.waha.router import background_tasks, router
from api.routes.webhook.waha.services import process_waha_webhook
from external.waha.base import chat_id, request
from external.waha.identifiers import stanza_id, reply_id, sent_response
from external.waha.image import get_profile_info, send_image, send_sticker, send_video
from external.waha.audio import send_audio
from external.waha.media import download_media, file_payload
from external.waha.message import send_message
from external.waha.presence import send_presence
from scripts.waha_session import configure_session, session_config
from services.message_context import verifiy_media


def event(**changes):
    payload = {
        "id": "false_120363123456789012@g.us_MSG_WITH_UNDERSCORES_987654321@lid",
        "timestamp": 1792425600, "from": "120363123456789012@g.us",
        "participant": "987654321@lid", "body": "!status", "fromMe": False,
        "_data": {"Info": {"SenderAlt": "5511999999999@s.whatsapp.net", "PushName": "Ana"}},
    }
    payload.update(changes)
    return {"event": "message.any", "session": "default", "payload": payload}


class WahaNormalizationTests(unittest.TestCase):
    def test_incoming_group_preserves_stanza_lid_phone_name_and_command(self):
        normalized = normalize_webhook(event())
        self.assertEqual(normalized["event"], "messages.upsert")
        data = normalized["data"]
        self.assertEqual(data["key"]["id"], "MSG_WITH_UNDERSCORES")
        self.assertEqual(data["key"]["participantAlt"], "5511999999999@s.whatsapp.net")
        self.assertEqual(data["pushName"], "Ana")
        self.assertEqual(verifiy_media(normalized)["text_message"], "!status")

    def test_native_mentions_quote_and_caption_reach_existing_handlers(self):
        body = event(body="!image @111", _data={"Message": {"imageMessage": {
            "caption": "!image @111", "contextInfo": {
                "mentionedJID": ["111@c.us", "222@lid"], "stanzaID": "OLD_STANZA",
                "quotedMessage": {"imageMessage": {"mimetype": "image/png"}},
            },
        }}})
        original = deepcopy(body)
        context = verifiy_media(normalize_webhook(body))
        self.assertEqual(context["mentions"], ["111", "222"])
        self.assertEqual(context["quoted_message"], "OLD_STANZA")
        self.assertEqual(context["image_quote"], "OLD_STANZA")
        self.assertEqual(context["image_message"], "MSG_WITH_UNDERSCORES")
        self.assertEqual(body, original)

    def test_reply_to_preserves_text_and_stanza_for_historical_lookup(self):
        body = event(replyTo={"id": "true_120363123456789012@g.us_OLD_ID", "body": "resposta do Gork"})
        context = verifiy_media(normalize_webhook(body))
        self.assertEqual(context["text_quote"], ("resposta do Gork", "OLD_ID"))

    def test_outgoing_group_uses_serialized_chat_and_never_runs_commands(self):
        body = event(fromMe=True, **{"from": "5511000000000@c.us", "to": "120363123456789012@g.us"})
        body["payload"]["id"] = "true_120363123456789012@g.us_SENT"
        normalized = normalize_webhook(body)
        self.assertEqual(normalized["event"], "send.message")
        self.assertEqual(normalized["data"]["key"]["remoteJid"], "120363123456789012@g.us")

    def test_private_phone_and_lid_alias_are_kept(self):
        body = event(id="false_555@lid_PRIVATE", **{"from": "555@lid"})
        data = normalize_webhook(body)["data"]
        self.assertEqual(data["key"]["remoteJid"], "555@lid")
        self.assertEqual(data["key"]["remoteJidAlt"], "5511999999999@s.whatsapp.net")

    def test_all_media_kinds_are_preserved_even_without_public_metadata(self):
        for kind in ("image", "sticker", "audio", "video", "document"):
            with self.subTest(kind=kind):
                normalized = normalize_webhook(event(body="", _data={"RawMessage": {kind + "Message": {"mimetype": "test"}}}))
                self.assertEqual(normalized["data"]["messageType"], kind + "Message")
                if kind != "document":
                    self.assertIn(kind + "_message", verifiy_media(normalized))

    def test_public_media_without_native_data_is_classified(self):
        for mime, kind in (("image/png", "image"), ("image/webp", "sticker"), ("audio/ogg", "audio"), ("video/mp4", "video")):
            with self.subTest(mime=mime):
                data = normalize_webhook(event(hasMedia=True, media={"mimetype": mime}))["data"]
                self.assertEqual(data["messageType"], kind + "Message")

    def test_nested_ephemeral_extended_text_and_view_once_quotes(self):
        body = event(body="", _data={"Message": {"ephemeralMessage": {"message": {"extendedTextMessage": {
            "text": "!describe", "contextInfo": {"stanzaID": "PHOTO", "quotedMessage": {
                "viewOnceMessageV2": {"message": {"imageMessage": {"caption": "foto"}}},
            }},
        }}}}})
        context = verifiy_media(normalize_webhook(body))
        self.assertEqual(context["text_message"], "!describe")
        self.assertEqual(context["image_quote"], "PHOTO")

    def test_ignores_broadcasts_newsletters_and_nonmessage_events(self):
        for address in ("status@broadcast", "123@newsletter", "bad"):
            self.assertIsNone(normalize_webhook(event(id="anything", chatId=address)))
        body = event()
        body["event"] = "message.ack"
        self.assertIsNone(normalize_webhook(body))

    def test_missing_timestamp_or_id_is_rejected(self):
        for key in ("id", "timestamp"):
            with self.subTest(key=key):
                body = event()
                body["payload"][key] = None
                with self.assertRaises(ValueError):
                    normalize_webhook(body)

    def test_reply_to_direct_native_media_is_recognized(self):
        body = event(replyTo={"id": "false_111@c.us_PHOTO", "_data": {"imageMessage": {"mimetype": "image/png"}}})
        self.assertEqual(verifiy_media(normalize_webhook(body))["image_quote"], "PHOTO")

    def test_reply_to_public_media_is_recognized(self):
        body = event(replyTo={"id": "false_111@c.us_VOICE", "media": {"mimetype": "audio/ogg"}})
        self.assertEqual(verifiy_media(normalize_webhook(body))["audio_quote"], "VOICE")

    def test_address_and_stanza_conversion(self):
        self.assertEqual(chat_id("5511999999999@s.whatsapp.net"), "5511999999999@c.us")
        self.assertEqual(chat_id("111@lid"), "111@lid")
        self.assertEqual(chat_id("120363123456789012"), "120363123456789012@g.us")
        self.assertEqual(chat_id("123-456"), "123-456@g.us")
        self.assertEqual(stanza_id("true_111@c.us_WITH_UNDERSCORES"), "WITH_UNDERSCORES")
        self.assertEqual(stanza_id("OLD_ID"), "OLD_ID")


class WahaTransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_text_mentions_and_reply_use_waha_contract(self):
        with (
            patch("external.waha.message.request", new=AsyncMock(return_value={"id": "true_111@c.us_SENT"})) as send,
            patch("external.waha.identifiers.reply_id", new=AsyncMock(return_value="false_111@c.us_QUOTE")),
            patch("external.waha.identifiers.save_reference", new=AsyncMock()),
        ):
            result = await send_message("111", "@222 oi", "QUOTE", simulate_typing=False,
                                        mentioned=["222@s.whatsapp.net", "222@s.whatsapp.net", "333@lid"])
        payload = send.await_args.kwargs["payload"]
        self.assertEqual(send.await_args.args, ("POST", "/api/sendText"))
        self.assertEqual(payload["chatId"], "111@c.us")
        self.assertEqual(payload["mentions"], ["222@c.us", "333@lid"])
        self.assertEqual(payload["reply_to"], "false_111@c.us_QUOTE")
        self.assertEqual(result["key"]["id"], "SENT")

    async def test_later_text_chunk_does_not_quote_again(self):
        with (patch("external.waha.message.request", new=AsyncMock(return_value={"id": "true_111@c.us_SENT"})) as send,
              patch("external.waha.identifiers.save_reference", new=AsyncMock())):
            await send_message("111", "second", "QUOTE", is_first=False, simulate_typing=False)
        self.assertNotIn("reply_to", send.await_args.kwargs["payload"])

    async def test_http_failure_raises_before_any_reference_is_saved(self):
        async def handler(req):
            return httpx.Response(401, json={"error": "bad key"})
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        with (patch("external.waha.base.httpx.AsyncClient", return_value=client),
              patch("external.waha.base.waha_api_key", "test-key")):
            with self.assertRaises(httpx.HTTPStatusError):
                await request("POST", "/api/sendText", payload={})

    async def test_request_sends_api_key_and_session_urls(self):
        observed = []
        async def handler(req):
            observed.append(req)
            return httpx.Response(200, json={"id": "sent"})
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        with (patch("external.waha.base.httpx.AsyncClient", return_value=client),
              patch("external.waha.base.waha_api_key", "test-key")):
            await request("GET", "/api/default/chats/111%40c.us/messages/ID", params={"downloadMedia": "true"})
        self.assertEqual(observed[0].headers["X-Api-Key"], "test-key")
        self.assertEqual(observed[0].url.params["downloadMedia"], "true")

    async def test_images_stickers_and_video_use_native_endpoints(self):
        with (patch("external.waha.media.request", new=AsyncMock(return_value={"id": "true_111@c.us_SENT"})) as send,
              patch("external.waha.identifiers.save_reference", new=AsyncMock()),
              patch("external.waha.identifiers.reply_id", new=AsyncMock(return_value="full-quote"))):
            await send_image("111", "aGVsbG8=", filename="test.png", mimetype="image/png", caption="caption")
            self.assertEqual(send.await_args.args[1], "/api/sendImage")
            self.assertEqual(send.await_args.kwargs["payload"]["file"], {"data": "aGVsbG8=", "filename": "test.png", "mimetype": "image/png"})
            await send_sticker("111", "https://storage.test/animated.webp")
            self.assertEqual(send.await_args.args[1], "/api/sendSticker")
            self.assertEqual(send.await_args.kwargs["payload"]["file"]["url"], "https://storage.test/animated.webp")
            await send_video("111", "base64", "QUOTE", caption="video")
            self.assertEqual(send.await_args.args[1], "/api/sendVideo")
            self.assertEqual(send.await_args.kwargs["payload"]["reply_to"], "full-quote")

    async def test_wav_tts_is_sent_as_converted_voice_note(self):
        with (patch("external.waha.audio.send_presence", new=AsyncMock()) as presence,
              patch("external.waha.audio.send_file", new=AsyncMock()) as send):
            await send_audio("111", "aGVsbG8=", "QUOTE")
        self.assertEqual(presence.await_args.args[1], "recording")
        self.assertEqual(send.await_args.args[1], "/api/sendVoice")
        self.assertEqual(send.await_args.args[-2:], ("audio/wav", "QUOTE"))
        self.assertTrue(send.await_args.kwargs["convert"])

    async def test_presence_uses_typing_then_paused_and_local_delay(self):
        with (patch("external.waha.presence.request", new=AsyncMock()) as send,
              patch("external.waha.presence.asyncio.sleep", new=AsyncMock()) as sleep):
            await send_presence("111", "composing", 1500)
        self.assertEqual(send.await_args_list[0].kwargs["payload"]["presence"], "typing")
        self.assertEqual(send.await_args_list[1].kwargs["payload"]["presence"], "paused")
        sleep.assert_awaited_once_with(1.5)

    async def test_media_download_uses_durable_reference_and_authenticated_internal_url(self):
        reference = {"provider_id": "false_111@c.us_PHOTO", "chat_id": "111@c.us",
                     "media": {"url": "http://localhost:3000/api/files/photo.png", "filename": "photo.png"}}
        observed = []
        async def handler(req):
            observed.append(req)
            return httpx.Response(200, content=b"photo-bytes")
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        with (patch("external.waha.media.get_reference", new=AsyncMock(return_value=reference)),
              patch("external.waha.media.httpx.AsyncClient", return_value=client),
              patch("external.waha.media.waha_api_key", "test-key"),
              patch("external.waha.media.waha_api", "http://waha:3000")):
            value, name = await download_media("PHOTO")
        self.assertEqual(base64.b64decode(value), b"photo-bytes")
        self.assertEqual(name, "photo.png")
        self.assertEqual(observed[0].url.host, "waha")
        self.assertEqual(observed[0].headers["X-Api-Key"], "test-key")

    async def test_missing_media_url_is_refetched_by_full_message_id(self):
        reference = {"provider_id": "false_111@c.us_PHOTO", "chat_id": "111@c.us", "media": None}
        media = {"url": "http://waha:3000/api/files/photo.png"}
        with (patch("external.waha.media.get_reference", new=AsyncMock(return_value=reference)),
              patch("external.waha.media.request", new=AsyncMock(return_value={"id": reference["provider_id"], "media": media})) as fetch,
              patch("external.waha.media.save_reference", new=AsyncMock()),
              patch("external.waha.media._download_file", new=AsyncMock(return_value=("base64", "photo.png")))):
            self.assertEqual(await download_media("PHOTO"), ("base64", "photo.png"))
        self.assertIn("false_111%40c.us_PHOTO", fetch.await_args.args[1])
        self.assertEqual(fetch.await_args.kwargs["params"], {"downloadMedia": "true"})

    async def test_reply_reference_survives_worker_restart(self):
        with patch("external.waha.identifiers.get_reference", new=AsyncMock(return_value={"provider_id": "true_111@c.us_OLD"})):
            self.assertEqual(await reply_id("OLD", "111"), "true_111@c.us_OLD")

    async def test_missing_send_id_is_not_reported_as_success(self):
        with self.assertRaises(ValueError):
            await sent_response({"error": "failure"}, "111")

    async def test_profile_picture_uses_waha_contact_address(self):
        with patch("external.waha.image.request", new=AsyncMock(return_value={"profilePictureURL": "https://avatar.test/a.jpg"})) as fetch:
            self.assertEqual((await get_profile_info("111"))["picture"], "https://avatar.test/a.jpg")
        self.assertEqual(fetch.await_args.kwargs["params"]["contactId"], "111@c.us")

    def test_data_url_and_remote_url_file_payloads(self):
        self.assertEqual(file_payload("data:image/png;base64,QUJD", "a.png", "image/jpeg")["mimetype"], "image/png")
        self.assertEqual(file_payload("data:image/png;base64,QUJD", "a.png", "image/jpeg")["data"], "QUJD")


class WahaWebhookTests(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self):
        import asyncio
        pending = list(background_tasks)
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    async def post(self, body, token="token", configured_token="token"):
        app = FastAPI()
        app.include_router(router)
        values = {"WAHA_WEBHOOK_TOKEN": configured_token, "WAHA_SESSION": "default"}
        with patch("api.routes.webhook.waha.router.get_env_var", side_effect=values.get):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                return await client.post("/webhook/waha", json=body, headers={"X-Webhook-Token": token})

    async def test_requires_configured_secret_and_correct_session(self):
        for supplied, configured in (("bad", "token"), ("", "")):
            self.assertEqual((await self.post(event(), supplied, configured)).status_code, 401)
        body = event()
        body["session"] = "other"
        self.assertEqual((await self.post(body)).status_code, 403)

    async def test_authenticated_message_is_dispatched_once(self):
        import asyncio
        with patch("api.routes.webhook.waha.router.process_waha_webhook", new=AsyncMock()) as process:
            response = await self.post(event())
            await asyncio.gather(*list(background_tasks))
        self.assertEqual(response.status_code, 200)
        process.assert_awaited_once()

    async def test_nonmessage_events_are_ignored(self):
        body = event()
        body["event"] = "session.status"
        with patch("api.routes.webhook.waha.router.process_waha_webhook", new=AsyncMock()) as process:
            response = await self.post(body)
        self.assertEqual(response.json()["status"], "ignored")
        process.assert_not_awaited()

    async def test_malformed_message_is_rejected_before_background_dispatch(self):
        body = event(timestamp=None)
        with patch("api.routes.webhook.waha.router.process_waha_webhook", new=AsyncMock()) as process:
            self.assertEqual((await self.post(body)).status_code, 400)
        process.assert_not_awaited()

    async def test_native_quote_without_prior_event_gets_durable_download_reference(self):
        body = event(_data={"Info": {"SenderAlt": "5511@s.whatsapp.net"}, "Message": {
            "extendedTextMessage": {"text": "!describe", "contextInfo": {
                "stanzaID": "OLD", "participant": "999@s.whatsapp.net",
                "quotedMessage": {"imageMessage": {"caption": "foto"}},
            }},
        }})
        body["me"] = {"id": "999@c.us"}
        with (patch("api.routes.webhook.waha.services.get_reference", new=AsyncMock(return_value=None)),
              patch("api.routes.webhook.waha.services.save_reference", new=AsyncMock()) as save,
              patch("api.routes.webhook.waha.services.process_webhook", new=AsyncMock())):
            await process_waha_webhook(body, Mock())
        self.assertEqual(save.await_args_list[1].args[0]["id"], "true_120363123456789012@g.us_OLD")

    async def test_quote_does_not_overwrite_original_full_reference(self):
        body = event(replyTo={"id": "false_111@c.us_OLD"})
        with (patch("api.routes.webhook.waha.services.get_reference", new=AsyncMock(return_value={"provider_id": "true_120363123456789012@g.us_OLD"})),
              patch("api.routes.webhook.waha.services.save_reference", new=AsyncMock()) as save,
              patch("api.routes.webhook.waha.services.process_webhook", new=AsyncMock())):
            await process_waha_webhook(body, Mock())
        self.assertEqual(save.await_count, 1)

    async def test_lid_alias_is_resolved_before_pipeline_and_reference_saved(self):
        body = event(_data={})
        with (patch("api.routes.webhook.waha.services.request", new=AsyncMock(return_value={"pn": "5511999999999@c.us"})),
              patch("api.routes.webhook.waha.services.save_reference", new=AsyncMock()) as save,
              patch("api.routes.webhook.waha.services.process_webhook", new=AsyncMock()) as process):
            await process_waha_webhook(body, Mock())
        self.assertEqual(process.await_args.args[0]["data"]["key"]["participantAlt"], "5511999999999@s.whatsapp.net")
        save.assert_awaited_once_with(body["payload"], "120363123456789012@g.us")

    def test_session_subscribes_only_to_message_any_with_authentication(self):
        config = session_config("http://gork/webhook/waha", "token")
        self.assertEqual(config["webhooks"][0]["events"], ["message.any"])
        self.assertEqual(config["webhooks"][0]["customHeaders"], [{"name": "X-Webhook-Token", "value": "token"}])
        self.assertTrue(config["gows"]["storage"]["messages"])

    async def test_reconfiguring_working_session_does_not_logout_or_restart(self):
        with (patch("scripts.waha_session.request", new=AsyncMock(return_value={"status": "WORKING", "config": {"debug": False}})) as send,
              patch("scripts.waha_session.get_env_var", return_value="token")):
            self.assertEqual(await configure_session("http://gork/webhook/waha"), "WORKING")
        self.assertEqual([call.args[0] for call in send.await_args_list], ["GET", "PUT", "GET"])
        self.assertFalse(send.await_args_list[1].kwargs["payload"]["config"]["debug"])


if __name__ == "__main__":
    unittest.main()
