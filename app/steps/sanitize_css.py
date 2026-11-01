from __future__ import annotations

import re
from dataclasses import dataclass

import tinycss2
from tinycss2.ast import AtRule, Declaration, QualifiedRule

from app.content.themes import APPROVED_FONTS
from app.content.tiers import TIERS


MAX_RULES = {"low": 0, "medium": 40, "high": 80}
ALLOWED_PROPERTIES = {
    "color",
    "background-color",
    "background-image",
    "border",
    "border-color",
    "border-style",
    "border-width",
    "border-top",
    "border-right",
    "border-bottom",
    "border-left",
    "border-radius",
    "box-shadow",
    "text-shadow",
    "text-decoration",
    "text-decoration-color",
    "text-decoration-line",
    "text-decoration-style",
    "text-transform",
    "letter-spacing",
    "font-family",
    "font-weight",
    "font-style",
    "list-style",
    "list-style-type",
    "transition",
    "transition-property",
    "transition-duration",
    "transition-timing-function",
    "transition-delay",
    "animation",
    "animation-name",
    "animation-duration",
    "animation-timing-function",
    "animation-delay",
    "animation-iteration-count",
    "animation-direction",
    "animation-fill-mode",
    "animation-play-state",
    "transform",
    "transform-origin",
    "transform-box",
    "opacity",
    "position",
    "top",
    "right",
    "bottom",
    "left",
    "content",
}
ANTI_HIDE_PROPERTIES = {
    "clip",
    "clip-path",
    "height",
    "text-indent",
    "visibility",
}
FORBIDDEN_FUNCTIONS = {"expression", "element", "image-set", "-moz-binding"}
ALLOWED_DATA_TYPES = {
    "image/svg+xml",
    "image/png",
    "image/jpeg",
    "image/webp",
}
MEDIA_QUERY = re.compile(
    r"^(?:\(\s*(?:prefers-reduced-motion\s*:\s*(?:reduce|no-preference)|"
    r"(?:min|max)-width\s*:\s*\d+(?:\.\d+)?(?:px|em|rem|vw))\s*\)"
    r"(?:\s+and\s+\(\s*(?:prefers-reduced-motion\s*:\s*(?:reduce|no-preference)|"
    r"(?:min|max)-width\s*:\s*\d+(?:\.\d+)?(?:px|em|rem|vw))\s*\))*)$",
    re.I,
)


@dataclass(frozen=True)
class SanitizedCSS:
    css: str
    accepted_rules: int
    dropped_rules: int
    rejected: bool = False


def _contains_error(tokens: list[object]) -> bool:
    for token in tokens:
        if token.type == "error":
            return True
        content = getattr(token, "content", None)
        if isinstance(content, list) and _contains_error(content):
            return True
        arguments = getattr(token, "arguments", None)
        if isinstance(arguments, list) and _contains_error(arguments):
            return True
        for attribute in ("prelude", "value"):
            nested = getattr(token, attribute, None)
            if isinstance(nested, list) and _contains_error(nested):
                return True
    return False


def _token_values(tokens: list[object]):
    for token in tokens:
        yield token
        for attribute in ("content", "arguments"):
            nested = getattr(token, attribute, None)
            if isinstance(nested, list):
                yield from _token_values(nested)


def _is_data_image_url(value: str) -> bool:
    match = re.fullmatch(
        r"data:(image/(?:svg\+xml|png|jpeg|webp))(?:;[^,]*)?,.+",
        value.strip(),
        re.I | re.S,
    )
    return bool(match and match.group(1).lower() in ALLOWED_DATA_TYPES)


