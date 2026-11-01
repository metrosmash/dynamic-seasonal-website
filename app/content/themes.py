from __future__ import annotations

import hashlib
from dataclasses import dataclass


@dataclass(frozen=True)
class Palette:
    bg: str
    text: str
    muted: str
    link: str
    accent: str
    surface: str


@dataclass(frozen=True)
class Theme:
    id: str
    description: str
    heading_font: str
    accent_font: str
    banner: str
    light: Palette
    dark: Palette
    defaults: dict[str, tuple[tuple[str, str], ...]]


THEMES: dict[str, Theme] = {
    "haunted-library": Theme(
        "haunted-library", "a candlelit old library in deep plum and antique gold",
        "IM Fell English", "UnifrakturCook", "Whispers from the old library",
        Palette("#f4efe4", "#302637", "#625965", "#563b74", "#563b74", "#fffaf0"),
        Palette("#17111d", "#f2eaf5", "#c5b9ca", "#d9b6ff", "#d9b6ff", "#282030"),
        {"low": (("cobweb", "top-left"),), "medium": (("cobweb", "top-left"), ("candle", "footer")), "high": (("cobweb", "top-left"), ("candle", "footer"), ("ghost", "float"))},
    ),
    "graveyard-fog": Theme(
        "graveyard-fog", "a misty graveyard in slate, silver, and moss",
        "Special Elite", "IM Fell English", "A little fog, a little folklore",
        Palette("#edf0eb", "#26302c", "#56615b", "#365c4d", "#365c4d", "#f9fbf7"),
        Palette("#141a18", "#e7eee9", "#b3c1b8", "#a9d8bd", "#a9d8bd", "#222c27"),
        {"low": (("moon", "top-right"),), "medium": (("moon", "top-right"), ("tombstone", "footer")), "high": (("moon", "top-right"), ("tombstone", "footer"), ("crow", "margin-right"))},
    ),
    "witchs-kitchen": Theme(
        "witchs-kitchen", "an herbal witch's kitchen in forest green and violet",
        "Eater", "Metal Mania", "Brewing up something delightful",
        Palette("#eff2e7", "#283126", "#58634f", "#435b2a", "#435b2a", "#fbfcf5"),
        Palette("#151b13", "#eaf0e4", "#b8c5ae", "#c4df91", "#c4df91", "#252e21"),
        {"low": (("bat", "top-left"),), "medium": (("bat", "top-left"), ("pumpkin", "footer")), "high": (("bat", "top-left"), ("pumpkin", "footer"), ("spider", "top-right"))},
    ),
    "pumpkin-patch": Theme(
        "pumpkin-patch", "a warm autumn harvest with pumpkins and candlelight",
        "IM Fell English", "Creepster", "Welcome to the pumpkin patch",
        Palette("#fff3df", "#392417", "#72573f", "#754016", "#754016", "#fffaf0"),
        Palette("#1b100a", "#f5e6d5", "#cdb59c", "#ffb36b", "#ffb36b", "#2b1b12"),
        {"low": (("moon", "top-right"),), "medium": (("moon", "top-right"), ("pumpkin", "footer")), "high": (("moon", "top-right"), ("pumpkin", "footer"), ("bat", "float"))},
    ),
    "blood-moon": Theme(
        "blood-moon", "a dramatic crimson moon against charcoal and rose",
        "Nosifer", "Eater", "Under the blood moon",
        Palette("#f7eceb", "#351f24", "#71575b", "#792c3b", "#792c3b", "#fff7f5"),
        Palette("#1c1014", "#f4e5e7", "#cdb5b9", "#ff9daa", "#ff9daa", "#2d1a20"),
        {"low": (("moon", "top-right"),), "medium": (("moon", "top-right"), ("cobweb", "footer")), "high": (("moon", "top-right"), ("cobweb", "footer"), ("bat", "float"))},
    ),
    "cobweb-attic": Theme(
        "cobweb-attic", "a dusty attic in parchment, charcoal, and silver",
        "Special Elite", "Butcherman", "Something stirs in the attic",
        Palette("#f1eee8", "#292b30", "#5a5d64", "#414a59", "#414a59", "#fbfaf6"),
        Palette("#151619", "#e9e9eb", "#b8b8bf", "#c7c9e2", "#c7c9e2", "#24252a"),
        {"low": (("cobweb", "top-left"),), "medium": (("cobweb", "top-left"), ("spider", "top-right")), "high": (("cobweb", "top-left"), ("spider", "top-right"), ("ghost", "float"))},
    ),
    "midnight-carnival": Theme(
        "midnight-carnival", "a midnight carnival in ink blue, gold, and magenta",
        "Metal Mania", "Creepster", "Step right up after dark",
        Palette("#f2eef9", "#28213b", "#5e5672", "#594287", "#594287", "#fcfaff"),
        Palette("#14111e", "#eee9f8", "#bdb5ce", "#e2a8ff", "#e2a8ff", "#241d32"),
        {"low": (("bat", "top-right"),), "medium": (("bat", "top-right"), ("pumpkin", "footer")), "high": (("bat", "top-right"), ("pumpkin", "footer"), ("ghost", "float"))},
    ),
    "spooky-forest": Theme(
        "spooky-forest", "a moonlit forest in pine, amber, and deep green",
        "Eater", "UnifrakturCook", "Take the winding forest path",
        Palette("#edf2e8", "#263229", "#536451", "#365a37", "#365a37", "#f8fbf4"),
        Palette("#111912", "#e8f0e5", "#b6c6b3", "#a6d78e", "#a6d78e", "#202b21"),
        {"low": (("crow", "header"),), "medium": (("crow", "header"), ("cobweb", "footer")), "high": (("crow", "margin-right"), ("cobweb", "footer"), ("bat", "float"))},
    ),
    "vampire-lounge": Theme(
        "vampire-lounge", "a velvet lounge in burgundy, black, and antique rose",
        "UnifrakturCook", "Nosifer", "An evening at the vampire lounge",
        Palette("#f5ecee", "#321e25", "#70575d", "#742d42", "#742d42", "#fff8f8"),
        Palette("#1b1015", "#f3e6e9", "#cbb5bc", "#ffa5bd", "#ffa5bd", "#2b1b22"),
        {"low": (("spider", "top-right"),), "medium": (("spider", "top-right"), ("bat", "header")), "high": (("candle", "footer"), ("bat", "header"), ("spider", "top-left"))},
    ),
    "ghost-ship": Theme(
        "ghost-ship", "a haunted ship at sea in deep navy, sea glass, and fog",
        "IM Fell English", "Eater", "All aboard the ghost ship",
        Palette("#eaf1f2", "#243238", "#52666c", "#315964", "#315964", "#f7fbfc"),
        Palette("#10181c", "#e5eff2", "#b0c2c8", "#a3d8e5", "#a3d8e5", "#1f2a30"),
        {"low": (("moon", "top-right"),), "medium": (("moon", "top-right"), ("ghost", "before-h2:1")), "high": (("moon", "top-right"), ("ghost", "before-h2:1"), ("cobweb", "top-left"))},
    ),
}

APPROVED_FONTS = {
    "Creepster",
    "Nosifer",
    "Eater",
    "Butcherman",
    "Metal Mania",
    "Special Elite",
    "IM Fell English",
    "UnifrakturCook",
}


def select_theme(source_id: str, intensity: str, variant: int = 0) -> Theme:
    seed = f"{source_id}\0{intensity}\0{variant}".encode("utf-8")
    index = int.from_bytes(hashlib.sha256(seed).digest()[:8], "big") % len(THEMES)
    return tuple(THEMES.values())[index]
