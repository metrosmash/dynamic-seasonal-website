"""Seasonal redesign proof-of-concept for the Sample Cafe demo site.

This demo uses toggles. A real system would trigger seasonal redesigns from a
calendar (e.g. automatically on December 1 for Christmas) instead of user clicks.
"""

from __future__ import annotations

import hashlib
import html
import html.parser
import json
import re
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path

import tinycss2
from flask import current_app, jsonify, redirect, render_template, request
from tinycss2.ast import AtRule, Declaration, QualifiedRule

from app import llm
from app import wiki


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SITE_DIR = ROOT / "seasonal" / "site"
DEFAULT_ORIGINAL_DIR = ROOT / "seasonal" / "original"

# The agent may only ever change these files inside the site folder.
FILES = ("index.html", "style.css", "script.js")
HISTORY_LIMIT = 5
MAX_FILE_BYTES = 200 * 1024
MAX_SEASON_CHARS = 80

BANNER_TEXT = (
    "Proof of concept demo: seasonal redesigns are triggered by toggles here. "
    "A production system would use a calendar to apply seasonal changes automatically."
)

# Passed to the agent for every redesign (requirement 5).
AGENT_INSTRUCTION = (
    "Redesign this website for the season: {season}. You have creative freedom over colors, "
    "typography, layout, decorative imagery, animations, and the tone of the hero and section copy. "
    "Keep the navigation and all sections (Home, Menu, About, Contact) working and present. "
    "Keep the contact section functional. Do not invent real-looking addresses, phone numbers, "
    "prices, or claims. Any sample text should stay clearly placeholder content. "
    "Keep text contrast accessible (WCAG AA minimum). Keep the page usable on phones. "
    "Return the complete updated files."
)

REQUIRED_IDS = ("home", "menu", "about", "contact")
REQUIRED_NAV_TARGETS = ("#home", "#menu", "#about", "#contact")


class SeasonalError(ValueError):
    pass


class AgentError(SeasonalError):
    pass


class ValidationError(SeasonalError):
    def __init__(self, errors: list[str]) -> None:
        super().__init__("; ".join(errors) if errors else "Invalid seasonal files.")
        self.errors = errors


# ---------------------------------------------------------------------------
# Site folder access (guardrail: nothing outside the site folder is writable)
# ---------------------------------------------------------------------------

def site_dir(config: dict) -> Path:
    return Path(config.get("SEASONAL_SITE_DIR", DEFAULT_SITE_DIR))


def original_dir(config: dict) -> Path:
    return Path(config.get("SEASONAL_ORIGINAL_DIR", DEFAULT_ORIGINAL_DIR))


def resolve_site_path(config: dict, name: str) -> Path:
    """Resolve a site file name, refusing anything outside the site folder."""
    if name not in FILES:
        raise SeasonalError(f"Refusing to touch a file outside the site folder: {name!r}.")
    root = site_dir(config).resolve()
    target = (site_dir(config) / name).resolve()
    if target != root and root not in target.parents:
        raise SeasonalError(f"Refusing to touch a file outside the site folder: {name!r}.")
    return target


def read_files(folder: Path) -> dict[str, str]:
    return {name: (folder / name).read_text(encoding="utf-8") for name in FILES}


def write_files(config: dict, files: dict[str, str]) -> None:
    """Write only the known site files; unknown agent-supplied names are dropped."""
    folder = site_dir(config)
    folder.mkdir(parents=True, exist_ok=True)
    for name in FILES:
        resolve_site_path(config, name).write_text(files[name], encoding="utf-8")


def load_original(config: dict) -> dict[str, str]:
    return read_files(original_dir(config))


def ensure_seeded(config: dict) -> None:
    """Seed the working site from the preserved original when files are missing."""
    folder = site_dir(config)
    missing = [name for name in FILES if not (folder / name).exists()]
    if not missing:
        return
    originals = load_original(config)
    folder.mkdir(parents=True, exist_ok=True)
    for name in missing:
        resolve_site_path(config, name).write_text(originals[name], encoding="utf-8")


# ---------------------------------------------------------------------------
# State and version history (in-memory; restart clears it back to the original)
# ---------------------------------------------------------------------------

def _state(config: dict) -> dict:
    state = config.get("SEASONAL")
    if state is None:
        ensure_seeded(config)
        state = {
            "entries": [{"season": "Original", "files": read_files(site_dir(config))}],
            "index": 0,
            "lock": threading.RLock(),
        }
        config["SEASONAL"] = state
    return state


def current_entry(config: dict) -> dict:
    state = _state(config)
    return state["entries"][state["index"]]


def summarize(config: dict) -> dict:
    state = _state(config)
    entries = state["entries"]
    index = state["index"]
    return {
        "season": entries[index]["season"],
        "history": [entry["season"] for entry in entries],
        "index": index,
        "can_back": index > 0,
        "can_forward": index < len(entries) - 1,
    }


def apply_files(config: dict, season: str, files: dict[str, str]) -> dict:
    """Validate-then-apply is done by callers; this records history and writes disk."""
    state = _state(config)
    with state["lock"]:
        entries = state["entries"][: state["index"] + 1]
        entries.append({"season": season, "files": dict(files)})
        entries = entries[-HISTORY_LIMIT:]
        state["entries"] = entries
        state["index"] = len(entries) - 1
        write_files(config, files)
        return summarize(config)


def step(config: dict, delta: int) -> dict:
    state = _state(config)
    with state["lock"]:
        index = min(max(state["index"] + delta, 0), len(state["entries"]) - 1)
        state["index"] = index
        write_files(config, state["entries"][index]["files"])
        return summarize(config)