def _safe_value(
    declaration: Declaration,
    *,
    decoration_only: bool,
) -> bool:
    prop = declaration.lower_name
    if prop not in ALLOWED_PROPERTIES or declaration.important:
        return False
    serialized = tinycss2.serialize(declaration.value).strip()
    lowered = serialized.lower()
    if not serialized or any(
        marker in lowered
        for marker in ("expression(", "javascript:", "-moz-binding", "behavior:")
    ):
        return False
    tokens = list(_token_values(declaration.value))
    for token in tokens:
        if token.type == "error" or token.type == "bad-url":
            return False
        if token.type == "url" and not _is_data_image_url(token.value):
            return False
        if token.type == "function":
            name = token.lower_name
            if name in FORBIDDEN_FUNCTIONS:
                return False
            if name == "url":
                url_value = tinycss2.serialize(token.arguments).strip().strip("\"'")
                if not _is_data_image_url(url_value):
                    return False
            if prop == "background-image" and not name.endswith("gradient"):
                return False

    if prop == "background-image":
        functions = [token.lower_name for token in tokens if token.type == "function"]
        if not functions or any(not name.endswith("gradient") for name in functions):
            return False
    elif prop == "background" and "gradient(" not in lowered:
        return False
    if prop == "font-family":
        font_names = {
            part.strip().strip("\"'").casefold()
            for part in serialized.split(",")
        }
        if not font_names or not font_names.issubset(
            {font.casefold() for font in APPROVED_FONTS} | {"serif", "sans-serif", "monospace"}
        ):
            return False
    if prop == "content":
        return lowered in {"none", '""', "''"}
    if prop in ANTI_HIDE_PROPERTIES:
        return False
    if prop == "display" and lowered == "none":
        return False
    if prop == "visibility" and lowered == "hidden":
        return False
    if prop == "opacity" and (not decoration_only or _opacity_below_threshold(serialized)):
        return False
    if prop in {
        "transform", "transform-origin", "transform-box", "animation",
        "animation-name", "animation-duration", "animation-timing-function",
        "animation-delay", "animation-iteration-count", "animation-direction",
        "animation-fill-mode", "animation-play-state", "transition",
        "transition-property", "transition-duration", "transition-timing-function",
        "transition-delay", "position", "top", "right", "bottom", "left",
    } and not decoration_only:
        return False
    if prop == "color" and lowered == "transparent":
        return False
    if prop == "font-size":
        return False
    if prop == "height" and re.fullmatch(r"0(?:px|em|rem|%)?", lowered):
        return False
    if prop == "text-indent" and re.match(r"-\s*(?:\d{3,}|[1-9]\d{2,})", lowered):
        return False
    return True


def _opacity_below_threshold(value: str) -> bool:
    match = re.fullmatch(r"(?:0(?:\.\d+)?|1(?:\.0+)?)", value.strip())
    return bool(match and float(match.group()) < 0.6)


def _balanced_blocks(css: str) -> bool:
    depth = 0
    quote: str | None = None
    escaped = False
    in_comment = False
    index = 0
    while index < len(css):
        char = css[index]
        following = css[index + 1] if index + 1 < len(css) else ""
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
        elif char in {"\"", "'"}:
            quote = char
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth < 0:
                return False
        index += 1
    return depth == 0 and not quote and not in_comment


def _selector_is_safe(selector: str) -> bool:
    lowered = selector.lower()
    if not selector or len(selector) > 500:
        return False
    if any(token in lowered for token in ("</", "/*", "*/", ":root")):
        return False
    if re.search(r"(^|[\s>+~,(])(?:html|body)(?=$|[\s.#:[>+~,)])", lowered):
        return False
    return not any(char in selector for char in "{};")


def _is_decoration_selector(selector: str) -> bool:
    return all(
        component.strip().startswith(".hw-")
        for component in selector.split(",")
    )


