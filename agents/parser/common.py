import json
import re
from typing import Any, Dict, List, Union

from log import logger


class LLMJsonParserError(Exception):
    pass


JsonType = Union[Dict[str, Any], List[Any]]


async def parse_llm_json(llm_output: str) -> JsonType:
    if not isinstance(llm_output, str) or not llm_output.strip():
        raise LLMJsonParserError("Input must be a non-empty string")

    text = llm_output.strip()

    for candidate in _candidate_json_strings(text):
        try:
            parsed = json.loads(candidate)
            _validate_result(parsed)
            return parsed
        except json.JSONDecodeError:
            continue

    await logger.error("Parser", "Json", llm_output)
    raise LLMJsonParserError("Failed to parse JSON from LLM output")


def _candidate_json_strings(text: str) -> List[str]:
    seen = set()
    candidates: List[str] = []

    def add_candidate(candidate: str) -> None:
        if candidate and candidate not in seen:
            seen.add(candidate)
            candidates.append(candidate)

    add_candidate(text)

    for candidate in _extract_code_blocks(text):
        add_candidate(candidate)

    extracted = _extract_balanced_json(text)
    if extracted:
        add_candidate(extracted)

    cleaned = _light_cleanup(text)
    if cleaned != text:
        add_candidate(cleaned)

    return candidates


def _extract_code_blocks(text: str) -> List[str]:
    blocks = re.findall(
        r"```(?:json)?\s*(.*?)```",
        text,
        flags=re.DOTALL | re.IGNORECASE
    )
    return [b.strip() for b in blocks if b.strip()]


def _extract_balanced_json(text: str) -> Union[str, None]:
    start_idx = -1
    for i, c in enumerate(text):
        if c in "{[":
            start_idx = i
            break

    if start_idx == -1:
        return None

    stack = []
    in_string = False
    escape = False

    for j in range(start_idx, len(text)):
        c = text[j]

        if escape:
            escape = False
            continue

        if c == "\\":
            escape = True
            continue

        if c == '"':
            in_string = not in_string
            continue

        if in_string:
            continue

        if c in "{[":
            stack.append(c)
        elif c in "}]":
            if not stack:
                return None
            open_c = stack.pop()
            if (open_c, c) not in {("{", "}"), ("[", "]")}:
                return None
            if not stack:
                return text[start_idx: j + 1]

    return None


def _light_cleanup(text: str) -> str:
    text = re.sub(r"^[^{\[]*", "", text, flags=re.DOTALL)
    text = re.sub(r"[^\}\]]*$", "", text, flags=re.DOTALL)
    text = re.sub(r",\s*([\}\]])", r"\1", text)
    return text.strip()


def _validate_result(result: JsonType) -> None:
    if isinstance(result, dict):
        return
    if isinstance(result, list):
        if not result:
            raise LLMJsonParserError("Parsed list is empty")
        return
    raise LLMJsonParserError(f"Expected dict or list, got {type(result).__name__}")