def reset_to_original(config: dict) -> dict:
    state = _state(config)
    with state["lock"]:
        originals = load_original(config)
        state["entries"] = [{"season": "Original", "files": originals}]
        state["index"] = 0
        write_files(config, originals)
        return summarize(config)


# ---------------------------------------------------------------------------
# Validation (invalid agent output keeps the previous version plus an error)
# ---------------------------------------------------------------------------

class _Structure(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.ids: set[str] = set()
        self.nav_hrefs: list[str] = []
        self._nav_depth = 0
        self.has_contact_form = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        found = dict(attrs)
        if tag == "nav":
            self._nav_depth += 1
        if tag == "a" and self._nav_depth and found.get("href"):
            self.nav_hrefs.append(str(found["href"]))
        element_id = found.get("id")
        if element_id:
            self.ids.add(str(element_id))
            if tag == "form" and element_id == "contact-form":
                self.has_contact_form = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "nav" and self._nav_depth:
            self._nav_depth -= 1


def validate_html(text: object) -> list[str]:
    errors: list[str] = []
    if not isinstance(text, str) or not text.strip():
        return ["index.html is empty."]
    if len(text.encode("utf-8")) > MAX_FILE_BYTES:
        return ["index.html exceeds the size limit."]
    lowered = text.lower()
    if "<html" not in lowered or "</html>" not in lowered:
        errors.append("index.html must be a complete HTML document.")
    parser = _Structure()
    try:
        parser.feed(text)
        parser.close()
    except Exception as exc:
        return [f"index.html could not be parsed: {exc}."]
    missing = [f"#{name}" for name in REQUIRED_IDS if name not in parser.ids]
    if missing:
        errors.append("index.html is missing required sections: " + ", ".join(missing) + ".")
    missing_nav = [target for target in REQUIRED_NAV_TARGETS if target not in parser.nav_hrefs]
    if missing_nav:
        errors.append("index.html navigation must link to: " + ", ".join(missing_nav) + ".")
    if not parser.has_contact_form:
        errors.append("index.html must keep a working contact form (form#contact-form).")
    return errors


def _balanced_blocks(text: str) -> bool:
    depth = 0
    quote: str | None = None
    escaped = False
    in_comment = False
    index = 0
    while index < len(text):
        char = text[index]
        following = text[index + 1] if index + 1 < len(text) else ""
        if in_comment:
            if char == "*" and following == "/":
                in_comment = False
                index += 2
                continue
        elif quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
        elif char == "/" and following == "*":
            in_comment = True
            index += 2
            continue
        elif char in {"'", '"'}:
            quote = char
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth < 0:
                return False
        index += 1
    return depth == 0 and not quote and not in_comment


def _css_has_error(tokens: list[object]) -> bool:
    for token in tokens:
        token_type = getattr(token, "type", None)
        if token_type == "error":
            return True
        if isinstance(token, QualifiedRule):
            declarations = tinycss2.parse_declaration_list(
                token.content, skip_comments=True, skip_whitespace=True
            )
            if any(getattr(item, "type", None) == "error" for item in declarations):
                return True
            if any(
                isinstance(item, Declaration) and not item.name for item in declarations
            ):
                return True
        elif isinstance(token, AtRule) and token.content is not None:
            nested = tinycss2.parse_rule_list(
                token.content, skip_comments=True, skip_whitespace=True
            )
            if _css_has_error(nested):
                return True
    return False


def validate_css(text: object) -> list[str]:
    if not isinstance(text, str):
        return ["style.css must be text."]
    if not text.strip():
        return []
    if len(text.encode("utf-8")) > MAX_FILE_BYTES:
        return ["style.css exceeds the size limit."]
    if not _balanced_blocks(text):
        return ["style.css has unbalanced braces, quotes, or comments."]
    try:
        rules = tinycss2.parse_stylesheet(text, skip_comments=True, skip_whitespace=True)
    except Exception as exc:
        return [f"style.css could not be parsed: {exc}."]
    if _css_has_error(rules):
        return ["style.css contains invalid CSS."]
    return []


def _balanced_js(text: str) -> bool:
    stack: list[str] = []
    pairs = {")": "(", "]": "[", "}": "{"}
    state = "code"
    quote = ""
    index = 0
    while index < len(text):
        char = text[index]
        following = text[index + 1] if index + 1 < len(text) else ""
        if state == "line-comment":
            if char == "\n":
                state = "code"
        elif state == "block-comment":
            if char == "*" and following == "/":
                state = "code"
                index += 1
        elif state == "string":
            if char == "\\":
                index += 1
            elif char == quote:
                state = "code"
            elif quote != "`" and char == "\n":
                return False
        elif char == "/" and following == "/":
            state = "line-comment"
            index += 1
        elif char == "/" and following == "*":
            state = "block-comment"
            index += 1
        elif char in {"'", '"', "`"}:
            state = "string"
            quote = char
        elif char in "([":
            stack.append(char)
        elif char == "{":
            stack.append(char)
        elif char in pairs:
            if not stack or stack.pop() != pairs[char]:
                return False
        index += 1
    return state in {"code", "line-comment"} and not stack


def _check_js_with_node(text: str) -> str | None:
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=True) as handle:
        handle.write(text)
        handle.flush()
        proc = subprocess.run(
            ["node", "--check", handle.name],
            capture_output=True,
            text=True,
            timeout=10,
        )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).strip().splitlines()
        return (detail[-1] if detail else "node --check failed")[:300]
    return None


