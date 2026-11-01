from __future__ import annotations

from app.content.themes import THEMES
from app.parser import DesignResult


def code_only_design(theme_id: str, tier: str) -> DesignResult:
    """Return curated placements for provider-free or failed model responses."""
    theme = THEMES[theme_id]
    return DesignResult(theme_id, None, theme.defaults[tier], "", ())
