import json
from pathlib import Path
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]


class ProjectLayoutTests(unittest.TestCase):
    def test_each_agent_owns_its_code_prompt_and_schema(self):
        config = yaml.safe_load((ROOT / "agents/agents.yaml").read_text(encoding="utf-8"))
        for agent in config["agents"]:
            directory = ROOT / "agents" / agent["name"].replace("-", "_")
            with self.subTest(agent=agent["name"]):
                self.assertTrue((directory / "agent.py").is_file())
                self.assertEqual(ROOT / agent["prompt_path"], directory / "prompt.md")
                self.assertTrue((directory / "prompt.md").is_file())
                if agent.get("schema_path"):
                    self.assertEqual(ROOT / agent["schema_path"], directory / "schema.json")
                    json.loads((directory / "schema.json").read_text(encoding="utf-8"))

    def test_docker_paths_resolve_after_moving_development_compose(self):
        for relative in ("compose.yaml", "docker/compose.dev.yaml"):
            file = ROOT / relative
            config = yaml.safe_load(file.read_text(encoding="utf-8"))
            for service in config["services"].values():
                if service.get("build"):
                    build = service["build"]
                    context = (file.parent / build["context"]).resolve()
                    self.assertTrue((context / build.get("dockerfile", "Dockerfile")).is_file())
                for volume in service.get("volumes", []):
                    source = volume.split(":")[0]
                    if source.startswith("."):
                        target = (file.parent / source).resolve()
                        if target.name == ".env":
                            self.assertTrue(target.exists() or target.with_name(".env.example").exists())
                            continue
                        self.assertTrue(target.exists(), source)
        self.assertEqual(config["name"], "gork")

    def test_conversation_profiles_share_the_same_response_contract(self):
        schemas = [json.loads((ROOT / f"agents/{name}/schema.json").read_text(encoding="utf-8"))
                   for name in ("conversation_dm", "conversation_group")]
        self.assertEqual(*schemas)

    def test_default_webhook_host_exists_in_each_compose_stack(self):
        from urllib.parse import urlsplit
        from scripts.waha_session import DEFAULT_WEBHOOK_URL

        host = urlsplit(DEFAULT_WEBHOOK_URL).hostname
        for relative in ("compose.yaml", "docker/compose.dev.yaml"):
            with self.subTest(compose=relative):
                config = yaml.safe_load((ROOT / relative).read_text(encoding="utf-8"))
                backends = [service for service in config['services'].values()
                            if service.get('container_name') == host]
                self.assertEqual(len(backends), 1)
                self.assertEqual(backends[0]['build']['dockerfile'], 'docker/Dockerfile')