def validate_js(text: object) -> list[str]:
    if not isinstance(text, str):
        return ["script.js must be text."]
    if not text.strip():
        return []
    if len(text.encode("utf-8")) > MAX_FILE_BYTES:
        return ["script.js exceeds the size limit."]
    if shutil.which("node"):
        try:
            failure = _check_js_with_node(text)
        except (OSError, subprocess.SubprocessError):
            failure = None
        if failure:
            return [f"script.js is not valid JavaScript: {failure}."]
        return []
    # No JS engine available: fall back to a delimiter-balance check (PoC).
    if not _balanced_js(text):
        return ["script.js has unbalanced brackets, quotes, or comments."]
    return []


def validate_files(files: dict[str, str]) -> None:
    errors: list[str] = []
    for name in FILES:
        if name not in files or not isinstance(files[name], str):
            errors.append(f"Agent output is missing {name}.")
    if errors:
        raise ValidationError(errors)
    errors.extend(validate_html(files["index.html"]))
    errors.extend(validate_css(files["style.css"]))
    errors.extend(validate_js(files["script.js"]))
    if errors:
        raise ValidationError(errors)


# ---------------------------------------------------------------------------
# Built-in PoC "agent": deterministic seasonal redesigns (no network needed)
# ---------------------------------------------------------------------------

def _normalize_season(season: str) -> str:
    cleaned = season.strip().lower().replace("’", "'").replace("‘", "'")
    return " ".join(cleaned.split())


def canonical_season(season: str) -> str:
    """Map a season name to a known design, or 'custom' for open input."""
    key = _normalize_season(season)
    nospace = key.replace("'", "")
    candidates = {key, nospace}
    inner = re.search(r"\(([^)]+)\)", key)
    if inner:
        candidates.add(inner.group(1).strip())
        candidates.add(key.split("(", 1)[0].strip())
    if "christmas" in key or "xmas" in key:
        return "christmas"
    if "halloween" in key or "spooky" in key:
        return "halloween"
    if "worker" in nospace:
        return "workers day"
    if "children" in nospace or "kids day" in nospace:
        return "childrens day"
    if any(word in candidates for word in ("eid", "sallah", "eid al-fitr", "eid al fitr")):
        return "eid"
    if "eid" in key or "sallah" in key or "fitr" in key:
        return "eid"
    return "custom"


def _custom_hue(season: str) -> int:
    digest = hashlib.md5(_normalize_season(season).encode("utf-8")).hexdigest()
    return int(digest[:4], 16) % 360


