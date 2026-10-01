from pathlib import Path
import unittest

import yaml


class ConversationAgentConfigTests(unittest.TestCase):
    def test_specialized_conversation_agents_use_gpt_6_luna(self):
        config_path = Path(__file__).parents[1] / "agents" / "agents.yaml"
        config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        agents = {agent["name"]: agent for agent in config["agents"]}

        self.assertNotIn("conversation", agents)
        self.assertEqual(agents["conversation-dm"]["model"], "openai/gpt-6-luna")
        self.assertEqual(agents["conversation-group"]["model"], "openai/gpt-6-luna")


if __name__ == "__main__":
    unittest.main()
