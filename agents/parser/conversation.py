import json
import re
from typing import Any, Dict, List, Optional

from log import logger


def _empty_gork_response(reasoning: str = "") -> Dict[str, Any]:
    return {
        "reasoning": reasoning,
        "queries": [],
        "actions": [],
    }


async def parse_gork_response(llm_output: str) -> Dict[str, Any]:
    """
    Parse and validate Gork's JSON response.

    Expected Schema:
    {
        "reasoning": str,              # Required - Gork's thought process
        "queries": [                   # Optional - Database queries to execute
            {
                "query_type": str,     # Required - Query type
                "parameters": dict     # Required - Query parameters
            }
        ],
        "next_call_instruction": str,  # Required when queries is not empty
        "actions": [                   # Required when queries is empty
            {
                "action": str,         # Required - Action type
                "content": str,        # Required for "message" action
                "language": str,       # Required for "message" action ("pt"|"en"|"es")
                "parameters": dict     # Optional - Action parameters
            }
        ]
    }

    Query Types:
    - "get_group_users": Get list of users in group
    - "get_user_messages": Get messages from specific user
    - "search_messages": Search messages by text
    - "get_user_images": Get images sent by user

    Action Types:
    - "message": Requires "content" and "language" fields
    - "audio", "sticker", "picture", "image", "describe", "web_search",
      "transcribe", "remember", "twitter", "instagram", "gallery", "favorite":
      May have optional "parameters" dict
    - "resume", "help", "model", "consumption": No parameters needed

    Validation Rules:
    - If queries is not empty, actions MUST be empty
    - If queries is empty, actions MUST not be empty
    - If queries is not empty, next_call_instruction is REQUIRED

    Args:
        llm_output: Raw string output from LLM

    Returns:
        Dict with validated Gork response

    Raises:
        ValueError: When parsing fails or structure is invalid
    """
    if not isinstance(llm_output, str) or not llm_output.strip():
        return _empty_gork_response("Model returned an empty response.")

    text = llm_output.strip()

    # Try candidates in order of likelihood
    for attempt, candidate in enumerate(_candidate_json_strings(text), 1):
        try:
            parsed = json.loads(candidate)
            _validate_gork_structure(parsed)
            return parsed
        except json.JSONDecodeError as error:
            await _log_parse_attempt_error("JsonDecodeError", attempt, candidate, error)
            continue
        except ValueError as error:
            # Structure is wrong, but JSON is valid - might be partially correct
            await _log_parse_attempt_error("ValidationError", attempt, candidate, error)
            continue

    # If all candidates fail, log and raise
    await logger.error("GorkParser", "ParseFailed", llm_output)
    raise ValueError("Failed to parse valid Gork JSON response")


async def _log_parse_attempt_error(
        error_type: str,
        attempt: int,
        candidate: str,
        error: Exception,
) -> None:
    await logger.error(
        "GorkParser",
        f"ParseAttempt{attempt}{error_type}",
        f"{error}. Candidate: {candidate[:1000]}",
    )


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
    - Must have "queries" key (can be empty list)
    - Must have "actions" key (can be empty list)
    - If queries not empty, actions must be empty
    - If queries not empty, next_call_instruction is required
    - If queries empty, actions must not be empty

    Optional:
    - "reasoning" key (recommended but not required for backward compat)

    Raises:
        ValueError: If structure is invalid
    """
    if not isinstance(response, dict):
        raise ValueError(
            f"Response must be a dict, got {type(response).__name__}"
        )

    if not response:
        response.update(_empty_gork_response())
        return

    # Check for required keys
    if "queries" not in response:
        raise ValueError("Response missing required 'queries' key")

    if "actions" not in response:
        raise ValueError("Response missing required 'actions' key")

    queries = response["queries"]
    actions = response["actions"]

    # Validate types
    if not isinstance(queries, list):
        raise ValueError(
            f"'queries' must be a list, got {type(queries).__name__}"
        )

    if not isinstance(actions, list):
        raise ValueError(
            f"'actions' must be a list, got {type(actions).__name__}"
        )

    # Validate mutual exclusivity
    if queries and actions:
        raise ValueError(
            "If 'queries' is not empty, 'actions' must be empty (gathering data mode)"
        )

    if not queries and not actions:
        return

    # Validate next_call_instruction when queries present
    if queries:
        if "next_call_instruction" not in response:
            raise ValueError(
                "When 'queries' is not empty, 'next_call_instruction' is required"
            )

        next_instruction = response["next_call_instruction"]
        if not isinstance(next_instruction, str) or not next_instruction.strip():
            raise ValueError(
                "'next_call_instruction' must be a non-empty string"
            )

    # Validate each query
    for idx, query in enumerate(queries):
        if not isinstance(query, dict):
            raise ValueError(
                f"Query at index {idx} must be a dict, got {type(query).__name__}"
            )

        if "query_type" not in query:
            raise ValueError(
                f"Query at index {idx} missing required 'query_type' key"
            )

        if "parameters" not in query:
            raise ValueError(
                f"Query at index {idx} missing required 'parameters' key"
            )

        #_validate_query_type(query["query_type"], query, idx)

    # Validate each action
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

        # Validate action-specific requirements
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
        # These actions may have parameters
        if "parameters" in action and not isinstance(action["parameters"], dict):
            raise ValueError(
                f"Action '{action_type}' at index {idx} has invalid parameters (must be dict)"
            )

    elif action_type in ["resume", "help", "model", "consumption"]:
        # These actions don't need parameters
        pass

    else:
        # Unknown action type - log warning but don't fail
        # (allows for future extensibility)
        pass
