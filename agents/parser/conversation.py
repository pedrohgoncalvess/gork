import json
import re
from typing import Any, Dict, List, Optional

from log import logger


async def parse_gork_response(llm_output: str) -> Dict[str, Any]:
    """
    Parse and validate Gork's JSON response.

    Expected Schema:
    {
        "reasoning": str,              # Required - Gork's thought process
        "actions": [                   # Required - List of actions (min 1)
            {
                "action": str,         # Required - Action type
                "content": str,        # Required for "message" action
                "language": str,       # Required for "message" action ("pt"|"en"|"es")
                "parameters": dict     # Optional - Action parameters
            },
            ...
        ]
    }

    Action Types:
    - "message": Requires "content" and "language" fields
    - "audio", "sticker", "picture", "image", "describe", "web_search",
      "transcribe", "remember", "twitter", "instagram", "gallery", "favorite":
      May have optional "parameters" dict
    - "resume", "help", "model", "consumption": No parameters needed

    Args:
        llm_output: Raw string output from LLM

    Returns:
        Dict with validated Gork response

    Raises:
        ValueError: When parsing fails or structure is invalid
    """
    if not isinstance(llm_output, str) or not llm_output.strip():
        raise ValueError("Input must be a non-empty string")

    text = llm_output.strip()

    for candidate in _candidate_json_strings(text):
        try:
            parsed = json.loads(candidate)
            _validate_gork_structure(parsed)
            return parsed
        except json.JSONDecodeError:
            continue
        except ValueError:
            continue

    await logger.error("GorkParser", "ParseFailed", llm_output)
    raise ValueError("Failed to parse valid Gork JSON response")


def _candidate_json_strings(text: str) -> List[str]:
    """
    Generate candidate JSON strings from LLM output.
    Optimized for Gork's expected response patterns.
    """
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

    actions_only = _extract_actions_array(text)
    if actions_only:
        add_candidate(actions_only)

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
    """
    Extract first balanced JSON object or array.
    Handles nested structures and escaped quotes.
    """
    start_idx = -1
    for i, c in enumerate(text):
        if c == "{":
            start_idx = i
            break

    if start_idx == -1:
        for i, c in enumerate(text):
            if c == "[":
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


def _extract_actions_array(text: str) -> Optional[str]:
    """
    Emergency fallback: try to extract just the actions array
    and wrap it in minimal valid structure.
    """
    # Look for "actions": [...] pattern
    match = re.search(
        r'"actions"\s*:\s*(\[.*?\])',
        text,
        flags=re.DOTALL
    )

    if match:
        actions_json = match.group(1)
        try:
            # Validate it's valid JSON
            json.loads(actions_json)
            # Wrap in minimal structure
            return json.dumps({
                "reasoning": "Emergency fallback - reasoning not provided",
                "actions": json.loads(actions_json)
            })
        except json.JSONDecodeError:
            pass

    return None


def _light_cleanup(text: str) -> str:
    """Remove common JSON formatting issues"""
    text = re.sub(r"^[^{\[]*", "", text, flags=re.DOTALL)
    text = re.sub(r"[^\}\]]*$", "", text, flags=re.DOTALL)
    text = re.sub(r",\s*([\}\]])", r"\1", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _validate_gork_structure(response: Any) -> None:
    """
    Validate that parsed JSON matches Gork's expected structure.

    Required:
    - Must be a dict
    - Must have "actions" key with list value
    - Each action must have "action" key

    Optional:
    - "reasoning" key (recommended but not required for backward compat)

    Raises:
        ValueError: If structure is invalid
    """
    if not isinstance(response, dict):
        raise ValueError(
            f"Response must be a dict, got {type(response).__name__}"
        )

    if "actions" not in response:
        raise ValueError("Response missing required 'actions' key")

    actions = response["actions"]

    if not isinstance(actions, list):
        raise ValueError(
            f"'actions' must be a list, got {type(actions).__name__}"
        )

    if not actions:
        raise ValueError("'actions' list cannot be empty")

    for idx, action in enumerate(actions):
        if not isinstance(action, dict):
            raise ValueError(
                f"Action at index {idx} must be a dict, got {type(action).__name__}"
            )

        if "action" not in action:
            raise ValueError(
                f"Action at index {idx} missing required 'action' key"
            )

        action_type = action["action"]

        _validate_action_type(action_type, action, idx)


def _validate_action_type(action_type: str, action: Dict, idx: int) -> None:
    """Validate specific action types and their required fields"""

    if action_type == "message":
        if "content" not in action:
            raise ValueError(
                f"Message action at index {idx} missing 'content'"
            )
        if "language" not in action:
            raise ValueError(
                f"Message action at index {idx} missing 'language'"
            )
        if action["language"] not in ["pt", "en", "es"]:
            raise ValueError(
                f"Message action at index {idx} has invalid language: {action['language']}"
            )

    elif action_type in [
        "sticker", "audio", "picture", "image", "describe",
        "search", "web_search", "transcribe", "remember", "twitter", "instagram",
        "gallery", "favorite"
    ]:
        if "parameters" in action and not isinstance(action["parameters"], dict):
            raise ValueError(
                f"Action '{action_type}' at index {idx} has invalid parameters (must be dict)"
            )

    elif action_type in ["resume", "help", "model", "consumption"]:
        pass

    else:
        pass