# All body text stays dark-on-light and headers/buttons stay white-on-dark so
# contrast meets WCAG AA; bright colors are decoration only, never body text.
SEASON_DESIGNS = {
    "christmas": {
        "page_bg": "#f6f1e5",
        "ink": "#232323",
        "header_bg": "#123f2a",
        "accent": "#a11a12",
        "panel_border": "#123f2a",
        "soft_panel": "#fffdf6",
        "font": 'Georgia, "Times New Roman", serif',
        "kicker": "Sample Christmas heading (placeholder)",
        "hero_title": "Sample Café at Christmas (sample text)",
        "hero_text": (
            "Sample seasonal paragraph (placeholder): this fictional café blurb shows "
            "what a Christmas redesign could look like. It makes no real claims."
        ),
        "menu_note": "Sample Christmas menu items for illustration only. No prices: placeholder content.",
        "menu_items": [
            ("Sample pine pastry A", "sample Christmas description, placeholder item."),
            ("Sample pine pastry B", "sample Christmas description, placeholder item."),
            ("Sample winter drink A", "sample Christmas description, placeholder item."),
            ("Sample winter drink B", "sample Christmas description, placeholder item."),
        ],
        "about_text": (
            "Sample Christmas paragraph (placeholder): Sample Café is a fictional café. "
            "Nothing here describes a real business, place, or event."
        ),
        "decor_css": (
            ".season-decor {\n"
            "  height: 1.4rem;\n"
            "  border-radius: 999px;\n"
            "  background: repeating-linear-gradient(90deg, #a11a12 0 1.2rem, #fffdf6 1.2rem 2.4rem, #123f2a 2.4rem 3.6rem);\n"
            "  border: 2px solid #123f2a;\n"
            "}\n"
        ),
    },
    "halloween": {
        "page_bg": "#f5eee4",
        "ink": "#232323",
        "header_bg": "#241031",
        "accent": "#8f3c00",
        "panel_border": "#241031",
        "soft_panel": "#fffdf8",
        "font": 'Georgia, "Times New Roman", serif',
        "kicker": "Sample Halloween heading (placeholder)",
        "hero_title": "Sample Café at Halloween (sample text)",
        "hero_text": (
            "Sample seasonal paragraph (placeholder): this fictional café blurb shows "
            "what a Halloween redesign could look like. It makes no real claims."
        ),
        "menu_note": "Sample Halloween menu items for illustration only. No prices: placeholder content.",
        "menu_items": [
            ("Sample pumpkin pastry A", "sample Halloween description, placeholder item."),
            ("Sample pumpkin pastry B", "sample Halloween description, placeholder item."),
            ("Sample autumn drink A", "sample Halloween description, placeholder item."),
            ("Sample autumn drink B", "sample Halloween description, placeholder item."),
        ],
        "about_text": (
            "Sample Halloween paragraph (placeholder): Sample Café is a fictional café. "
            "Nothing here describes a real business, place, or event."
        ),
        "decor_css": (
            ".season-decor {\n"
            "  height: 3.2rem;\n"
            "  border-radius: 10px;\n"
            "  border: 2px solid #241031;\n"
            "  background:\n"
            "    radial-gradient(circle at 82% 45%, #f2e6c9 0 1rem, rgba(242, 230, 201, 0) 1.1rem),\n"
            "    repeating-linear-gradient(90deg, #e8641b 0 1.6rem, #241031 1.6rem 3.2rem);\n"
            "}\n"
        ),
    },
    "workers day": {
        "page_bg": "#f3f1ec",
        "ink": "#232323",
        "header_bg": "#1f3a5f",
        "accent": "#8f1d22",
        "panel_border": "#1f3a5f",
        "soft_panel": "#ffffff",
        "font": '"Trebuchet MS", Verdana, sans-serif',
        "kicker": "Sample Workers' Day heading (placeholder)",
        "hero_title": "Sample Café on Workers' Day (sample text)",
        "hero_text": (
            "Sample seasonal paragraph (placeholder): this fictional café blurb shows "
            "what a Workers' Day redesign could look like. It makes no real claims."
        ),
        "menu_note": "Sample Workers' Day menu items for illustration only. No prices: placeholder content.",
        "menu_items": [
            ("Sample harvest pastry A", "sample Workers' Day description, placeholder item."),
            ("Sample harvest pastry B", "sample Workers' Day description, placeholder item."),
            ("Sample break-time drink A", "sample Workers' Day description, placeholder item."),
            ("Sample break-time drink B", "sample Workers' Day description, placeholder item."),
        ],
        "about_text": (
            "Sample Workers' Day paragraph (placeholder): Sample Café is a fictional café. "
            "Nothing here describes a real business, place, or event."
        ),
        "decor_css": (
            ".season-decor {\n"
            "  height: 1.6rem;\n"
            "  border-radius: 4px;\n"
            "  border: 2px solid #1f3a5f;\n"
            "  background: linear-gradient(180deg, #8f1d22 0 33%, #ffffff 33% 66%, #1f3a5f 66% 100%);\n"
            "}\n"
        ),
    },
    "childrens day": {
        "page_bg": "#fdf4e7",
        "ink": "#232323",
        "header_bg": "#0b5563",
        "accent": "#7c1a6d",
        "panel_border": "#0b5563",
        "soft_panel": "#ffffff",
        "font": '"Trebuchet MS", Verdana, sans-serif',
        "kicker": "Sample Children's Day heading (placeholder)",
        "hero_title": "Sample Café on Children's Day (sample text)",
        "hero_text": (
            "Sample seasonal paragraph (placeholder): this fictional café blurb shows "
            "what a Children's Day redesign could look like. It makes no real claims."
        ),
        "menu_note": "Sample Children's Day menu items for illustration only. No prices: placeholder content.",
        "menu_items": [
            ("Sample party pastry A", "sample Children's Day description, placeholder item."),
            ("Sample party pastry B", "sample Children's Day description, placeholder item."),
            ("Sample party drink A", "sample Children's Day description, placeholder item."),
            ("Sample party drink B", "sample Children's Day description, placeholder item."),
        ],
        "about_text": (
            "Sample Children's Day paragraph (placeholder): Sample Café is a fictional café. "
            "Nothing here describes a real business, place, or event."
        ),
        "decor_css": (
            ".season-decor {\n"
            "  height: 2.6rem;\n"
            "  border-radius: 999px;\n"
            "  border: 2px solid #0b5563;\n"
            "  background:\n"
            "    radial-gradient(circle at 12% 50%, #7c1a6d 0 0.45rem, rgba(0, 0, 0, 0) 0.5rem),\n"
            "    radial-gradient(circle at 37% 50%, #0b5563 0 0.45rem, rgba(0, 0, 0, 0) 0.5rem),\n"
            "    radial-gradient(circle at 62% 50%, #b25a00 0 0.45rem, rgba(0, 0, 0, 0) 0.5rem),\n"
            "    radial-gradient(circle at 87% 50%, #1d7a3a 0 0.45rem, rgba(0, 0, 0, 0) 0.5rem),\n"
            "    #ffffff;\n"
            "}\n"
        ),
    },
    "eid": {
        "page_bg": "#faf7ee",
        "ink": "#232323",
        "header_bg": "#0c4a3c",
        "accent": "#7a5c00",
        "panel_border": "#0c4a3c",
        "soft_panel": "#fffef9",
        "font": 'Georgia, "Times New Roman", serif',
        "kicker": "Sample Eid al-Fitr heading (placeholder)",
        "hero_title": "Sample Café at Eid al-Fitr (sample text)",
        "hero_text": (
            "Sample seasonal paragraph (placeholder): this fictional café blurb shows "
            "what an Eid al-Fitr redesign could look like. It makes no real claims."
        ),
        "menu_note": "Sample Eid menu items for illustration only. No prices: placeholder content.",
        "menu_items": [
            ("Sample festive pastry A", "sample Eid description, placeholder item."),
            ("Sample festive pastry B", "sample Eid description, placeholder item."),
            ("Sample festive drink A", "sample Eid description, placeholder item."),
            ("Sample festive drink B", "sample Eid description, placeholder item."),
        ],
        "about_text": (
            "Sample Eid al-Fitr paragraph (placeholder): Sample Café is a fictional café. "
            "Nothing here describes a real business, place, or event."
        ),
        "decor_css": (
            ".season-decor {\n"
            "  height: 3rem;\n"
            "  border-radius: 10px;\n"
            "  border: 2px solid #0c4a3c;\n"
            "  background:\n"
            "    radial-gradient(circle at 50% 42%, #d9b845 0 0.8rem, rgba(0, 0, 0, 0) 0.85rem),\n"
            "    radial-gradient(circle at 56% 36%, #0c4a3c 0 0.75rem, rgba(0, 0, 0, 0) 0.8rem),\n"
            "    repeating-linear-gradient(45deg, #0c4a3c 0 0.6rem, #14604f 0.6rem 1.2rem);\n"
            "}\n"
        ),
    },
}


