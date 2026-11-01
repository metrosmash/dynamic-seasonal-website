from __future__ import annotations

import xml.etree.ElementTree as ET

from bs4 import BeautifulSoup

from app.content.decor_catalog import DECORATIONS, load_decoration_svg
from app.content.themes import THEMES, select_theme
from app.content.tiers import TIERS
from app.parser import parse_design_response
from app.steps.assemble import _contrast_ratio, assemble_page


def test_every_theme_palette_meets_wcag_contrast_targets():
    for theme in THEMES.values():
        for palette_name in ("light", "dark"):
            palette = getattr(theme, palette_name)
            assert _contrast_ratio(palette.text, palette.bg) >= 4.5, (theme.id, palette_name, "text/bg")
            assert _contrast_ratio(palette.text, palette.surface) >= 4.5, (
                theme.id, palette_name, "text/surface"
            )
            assert _contrast_ratio(palette.link, palette.bg) >= 4.5, (theme.id, palette_name, "link/bg")
            assert _contrast_ratio(palette.accent, palette.bg) >= 3, (
                theme.id, palette_name, "accent/bg"
            )


def test_theme_selection_is_stable_and_uses_supported_ids():
    first = select_theme("https://example.com/", "medium")

    assert first == select_theme("https://example.com/", "medium")
    assert first.id in THEMES
    assert len({select_theme(f"page-{index}", "medium").id for index in range(50)}) > 1
    assert first.id != select_theme("https://example.com/", "medium", variant=1).id


def test_catalog_and_theme_defaults_only_use_supported_slots():
    for name, theme in THEMES.items():
        assert name == theme.id
        for tier, placements in theme.defaults.items():
            assert len(placements) <= TIERS[tier]["max_decorations"]
            for decoration, slot in placements:
                assert slot.split(":", 1)[0] in DECORATIONS[decoration]["slots"]


def test_each_decoration_loads_from_its_own_standalone_svg_file():
    for name, metadata in DECORATIONS.items():
        svg = load_decoration_svg(name)
        root = ET.fromstring(svg)

        assert metadata["svg_file"] == f"{name}.svg"
        assert root.tag.endswith("svg")
        view_box = tuple(map(float, root.attrib["viewBox"].split()))
        assert len(view_box) == 4
        assert view_box[2] > 0
        assert view_box[3] > 0
        assert list(root)
        assert "<script" not in svg.lower()
        assert all(
            not attribute_name.endswith("href")
            for element in root.iter()
            for attribute_name in element.attrib
        )


def test_assembler_keeps_original_text_and_inserts_banner_and_attribution():
    source = (
        "<html><head><title>Sample</title></head><body><main>"
        "<h1>Title</h1><p>First paragraph.</p><h2>Section</h2>"
        '<p><a href="#section">Jump</a> <a href="/page">Page link</a></p>'
        "<p>Second paragraph.</p></main></body></html>"
    )
    placements = (
        ("bat", "header"),
        ("pumpkin", "before-h2:2"),
        ("ghost", "before-h2:1"),
        ("cobweb", "footer"),
    )

    rendered = assemble_page(
        source,
        source_url="https://example.com/page",
        theme_id="haunted-library",
        intensity="medium",
        placements=placements,
    )
    soup = BeautifulSoup(rendered, "html.parser")
    rendered_hrefs = [
        link.get("href")
        for link in soup.find_all("a")
        if not link.find_parent(attrs={"data-hw-added": "attribution"})
    ]
    for added in soup.select("[data-hw-added]"):
        added.decompose()
    original = BeautifulSoup(source, "html.parser")
    original_hrefs = [link.get("href") for link in original.find_all("a")]

    assert soup.get_text(" ", strip=True) == original.get_text(" ", strip=True)
    assert rendered_hrefs == original_hrefs
    assert BeautifulSoup(rendered, "html.parser").select_one("[data-hw-added=banner]")
    assert BeautifulSoup(rendered, "html.parser").select_one("[data-hw-added=attribution]")
    assert not BeautifulSoup(rendered, "html.parser").find("base")
    assert not BeautifulSoup(rendered, "html.parser").find(attrs={"data-hw-slot": "before-h2:2"})


def test_before_h2_placement_is_skipped_when_heading_does_not_exist():
    rendered = assemble_page(
        "<html><body><h2>Only section</h2><p>Content</p></body></html>",
        source_url="https://example.com/",
        theme_id="pumpkin-patch",
        intensity="medium",
        placements=(("pumpkin", "before-h2:2"),),
    )

    assert 'data-hw-slot="before-h2:2"' not in rendered


def test_wikipedia_source_includes_license_attribution():
    rendered = assemble_page(
        "<html><body><h1>Article</h1></body></html>",
        source_url="https://en.wikipedia.org/wiki/Halloween",
        theme_id="haunted-library",
        intensity="medium",
        placements=(),
    )

    assert "CC BY-SA 4.0" in rendered
    assert "creativecommons.org/licenses/by-sa/4.0/" in rendered


