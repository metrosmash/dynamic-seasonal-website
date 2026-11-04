from __future__ import annotations

import io
import json
import unittest
import urllib.error
from unittest.mock import patch

from app.harness import HarnessEdit, HarnessError, create_harness
from app.harness.browserbase import (
    BrowserbaseHarness,
    release_session,
    to_data_url,
)
from app.harness.js_sandbox import JsNotEnabled, JsNotImplemented, run_js
from app.harness.local import LocalHarness


HTML_PAGE = (
    "<!doctype html><html><head><title>Sample</title></head>"
    "<body><main><h1>Headline</h1><h2>Section</h2><p>Readable content.</p></main></body></html>"
)

CONFIG = {
    "HARNESS_PROVIDER": "auto",
    "BROWSERBASE_API_KEY": "",
    "BROWSERBASE_PROJECT_ID": "",
    "BROWSERBASE_BASE_URL": "https://api.browserbase.com",
    "BROWSERBASE_TIMEOUT_S": 60,
    "HARNESS_ALLOW_JS": False,
}


def _local() -> LocalHarness:
    harness = LocalHarness()
    harness.load(HTML_PAGE, "https://example.com/", "pumpkin-patch", "medium")
    return harness


class LocalHarnessTests(unittest.TestCase):
    def test_rejects_script_input(self):
        harness = LocalHarness()
        with self.assertRaisesRegex(ValueError, "script-free"):
            harness.load("<html><body><script>alert(1)</script></body></html>", "https://x.example/", "pumpkin-patch", "medium")

    def test_rejects_unknown_theme_and_intensity(self):
        harness = LocalHarness()
        with self.assertRaises(ValueError):
            harness.load(HTML_PAGE, "https://example.com/", "nope", "medium")
        with self.assertRaises(ValueError):
            harness.load(HTML_PAGE, "https://example.com/", "pumpkin-patch", "ultra")

    def test_applies_valid_edits_and_snapshot_has_no_scripts(self):
        harness = _local()
        self.assertEqual(harness.apply(HarnessEdit(kind="accent", accent="#ff7a1a")), "")
        self.assertEqual(
            harness.apply(HarnessEdit(kind="placements", placements=(("ghost", "float"), ("crow", "header")))),
            "Some placements were invalid and were skipped.",
        )
        snapshot = harness.snapshot()
        self.assertIn("hw-added", snapshot.html)
        self.assertNotIn("<script", snapshot.html)
        self.assertEqual(snapshot.placements, (("crow", "header"),))
        self.assertEqual(snapshot.harness, "local")

    def test_invalid_edits_fail_closed_with_warnings(self):
        harness = _local()
        before = harness.snapshot()
        self.assertIn("unknown theme", harness.apply(HarnessEdit(kind="theme", theme_id="nope")))
        self.assertIn("invalid accent", harness.apply(HarnessEdit(kind="accent", accent="red")))
        self.assertIn("none were valid", harness.apply(HarnessEdit(kind="placements", placements=(("ghost", "nope"),))))
        self.assertIn("safety rules", harness.apply(HarnessEdit(kind="css", css="body { display: none }")))
        self.assertIn("unknown edit kind", harness.apply(HarnessEdit(kind="exec")))
        self.assertEqual(harness.snapshot().placements, before.placements)
        self.assertEqual(harness.snapshot().theme_id, before.theme_id)

    def test_reset_restores_theme_defaults(self):
        harness = _local()
        harness.apply(HarnessEdit(kind="placements", placements=(("crow", "header"),)))
        harness.apply(HarnessEdit(kind="reset"))
        snapshot = harness.snapshot()
        self.assertEqual(snapshot.theme_id, "pumpkin-patch")
        self.assertTrue(snapshot.placements)


class HarnessFactoryTests(unittest.TestCase):
    def test_auto_without_key_is_local(self):
        self.assertIsInstance(create_harness(CONFIG), LocalHarness)

    def test_unknown_provider_raises(self):
        with self.assertRaises(HarnessError):
            create_harness({**CONFIG, "HARNESS_PROVIDER": "nope"})

    def test_browserbase_without_key_raises(self):
        with self.assertRaises(HarnessError):
            create_harness({**CONFIG, "HARNESS_PROVIDER": "browserbase"})


class BrowserbaseHarnessTests(unittest.TestCase):
    def _response(self, payload: dict):
        response = io.BytesIO(json.dumps(payload).encode())
        context = unittest.mock.MagicMock()
        context.__enter__.return_value.read.return_value = response.read()
        return context

    @patch("app.harness.browserbase.urllib.request.urlopen")
    def test_session_lifecycle_and_live_view(self, urlopen):
        urlopen.side_effect = [
            self._response({"id": "sess-1", "connectUrl": "wss://connect.example"}),
            self._response({"debuggerFullscreenUrl": "https://live.example/sess-1"}),
            self._response({}),
        ]
        config = {**CONFIG, "BROWSERBASE_API_KEY": "secret-key"}
        harness = BrowserbaseHarness(config)
        harness.load(HTML_PAGE, "https://example.com/", "pumpkin-patch", "medium")
        snapshot = harness.snapshot()
        self.assertEqual(snapshot.session_id, "sess-1")
        self.assertEqual(snapshot.live_view_url, "https://live.example/sess-1")
        self.assertEqual(snapshot.harness, "browserbase")
        sent = urlopen.call_args_list[0].args[0]
        sent_headers = {key.lower(): value for key, value in sent.header_items()}
        self.assertEqual(sent_headers["x-bb-api-key"], "secret-key")
        harness.close()
        self.assertEqual(urlopen.call_count, 3)

    @patch("app.harness.browserbase.urllib.request.urlopen")
    def test_api_key_redacted_from_errors(self, urlopen):
        urlopen.side_effect = urllib.error.HTTPError(
            "https://api.browserbase.com/v1/sessions",
            401,
            "Unauthorized",
            {},
            io.BytesIO(b'{"error":"bad key secret-key"}'),
        )
        harness = BrowserbaseHarness({**CONFIG, "BROWSERBASE_API_KEY": "secret-key"})
        with self.assertRaises(HarnessError) as raised:
            harness.load(HTML_PAGE, "https://example.com/", "pumpkin-patch", "medium")
        self.assertIn("[REDACTED]", str(raised.exception))
        self.assertNotIn("secret-key", str(raised.exception))

    @patch("app.harness.browserbase.urllib.request.urlopen")
    def test_release_is_best_effort(self, urlopen):
        urlopen.side_effect = urllib.error.URLError("down")
        release_session("https://api.browserbase.com", "secret-key", "sess-1")

    def test_data_url_round_trip_and_limit(self):
        url = to_data_url("<h1>hi</h1>")
        self.assertTrue(url.startswith("data:text/html"))
        with self.assertRaises(HarnessError):
            to_data_url("x" * 100, max_bytes=10)


class JsSandboxTests(unittest.TestCase):
    def test_disabled_by_default(self):
        with self.assertRaises(JsNotEnabled):
            run_js(CONFIG, "local", "1+1")

    def test_enabled_still_fails_closed(self):
        config = {**CONFIG, "HARNESS_ALLOW_JS": True}
        with self.assertRaises(JsNotImplemented):
            run_js(config, "browserbase", "document.title")
        with self.assertRaises(ValueError):
            run_js(config, "browserbase", "")


if __name__ == "__main__":
    unittest.main()
