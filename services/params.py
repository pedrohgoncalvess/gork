import re


PARAMS = (
    "id",
    "no-background",
    "no_background",
    "no-backgorund",
    "no-color",
    "random",
    "effect",
    "size",
    "fill",
    "direction",
    "url",
    "font-size",
    "quote",
    "speed",
    "cut",
    "cut-video",
    "cut-audio",
    "blur",
    "dead",
    "text",
    "tweet",
    "user",
    "when",
    "granularity",
    "duration",
    "audio",
    "quality",
    "resize",
    "voice",
)

PARAM_DEFAULTS = {
    "no-background": False,
    "no_background": False,
    "no-backgorund": False,
    "no-color": False,
    "random": False,
    "fill": False,
    "dead": False,
    "text": False,
    "tweet": False,
    "audio": False,
    "resize": False,
}

_CUT_TIMESTAMP = r"\d+(?::\d+)?(?:\.\d+)?"
_CUT_VALUE = rf"(?:{_CUT_TIMESTAMP}(?:-(?:{_CUT_TIMESTAMP})?)?|-{_CUT_TIMESTAMP})"
SPACED_CUT_PATTERN = rf":(cut-video|cut-audio|cut)\s+({_CUT_VALUE})(?=\s|$)"


def parse_params(message: str | None) -> dict:
    if not message:
        return {}

    keys_pattern = "|".join(map(re.escape, PARAMS))

    pattern = rf'''{SPACED_CUT_PATTERN}|:({keys_pattern})(?:=(?:"([^"]+)"|'([^']+)'|([^\s]+))|(?=\s|$))'''

    matches = re.findall(pattern, message, re.IGNORECASE)

    def _coerce(value: str):
        if value.isdigit():
            return int(value)
        try:
            return float(value)
        except ValueError:
            return value

    result = {}
    for cut_key, spaced_cut, key, double_quoted, single_quoted, unquoted in matches:
        key_lower = (cut_key or key).lower()
        value = spaced_cut or double_quoted or single_quoted or unquoted
        if value:
            result[key_lower] = _coerce(value)
        else:
            result[key_lower] = not PARAM_DEFAULTS[key_lower] if key_lower in PARAM_DEFAULTS else True

    return result
