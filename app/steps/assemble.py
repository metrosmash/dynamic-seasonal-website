from __future__ import annotations

from bs4 import BeautifulSoup


DECORATION_SVG = {
    "pumpkin": (
        '<svg viewBox="0 0 100 82" aria-hidden="true" focusable="false">'
        '<path d="M50 20c-4-10 1-15 10-17 2 8-1 13-10 17Z" fill="#91a96a"/>'
        '<path d="M50 20c-25-15-43 5-43 27 0 21 15 32 43 32s43-11 43-32C93 25 75 5 50 20Z" fill="currentColor"/>'
        '<path d="M50 21c-9 5-13 17-13 27s4 22 13 31m0-58c9 5 13 17 13 27s-4 22-13 31" fill="none" stroke="#8f381d" stroke-width="3"/>'
        '</svg>'
    ),
    "moon": (
        '<svg viewBox="0 0 100 100" aria-hidden="true" focusable="false">'
        '<path d="M67 8a42 42 0 1 0 25 65A38 38 0 0 1 67 8Z" fill="currentColor"/>'
        '</svg>'
    ),
}


def _theme_css(accent: str, intensity: str) -> str:
    return f"""
:root {{
  color-scheme: dark;
  --hw-bg: #120b08;
  --hw-text: #ebdcd0;
  --hw-link: #ff9e42;
  --hw-accent: {accent};
  --hw-surface: #1f140f;
}}
html, body {{ background: var(--hw-bg); color: var(--hw-text); }}
body {{ min-height: 100vh; }}
a {{ color: var(--hw-link); }}
h1, h2, h3 {{ color: var(--hw-accent); }}
img, video, canvas, svg {{ max-width: 100%; }}
.hw-added {{ box-sizing: border-box; pointer-events: none; }}
.hw-added svg {{ display: block; width: 100%; height: 100%; }}
.hw-corner {{
  position: fixed; z-index: 2147483000; top: 1rem; right: 1rem;
  width: 64px; height: 64px; color: var(--hw-accent);
  filter: drop-shadow(0 0 12px #ff7a1a66);
}}
@media (max-width: 600px) {{ .hw-corner {{ width: 42px; height: 42px; opacity: .7; }} }}
@media (prefers-reduced-motion: reduce) {{ *, *::before, *::after {{ animation: none !important; transition: none !important; }} }}
""".strip()


def assemble_page(
    source_html: str,
    *,
    source_url: str,
    accent: str,
    placement: tuple[str, str],
    intensity: str,
) -> str:
    soup = BeautifulSoup(source_html, "html.parser")
    if soup.head is None:
        head = soup.new_tag("head")
        soup.html.insert(0, head)
    if soup.body is None:
        body = soup.new_tag("body")
        soup.html.append(body)
    style = soup.new_tag("style", attrs={"data-hw-added": "theme"})
    style.string = _theme_css(accent, intensity)
    soup.head.append(style)

    name, slot = placement
    svg = DECORATION_SVG.get(name, DECORATION_SVG["pumpkin"])
    decoration = BeautifulSoup(
        f'<div class="hw-added hw-corner" data-hw-added="decoration" aria-hidden="true">{svg}</div>',
        "html.parser",
    ).div
    decoration["data-hw-slot"] = slot
    soup.body.insert(0, decoration)

    source_link = soup.new_tag("a", href=source_url, target="_blank", rel="noopener noreferrer")
    source_link.string = "View the original website"
    attribution = soup.new_tag("p", attrs={"data-hw-added": "attribution"})
    attribution.string = "Halloween preview · "
    attribution.append(source_link)
    soup.body.append(attribution)
    return "<!doctype html>\n" + str(soup)
