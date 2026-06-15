"""
Philosopher data for the !philo command.

Each entry defines:
- key          : canonical slug used to match :quote= values
- display_name : formatted name shown on the image
- aliases      : alternative strings that map to this philosopher
- filename     : image file inside assets/philosophys/
- period       : historical period displayed on the image
- text_region  : where the main quote should be drawn inside the image.
                 Value is one of:
                   "right_upper"   - dark area to the right, upper portion  (Aristoteles, Nietzsche)
                   "left_upper"    - dark area to the left, upper portion    (Platão)
                   "bottom_center" - lower strip centred                     (Sócrates)
                   "bottom_right"  - lower-right corner                      (Tales de Mileto)
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import List


@dataclass(frozen=True)
class PhilosopherData:
    key: str
    display_name: str
    aliases: List[str]
    filename: str
    period: str
    # Where the quote box sits inside the (width × height) image space.
    # Expressed as (x_fraction, y_fraction, w_fraction, h_fraction) – all 0-1.
    # x/y = top-left corner of the text box, w/h = size of the text box.
    text_box: tuple  # (x_frac, y_frac, w_frac, h_frac)


PHILOSOPHERS: List[PhilosopherData] = [
    PhilosopherData(
        key="aristoteles",
        display_name="Aristóteles",
        aliases=["aristoteles", "aristotle", "aristoteles"],
        filename="aristoteles.jpg",
        period="384–322 a.C.",
        # rosto na esquerda; área escura cobre ~55 % direita × 100 % altura
        text_box=(0.42, 0.05, 0.54, 0.60),
    ),
    PhilosopherData(
        key="nietzsche",
        display_name="Friedrich Nietzsche",
        aliases=["nietzsche", "friedrich"],
        filename="nietzsche.jpg",
        period="1844–1900 d.C.",
        # rosto na esquerda; área escura cobre ~55 % direita × 100 % altura
        text_box=(0.42, 0.05, 0.54, 0.60),
    ),
    PhilosopherData(
        key="platao",
        display_name="Platão",
        aliases=["platao", "plato", "platão"],
        filename="platao.jpg",
        period="428–348 a.C.",
        # rosto à direita/centro-inferior; área escura no canto superior esquerdo
        text_box=(0.02, 0.03, 0.48, 0.55),
    ),
    PhilosopherData(
        key="socrates",
        display_name="Sócrates",
        aliases=["socrates", "sócrates"],
        filename="socratesjpg.jpg",
        period="470–399 a.C.",
        # escultura ao centro, céu acima; colocar texto na faixa inferior
        text_box=(0.05, 0.68, 0.90, 0.28),
    ),
    PhilosopherData(
        key="tales_mileto",
        display_name="Tales de Mileto",
        aliases=["tales", "mileto", "tales_mileto", "thales"],
        filename="tales_mileto.jpg",
        period="624–546 a.C.",
        # rosto ocupa quase tudo; cantos inferiores são mais escuros
        text_box=(0.03, 0.70, 0.94, 0.27),
    ),
]

# Fast lookup: alias → PhilosopherData
_ALIAS_MAP: dict[str, PhilosopherData] = {}
for _p in PHILOSOPHERS:
    for _alias in _p.aliases:
        _ALIAS_MAP[_alias.lower().replace(" ", "_")] = _p


def get_philosopher(name: str | None) -> PhilosopherData | None:
    """
    Return a PhilosopherData for the given name/alias, or None if not found.
    Pass None (or an empty string) to trigger random selection.
    """
    if not name:
        return None
    return _ALIAS_MAP.get(name.lower().replace(" ", "_"))
