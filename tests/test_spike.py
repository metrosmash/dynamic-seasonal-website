import io
import json
import random
import urllib.error
from pathlib import Path
import unittest
from unittest.mock import patch

import pytest

from app.brief import build_prompt
from app.parser import DesignResult, parse_design_response, summarize_html
from scripts.spike import (
    _error_label,
    call_model,
    summarize_page,
)


@pytest.fixture
def valid_design_response():
    return """THEME: pumpkin-patch
ACCENT: #ff7a1a
PLACE: bat @ top-right"""


@pytest.mark.parametrize("response", ["", "Just some prose with no design labels."])
def test_parser_returns_noncompliant_result_for_empty_or_prose(response):
    design = parse_design_response(response, "medium")

    assert isinstance(design, DesignResult)
    assert not design.compliant
    assert design.placements == ()


def test_parser_reports_unknown_intensity_without_raising(valid_design_response):
    design = parse_design_response(valid_design_response, "unknown")

    assert not design.compliant
    assert "unknown intensity" in design.issues


def test_parser_accepts_crlf_line_endings(valid_design_response):
    design = parse_design_response(valid_design_response.replace("\n", "\r\n"), "medium")

    assert design.compliant
    assert design.theme == "pumpkin-patch"
    assert design.accent == "#ff7a1a"


def test_parser_unquotes_unicode_smart_quotes():
    response = """THEME: “pumpkin-patch”
ACCENT: ‘#ff7a1a’
PLACE: “bat @ top-right”"""

    design = parse_design_response(response, "medium")

    assert design.compliant
    assert design.theme == "pumpkin-patch"
    assert design.accent == "#ff7a1a"
    assert design.placements == (("bat", "top-right"),)


def test_parser_accepts_uppercase_labels(valid_design_response):
    response = valid_design_response.replace("THEME:", "theme:").replace(
        "ACCENT:", "accent:"
    ).replace("PLACE:", "place:")

    design = parse_design_response(response, "medium")

    assert design.compliant


def test_parser_uses_last_theme_and_accent_values():
    design = parse_design_response(
        """THEME: haunted-library
ACCENT: #111111
THEME: pumpkin-patch
ACCENT: #ff7a1a
PLACE: bat @ top-right""",
        "medium",
    )

    assert design.theme == "pumpkin-patch"
    assert design.accent == "#ff7a1a"
    assert design.compliant


def test_parser_handles_very_long_lines(valid_design_response):
    response = ("unstructured " * 100_000) + "\n" + valid_design_response

    design = parse_design_response(response, "medium")

    assert design.compliant
    assert design.theme == "pumpkin-patch"


def test_parser_drops_placement_with_excessively_long_heading_index():
    design = parse_design_response(
        "PLACE: pumpkin @ before-h2:" + "9" * 5000,
        "high",
    )

    assert design.placements == ()


def test_place_label_inside_css_comment_is_not_a_placement():
    design = parse_design_response(
        """THEME: pumpkin-patch
ACCENT: #ff7a1a
PLACE: bat @ top-right
CSS:
/* PLACE: ghost @ float */
h1 { color: var(--hw-accent); }""",
        "medium",
    )

    assert design.placements == (("bat", "top-right"),)
    assert "PLACE: ghost @ float" in design.css
    assert design.compliant


def test_parser_never_raises_for_random_bytes_decoded_as_text():
    rng = random.Random(0)

    for _ in range(250):
        decoded = rng.randbytes(rng.randrange(0, 4096)).decode("utf-8", errors="replace")
        design = parse_design_response(decoded, "medium")
        assert isinstance(design, DesignResult)


