from __future__ import annotations

import re

from app.content.decor_catalog import is_valid_placement
from app.content.themes import THEMES
from app.harness import BaseHarness, HarnessEdit, HarnessSnapshot, HarnessState
from app.steps.assemble import assemble_page
from app.steps.sanitize_css import sanitize_css


class LocalHarness(BaseHarness):
    """In-process DOM+CSS harness. No network, no JS execution.

    This is the default backend and the edit validator for every backend:
    Browserbase sessions reuse this logic so agent edits stay auditable even
    when rendering happens in the cloud.
    """

    name = "local"

    def __init__(self) -> None:
        self._state = HarnessState()

    def load(
        self,
        source_html: str,
        source_url: str,
        theme_id: str,
        intensity: str,
    ) -> None:
        if intensity not in {"low", "medium", "high"}:
            raise ValueError("Choose a valid decoration intensity.")
        if theme_id not in THEMES:
            raise ValueError("Unknown theme.")
        if "<script" in source_html.lower():
            raise ValueError("Harness input must be script-free prepared HTML.")
        self._state = HarnessState(
            source_html=source_html,
            source_url=source_url,
            theme_id=theme_id,
            intensity=intensity,
            placements=list(THEMES[theme_id].defaults[intensity]),
        )

    def apply(self, edit: HarnessEdit) -> str:
        state = self._state
        if not state.source_html:
            raise ValueError("Harness has no page loaded.")
        if edit.kind == "reset":
            state.accent = None
            state.css = ""
            state.placements = list(THEMES[state.theme_id].defaults[state.intensity])
            return ""
        if edit.kind == "theme":
            if edit.theme_id not in THEMES:
                return f"Ignored unknown theme {edit.theme_id!r}."
            state.theme_id = edit.theme_id
            state.placements = list(THEMES[state.theme_id].defaults[state.intensity])
            return ""
        if edit.kind == "accent":
            if not re.fullmatch(r"#[0-9a-f]{6}", edit.accent, re.I):
                return "Ignored invalid accent color."
            state.accent = edit.accent.lower()
            return ""
        if edit.kind == "placements":
            accepted: list[tuple[str, str]] = []
            for name, slot in edit.placements:
                if is_valid_placement(name, slot, state.intensity):
                    accepted.append((name, slot))
            if not accepted:
                return "Ignored placements: none were valid for this intensity."
            state.placements = accepted
            if len(accepted) < len(edit.placements):
                return "Some placements were invalid and were skipped."
            return ""
        if edit.kind == "css":
            result = sanitize_css(edit.css, state.intensity)
            if result.rejected or (not result.css and edit.css.strip()):
                return "Ignored CSS: it did not meet the safety rules."
            state.css = result.css
            if result.dropped_rules:
                return "Some CSS rules were removed by the safety filter."
            return ""
        return f"Ignored unknown edit kind {edit.kind!r}."

    def snapshot(self) -> HarnessSnapshot:
        state = self._state
        if not state.source_html:
            raise ValueError("Harness has no page loaded.")
        html = assemble_page(
            state.source_html,
            source_url=state.source_url,
            accent=state.accent,
            placements=tuple(state.placements),
            theme_id=state.theme_id,
            intensity=state.intensity,
            model_css=state.css,
        )
        return HarnessSnapshot(
            html=html,
            theme_id=state.theme_id,
            placements=tuple(state.placements),
            css=state.css,
            warning=" ".join(state.warnings),
            harness=self.name,
        )

    def close(self) -> None:
        self._state = HarnessState()
