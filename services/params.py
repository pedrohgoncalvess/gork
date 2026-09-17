import re


PARAMS = (
    "id",
    "no-background",
    "no_background",
    "no-backgorund",
    "no-color",
    "random",
    "effect",
    "fill",
    "direction",
    "url",
    "font-size",
    "quote",
    "speed",
    "cut",
    "blur",
    "dead",
    "text",
    "user",
    "when",
    "granularity",
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
    "audio": False,
}


def parse_params(message: str | None) -> dict:
    if not message:
        return {}

    keys_pattern = "|".join(map(re.escape, PARAMS))

    pattern = rf''':({keys_pattern})(?:=(?:"([^"]+)"|'([^']+)'|([^\s]+))|(?=\s|$))'''

    matches = re.findall(pattern, message, re.IGNORECASE)

    def _coerce(value: str):
        if value.isdigit():
            return int(value)
        try:
            return float(value)
        except ValueError:
            return value

    result = {}
    for key, double_quoted, single_quoted, unquoted in matches:
        key_lower = key.lower()
        value = double_quoted or single_quoted or unquoted
        if value:
            result[key_lower] = _coerce(value)
        else:
            result[key_lower] = not PARAM_DEFAULTS[key_lower] if key_lower in PARAM_DEFAULTS else True

    return result
