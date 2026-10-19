import unittest
from contextlib import ExitStack, nullcontext
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from api.routes.webhook.evolution.processors.group import process_group_message


MODULE = "api.routes.webhook.evolution.processors.group."


class GroupStickerLockTests(unittest.IsolatedAsyncioTestCase):
    async def _process(self, content, *, blocked=False):
        user = SimpleNamespace(id=7)
        group = SimpleNamespace(id=1, name="Grupo", auto_message=False)
        body = {"data": {"key": {"participant": "participant@lid", "id": "command-id"},
                         "pushName": "Nome", "messageTimestamp": 1791577704}}
        with ExitStack() as stack:
            def mock(name, **kwargs):
                return stack.enter_context(patch(MODULE + name, **kwargs))

            mock("is_message_too_old", new=AsyncMock(return_value=False))
            mock("verifiy_media", return_value={"text_message": content})
            user_repo = AsyncMock()
            user_repo.find_by_phone.return_value = None
            user_repo.find_or_create.return_value = user
            mock("UserRepository", return_value=user_repo)
            group_repo = AsyncMock()
            group_repo.find_or_create.return_value = group
            mock("GroupRepository", return_value=group_repo)
            whitelist = AsyncMock()
            whitelist.is_whitelisted.return_value = True
            mock("WhiteListRepository", return_value=whitelist)
            mock("MessageRepository", return_value=AsyncMock())
            mock("save_profile_pic", new=AsyncMock())
            mock("is_feature_blocked", new=AsyncMock(return_value=blocked))
            mock("log_blocked_request", new=AsyncMock())
            send = mock("send_message", new=AsyncMock())
            dispatch = mock("process_commands", new=AsyncMock())
            lock = mock("serialize_group_conversation", return_value=nullcontext())
            if "!sticker" in content:
                lock.side_effect = TimeoutError("conversation lock is still held")
            await process_group_message(body, "group-id", Mock(), Mock())
        return dispatch, lock, send

    async def test_tweet_sticker_runs_even_when_agent_conversation_lock_is_held(self):
        dispatch, lock, _ = await self._process(
            "!sticker :tweet=https://x.com/gdois__/status/2095335085763371454?s=20"
        )
        dispatch.assert_awaited_once()
        lock.assert_not_called()

    async def test_normal_sticker_also_does_not_wait_for_agent(self):
        dispatch, lock, _ = await self._process("!sticker teste")
        dispatch.assert_awaited_once()
        lock.assert_not_called()

    async def test_other_commands_still_use_conversation_lock(self):
        dispatch, lock, _ = await self._process("!resume")
        dispatch.assert_awaited_once()
        lock.assert_called_once_with(1)

    async def test_blocked_sticker_does_not_bypass_access_check(self):
        dispatch, lock, send = await self._process("!sticker :tweet", blocked=True)
        dispatch.assert_not_awaited()
        lock.assert_not_called()
        send.assert_awaited_once()
