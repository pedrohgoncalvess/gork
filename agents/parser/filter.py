import json
import re
from typing import Any, Dict, List, Optional

from log import logger


async def parse_filter_response(llm_output: str) -> Dict[str, Any]:
    """
    Parse and validate Gork filter's JSON response.

    Expected Schema:
    {
        "reasoning": str,              # Required - Filter's thought process
        "should_respond": bool,        # Required - Whether Gork should respond
        "confidence": str,             # Required - "high"|"medium"|"low"
        "trigger_type": str | None     # Required - Trigger type or null
    }

    Trigger Types (required when should_respond=true, null when false):
    - "direct_mention": Gork was explicitly mentioned
    - "command": Message contains a command (!sticker, !audio, etc.)
    - "fact_check": Opportunity to verify factual claims or data
    - "question": Direct question that Gork should answer
    - "information_gap": Clear need for information that Gork can provide
    - "research": Request for research or data lookup
    - "technical": Technical/educational question
    - "conversation_gap": Dead-end where Gork could help

    Validation Rules:
    - If should_respond=true, trigger_type MUST be specified (cannot be null)
    - If should_respond=false, trigger_type MUST be null

    Args:
        llm_output: Raw string output from LLM

    Returns:
        Dict with validated filter response

    Raises:
        ValueError: When parsing fails or structure is invalid
    """
    if not isinstance(llm_output, str) or not llm_output.strip():
        raise ValueError("Input must be a non-empty string")

    text = llm_output.strip()

    for candidate in _candidate_json_strings(text):
        try:
            parsed = json.loads(candidate)
            _validate_filter_structure(parsed)
            return parsed
        except json.JSONDecodeError:
            continue
        except ValueError:
            continue

    await logger.error("GorkFilter", "ParseFailed", llm_output)
    raise ValueError("Failed to parse valid filter JSON response")


def _candidate_json_strings(text: str) -> List[str]:
    """Generate candidate JSON strings from LLM output"""
    seen = set()
    candidates: List[str] = []

    def add_candidate(candidate: str) -> None:
        if candidate and candidate not in seen:
            seen.add(candidate)
            candidates.append(candidate)

    add_candidate(text)

    for block in _extract_code_blocks(text):
        add_candidate(block)

    extracted = _extract_balanced_json(text)
    if extracted:
        add_candidate(extracted)

    cleaned = _light_cleanup(text)
    if cleaned != text:
        add_candidate(cleaned)

    return candidates


def _extract_code_blocks(text: str) -> List[str]:
    """Extract content from ```json``` or ``` code blocks"""
    blocks = re.findall(
        r"```(?:json)?\s*(.*?)```",
        text,
        flags=re.DOTALL | re.IGNORECASE
    )
    return [b.strip() for b in blocks if b.strip()]


def _extract_balanced_json(text: str) -> Optional[str]:
    """Extract first balanced JSON object"""
    start_idx = -1
    for i, c in enumerate(text):
        if c == "{":
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

        if c == "{":
            stack.append(c)
        elif c == "}":
            if not stack:
                return None
            stack.pop()
            if not stack:
                return text[start_idx: j + 1]

    return None


def _light_cleanup(text: str) -> str:
    """Remove common JSON formatting issues"""
    text = re.sub(r"^[^{]*", "", text, flags=re.DOTALL)
    text = re.sub(r"[^}]*$", "", text, flags=re.DOTALL)
    text = re.sub(r",\s*}", "}", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _validate_filter_structure(data: Any) -> None:
    """
    Validate parsed JSON structure.

    Raises:
        ValueError: If structure is invalid
    """
    if not isinstance(data, dict):
        raise ValueError(
            f"Response must be a dict, got {type(data).__name__}"
        )

    if "reasoning" not in data:
        raise ValueError("Missing required field 'reasoning'")

    if "should_respond" not in data:
        raise ValueError("Missing required field 'should_respond'")

    if "confidence" not in data:
        raise ValueError("Missing required field 'confidence'")

    reasoning = data["reasoning"]
    should_respond = data["should_respond"]
    confidence = data["confidence"]
    trigger_type = data.get("trigger_type")

    if not isinstance(reasoning, str):
        raise ValueError(
            f"'reasoning' must be a string, got {type(reasoning).__name__}"
        )

    if not isinstance(should_respond, bool):
        raise ValueError(
            f"'should_respond' must be a boolean, got {type(should_respond).__name__}"
        )

    valid_confidence = ["high", "medium", "low"]
    if confidence not in valid_confidence:
        raise ValueError(
            f"'confidence' must be one of {valid_confidence}, got '{confidence}'"
        )

    valid_triggers = [
        "direct_mention",
        "command",
        "fact_check",
        "question",
        "information_gap",
        "research",
        "technical",
        "conversation_gap",
        None
    ]

    if trigger_type not in valid_triggers:
        raise ValueError(
            f"'trigger_type' must be one of {valid_triggers}, got '{trigger_type}'"
        )

    if should_respond and trigger_type is None:
        raise ValueError(
            "When 'should_respond' is true, 'trigger_type' must be specified"
        )

    if not should_respond and trigger_type is not None:
        raise ValueError(
            "When 'should_respond' is false, 'trigger_type' must be null"
        )