def _custom_design(season: str) -> dict:
    hue = _custom_hue(season)
    label = " ".join(word.capitalize() for word in _normalize_season(season).split()) or season.strip()
    return {
        "page_bg": f"hsl({hue}, 28%, 95%)",
        "ink": "#232323",
        "header_bg": f"hsl({hue}, 48%, 22%)",
        "accent": f"hsl({hue}, 62%, 27%)",
        "panel_border": f"hsl({hue}, 48%, 22%)",
        "soft_panel": "#ffffff",
        "font": 'Georgia, "Times New Roman", serif',
        "kicker": f"Sample {label} heading (placeholder)",
        "hero_title": f"Sample Café celebrates {label} (sample text)",
        "hero_text": (
            "Sample seasonal paragraph (placeholder): this fictional café blurb shows "
            f"what a {label} redesign could look like. It makes no real claims."
        ),
        "menu_note": f"Sample {label} menu items for illustration only. No prices: placeholder content.",
        "menu_items": [
            (f"Sample {label} pastry A", f"sample {label} description, placeholder item."),
            (f"Sample {label} pastry B", f"sample {label} description, placeholder item."),
            (f"Sample {label} drink A", f"sample {label} description, placeholder item."),
            (f"Sample {label} drink B", f"sample {label} description, placeholder item."),
        ],
        "about_text": (
            f"Sample {label} paragraph (placeholder): Sample Café is a fictional café. "
            "Nothing here describes a real business, place, or event."
        ),
        "decor_css": (
            ".season-decor {\n"
            "  height: 1.8rem;\n"
            "  border-radius: 999px;\n"
            f"  border: 2px solid hsl({hue}, 48%, 22%);\n"
            "  background:\n"
            f"    radial-gradient(circle at 25% 50%, hsl({hue}, 62%, 27%) 0 0.4rem, rgba(0, 0, 0, 0) 0.45rem),\n"
            f"    radial-gradient(circle at 50% 50%, hsl({hue}, 62%, 27%) 0 0.4rem, rgba(0, 0, 0, 0) 0.45rem),\n"
            f"    radial-gradient(circle at 75% 50%, hsl({hue}, 62%, 27%) 0 0.4rem, rgba(0, 0, 0, 0) 0.45rem),\n"
            "    #ffffff;\n"
            "}\n"
        ),
    }


def design_locally(season: str) -> dict[str, str]:
    """Deterministic stand-in for the LLM agent used by the default providers."""
    key = canonical_season(season)
    design = SEASON_DESIGNS[key] if key != "custom" else _custom_design(season)
    safe_season = html.escape(season.strip(), quote=True)

    def esc(value: str) -> str:
        return html.escape(value, quote=True)

    menu_html = "\n".join(
        f'        <li><strong>{esc(name)}</strong> — {esc(desc)}</li>'
        for name, desc in design["menu_items"]
    )
    index_html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Sample Café: {safe_season} (placeholder demo site)</title>
  <link rel="stylesheet" href="./style.css">
</head>
<body data-season="{esc(key)}">
  <header class="site-header">
    <p class="brand">Sample Café</p>
    <nav class="site-nav" aria-label="Main navigation">
      <a href="#home">Home</a>
      <a href="#menu">Menu</a>
      <a href="#about">About</a>
      <a href="#contact">Contact</a>
    </nav>
  </header>

  <main>
    <section id="home" class="hero">
      <div class="season-decor" aria-hidden="true"></div>
      <p class="season-kicker">{esc(design["kicker"])}</p>
      <h1>{esc(design["hero_title"])}</h1>
      <p>{esc(design["hero_text"])}</p>
      <p><a class="button" href="#menu">See the sample menu</a></p>
    </section>

    <section id="menu" class="panel">
      <h2>Menu</h2>
      <p>{esc(design["menu_note"])}</p>
      <ul class="menu-list">
{menu_html}
      </ul>
    </section>

    <section id="about" class="panel">
      <h2>About</h2>
      <p>{esc(design["about_text"])}</p>
    </section>

    <section id="contact" class="panel">
      <h2>Contact</h2>
      <p>Sample contact form for demo purposes only. It does not send anything anywhere.</p>
      <form id="contact-form" action="#" method="post">
        <label for="contact-name">Name (sample field)</label>
        <input id="contact-name" name="name" type="text" autocomplete="name" required>
        <label for="contact-message">Message (sample field)</label>
        <textarea id="contact-message" name="message" rows="4" required></textarea>
        <button type="submit">Send sample message</button>
      </form>
      <p id="contact-note" role="status"></p>
    </section>
  </main>

  <footer class="site-footer">
    <p>Sample Café — fictional placeholder site for the seasonal redesign demo.</p>
  </footer>

  <script src="./script.js"></script>
</body>
</html>
"""
    style_css = f"""/* Sample Café {safe_season} redesign (placeholder demo styles). */
* {{
  box-sizing: border-box;
}}

body {{
  margin: 0;
  font-family: {design["font"]};
  line-height: 1.6;
  color: {design["ink"]};
  background: {design["page_bg"]};
}}

.site-header {{
  background: {design["header_bg"]};
  color: #ffffff;
  padding: 1rem 1.25rem;
}}

