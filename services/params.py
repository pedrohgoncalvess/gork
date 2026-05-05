import re


def parse_params(message: str) -> dict:
    PARAMS = ["id", "no-background", "random", "effect", "fill"]
    keys_pattern = "|".join(map(re.escape, PARAMS))

    pattern = rf':({keys_pattern})=([^\s]+)'

    matches = re.findall(pattern, message)

    result = {}
    for key, value in matches:
        if value.isdigit():
            value = int(value)
        result.update({key: value})

    return result
