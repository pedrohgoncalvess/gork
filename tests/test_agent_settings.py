from types import SimpleNamespace
import unittest

from services.agent_settings import apply_prompt_setting
from services.model_capabilities import agent_output, model_catalog, output_modalities


class ModelCapabilitiesTests(unittest.TestCase):
    def test_input_capabilities_never_count_as_output(self):
        metadata = {"catalog": {"architecture": {
            "input_modalities": ["text", "image", "audio", "video"],
            "output_modalities": ["text"],
        }}}
        self.assertEqual(output_modalities(metadata), ["text"])
        self.assertEqual(output_modalities({}), [])
        self.assertEqual(output_modalities({"catalog": {"architecture": {
            "output_modalities": ["speech"]}}}), ["audio"])

    def test_specialized_catalogs_and_legacy_architecture(self):
        self.assertEqual(output_modalities({"catalog": {"architecture": {
            "modality": "text+image->text+image"}}}), ["image", "text"])
        self.assertEqual(output_modalities({"image": {"id": "image-model"}}), ["image"])
        self.assertEqual(output_modalities({"video": {"id": "video-model"}}), ["video"])

    def test_duplicate_catalog_entries_retain_existing_setting_ids(self):
        rows = [SimpleNamespace(id=2, name="First", openrouter_id="test/model", metadata_={}),
                SimpleNamespace(id=7, name="Second", openrouter_id="test/model", metadata_={
                    "catalog": {"architecture": {"output_modalities": ["audio"]}}})]
        catalog = model_catalog(rows)
        self.assertEqual(len(catalog), 1)
        self.assertEqual(catalog[0]["model_ids"], [2, 7])
        self.assertEqual(catalog[0]["output_modalities"], ["audio"])

    def test_agents_require_their_response_type(self):
        for agent, expected in (("audio-generation", "audio"), ("voice-cloning", "audio"), ("modify-image", "image"),
                                ("resize-image", "image"), ("video-generation", "video"),
                                ("transcriber", "text"), ("describe-image", "text")):
            self.assertEqual(agent_output(agent), expected)


class AgentPromptSettingTests(unittest.TestCase):
    def test_disabled_setting_removes_instructions_and_preserves_attachment(self):
        user = {"role": "user", "content": [{"type": "image_url", "image_url": {"url": "image"}}]}
        payload = {"messages": [{"role": "system", "content": "secret"},
                                {"role": "developer", "content": "instructions"}, user]}
        apply_prompt_setting(payload, SimpleNamespace(disable_system_prompt=True))
        self.assertEqual(payload["messages"], [user])

    def test_default_keeps_instructions(self):
        for agent in (None, SimpleNamespace(), SimpleNamespace(disable_system_prompt=False)):
            payload = {"messages": [{"role": "system", "content": "instructions"}]}
            apply_prompt_setting(payload, agent)
            self.assertEqual(len(payload["messages"]), 1)
