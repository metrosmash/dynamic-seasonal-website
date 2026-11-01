from __future__ import annotations

import io
import unittest
from unittest.mock import patch

from app import create_app
from app.steps.inline_upload import UploadError, inline_upload, validate_uploads


UPLOAD_HTML = b"""<!doctype html>
<html><head><link rel="stylesheet" href="assets/site.css"></head>
<body><h1>Uploaded site</h1><img src="images/lantern.png"></body></html>"""
UPLOAD_CSS = b".hero { background-image: url('../images/lantern.png'); }"
UPLOAD_PNG = b"\x89PNG\r\n\x1a\nsmall-image"
UPLOAD_FILES = {
    "site.css": UPLOAD_CSS,
    "lantern.png": UPLOAD_PNG,
}


def _upload_data(
    *,
    html: bytes = UPLOAD_HTML,
    html_name: str = "index.html",
    assets: dict[str, bytes] | None = None,
):
    assets = UPLOAD_FILES if assets is None else assets
    data = {
        "html_file": (io.BytesIO(html), html_name),
        "intensity": "medium",
    }
    if assets:
        data["assets"] = [
            (io.BytesIO(content), name) for name, content in assets.items()
        ]
    return data


class InlineUploadTests(unittest.TestCase):
    def test_inlines_uploaded_stylesheet_and_images(self):
        result = inline_upload("index.html", UPLOAD_HTML, UPLOAD_FILES)

        self.assertIn('data-uploaded-stylesheet="site.css"', result.html)
        self.assertNotIn('<link rel="stylesheet" href="assets/site.css">', result.html)
        self.assertIn(".hero", result.html)
        self.assertIn("data:image/png;base64,", result.html)
        self.assertNotIn("lantern.png", result.html)
        self.assertEqual(result.warnings, ())

    def test_reports_missing_assets_and_keeps_references(self):
        html = b'<html><head><link rel="stylesheet" href="missing.css"></head><body><h1>Page</h1><img src="missing.png"></body></html>'

        result = inline_upload("index.html", html, {})

        self.assertIn("missing.css", result.html)
        self.assertIn('src="missing.png"', result.html)
        self.assertEqual(result.warnings, (
            "missing.css was referenced but not uploaded.",
            "missing.png was referenced but not uploaded.",
        ))

    def test_source_id_is_stable_and_changes_with_uploaded_content(self):
        first = inline_upload("index.html", UPLOAD_HTML, UPLOAD_FILES)
        second = inline_upload("index.html", UPLOAD_HTML, dict(UPLOAD_FILES))
        changed = inline_upload("index.html", UPLOAD_HTML + b" ", UPLOAD_FILES)

        self.assertEqual(first.source_id, second.source_id)
        self.assertNotEqual(first.source_id, changed.source_id)

    def test_rejects_bad_extensions_empty_html_and_size_overages(self):
        with self.assertRaisesRegex(UploadError, "ending in .html or .htm"):
            validate_uploads("page.txt", UPLOAD_HTML, {}, max_html_bytes=1024, max_total_bytes=2048)
        with self.assertRaisesRegex(UploadError, "Unsupported file type"):
            validate_uploads(
                "page.html", UPLOAD_HTML, {"payload.svg": b"<svg/>"},
                max_html_bytes=1024, max_total_bytes=2048,
            )
        with self.assertRaisesRegex(UploadError, "empty"):
            validate_uploads("page.html", b"", {}, max_html_bytes=1024, max_total_bytes=2048)
        with self.assertRaisesRegex(UploadError, "HTML file exceeds"):
            validate_uploads(
                "page.html", b"12345", {}, max_html_bytes=4, max_total_bytes=10
            )
        with self.assertRaisesRegex(UploadError, "total limit"):
            validate_uploads(
                "page.html", b"1234", {"site.css": b"56789"},
                max_html_bytes=8, max_total_bytes=8,
            )

    def test_rejects_duplicate_asset_names_even_with_path_prefixes(self):
        with self.assertRaisesRegex(UploadError, "More than one uploaded file"):
            validate_uploads(
                "page.html",
                UPLOAD_HTML,
                {"assets/site.css": b"a{}", "site.css": b"b{}"},
                max_html_bytes=1024,
                max_total_bytes=2048,
            )


class UploadRouteTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app({
            "TESTING": True,
            "PROVIDER": "fake",
            "MAX_UPLOAD_HTML_BYTES": 1024,
            "MAX_UPLOAD_TOTAL_BYTES": 4096,
            "UPLOAD_CACHE_MAX_BYTES": 8192,
            "MAX_UPLOAD_FILES": 8,
        })
        self.client = self.app.test_client()

    def _post_upload(self, **kwargs):
        return self.client.post(
            "/decorate",
            data=_upload_data(**kwargs),
            content_type="multipart/form-data",
        )

    @patch("app.pipeline.fake.complete")
    def test_upload_decorates_and_repeated_upload_hits_cache(self, complete):
        complete.return_value = (
            "THEME: pumpkin-patch\nACCENT: #ff7a1a\nPLACE: bat @ top-right"
        )

        first = self._post_upload()
        first_job = next(iter(self.app.config["JOBS"].values()))
        second = self._post_upload()
        second_job = list(self.app.config["JOBS"].values())[-1]

        self.assertEqual(first.status_code, 303)
        self.assertEqual(second.status_code, 303)
        self.assertEqual(first_job["source_id"], second_job["source_id"])
        self.assertFalse(first_job["cache_hit"])
        self.assertTrue(second_job["cache_hit"])
        self.assertIn("data:image/png;base64,", first_job["original_html"])
        self.assertIn("data-uploaded-stylesheet", first_job["original_html"])
        self.assertIn("Decorated version of uploaded website files", first_job["decorated_html"])
        self.assertEqual(complete.call_count, 1)

    @patch("app.pipeline.fake.complete")
    def test_missing_asset_warning_is_visible_on_result_page(self, complete):
        complete.return_value = (
            "THEME: pumpkin-patch\nACCENT: #ff7a1a\nPLACE: bat @ top-right"
        )
        response = self._post_upload(
            html=b'<html><head><link rel="stylesheet" href="missing.css"></head><body><h1>Page</h1></body></html>',
            assets={},
        )

        result_page = self.client.get(response.headers["Location"])

        self.assertEqual(response.status_code, 303)
        self.assertIn(b"missing.css was referenced but not uploaded.", result_page.data)

    def test_upload_size_and_extension_errors_are_shown_to_user(self):
        oversized = self._post_upload(html=b"x" * 1025)
        wrong_extension = self._post_upload(html_name="page.txt")

        self.assertEqual(oversized.status_code, 400)
        self.assertIn(b"HTML file exceeds", oversized.data)
        self.assertEqual(wrong_extension.status_code, 400)
        self.assertIn(b"ending in .html or .htm", wrong_extension.data)

    @patch("app.load_page")
    def test_existing_url_flow_still_works(self, load):
        load.return_value = (
            "<html><body><h1>URL source</h1><p>Content</p></body></html>",
            "https://example.com/",
        )

        response = self.client.post(
            "/decorate",
            data={"url": "https://example.com/", "intensity": "medium"},
        )

        self.assertEqual(response.status_code, 303)
        load.assert_called_once()


if __name__ == "__main__":
    unittest.main()