def _sanitize_rule_list(
    rules: list[QualifiedRule | AtRule],
    *,
    max_rules: int,
    counters: list[int],
    in_keyframes: bool = False,
) -> str:
    output: list[str] = []
    for rule in rules:
        if rule.type == "error":
            counters[1] += 1
            continue
        if isinstance(rule, QualifiedRule):
            selector = tinycss2.serialize(rule.prelude).strip()
            if in_keyframes:
                if not re.fullmatch(r"(?:from|to|\d+(?:\.\d+)?%)", selector, re.I):
                    counters[1] += 1
                    continue
                decoration_only = True
            else:
                if not _selector_is_safe(selector):
                    counters[1] += 1
                    continue
                decoration_only = _is_decoration_selector(selector)
            declarations = tinycss2.parse_declaration_list(
                rule.content, skip_comments=True, skip_whitespace=True
            )
            if _contains_error(declarations):
                counters[2] = 1
                continue
            safe: list[Declaration] = []
            for declaration in declarations:
                if not isinstance(declaration, Declaration):
                    continue
                if _safe_value(declaration, decoration_only=decoration_only):
                    safe.append(declaration)
            if not safe:
                counters[1] += 1
                continue
            counters[0] += 1
            if counters[0] + counters[1] > max_rules:
                counters[1] += 1
                counters[0] -= 1
                continue
            serialized_declarations = "; ".join(
                f"{item.name}: {tinycss2.serialize(item.value).strip()}"
                for item in safe
            )
            output.append(f"{selector} {{ {serialized_declarations}; }}")
            continue

        if isinstance(rule, AtRule):
            name = rule.lower_at_keyword
            prelude = tinycss2.serialize(rule.prelude).strip()
            if name == "media" and rule.content is not None and MEDIA_QUERY.fullmatch(prelude):
                nested = tinycss2.parse_rule_list(
                    rule.content, skip_comments=True, skip_whitespace=True
                )
                if _contains_error(nested):
                    counters[2] = 1
                    continue
                nested_css = _sanitize_rule_list(
                    nested, max_rules=max_rules, counters=counters, in_keyframes=in_keyframes
                )
                if nested_css:
                    output.append(f"@media {prelude} {{ {nested_css} }}")
                else:
                    counters[1] += 1
                continue
            if name in {"keyframes", "-webkit-keyframes"} and rule.content is not None:
                animation_name = prelude.strip("\"'")
                if not re.fullmatch(r"hw-[a-z0-9_-]+", animation_name, re.I):
                    counters[1] += 1
                    continue
                nested = tinycss2.parse_rule_list(
                    rule.content, skip_comments=True, skip_whitespace=True
                )
                if _contains_error(nested):
                    counters[2] = 1
                    continue
                nested_css = _sanitize_rule_list(
                    nested, max_rules=max_rules, counters=counters, in_keyframes=True
                )
                if nested_css:
                    output.append(f"@keyframes {animation_name} {{ {nested_css} }}")
                else:
                    counters[1] += 1
                continue
        counters[1] += 1
    return "\n".join(output)


def sanitize_css(css: str, tier: str) -> SanitizedCSS:
    """Keep only small, explicitly allowed model CSS; fail closed on parser errors."""
    settings = TIERS.get(tier)
    if settings is None:
        return SanitizedCSS("", 0, 0, rejected=True)
    max_chars = settings["css_chars"]
    if not css or not max_chars:
        return SanitizedCSS("", 0, 0)
    if len(css) > max_chars:
        return SanitizedCSS("", 0, 1, rejected=True)
    if not _balanced_blocks(css):
        return SanitizedCSS("", 0, 1, rejected=True)
    rules = tinycss2.parse_stylesheet(css, skip_comments=True, skip_whitespace=True)
    if _contains_error(rules):
        return SanitizedCSS("", 0, max(1, len(rules)), rejected=True)
    counters = [0, 0, 0]
    sanitized = _sanitize_rule_list(
        rules, max_rules=MAX_RULES[tier], counters=counters
    )
    total = counters[0] + counters[1]
    if counters[2]:
        return SanitizedCSS("", counters[0], max(1, counters[1]), rejected=True)
    if counters[1] > total / 2:
        return SanitizedCSS("", counters[0], counters[1], rejected=True)
    return SanitizedCSS(sanitized, counters[0], counters[1])