.brand {{
  margin: 0 0 0.5rem;
  font-size: 1.4rem;
  font-weight: bold;
}}

.site-nav {{
  display: flex;
  flex-wrap: wrap;
  gap: 0.25rem 1rem;
}}

.site-nav a {{
  color: #ffffff;
}}

main {{
  max-width: 46rem;
  margin: 0 auto;
  padding: 1.25rem;
}}

.hero {{
  background: {design["soft_panel"]};
  border: 2px solid {design["panel_border"]};
  border-radius: 10px;
  padding: 1.5rem;
}}

.season-decor {{
  margin-bottom: 1rem;
}}

{design["decor_css"]}
.season-kicker {{
  margin: 0 0 0.25rem;
  font-size: 0.95rem;
  color: {design["accent"]};
  font-weight: bold;
}}

h1 {{
  margin: 0 0 0.5rem;
  font-size: 2rem;
}}

.panel {{
  background: {design["soft_panel"]};
  border: 1px solid {design["panel_border"]};
  border-radius: 10px;
  padding: 1.25rem;
  margin-top: 1rem;
}}

.panel h2 {{
  color: {design["accent"]};
}}

.menu-list {{
  padding-left: 1.25rem;
}}

.button,
button {{
  display: inline-block;
  background: {design["header_bg"]};
  color: #ffffff;
  border: none;
  border-radius: 8px;
  padding: 0.6rem 1rem;
  font-size: 1rem;
  text-decoration: none;
  cursor: pointer;
}}

label {{
  display: block;
  margin-top: 0.75rem;
  font-weight: bold;
}}

input,
textarea {{
  display: block;
  width: 100%;
  max-width: 28rem;
  margin-top: 0.25rem;
  padding: 0.5rem;
  font: inherit;
  border: 1px solid #6f6a5e;
  border-radius: 6px;
  background: #ffffff;
  color: {design["ink"]};
}}

form button {{
  margin-top: 1rem;
}}

.site-footer {{
  text-align: center;
  padding: 1.5rem 1rem 2rem;
  color: {design["ink"]};
}}

@media (prefers-reduced-motion: no-preference) {{
  .season-decor {{
    animation: season-drift 6s ease-in-out infinite alternate;
  }}
}}

@keyframes season-drift {{
  from {{
    transform: translateY(0);
  }}
  to {{
    transform: translateY(-3px);
  }}
}}

@media (max-width: 36rem) {{
  h1 {{
    font-size: 1.6rem;
  }}

  main {{
    padding: 0.75rem;
  }}
}}

