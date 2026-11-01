from __future__ import annotations

from functools import lru_cache
from importlib.resources import files


DECORATIONS = {
    "bat": {
        "slots": {"top-left", "top-right", "header", "margin-left", "margin-right", "float"},
        "size": 72,
        "animation": "hw-flap",
        "svg_file": "bat.svg",
    },
    "cobweb": {
        "slots": {"top-left", "top-right", "footer"},
        "size": 92,
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
        "size": 112,
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


@lru_cache(maxsize=len(DECORATIONS))
def load_decoration_svg(name: str) -> str:
    asset_name = DECORATIONS[name]["svg_file"]
    return files("app.content.decor").joinpath(asset_name).read_text(encoding="utf-8")
