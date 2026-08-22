import re


PARAMS = (
    "id",
    "no-background",
    "no-backgorund",
    "no-color",
    "random",
    "effect",
    "fill",
    "url",
    "font-size",
    "quote",
    "speed",
    "cut",
    "blur",
    "dead",
    "user",
    "when",
    "granularity",
)

PARAM_DEFAULTS = {
    "no-background": False,
    "no-backgorund": False,
    "no-color": False,
    "random": False,
    "fill": False,
    "dead": False,
}


def parse_params(message: str | None) -> dict:
    if not message:
        return {}

    keys_pattern = "|".join(map(re.escape, PARAMS))

    pattern = rf''':({keys_pattern})(?:=(?:"([^"]+)"|'([^']+)'|([^\s]+))|(?=\s|$))'''

    matches = re.findall(pattern, message)

    def _coerce(value: str):
        if value.isdigit():
            return int(value)
        try:
            return float(value)
        except ValueError:
            return value

    result = {}
    for key, double_quoted, single_quoted, unquoted in matches:
        value = double_quoted or single_quoted or unquoted
        if value:
            result[key] = _coerce(value)
        else:
            result[key] = not PARAM_DEFAULTS[key] if key in PARAM_DEFAULTS else True

    return result
