def verifiy_media(body: dict) -> dict[str, str]:
    event_data = body.get("data")
    message_id = event_data["key"]["id"]
    phone_send = event_data["key"]["participantAlt"] if event_data["key"].get("participantAlt") else event_data["key"].get("remoteJidAlt")
    message_type = event_data["messageType"]

    audio_message = True if message_type == "audioMessage" else False
    image_message = True if message_type == "imageMessage" else False
    video_message = True if message_type == "videoMessage" else False

    context_info = event_data.get("contextInfo") if event_data.get("contextInfo") is not None else {}
    if not context_info:
        raw_context_info = (event_data.get("message", {})
            .get("ephemeralMessage", {})
            .get("message", {})
            .get("extendedTextMessage", {})
            .get("contextInfo")
                        )
        context_info = raw_context_info if raw_context_info else {}

    quoted_id = context_info.get("stanzaId")

    image_quote = context_info.get("quotedMessage", {}).get("imageMessage")
    if not image_quote:
        image_quote = (
            context_info
            .get("quotedMessage", {})
            .get("ephemeralMessage", {})
            .get("message", {})
            .get("imageMessage")
        )

    video_quote = context_info.get("quotedMessage", {}).get("videoMessage")
    if not video_quote:
        image_quote = (
            context_info
            .get("quotedMessage", {})
            .get("ephemeralMessage", {})
            .get("message", {})
            .get("videoMessage")
        )

    caption = context_info.get('imageMessage', {}).get('caption', '')
    if not caption:
        context_info.get('videoMessage', {}).get('caption', '')

    conversation = caption if caption else event_data["message"].get("conversation", "")

    if not conversation:
        conversation = (
            event_data["message"]
            .get("ephemeralMessage", {})
            .get("message", {})
            .get("extendedTextMessage", {})
            .get("text", "")
        )
        if not conversation:
            conversation = event_data["message"].get("videoMessage", {}).get("caption", "")

    text_quote = context_info.get("quotedMessage", {}).get("conversation")
    if not text_quote:
        text_quote = (
            context_info
            .get("quotedMessage", {})
            .get("ephemeralMessage", {})
            .get("message", {})
            .get("extendedTextMessage", {})
            .get("text")
        )

    audio_quote = context_info.get("quotedMessage", {}).get("audioMessage")
    if not audio_quote:
        audio_quote = (
            context_info
            .get("quotedMessage", {})
            .get("ephemeralMessage", {})
            .get("message", {})
            .get("audioMessage")
        )

    mentions: list[str] = context_info.get("mentionedJid", [])
    if not mentions:
        mentions: list[str] = (
            context_info
            .get("ephemeralMessage", {})
            .get("message", {})
            .get("extendedTextMessage", {})
            .get("contextInfo", {})
            .get("mentionedJid", [])
        )

    if conversation:
        if "@me" in conversation:
            mentions.append(phone_send)

    clean_id = lambda t: t.replace("@s.whatsapp.net", "").replace("@lid", "")
    tt_mentions = list(map(clean_id, mentions))

    medias = {}
    if quoted_id:
        medias.update({"quoted_message": quoted_id})
    if conversation:
        medias.update({"text_message": conversation})
    if audio_quote:
        medias.update({"audio_quote": quoted_id})
    if image_quote:
        medias.update({"image_quote": quoted_id})
    if video_quote:
        medias.update({"video_quote": quoted_id})
    if image_message:
        medias.update({"image_message": message_id})
    if audio_message:
        medias.update({"audio_message": message_id})
    if video_message:
        medias.update({"video_message": message_id})
    if text_quote:
        medias.update({"text_quote": (text_quote, quoted_id)})
    if tt_mentions:
        medias.update({"mentions": tt_mentions})

    return medias