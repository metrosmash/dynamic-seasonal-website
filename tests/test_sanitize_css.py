from __future__ import annotations

from unittest.mock import patch

import pytest

from app.pipeline import decorate_page
from app.steps.sanitize_css import sanitize_css


@pytest.mark.parametrize(
    "css",
    [
        "@import url(https://attacker.example/a.css);",
        "p { background-image: url(https://attacker.example/a.png); }",
        "p { width: expression(alert(1)); }",
        "p { color: url(javascript:alert(1)); }",
        'p::before { content: "injected"; }',
        "p { display: none; }",
        "p { color: transparent; }",
        "body { position: fixed; }",
        ".content { position: absolute; }",
        "p { visibility: hidden; }",
        "p { opacity: 0.1; }",
    ],
)
def test_sanitizer_removes_css_attack_patterns(css: str):
    result = sanitize_css(css, "high")

    assert result.css == ""
    assert result.dropped_rules > 0


def test_sanitizer_keeps_safe_flourishes_and_gradient_backgrounds():
    css = """
h1 { letter-spacing: 0.04em; color: var(--hw-accent); }
.card { background-image: linear-gradient(90deg, #000, #333); border-radius: 8px; }
"""

    result = sanitize_css(css, "medium")

    assert result.css == (
        "h1 { letter-spacing: 0.04em; color: var(--hw-accent); }\n"
        ".card { background-image: linear-gradient(90deg, #000, #333); border-radius: 8px; }"
    )
    assert result.dropped_rules == 0
    assert not result.rejected


def test_sanitizer_allows_constrained_media_and_decoration_keyframes():
    css = """
@media (prefers-reduced-motion: no-preference) {
  .hw-deco { opacity: 0.8; position: fixed; }
}
@keyframes hw-fade { from { opacity: 0.7; } to { opacity: 1; } }
"""

    result = sanitize_css(css, "high")

    assert "@media (prefers-reduced-motion: no-preference)" in result.css
    assert ".hw-deco { opacity: 0.8; position: fixed; }" in result.css
    assert "@keyframes hw-fade" in result.css
    assert result.dropped_rules == 0


def test_sanitizer_rejects_bad_at_rules_and_invalid_media_queries():
    result = sanitize_css(
        '@font-face { font-family: Evil; src: url(https://evil); } '
        '@media (min-width: 20s) { p { color: red; } } '
        '@supports (display: grid) { p { color: red; } }',
        "high",
    )

    assert result.css == ""
    assert result.dropped_rules == 3


@pytest.mark.parametrize(
    ("css", "tier"),
    [
        ("p { color: red", "high"),
        ("p { color: red; }" * 1000, "medium"),
        ("p { letter-spacing: .1em; }", "low"),
    ],
)
def test_sanitizer_fails_closed_for_malformed_oversized_or_disabled_css(css: str, tier: str):
    result = sanitize_css(css, tier)

    assert result.css == ""
    if tier != "low":
        assert result.rejected


def test_sanitizer_discards_all_when_more_than_half_of_rules_are_dropped():
    result = sanitize_css(
        "h1 { letter-spacing: .1em; } p { display: none; } p { color: transparent; }",
        "high",
    )

    assert result.css == ""
    assert result.rejected
    assert result.accepted_rules == 1
    assert result.dropped_rules == 2


@patch("app.pipeline.fake.complete")
def test_pipeline_applies_only_sanitized_model_css(complete):
    complete.return_value = """PLACE: moon @ top-right
CSS:
h1 { letter-spacing: 0.04em; }
p { display: none; }"""
    result = decorate_page(
        "<html><body><h1>Sample</h1></body></html>",
        source_url="https://example.com/",
        intensity="medium",
        provider="fake",
        provider_base_url="",
        provider_api_key="",
        model_name="",
        model_timeout=1,
    )

    assert "letter-spacing: 0.04em" in result["html"]
    assert "display: none" not in result["html"]


@patch("app.pipeline.fake.complete")
def test_pipeline_retries_unparseable_output_once_then_uses_code_only_fallback(complete):
    complete.side_effect = [
        "unstructured model output",
        "still not a design spec",
    ]

    result = decorate_page(
        "<html><body><h1>Sample</h1></body></html>",
        source_url="https://example.com/",
        intensity="medium",
        provider="fake",
        provider_base_url="",
        provider_api_key="",
        model_name="",
        model_timeout=1,
    )

    assert complete.call_count == 2
    assert result["design_mode"] == "code-only design"
    assert "built-in" in result["warning"]
    assert 'data-hw-added="decoration"' in result["html"]


@patch("app.pipeline.fake.complete")
def test_pipeline_rejects_css_exceeding_the_tier_budget(complete):
    complete.return_value = (
        "PLACE: moon @ top-right\nCSS:\n"
        + ("h1 { letter-spacing: .04em; }\n" * 100)
    )

    result = decorate_page(
        "<html><body><h1>Sample</h1></body></html>",
        source_url="https://example.com/",
        intensity="medium",
        provider="fake",
        provider_base_url="",
        provider_api_key="",
        model_name="",
        model_timeout=1,
    )

    assert "letter-spacing: .04em" not in result["html"]
    assert "removed" in result["warning"]