@media (prefers-reduced-motion: reduce) {{
  *,
  *::before,
  *::after {{
    animation: none !important;
    transition: none !important;
  }}
}}
"""
    script_js = (
        "/* Sample Café seasonal script (placeholder demo site). */\n"
        "(function () {\n"
        '  "use strict";\n'
        "\n"
        '  var form = document.getElementById("contact-form");\n'
        '  var note = document.getElementById("contact-note");\n'
        "\n"
        "  if (form && note) {\n"
        '    form.addEventListener("submit", function (event) {\n'
        "      event.preventDefault();\n"
        '      note.textContent = "Sample only: this demo form does not send messages anywhere.";\n'
        "      form.reset();\n"
        "    });\n"
        "  }\n"
        "})();\n"
    )
    return {"index.html": index_html, "style.css": style_css, "script.js": script_js}


# ---------------------------------------------------------------------------
# Festival lookup tool (grounds the agent without bloating every prompt)
# ---------------------------------------------------------------------------

FESTIVALS_PATH = Path(__file__).resolve().parent / "festivals.json"
MAX_TOOL_ROUNDS = 3

FESTIVAL_TOOL = {
    "type": "function",
    "function": {
        "name": "festival_info",
        "description": (
            "Look up verified facts about a seasonal occasion: its period, traditional "
            "symbols, palette, and things to avoid. Call it for the named season before "
            "designing. If it reports no verified facts, design a clearly generic "
            "seasonal style and invent nothing."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "The occasion name, e.g. 'Eid al-Fitr (Sallah)'.",
                }
            },
            "required": ["name"],
        },
    },
}

SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "search_festival",
        "description": (
            "Search an external encyclopedia for an occasion the curated lookup did not "
            "know. Returns a short factual summary or not-found. Use it only for dates, "
            "symbols, and sensitivities; keep all site copy clearly placeholder."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "The occasion name, e.g. 'Diwali'.",
                }
            },
            "required": ["name"],
        },
    },
}

TOOL_GUIDANCE = (
    "Ground every seasonal detail (dates, symbols, meanings) in tool results — never "
    "invent your own. Call festival_info first; if it reports no verified facts, call "
    "search_festival once; if that also finds nothing usable, design a clearly generic "
    "seasonal style and invent no dates, traditions, or meanings."
)


def _load_festivals() -> list[dict]:
    try:
        entries = json.loads(FESTIVALS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return entries if isinstance(entries, list) else []


def get_presets() -> list[str]:
    """Preset button labels, derived from festivals.json in file order.

    An entry becomes a button only when it has a non-empty display_name and
    explicitly opts in with a true is_preset flag. Anything else (missing or
    unrecognized flag, blank label) keeps it out of the buttons. A missing or
    corrupt file yields no presets instead of breaking the page.
    """
    presets: list[str] = []
    for entry in _load_festivals():
        if not isinstance(entry, dict):
            continue
        if not _is_preset_flag(entry.get("is_preset", False)):
            continue
        name = entry.get("display_name", "")
        if isinstance(name, str) and name.strip():
            presets.append(name.strip())
    return presets


def _is_preset_flag(value: object) -> bool:
    """Fail closed: only explicit true values opt an entry in as a preset."""
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes")
    return value is True


def lookup_festival(name: str) -> dict | None:
    """Return the verified-facts entry for an occasion, or None when unknown."""
    key = _normalize_season(name).replace("'", "")
    for entry in _load_festivals():
        candidates = [str(entry.get("id", ""))] + [str(n) for n in entry.get("names", [])]
        if any(key == _normalize_season(c).replace("'", "") for c in candidates):
            return entry
    return None


def run_festival_tool(name: str) -> str:
    entry = lookup_festival(name)
    if entry is None:
        return json.dumps({
            "found": False,
            "guidance": (
                f"No verified facts for {name!r}. Design a clearly generic seasonal style "
                "and invent no dates, traditions, meanings, or claims."
            ),
        })
    return json.dumps({
        "found": True,
        "facts": entry,
        "guidance": (
            "Ground the design in these facts only. Respect the 'avoid' list and never "
            "state details the facts do not give."
        ),
    })


def run_search_tool(name: str) -> str:
    found = wiki.search_festival(name)
    if not found.get("found"):
        return json.dumps({
            "found": False,
            "guidance": (
                f"External search found nothing usable for {name!r}. Design a clearly "
                "generic seasonal style and invent no dates, traditions, meanings, "
                "or claims."
            ),
        })
    return json.dumps({
        "found": True,
        "title": found.get("title", ""),
        "summary": found.get("summary", ""),
        "source": found.get("url", ""),
        "guidance": (
            "Treat this as background only: use it for dates, symbols, and "
            "sensitivities, keep all site copy clearly placeholder, and state nothing "
            "the summary does not support."
        ),
    })


# ---------------------------------------------------------------------------
# LLM agent path (used when an OpenAI-compatible provider is configured)
# ---------------------------------------------------------------------------

def build_agent_prompt(season: str, current: dict[str, str]) -> str:
    parts = [AGENT_INSTRUCTION.format(season=season), "", "Current site source files:"]
    for name in FILES:
        parts.append(f"--- {name} ---")
        parts.append(current[name])
    parts.append("--- end of current source ---")
    parts.append("")
    parts.append(
        "Return ONLY a JSON object with exactly these keys: "
        '"index.html", "style.css", "script.js". Each value is the complete updated '
        "file as a string. Do not wrap the JSON in code fences or add other text."
    )
    return "\n".join(parts)


def _extract_agent_files(text: str) -> dict[str, str]:
    cleaned = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", cleaned, re.S | re.I)
    if fence:
        cleaned = fence.group(1).strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValidationError(["The agent did not return a JSON object with the updated files."])
    try:
        payload = json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError as exc:
        raise ValidationError([f"The agent returned invalid JSON: {exc}."])
    if not isinstance(payload, dict):
        raise ValidationError(["The agent did not return a JSON object with the updated files."])
    files = {name: payload.get(name) for name in FILES}
    if any(not isinstance(value, str) for value in files.values()):
        raise ValidationError(
            ["The agent must return index.html, style.css, and script.js as strings."]
        )
    return files  # type: ignore[return-value]


def _provider_attempts(config: dict) -> list[tuple[str, str, str]]:
    attempts = []
    if config.get("PROVIDER") == "openai_compat":
        attempts.append((
            config.get("PROVIDER_BASE_URL", ""),
            config.get("PROVIDER_API_KEY", ""),
            config.get("MODEL_NAME", ""),
        ))
    if config.get("FALLBACK_PROVIDER") == "openai_compat":
        attempts.append((
            config.get("FALLBACK_PROVIDER_BASE_URL", ""),
            config.get("FALLBACK_PROVIDER_API_KEY", ""),
            config.get("FALLBACK_MODEL_NAME", ""),
        ))
    return attempts


def _chat(config: dict, messages: list[dict]) -> dict:
    last_error = "unknown error"
    for base_url, api_key, model in _provider_attempts(config):
        try:
            return llm.complete_with_tools(
                messages,
                base_url=base_url,
                api_key=api_key,
                model=model,
                temperature=0.7,
                max_tokens=12000,
                timeout_s=int(config.get("MODEL_TIMEOUT_S", 25)),
                tools=[FESTIVAL_TOOL, SEARCH_TOOL],
            )
        except Exception as exc:  # provider/network failure: try the fallback
            last_error = str(exc)[:300] or type(exc).__name__
    raise AgentError(f"The agent could not be reached ({last_error}).")


def _execute_tool_call(call: dict) -> tuple[str, str]:
    """Run one model-requested tool call; returns (tool_call_id, result_json)."""
    call_id = str(call.get("id", ""))
    function = call.get("function", {}) if isinstance(call, dict) else {}
    name = function.get("name", "") if isinstance(function, dict) else ""
    raw_args = function.get("arguments", "{}") if isinstance(function, dict) else "{}"
    try:
        args = json.loads(raw_args) if isinstance(raw_args, str) else {}
    except ValueError:
        args = {}
    if name not in {"festival_info", "search_festival"} or not isinstance(args, dict):
        return call_id, json.dumps({"error": f"Unknown tool: {name!r}."})
    season = args.get("name", "")
    if not isinstance(season, str) or not season.strip():
        return call_id, json.dumps({"error": "Pass the occasion name as 'name'."})
    if name == "search_festival":
        return call_id, run_search_tool(season.strip())
    return call_id, run_festival_tool(season.strip())


def call_llm_agent(season: str, current: dict[str, str], config: dict) -> dict[str, str]:
    if not _provider_attempts(config):
        raise AgentError("No LLM provider is configured for seasonal redesigns.")
    messages = [
        {"role": "system", "content": TOOL_GUIDANCE},
        {"role": "user", "content": build_agent_prompt(season, current)},
    ]
    for _ in range(MAX_TOOL_ROUNDS):
        reply = _chat(config, messages)
        tool_calls = reply.get("tool_calls") or []
        if not tool_calls:
            return _extract_agent_files(reply.get("content") or "")
        messages.append({
            "role": "assistant",
            "content": reply.get("content") or "",
            "tool_calls": tool_calls,
        })
        for call in tool_calls:
            call_id, result = _execute_tool_call(call)
            messages.append({"role": "tool", "tool_call_id": call_id, "content": result})
    raise ValidationError(["The agent kept calling tools without returning the files."])


def redesign_with_agent(
    season: str, current: dict[str, str], config: dict
) -> tuple[dict[str, str], str]:
    """Run the configured agent; returns (files, warning).

    Raises SeasonalError/ValidationError on bad input or invalid agent output
    (the caller keeps the previous version). An unreachable LLM falls back to
    the built-in designer with a warning, mirroring the repo's provider
    fallback chain, so the demo still works offline.
    """
    cleaned = season.strip()
    if not cleaned:
        raise SeasonalError("Enter a season name.")
    if len(cleaned) > MAX_SEASON_CHARS:
        raise SeasonalError("That season name is too long (80 characters max).")
    if config.get("PROVIDER") == "openai_compat" or config.get("FALLBACK_PROVIDER") == "openai_compat":
        try:
            files = call_llm_agent(cleaned, current, config)
        except AgentError as exc:
            files = design_locally(cleaned)
            validate_files(files)
            return files, f"Live agent unreachable ({exc}); used the built-in designer instead."
        validate_files(files)
        return files, ""
    # Default providers (fake/none): the built-in designer acts as the agent
    # so the demo works without network access or API keys.
    files = design_locally(cleaned)
    validate_files(files)
    return files, ""


# ---------------------------------------------------------------------------
# Preview assembly (current files inlined into one document for the iframe)
# ---------------------------------------------------------------------------

_LINK_RE = re.compile(r'<link\b[^>]*href=["\']\./style\.css["\'][^>]*>', re.I)
_SCRIPT_RE = re.compile(
    r'<script\b[^>]*src=["\']\./script\.js["\'][^>]*>\s*</script\s*>', re.I
)


def assemble_preview(files: dict[str, str]) -> str:
    page = _LINK_RE.sub("", files["index.html"])
    page = _SCRIPT_RE.sub("", page)
    css = files["style.css"].strip()
    js = files["script.js"].strip()
    if css:
        style_tag = f"<style>\n{css}\n</style>"
        if re.search(r"</head\s*>", page, re.I):
            page = re.sub(r"</head\s*>", style_tag + "\n</head>", page, count=1, flags=re.I)
        else:
            page = style_tag + "\n" + page
    if js:
        script_tag = f"<script>\n{js}\n</script>"
        if re.search(r"</body\s*>", page, re.I):
            page = re.sub(r"</body\s*>", script_tag + "\n</body>", page, count=1, flags=re.I)
        else:
            page = page + "\n" + script_tag
    return page


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

def _consume_limit() -> tuple[bool, int]:
    limiter = current_app.config.get("REQUEST_LIMITER")
    if limiter is None:
        return True, 0
    return limiter.consume(request.remote_addr or "unknown")


def register_seasonal(app) -> None:
    @app.get("/")
    def seasonal_page():
        return render_template(
            "seasonal.html",
            banner=BANNER_TEXT,
            presets=get_presets(),
            state=summarize(app.config),
        )

    @app.get("/seasonal")
    def seasonal_legacy():
        return redirect("/", code=302)

    @app.get("/preview")
    def seasonal_preview():
        files = current_entry(app.config)["files"]
        response = app.response_class(
            assemble_preview(files), content_type="text/html; charset=utf-8"
        )
        response.headers["Content-Security-Policy"] = (
            "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; "
            "img-src data:; font-src data:; media-src data:; "
            "connect-src 'none'; frame-src 'none'; object-src 'none'; form-action 'none'; "
            "base-uri 'none'; frame-ancestors 'self'"
        )
        return response

    @app.get("/api/state")
    def seasonal_state():
        return jsonify(summarize(app.config))

    def _payload_season() -> str:
        data = request.get_json(silent=True) or {}
        season = data.get("season", "") if isinstance(data, dict) else ""
        if not season:
            season = request.form.get("season", "")
        return season.strip()

    @app.post("/api/redesign")
    def seasonal_redesign():
        allowed, retry_after = _consume_limit()
        if not allowed:
            response = jsonify(error="Too many requests. Please wait and try again.")
            response.status_code = 429
            response.headers["Retry-After"] = str(retry_after)
            return response
        season = _payload_season()
        try:
            files, warning = redesign_with_agent(
                season, current_entry(app.config)["files"], app.config
            )
        except SeasonalError as exc:
            # Previous version is untouched: nothing was applied before validation.
            return jsonify(error=str(exc)), 400
        state = apply_files(app.config, season, files)
        state["warning"] = warning
        return jsonify(state)

    @app.post("/api/reset")
    def seasonal_reset():
        return jsonify(reset_to_original(app.config))

    @app.post("/api/back")
    def seasonal_back():
        return jsonify(step(app.config, -1))

    @app.post("/api/forward")
    def seasonal_forward():
        return jsonify(step(app.config, 1))