def test_low_tier_omits_banner_and_animations_respect_motion_preference():
    low = assemble_page(
        "<html><body><h1>Sample</h1></body></html>",
        source_url="https://example.com/",
        theme_id="pumpkin-patch",
        intensity="low",
        placements=(("bat", "top-left"),),
    )
    high = assemble_page(
        "<html><body><h1>Sample</h1></body></html>",
        source_url="https://example.com/",
        theme_id="pumpkin-patch",
        intensity="high",
        placements=(
            ("bat", "float"), ("ghost", "float"), ("pumpkin", "footer"),
            ("spider", "top-left"),
        ),
    )

    assert 'data-hw-added="banner"' not in low
    assert "@media (prefers-reduced-motion:no-preference)" in high
    assert "@media (prefers-reduced-motion:reduce)" in high
    high_soup = BeautifulSoup(high, "html.parser")
    assert high_soup.select(".hw-deco.hw-on-flap, .hw-deco.hw-on-bob, .hw-deco.hw-on-glow")
    animated_inline = high_soup.select(
        ".hw-deco.hw-on-flap:not(.hw-float), .hw-deco.hw-on-bob:not(.hw-float), "
        ".hw-deco.hw-on-glow:not(.hw-float), .hw-deco.hw-on-sway:not(.hw-float), "
        ".hw-deco.hw-on-flicker:not(.hw-float)"
    )
    assert len(animated_inline) <= TIERS["high"]["animations"]
    theme_css = BeautifulSoup(high, "html.parser").select_one("style[data-hw-added=theme]").string
    assert "html body h1, html body h2" in theme_css


def test_assembler_integrates_overlay_root_and_independent_inline_blocks():
    rendered = assemble_page(
        "<html><body><h1>Title</h1><p>Intro</p><h2>Section</h2><p>End</p></body></html>",
        source_url="https://example.com/",
        theme_id="haunted-library",
        intensity="high",
        placements=(
            ("bat", "float"),
            ("ghost", "before-h2:1"),
            ("spider", "header"),
            ("pumpkin", "footer"),
        ),
    )
    soup = BeautifulSoup(rendered, "html.parser")
    root = soup.body.find("div", class_="hw-root")
    inline_header = soup.body.find("div", class_="hw-inline-header")
    inline_section = soup.body.find("div", class_="hw-inline-before-h2")
    inline_footer = soup.body.find("div", class_="hw-inline-footer")
    generated_css = soup.select_one("style[data-hw-added=theme]").string

    assert root is not None
    assert root is soup.body.contents[-1]
    assert root.select_one(".hw-fog")
    assert root.select_one(".hw-vignette")
    assert root.select_one(".hw-deco.hw-bat.hw-float")
    assert inline_header is not None
    assert inline_header.find_previous_sibling("h1").get_text(strip=True) == "Title"
    assert inline_section is not None
    assert inline_section.find_next_sibling("h2").get_text(strip=True) == "Section"
    assert inline_footer is not None
    assert inline_footer.find_next_sibling(attrs={"data-hw-added": "attribution"})
    assert all(node.has_attr("data-hw-added") for node in root.find_all("div"))
    assert ":where(html body div:not([data-hw-added]))" in generated_css
    assert "@media (prefers-reduced-motion:no-preference)" in generated_css
    assert "@media (prefers-reduced-motion:reduce)" in generated_css


def test_decorations_sharing_a_corner_are_stacked_without_overlap():
    rendered = assemble_page(
        "<html><body><h1>Title</h1></body></html>",
        source_url="https://example.com/",
        theme_id="haunted-library",
        intensity="high",
        placements=(("spider", "top-right"), ("moon", "top-right")),
    )
    soup = BeautifulSoup(rendered, "html.parser")
    spider = soup.select_one(".hw-deco.hw-spider")
    moon = soup.select_one(".hw-deco.hw-moon")
    root = soup.select_one(".hw-root")

    assert spider["style"].find("--hw-stack-offset:0px") >= 0
    assert moon["style"].find("--hw-stack-offset:74px") >= 0
    assert root.select(".hw-slot-top-right") == [spider, moon]
    assert ".hw-slot-top-right{top:var(--hw-stack-offset,0);right:0}" in (
        soup.select_one("style[data-hw-added=theme]").string
    )


def test_low_contrast_model_accent_cannot_override_theme_palette():
    rendered = assemble_page(
        "<html><body><h1>Sample</h1></body></html>",
        source_url="https://example.com/",
        theme_id="pumpkin-patch",
        intensity="medium",
        placements=(),
        accent="#000000",
    )
    theme_css = BeautifulSoup(rendered, "html.parser").select_one("style[data-hw-added=theme]").string

    assert "--hw-accent: #ffb36b" in theme_css
    assert "--hw-accent: #000000" not in theme_css


def test_seeded_defaults_cover_all_supported_tiers():
    for theme in THEMES.values():
        for tier in TIERS:
            page = assemble_page(
                "<html><body><h1>Sample</h1><h2>Section</h2></body></html>",
                source_url="https://example.com/",
                theme_id=theme.id,
                intensity=tier,
                placements=theme.defaults[tier],
            )
            soup = BeautifulSoup(page, "html.parser")
            decorations = soup.select('[data-hw-added="decoration"]')
            assert len(decorations) <= TIERS[tier]["max_decorations"]
            assert len(decorations) == len(theme.defaults[tier])


def test_parser_caps_model_placements_and_preserves_input_order():
    response = "\n".join(
        f"PLACE: {name} @ {slot}"
        for name, slot in [
            ("bat", "top-left"), ("spider", "top-right"), ("moon", "header"),
            ("ghost", "float"), ("cobweb", "footer"), ("pumpkin", "footer"),
            ("candle", "footer"), ("crow", "header"), ("tombstone", "footer"),
        ]
    )

    design = parse_design_response(response, "medium")

    assert len(design.placements) == TIERS["medium"]["max_decorations"]
    assert design.placements[0] == ("bat", "top-left")
