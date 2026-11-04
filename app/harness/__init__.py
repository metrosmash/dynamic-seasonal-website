from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class HarnessEdit:
    """One validated agent edit. Only DOM+CSS kinds are enabled in v1."""

    kind: str  # "theme" | "accent" | "placements" | "css" | "reset"
    theme_id: str = ""
    accent: str = ""
    placements: tuple[tuple[str, str], ...] = ()
    css: str = ""


@dataclass(frozen=True)
class HarnessSnapshot:
    html: str
    theme_id: str
    placements: tuple[tuple[str, str], ...]
    css: str
    warning: str = ""
    live_view_url: str = ""
    session_id: str = ""
    harness: str = "local"


@dataclass
class HarnessState:
    source_html: str = ""
    source_url: str = ""
    theme_id: str = "pumpkin-patch"
    intensity: str = "medium"
    accent: str | None = None
    placements: list[tuple[str, str]] = field(default_factory=list)
    css: str = ""
    warnings: list[str] = field(default_factory=list)


class HarnessError(ValueError):
    pass


class BaseHarness:
    name = "local"

    def load(
        self,
        source_html: str,
        source_url: str,
        theme_id: str,
        intensity: str,
    ) -> None:
        raise NotImplementedError

    def apply(self, edit: HarnessEdit) -> str:
        """Apply one edit, returning a warning ("" when clean)."""
        raise NotImplementedError

    def snapshot(self) -> HarnessSnapshot:
        raise NotImplementedError

    def close(self) -> None:
        raise NotImplementedError


def create_harness(config: dict, harness: str = "") -> BaseHarness:
    """Pick the harness backend. "auto" uses Browserbase when a key exists."""
    from app.harness.browserbase import BrowserbaseHarness
    from app.harness.local import LocalHarness

    requested = (harness or str(config.get("HARNESS_PROVIDER", "auto"))).lower()
    if requested not in {"auto", "local", "browserbase"}:
        raise HarnessError("Unknown harness provider.")
    if requested == "local":
        return LocalHarness()
    if requested == "browserbase":
        return BrowserbaseHarness(config)
    if config.get("BROWSERBASE_API_KEY"):
        try:
            return BrowserbaseHarness(config)
        except HarnessError:
            return LocalHarness()
    return LocalHarness()
