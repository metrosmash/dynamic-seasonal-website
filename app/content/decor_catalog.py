from __future__ import annotations

import re
from functools import lru_cache
from importlib.resources import files


# "animation" is the catalog's name for the motion; decor_css.py defines it and
# decor_markup.py turns it into a class (hw-flap -> hw-on-flap).
DECORATIONS = {
    "bat": {
        "slots": {"top-left", "top-right", "header", "margin-left", "margin-right", "float"},
        "size": 72,
        "animation": "hw-flap",
        "svg_file": "bat.svg",
    },
    "cobweb": {
        "slots": {"top-left", "top-right", "footer"},
        "size": 150,  # corner webs show one quadrant, so the box is bigger than the visible part
        "animation": "",
        "svg_file": "cobweb.svg",
    },
    "pumpkin": {
        "slots": {"before-h2", "footer", "margin-left", "margin-right"},
        "size": 76,
        "animation": "hw-glow",
        "svg_file": "pumpkin.svg",
    },
    "ghost": {
        "slots": {"margin-left", "margin-right", "before-h2", "float"},
        "size": 72,
        "animation": "hw-bob",
        "svg_file": "ghost.svg",
    },
    "spider": {
        "slots": {"top-left", "top-right", "header"},
        "size": 66,
        "animation": "hw-sway",
        "svg_file": "spider.svg",
    },
    "moon": {
        "slots": {"top-right", "header"},
        "size": 72,
        "animation": "",
        "svg_file": "moon.svg",
    },
    "tombstone": {
        "slots": {"footer", "before-h2"},
        "size": 78,
        "animation": "",
        "svg_file": "tombstone.svg",
    },
    "candle": {
        "slots": {"margin-left", "margin-right", "footer"},
        "size": 58,
        "animation": "hw-flicker",
        "svg_file": "candle.svg",
    },
    "crow": {
        "slots": {"header", "margin-right"},
        "size": 76,
        "animation": "",
        "svg_file": "crow.svg",
    },
    "bone-divider": {
        "slots": {"before-h2"},
        "size": 220,  # horizontal divider (viewBox 240x36)
        "animation": "",
        "svg_file": "bone-divider.svg",
    },
}

SLOTS_BY_TIER = {
    "low": {"top-left", "top-right", "header"},
    "medium": {
        "top-left", "top-right", "header", "before-h2", "footer",
        "margin-left", "margin-right",
    },
    "high": set().union(*(entry["slots"] for entry in DECORATIONS.values())),
}


def split_slot(slot: str) -> tuple[str, int | None]:
    """'before-h2:2' -> ('before-h2', 2); 'top-left' -> ('top-left', None)."""
    base, _, index = slot.strip().lower().partition(":")
    return base, int(index) if index.strip().isdigit() else None


def is_valid_placement(name: str, slot: str, tier: str) -> bool:
    """True if `name` exists, may use this slot, and the tier allows the slot."""
    entry = DECORATIONS.get(name)
    if entry is None or tier not in SLOTS_BY_TIER:
        return False
    base, index = split_slot(slot)
    if base not in entry["slots"] or base not in SLOTS_BY_TIER[tier]:
        return False
    if base == "before-h2" and index is not None and index < 1:
        return False
    return True


# The files are ours, but this stops a bad file (or a copied-in one) from reaching a page.
_FORBIDDEN_SVG = re.compile(
    r"<script|<foreignObject|<image|<style|<use|\son\w+\s*=|javascript:|href\s*=|\sid\s*=|url\(",
    re.I,
)


def validate_svg(name: str, text: str) -> None:
    if "viewBox" not in text:
        raise ValueError(f"{name}: missing viewBox")
    if _FORBIDDEN_SVG.search(text):
        raise ValueError(f"{name}: contains a forbidden construct")


@lru_cache(maxsize=len(DECORATIONS))
def load_decoration_svg(name: str) -> str:
    asset_name = DECORATIONS[name]["svg_file"]
    text = files("app.content.decor").joinpath(asset_name).read_text(encoding="utf-8")
    validate_svg(asset_name, text)
    return text.strip()