class SpikeTests(unittest.TestCase):
    def test_summary_extracts_page_title_and_headings(self):
        page = Path(__file__).resolve().parents[1] / "fixtures" / "spike_sample.html"
        _, summary = summarize_page(page)

        self.assertEqual(summary["title"], "The Lantern House - A Harvest Supper")
        self.assertEqual(summary["h2_count"], 3)
        self.assertEqual(summary["headings"][0], (1, "A Supper by Lantern Light"))

    def test_summary_accepts_html_string_for_pipeline(self):
        summary = summarize_html(
            "<html><head><title>Fetched</title></head><body><h2>Section</h2></body></html>"
        )

        self.assertEqual(summary["title"], "Fetched")
        self.assertEqual(summary["h2_count"], 1)

    def test_prompt_contains_summary_and_tier_budget(self):
        summary = {
            "title": "Sample",
            "word_count": 40,
            "h2_count": 1,
            "headings": [(1, "A heading")],
        }

        prompt = build_prompt(summary, "medium")

        self.assertIn("at most 8 decorations", prompt)
        self.assertIn("at most 2500 characters of CSS", prompt)
        self.assertIn("A heading", prompt)
        self.assertIn("Output only the labelled lines", prompt)

    def test_prompt_uses_assigned_theme_and_its_palette(self):
        prompt = build_prompt(
            {
                "title": "Sample",
                "word_count": 40,
                "h2_count": 1,
                "headings": [(1, "A heading")],
            },
            "medium",
            "graveyard-fog",
        )

        self.assertIn("Assigned theme: graveyard-fog", prompt)
        self.assertIn("THEME: graveyard-fog", prompt)
        self.assertIn("ACCENT: #a9d8bd", prompt)

    def test_low_tier_prompt_does_not_show_disallowed_slots_or_css(self):
        summary = {
            "title": "Sample",
            "word_count": 40,
            "h2_count": 1,
            "headings": [(1, "A heading")],
        }

        prompt = build_prompt(summary, "low")

        self.assertNotIn("before-h2", prompt)
        self.assertNotIn("CSS:\nh1", prompt)
        self.assertIn("PLACE: bat @ top-right", prompt)

    def test_high_tier_prompt_does_not_include_low_tier_css_rule(self):
        summary = {
            "title": "Sample",
            "word_count": 40,
            "h2_count": 1,
            "headings": [(1, "A heading")],
        }

        prompt = build_prompt(summary, "high")

        self.assertNotIn("Low intensity has no model CSS", prompt)
        self.assertIn("within the stated character budget", prompt)

    def test_design_parser_accepts_valid_output_and_code_fences(self):
        response = """THEME: pumpkin-patch
ACCENT: #FF7A1A
PLACE: bat @ top-right
PLACE: pumpkin @ before-h2:2
CSS:
```css
h1 { letter-spacing: 0.04em; }
```"""

        design = parse_design_response(response, "medium")

        self.assertTrue(design.compliant)
        self.assertEqual(design.theme, "pumpkin-patch")
        self.assertEqual(design.accent, "#ff7a1a")
        self.assertEqual(design.placements, (("bat", "top-right"), ("pumpkin", "before-h2:2")))
        self.assertEqual(design.css, "h1 { letter-spacing: 0.04em; }")

    def test_design_parser_drops_unknown_and_tier_disallowed_choices(self):
        response = """THEME: not-a-theme
ACCENT: orange
PLACE: dragon @ top-right
PLACE: bat @ float"""

        design = parse_design_response(response, "low")

        self.assertFalse(design.compliant)
        self.assertIsNone(design.theme)
        self.assertIsNone(design.accent)
        self.assertEqual(design.placements, ())

    def test_low_tier_drops_model_css(self):
        design = parse_design_response(
            "PLACE: bat @ top-right\nCSS:\nh1 { color: red; }",
            "low",
        )

        self.assertEqual(design.css, "")

    def test_css_is_capped_to_tier_budget(self):
        design = parse_design_response(
            "PLACE: bat @ top-right\nCSS:\n" + ("a" * 3000),
            "medium",
        )

        self.assertEqual(len(design.css), 2501)

    def test_placements_are_truncated_to_tier_budget(self):
        response = "\n".join(
            ["PLACE: bat @ top-right", "PLACE: spider @ top-left",
             "PLACE: moon @ top-right", "PLACE: cobweb @ top-left"]
        )

        design = parse_design_response(response, "low")

        self.assertEqual(len(design.placements), 3)

    @patch("scripts.spike.urllib.request.urlopen")
    def test_provider_call_uses_openai_chat_completions_shape(self, urlopen):
        response = urlopen.return_value.__enter__.return_value
        response.read.return_value = json.dumps({
            "choices": [{"message": {"content": "PLACE: bat @ top-right"}}],
            "usage": {"prompt_tokens": 17, "completion_tokens": 9},
        }).encode()

        result = call_model(
            "test prompt",
            base_url="http://localhost:11434/v1",
            api_key="test-key",
            model="test-model",
            temperature=0.5,
            max_tokens=100,
            timeout_s=10,
        )

        request = urlopen.call_args.args[0]
        payload = json.loads(request.data)
        self.assertEqual(request.full_url, "http://localhost:11434/v1/chat/completions")
        self.assertEqual(payload["model"], "test-model")
        self.assertEqual(payload["messages"], [{"role": "user", "content": "test prompt"}])
        self.assertEqual(payload["temperature"], 0.5)
        self.assertEqual(request.get_header("Authorization"), "Bearer test-key")
        self.assertEqual(result, ("PLACE: bat @ top-right", 17, 9))

    def test_http_error_includes_provider_message_without_leaking_key(self):
        body = json.dumps({
            "error": {"message": "Invalid model for this API key secret-value"}
        }).encode()
        error = urllib.error.HTTPError(
            "https://provider.invalid/chat/completions",
            400,
            "Bad Request",
            {},
            io.BytesIO(body),
        )

        label = _error_label(error, "secret-value")

        self.assertIn("HTTP 400", label)
        self.assertIn("Invalid model for this API key [REDACTED]", label)
        self.assertNotIn("secret-value", label)

    def test_http_error_handles_list_shaped_provider_response(self):
        body = json.dumps([
            {"error": {"message": "Unsupported model name"}}
        ]).encode()
        error = urllib.error.HTTPError(
            "https://provider.invalid/chat/completions",
            400,
            "Bad Request",
            {},
            io.BytesIO(body),
        )

        label = _error_label(error)

        self.assertEqual(label, "HTTP 400: Unsupported model name")


if __name__ == "__main__":
    unittest.main()
