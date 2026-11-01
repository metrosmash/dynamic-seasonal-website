from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest
from bs4 import BeautifulSoup

from app.content.decor_catalog import DECORATIONS, load_decoration_svg
from app.steps.assemble import assemble_page


@pytest.mark.parametrize("name", sorted(DECORATIONS))
def test_decoration_svg_is_loaded_and_embedded_in_preview(name):
    metadata = DECORATIONS[name]
    source_svg = load_decoration_svg(name)
    svg_root = ET.fromstring(source_svg)
    slot = sorted(metadata["slots"])[0]
    if slot == "before-h2":
        slot = "before-h2:1"

    rendered = assemble_page(
        "<html><body><h1>Preview</h1><h2>Section</h2></body></html>",
        source_url="https://example.com/",
        theme_id="pumpkin-patch",
        intensity="high",
        placements=((name, slot),),
    )
    soup = BeautifulSoup(rendered, "html.parser")
    decoration = soup.select_one('[data-hw-added="decoration"]')

    assert metadata["svg_file"] == f"{name}.svg"
    assert svg_root.tag.endswith("svg")
    assert decoration is not None
    assert decoration.get("data-hw-slot") == slot
    assert decoration.select_one("svg") is not None
    for element in list(svg_root):
        drawing = element.attrib.get("d")
        if drawing:
            assert drawing in str(decoration)

