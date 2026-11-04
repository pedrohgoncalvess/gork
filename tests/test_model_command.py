from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from api.routes.webhook.waha.handles.utility import handle_model_command


class ModelCommandTests(unittest.IsolatedAsyncioTestCase):
    async def test_uses_agent_models_in_dm_and_group_scope(self):
        for group_id, conversation_agent in ((None, "conversation-dm"), (42, "conversation-group")):
            with self.subTest(group_id=group_id):
                agents = {
                    name: SimpleNamespace(id=index, name=name)
                    for index, name in enumerate((conversation_agent, "audio-generation", "modify-image"), 1)
                }
                models = [SimpleNamespace(name=name) for name in ("Scoped text", "Scoped audio", "Scoped image")]
                with (
                    patch("api.routes.webhook.waha.handles.utility.AgentRepository") as agent_repo,
                    patch("api.routes.webhook.waha.handles.utility.ModelConversationRepository") as model_repo,
                    patch("api.routes.webhook.waha.handles.utility.send_message", new_callable=AsyncMock) as send,
                ):
                    agent_repo.return_value.find_by_name = AsyncMock(side_effect=agents.get)
                    resolve = model_repo.return_value.resolve_agent_model = AsyncMock(side_effect=models)

                    await handle_model_command("remote", "message", object(), user_id=7, group_id=group_id)

                self.assertEqual(resolve.await_count, 3)
                for call, agent in zip(resolve.await_args_list, agents.values()):
                    self.assertEqual(call.args, (agent,))
                    self.assertEqual(call.kwargs, {"user_id": 7, "group_id": group_id})
                remote, message, reply_to = send.await_args.args
                self.assertEqual((remote, reply_to), ("remote", "message"))
                for model in models:
                    self.assertIn(model.name, message)
                self.assertNotIn("padrão do sistema", message)

    async def test_missing_agent_or_model_is_reported_as_unconfigured(self):
        with (
            patch("api.routes.webhook.waha.handles.utility.AgentRepository") as agent_repo,
            patch("api.routes.webhook.waha.handles.utility.ModelConversationRepository") as model_repo,
            patch("api.routes.webhook.waha.handles.utility.send_message", new_callable=AsyncMock) as send,
        ):
            agent_repo.return_value.find_by_name = AsyncMock(side_effect=[None, SimpleNamespace(id=2), None])
            resolve = model_repo.return_value.resolve_agent_model = AsyncMock(return_value=None)
            await handle_model_command("remote", "message", object(), user_id=7)

        resolve.assert_awaited_once()
        self.assertEqual(send.await_args.args[1].count("Não configurado"), 3)


if __name__ == "__main__":
    unittest.main()
