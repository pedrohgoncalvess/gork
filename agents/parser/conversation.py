import json
import re
from typing import Any, Dict, List, Optional, Union

from log import logger


class GorkParserError(Exception):
    """Raised when Gork response parsing fails"""
    pass


class GorkValidationError(Exception):
    """Raised when Gork response structure is invalid"""
    pass


GorkResponseType = Dict[str, Any]


async def parse_gork_response(llm_output: str) -> GorkResponseType:
    """
    Parse and validate Gork's JSON response.

    Expected structure:
    {
        "reasoning": "...",
        "actions": [
            {"action": "message", "content": "...", "language": "pt|en|es"},
            {"action": "sticker", "parameters": {...}},
            ...
        ]
    }

    Args:
        llm_output: Raw string output from LLM

    Returns:
        Validated Gork response dictionary

    Raises:
        GorkParserError: When JSON parsing fails
        GorkValidationError: When structure is invalid
    """
    if not isinstance(llm_output, str) or not llm_output.strip():
        raise GorkParserError("Input must be a non-empty string")

    text = llm_output.strip()

    # Try candidates in order of likelihood
    for candidate in _candidate_json_strings(text):
        try:
            parsed = json.loads(candidate)
            _validate_gork_structure(parsed)
            return parsed
        except json.JSONDecodeError:
            continue
        except GorkValidationError:
            # Structure is wrong, but JSON is valid - might be partially correct
            continue

    # If all candidates fail, log and raise
    await logger.error("GorkParser", "ParseFailed", llm_output)
    raise GorkParserError("Failed to parse valid Gork JSON response")


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

    # 1. Try raw text first (most likely if LLM follows instructions)
    add_candidate(text)

    # 2. Extract from code blocks (common LLM mistake)
    for block in _extract_code_blocks(text):
        add_candidate(block)

    # 3. Try to find balanced JSON (handles extra text before/after)
    extracted = _extract_balanced_json(text)
    if extracted:
        add_candidate(extracted)

    # 4. Light cleanup (remove trailing commas, extra whitespace)
    cleaned = _light_cleanup(text)
    if cleaned != text:
        add_candidate(cleaned)

    # 5. Try to extract just the actions array if reasoning failed
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
        if c == "{":  # Gork always returns object, prioritize {
            start_idx = i
            break

    if start_idx == -1:
        # Fallback to array if object not found
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
    # Remove text before first { or [
    text = re.sub(r"^[^{\[]*", "", text, flags=re.DOTALL)
    # Remove text after last } or ]
    text = re.sub(r"[^\}\]]*$", "", text, flags=re.DOTALL)
    # Remove trailing commas before closing brackets
    text = re.sub(r",\s*([\}\]])", r"\1", text)
    # Remove multiple consecutive spaces
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
        GorkValidationError: If structure is invalid
    """
    if not isinstance(response, dict):
        raise GorkValidationError(
            f"Response must be a dict, got {type(response).__name__}"
        )

    # Check for actions key
    if "actions" not in response:
        raise GorkValidationError("Response missing required 'actions' key")

    actions = response["actions"]

    if not isinstance(actions, list):
        raise GorkValidationError(
            f"'actions' must be a list, got {type(actions).__name__}"
        )

    if not actions:
        raise GorkValidationError("'actions' list cannot be empty")

    # Validate each action
    for idx, action in enumerate(actions):
        if not isinstance(action, dict):
            raise GorkValidationError(
                f"Action at index {idx} must be a dict, got {type(action).__name__}"
            )

        if "action" not in action:
            raise GorkValidationError(
                f"Action at index {idx} missing required 'action' key"
            )

        action_type = action["action"]

        # Validate action-specific requirements
        _validate_action_type(action_type, action, idx)


def _validate_action_type(action_type: str, action: Dict, idx: int) -> None:
    """Validate specific action types and their required fields"""

    if action_type == "message":
        if "content" not in action:
            raise GorkValidationError(
                f"Message action at index {idx} missing 'content'"
            )
        if "language" not in action:
            raise GorkValidationError(
                f"Message action at index {idx} missing 'language'"
            )
        if action["language"] not in ["pt", "en", "es"]:
            raise GorkValidationError(
                f"Message action at index {idx} has invalid language: {action['language']}"
            )

    elif action_type in [
        "sticker", "audio", "picture", "image", "describe",
        "search", "transcribe", "remember", "twitter", "instagram",
        "gallery", "favorite"
    ]:
        # These actions may have parameters
        if "parameters" in action and not isinstance(action["parameters"], dict):
            raise GorkValidationError(
                f"Action '{action_type}' at index {idx} has invalid parameters (must be dict)"
            )

    elif action_type in ["resume", "help", "model", "consumption"]:
        # These actions don't need parameters
        pass

    else:
        # Unknown action type - log warning but don't fail
        # (allows for future extensibility)
        pass


def extract_messages(gork_response: GorkResponseType) -> List[Dict[str, str]]:
    """
    Extract only message actions from Gork response.
    Useful for quick message-only responses.

    Returns:
        List of dicts with 'content' and 'language' keys
    """
    messages = []
    for action in gork_response.get("actions", []):
        if action.get("action") == "message":
            messages.append({
                "content": action.get("content", ""),
                "language": action.get("language", "pt")
            })
    return messages


def extract_functions(gork_response: GorkResponseType) -> List[Dict[str, Any]]:
    """
    Extract only function/command actions from Gork response.
    Excludes message actions.

    Returns:
        List of dicts with 'action' and optional 'parameters' keys
    """
    functions = []
    for action in gork_response.get("actions", []):
        if action.get("action") != "message":
            functions.append(action)
    return functions


def get_reasoning(gork_response: GorkResponseType) -> Optional[str]:
    """Extract reasoning from Gork response if present"""
    return gork_response.get("reasoning")


# Convenience function for backward compatibility
async def parse_llm_json(llm_output: str) -> GorkResponseType:
    """Alias for parse_gork_response for backward compatibility"""
    return await parse_gork_response(llm_output)