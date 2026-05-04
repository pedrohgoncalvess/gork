import json
import re
from typing import Any, Dict, List, Optional, Literal

from log import logger


class GorkFilterParserError(Exception):
    """Raised when filter response parsing fails"""
    pass


class GorkFilterValidationError(Exception):
    """Raised when filter response structure is invalid"""
    pass


TriggerType = Literal[
    "direct_mention",
    "command",
    "fact_check",
    "question",
    "information_gap",
    "research",
    "technical",
    "conversation_gap"
]

ConfidenceLevel = Literal["high", "medium", "low"]


class GorkFilterResponse:
    """Structured response from Gork filter agent"""

    def __init__(
            self,
            reasoning: str,
            should_respond: bool,
            confidence: ConfidenceLevel,
            trigger_type: Optional[TriggerType] = None
    ):
        self.reasoning = reasoning
        self.should_respond = should_respond
        self.confidence = confidence
        self.trigger_type = trigger_type

    def to_dict(self) -> Dict[str, Any]:
        return {
            "reasoning": self.reasoning,
            "should_respond": self.should_respond,
            "confidence": self.confidence,
            "trigger_type": self.trigger_type
        }

    def __repr__(self) -> str:
        return (
            f"GorkFilterResponse("
            f"should_respond={self.should_respond}, "
            f"confidence={self.confidence}, "
            f"trigger_type={self.trigger_type})"
        )


async def parse_filter_response(llm_output: str) -> GorkFilterResponse:
    """
    Parse and validate Gork filter's JSON response.

    Expected structure:
    {
        "reasoning": "...",
        "should_respond": true/false,
        "confidence": "high|medium|low",
        "trigger_type": "direct_mention|command|..." or null
    }

    Args:
        llm_output: Raw string output from LLM

    Returns:
        GorkFilterResponse object

    Raises:
        GorkFilterParserError: When JSON parsing fails
        GorkFilterValidationError: When structure is invalid
    """
    if not isinstance(llm_output, str) or not llm_output.strip():
        raise GorkFilterParserError("Input must be a non-empty string")

    text = llm_output.strip()

    for candidate in _candidate_json_strings(text):
        try:
            parsed = json.loads(candidate)
            return _validate_and_build_response(parsed)
        except json.JSONDecodeError:
            continue
        except GorkFilterValidationError:
            continue

    await logger.error("GorkFilter", "ParseFailed", llm_output)
    raise GorkFilterParserError("Failed to parse valid filter JSON response")


def _candidate_json_strings(text: str) -> List[str]:
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


def _validate_and_build_response(data: Any) -> GorkFilterResponse:
    """
    Validate parsed JSON and build GorkFilterResponse object.

    Raises:
        GorkFilterValidationError: If structure is invalid
    """
    if not isinstance(data, dict):
        raise GorkFilterValidationError(
            f"Response must be a dict, got {type(data).__name__}"
        )

    if "reasoning" not in data:
        raise GorkFilterValidationError("Missing required field 'reasoning'")

    if "should_respond" not in data:
        raise GorkFilterValidationError("Missing required field 'should_respond'")

    if "confidence" not in data:
        raise GorkFilterValidationError("Missing required field 'confidence'")

    reasoning = data["reasoning"]
    should_respond = data["should_respond"]
    confidence = data["confidence"]
    trigger_type = data.get("trigger_type")

    if not isinstance(reasoning, str):
        raise GorkFilterValidationError(
            f"'reasoning' must be a string, got {type(reasoning).__name__}"
        )

    if not isinstance(should_respond, bool):
        raise GorkFilterValidationError(
            f"'should_respond' must be a boolean, got {type(should_respond).__name__}"
        )

    valid_confidence = ["high", "medium", "low"]
    if confidence not in valid_confidence:
        raise GorkFilterValidationError(
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
        raise GorkFilterValidationError(
            f"'trigger_type' must be one of {valid_triggers}, got '{trigger_type}'"
        )

    if should_respond and trigger_type is None:
        raise GorkFilterValidationError(
            "When 'should_respond' is true, 'trigger_type' must be specified"
        )

    if not should_respond and trigger_type is not None:
        raise GorkFilterValidationError(
            "When 'should_respond' is false, 'trigger_type' must be null"
        )

    return GorkFilterResponse(
        reasoning=reasoning,
        should_respond=should_respond,
        confidence=confidence,
        trigger_type=trigger_type
    )