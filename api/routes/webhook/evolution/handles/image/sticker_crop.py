import re
import unicodedata


_DIRECTION_ALIASES = {
    "center": "center",
    "centre": "center",
    "centro": "center",
    "top": "top",
    "up": "top",
    "cima": "top",
    "topo": "top",
    "bottom": "bottom",
    "down": "bottom",
    "baixo": "bottom",
    "left": "left",
    "esquerda": "left",
    "right": "right",
    "direita": "right",
}


def normalize_fill_direction(direction: str | None) -> str:
    """Return a canonical cover-crop direction, falling back to center."""
    if not direction:
        return "center"

    normalized = unicodedata.normalize("NFKD", str(direction).strip().lower())
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    parts = [part for part in re.split(r"[\s_-]+", normalized) if part]
    mapped = [_DIRECTION_ALIASES.get(part, part) for part in parts]

    horizontal = next((part for part in mapped if part in {"left", "right"}), None)
    vertical = next((part for part in mapped if part in {"top", "bottom"}), None)
    unknown = [part for part in mapped if part not in {"center", "left", "right", "top", "bottom"}]
    if unknown:
        return "center"
    if vertical and horizontal:
        return f"{vertical}-{horizontal}"
    if vertical:
        return vertical
    if horizontal:
        return horizontal
    return "center"


def fill_alignment(direction: str | None) -> tuple[float, float]:
    """Return horizontal and vertical crop alignment in the 0..1 range."""
    normalized = normalize_fill_direction(direction)
    horizontal = 0.0 if "left" in normalized else 1.0 if "right" in normalized else 0.5
    vertical = 0.0 if "top" in normalized else 1.0 if "bottom" in normalized else 0.5
    return horizontal, vertical
