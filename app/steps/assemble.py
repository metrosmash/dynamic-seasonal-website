from __future__ import annotations

import re
from urllib.parse import urlencode, urlsplit

from bs4 import BeautifulSoup
from bs4.element import Doctype

from app.content.decor_css import decoration_css
from app.content.decor_markup import plan_placements, render_decoration, render_root
from app.content.themes import APPROVED_FONTS, THEMES, Palette
from app.content.tiers import TIERS


RESET_CONTAINERS = (
    "div, section, article, aside, header, footer, nav, main, table, th, td, "
    "ul, ol, li, blockquote, pre, code, figure, figcaption, details, summary"
)


def _contrast_ratio(first: str, second: str) -> float:
    def luminance(color: str) -> float:
        channels = [int(color[index:index + 2], 16) / 255 for index in (1, 3, 5)]
        linear = [
            channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4
            for channel in channels
        ]
        return sum(weight * channel for weight, channel in zip((0.2126, 0.7152, 0.0722), linear))

    light, dark = sorted((luminance(first), luminance(second)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


def _palette(theme_id: str, intensity: str) -> Palette:
    theme = THEMES[theme_id]
    return theme.light if TIERS[intensity]["palette"] == "light" else theme.dark


def _theme_css(
    theme_id: str,
    intensity: str,
    *,
    accent: str | None = None,
) -> str:
    theme = THEMES[theme_id]
    palette = _palette(theme_id, intensity)
    if accent and re.fullmatch(r"#[0-9a-f]{6}", accent, re.I) and _contrast_ratio(accent, palette.bg) >= 3:
        palette = Palette(
            palette.bg, palette.text, palette.muted, palette.link, accent, palette.surface
        )
    heading_font = theme.heading_font if theme.heading_font in APPROVED_FONTS else "Georgia"
    accent_font = theme.accent_font if theme.accent_font in APPROVED_FONTS else heading_font
    heading_selector = ", ".join(
        f"html body h{level}" for level in TIERS[intensity]["heading_levels"]
    )
    reset_selectors = ", ".join(
        f":where(html body {selector.strip()}:not([data-hw-added]))"
        for selector in RESET_CONTAINERS.split(",")
    )
    return f"""
:root {{
  color-scheme: {"light" if TIERS[intensity]["palette"] == "light" else "dark"};
  --hw-bg: {palette.bg};
  --hw-text: {palette.text};
  --hw-muted: {palette.muted};
  --hw-link: {palette.link};
  --hw-accent: {palette.accent};
  --hw-surface: {palette.surface};
}}
html body {{ background-color: var(--hw-bg) !important; color: var(--hw-text) !important; }}
{reset_selectors} {{ background-color: transparent !important; color: inherit !important; }}
html body .card, html body .infobox, html body .panel, html body [class~="surface"] {{
  background-color: var(--hw-surface) !important; color: var(--hw-text) !important;
}}
html body a, html body a:link {{ color: var(--hw-link) !important; }}
html body a:visited {{ color: {palette.link} !important; }}
{heading_selector} {{
  color: var(--hw-accent) !important;
  font-family: "{heading_font}", Georgia, serif;
}}
{f'html body blockquote {{ font-family: "{accent_font}", Georgia, serif; }}' if intensity == "high" else ""}
html body .hw-banner {{
  margin: 0 auto 1rem; padding: .65rem 1rem; width: fit-content; max-width: 100%;
  border: 1px solid var(--hw-accent); border-radius: .65rem;
  background: var(--hw-surface) !important; color: var(--hw-text) !important; text-align: center;
  font: 700 1rem/1.4 "{heading_font}", Georgia, serif;
}}
.hw-attribution {{ margin: 1rem auto; padding: .5rem 1rem; text-align: center; font-size: .85rem; }}
""".strip()


def _font_stylesheet(soup: BeautifulSoup, theme_id: str) -> None:
    theme = THEMES[theme_id]
    families = [
        font for font in dict.fromkeys((theme.heading_font, theme.accent_font))
        if font in APPROVED_FONTS
    ]
    if not families:
        return
    link = soup.new_tag(
        "link",
        rel="stylesheet",
        href="https://fonts.googleapis.com/css2?" + urlencode(
            [("family", font) for font in families] + [("display", "swap")]
        ),
        attrs={"data-hw-added": "fonts"},
    )
    soup.head.append(link)


def assemble_page(
    source_html: str,
    *,
    source_url: str,
    theme_id: str,
    intensity: str,
    placements: tuple[tuple[str, str], ...],
    accent: str | None = None,
) -> str:
    soup = BeautifulSoup(source_html, "html.parser")
    for element in list(soup.contents):
        if isinstance(element, Doctype):
            element.extract()
    if soup.html is None:
        wrapper = BeautifulSoup("<!doctype html><html><head></head><body></body></html>", "html.parser")
        wrapper.body.append(soup)
        soup = wrapper
    if soup.head is None:
        soup.html.insert(0, soup.new_tag("head"))
    if soup.body is None:
        soup.html.append(soup.new_tag("body"))

    planned, _warnings = plan_placements(
        list(placements),
        intensity,
        h2_count=len(soup.body.find_all("h2")),
    )
    style = soup.new_tag("style", attrs={"data-hw-added": "theme"})
    style.string = _theme_css(theme_id, intensity, accent=accent) + "\n" + decoration_css(intensity)
    soup.head.append(style)
    _font_stylesheet(soup, theme_id)

    if TIERS[intensity]["banner"]:
        banner = soup.new_tag("aside", attrs={
            "class": "hw-added hw-banner",
            "data-hw-added": "banner",
            "aria-label": "Halloween decoration",
        })
        banner.string = THEMES[theme_id].banner
        first_h1 = soup.body.find("h1")
        if first_h1:
            first_h1.insert_before(banner)
        else:
            soup.body.insert(0, banner)

    for placement in planned:
        if placement.overlay:
            continue
        node = BeautifulSoup(render_decoration(placement), "html.parser").div
        if placement.base == "header":
            heading = soup.body.find("h1")
            if heading:
                heading.insert_after(node)
            else:
                soup.body.insert(0, node)
        elif placement.base == "footer":
            soup.body.append(node)
        elif placement.base == "before-h2" and placement.index is not None:
            headings = soup.body.find_all("h2")
            headings[placement.index - 1].insert_before(node)

    attribution = soup.new_tag("p", attrs={
        "class": "hw-added hw-attribution",
        "data-hw-added": "attribution",
    })
    if source_url:
        attribution.append("Decorated version of ")
        source_link = soup.new_tag("a", href=source_url, target="_blank", rel="noopener noreferrer")
        source_link.string = source_url
        attribution.append(source_link)
    else:
        attribution.string = "Decorated version of uploaded website files."
    source_host = (urlsplit(source_url).hostname or "").lower()
    if source_host.endswith(".wikipedia.org") or source_host == "wikipedia.org":
        attribution.append(" · Wikipedia content is available under ")
        license_link = soup.new_tag(
            "a",
            href="https://creativecommons.org/licenses/by-sa/4.0/",
            target="_blank",
            rel="noopener noreferrer",
        )
        license_link.string = "CC BY-SA 4.0"
        attribution.append(license_link)
    soup.body.append(attribution)
    root = BeautifulSoup(render_root(planned, intensity), "html.parser").div
    if root is not None:
        soup.body.append(root)
    return "<!doctype html>\n" + str(soup)
