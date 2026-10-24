from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import AsyncMock, Mock, patch

from jsonschema.exceptions import ValidationError

from services.gork_knowledge import ROOT, TOPICS, TOOL_NAME, consult
from services.mcp_runtime import complete_with_mcp


class KnowledgeTests(unittest.TestCase):
    def test_index_does_not_read_documents(self):
        with patch.object(Path, "read_text", side_effect=AssertionError("eager read")):
            result = consult({})
        self.assertEqual(len(result["topics"]), len(TOPICS))
        self.assertTrue(all("text" not in topic for topic in result["topics"]))

    def test_every_topic_has_content_and_pageable_sources(self):
        for topic, (_, source) in TOPICS.items():
            with self.subTest(topic=topic):
                offset, chunks = 0, []
                while True:
                    result = consult({"topic": topic, "offset": offset, "limit": 6})
                    self.assertFalse(result["is_error"])
                    self.assertEqual(result["unavailable_sources"], [])
                    self.assertLessEqual(len(result["results"]), 6)
                    chunks.extend(result["results"])
                    if result["next_offset"] is None:
                        break
                    self.assertGreater(result["next_offset"], offset)
                    offset = result["next_offset"]
                self.assertEqual(len(chunks), result["total"])
                self.assertTrue(chunks)
                self.assertTrue(all(item["source"] == source for item in chunks))
                self.assertTrue(all(len(item["text"]) <= 2800 for item in chunks))
                original = (ROOT / source).read_text(encoding="utf-8")
                self.assertTrue(all(item["text"] in original for item in chunks))

    def test_search_finds_encryption_and_normalizes_accents(self):
        result = consult({"query": "criptografia AES", "topic": "encryption", "limit": 6})
        self.assertTrue(result["results"])
        self.assertIn("AES-GCM", json.dumps(result, ensure_ascii=False))
        a = consult({"query": "criptografia"})
        b = consult({"query": "CRIPTOGRAFÍA"})
        self.assertEqual(a, b)

    def test_no_match_is_explicit(self):
        result = consult({"query": "nonexistent_unique_word_019382"})
        self.assertEqual(result["results"], [])
        self.assertEqual(result["total"], 0)
        self.assertIsNone(result["next_offset"])

    def test_only_allowlisted_documents_and_valid_bounds(self):
        for arguments in ({"topic": "../../.env"}, {"path": ".env"}, {"query": "x" * 301},
                          {"limit": 7}, {"offset": -1}, {"limit": True}, {"query": ""}):
            with self.subTest(arguments=arguments), self.assertRaises(ValidationError):
                consult(arguments)

    def test_missing_source_is_reported_without_absolute_path(self):
        with TemporaryDirectory() as directory, patch("services.gork_knowledge.ROOT", Path(directory)):
            result = consult({"topic": "encryption"})
        self.assertTrue(result["is_error"])
        self.assertEqual(result["unavailable_sources"], ["docs/encryption.md"])
        self.assertNotIn(directory, json.dumps(result))


def response(calls=None, content=None):
    return {"choices": [{"message": {"role": "assistant", "content": content, "tool_calls": calls or []}}]}


def call(arguments, identifier="knowledge-1"):
    return {"id": identifier, "type": "function", "function": {
        "name": TOOL_NAME, "arguments": json.dumps(arguments)}}


class KnowledgeRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def run_loop(self, arguments, group_id=None):
        seen = []
        responses = [response([call(arguments)]), response(content='{"queries":[],"actions":[]}')]

        async def completion(payload):
            seen.append(deepcopy(payload))
            return responses.pop(0)

        payload = {"messages": [{"role": "system", "content": "custom managed prompt"},
                                {"role": "user", "content": "Como funciona sua criptografia?"}],
                   "response_format": {"type": "json_object"}}
        original = deepcopy(payload)
        record = AsyncMock()
        with (patch("services.mcp_runtime.available_bindings", new=AsyncMock(return_value=({}, []))),
              patch("services.mcp_runtime.invoke", new=AsyncMock()) as remote):
            await complete_with_mcp(payload, Mock(), user_id=1, group_id=group_id,
                                    message_id=2, completion=completion, record_response=record)
        remote.assert_not_awaited()
        self.assertEqual(record.await_count, 2)
        self.assertEqual(payload, original)
        self.assertEqual(seen[0]["response_format"], original["response_format"])
        self.assertIn("consult_gork_knowledge", seen[0]["messages"][1]["content"])
        self.assertNotIn("AES-GCM", json.dumps(seen[0]))
        tool_result = next(item for item in seen[1]["messages"] if item["role"] == "tool")
        self.assertEqual(tool_result["tool_call_id"], "knowledge-1")
        return json.loads(tool_result["content"])

    async def test_native_lookup_in_dm_and_group_without_remote_mcp(self):
        for group_id in (None, 7):
            with self.subTest(group_id=group_id):
                result = await self.run_loop({"topic": "encryption", "query": "AES"}, group_id)
                self.assertFalse(result["is_error"])
                self.assertIn("AES-GCM", json.dumps(result))

    async def test_invalid_arguments_return_tool_error_and_allow_final_answer(self):
        result = await self.run_loop({"topic": "../.env"})
        self.assertTrue(result["is_error"])

    async def test_duplicate_lookup_uses_existing_round_cache(self):
        completion = AsyncMock(side_effect=[response([call({}), call({}, "knowledge-2")]), response(content="final")])
        with (patch("services.mcp_runtime.available_bindings", new=AsyncMock(return_value=({}, []))),
              patch("services.mcp_runtime.consult", return_value={"topics": []}) as lookup):
            await complete_with_mcp({"messages": []}, Mock(), user_id=1, group_id=None,
                                    message_id=2, completion=completion, record_response=AsyncMock())
        lookup.assert_called_once_with({})


if __name__ == "__main__":
    unittest.main()
