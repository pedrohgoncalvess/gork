import re


def parse_params(message: str | None) -> dict:
    if not message:
        return {}

    PARAMS = [
        "id",
        "no-background",
        "no-backgorund",
        "random",
        "effect",
        "fill",
        "url",
        "font-size",
        "quote",
        "speed",
        "cut",
        "blur",
    ]
    keys_pattern = "|".join(map(re.escape, PARAMS))

    pattern = rf':({keys_pattern})=([^\s]+)'

    matches = re.findall(pattern, message)

    def _coerce(value: str):
        if value.isdigit():
            return int(value)
        try:
            return float(value)
        except ValueError:
            return value

    result = {}
    for key, value in matches:
        result.update({key: _coerce(value)})

    return result
