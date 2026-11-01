from __future__ import annotations

import io
import time
import unittest
from unittest.mock import patch
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from app import create_app
from app.steps.inline_upload import (
    UploadError,
    inline_upload,
    unpack_upload_zip,
    validate_uploads,
)


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
    data = {"intensity": "medium"}
    files = [(io.BytesIO(html), html_name)]
    if assets:
        files.extend((io.BytesIO(content), name) for name, content in assets.items())
    data["uploads"] = files
    return data


def _zip_bytes(files: dict[str, bytes]) -> bytes:
    output = io.BytesIO()
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        for filename, content in files.items():
            archive.writestr(filename, content)
    return output.getvalue()


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

    def test_unpacks_zip_with_one_html_and_assets(self):
        individual = inline_upload("index.html", UPLOAD_HTML, UPLOAD_FILES)
        uploaded = unpack_upload_zip(
            _zip_bytes({
                "site/index.html": UPLOAD_HTML,
                "site/site.css": UPLOAD_CSS,
                "site/lantern.png": UPLOAD_PNG,
            }),
            max_html_bytes=1024,
            max_total_bytes=4096,
            max_files=8,
        )

        self.assertEqual(uploaded.html_name, "index.html")
        self.assertEqual(uploaded.html_bytes, UPLOAD_HTML)
        self.assertEqual(uploaded.assets, UPLOAD_FILES)
        zipped = inline_upload(uploaded.html_name, uploaded.html_bytes, uploaded.assets)
        self.assertEqual(zipped.source_id, individual.source_id)

    def test_rejects_invalid_zip_without_html_or_with_multiple_html_files(self):
        with self.assertRaisesRegex(UploadError, "invalid or damaged"):
            unpack_upload_zip(
                b"not a zip",
                max_html_bytes=1024,
                max_total_bytes=4096,
                max_files=8,
            )
        with self.assertRaisesRegex(UploadError, "exactly one HTML"):
            unpack_upload_zip(
                _zip_bytes({"one.html": b"<h1>One</h1>", "two.htm": b"<h1>Two</h1>"}),
                max_html_bytes=1024,
                max_total_bytes=4096,
                max_files=8,
            )
        with self.assertRaisesRegex(UploadError, "must contain one"):
            unpack_upload_zip(
                _zip_bytes({"style.css": b"h1{}"}),
                max_html_bytes=1024,
                max_total_bytes=4096,
                max_files=8,
            )

    def test_rejects_unsafe_paths_unsupported_files_and_file_count(self):
        with self.assertRaisesRegex(UploadError, "unsafe path"):
            unpack_upload_zip(
                _zip_bytes({"../index.html": UPLOAD_HTML}),
                max_html_bytes=1024,
                max_total_bytes=4096,
                max_files=8,
            )
        with self.assertRaisesRegex(UploadError, "Unsupported file type"):
            unpack_upload_zip(
                _zip_bytes({"index.html": UPLOAD_HTML, "run.js": b"alert(1)"}),
                max_html_bytes=1024,
                max_total_bytes=4096,
                max_files=8,
            )
        with self.assertRaisesRegex(UploadError, "no more than 1 files"):
            unpack_upload_zip(
                _zip_bytes({"index.html": UPLOAD_HTML, "site.css": UPLOAD_CSS}),
                max_html_bytes=1024,
                max_total_bytes=4096,
                max_files=1,
            )

    def test_rejects_zip_symbolic_links(self):
        output = io.BytesIO()
        with ZipFile(output, "w") as archive:
            archive.writestr("index.html", UPLOAD_HTML)
            symlink = ZipInfo("linked.css")
            symlink.external_attr = (0o120777 << 16)
            archive.writestr(symlink, "target.css")

        with self.assertRaisesRegex(UploadError, "symbolic links"):
            unpack_upload_zip(
                output.getvalue(),
                max_html_bytes=1024,
                max_total_bytes=4096,
                max_files=8,
            )

    def test_zip_total_and_html_caps_apply_to_decompressed_bytes(self):
        with self.assertRaisesRegex(UploadError, "HTML file exceeds"):
            unpack_upload_zip(
                _zip_bytes({"index.html": b"x" * 100}),
                max_html_bytes=20,
                max_total_bytes=4096,
                max_files=8,
            )
        with self.assertRaisesRegex(UploadError, "total limit"):
            unpack_upload_zip(
                _zip_bytes({"index.html": b"<h1>ok</h1>", "site.css": b"a" * 100}),
                max_html_bytes=1024,
                max_total_bytes=40,
                max_files=8,
            )


class UploadRouteTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app({
            "TESTING": True,
            "PROVIDER": "fake",
            "MAX_UPLOAD_HTML_BYTES": 1024,
            "MAX_UPLOAD_TOTAL_BYTES": 4096,
            "MAX_UPLOAD_ARCHIVE_BYTES": 4096,
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

    def _wait_for_job(self, response):
        job_id = response.headers["Location"].rsplit("/", 1)[-1]
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            status = self.client.get(f"/status/{job_id}").json["status"]
            if status in {"done", "error"}:
                return self.app.config["JOBS"][job_id]
            time.sleep(0.01)
        self.fail(f"job {job_id} did not finish")

    def test_homepage_has_one_upload_field_for_all_supported_file_forms(self):
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'name="uploads"', response.data)
        self.assertIn(b'multiple', response.data)
        self.assertIn(b".html,.htm,.css,.png,.jpg,.jpeg,.gif,.webp,.zip", response.data)
        self.assertNotIn(b'name="html_file"', response.data)
        self.assertNotIn(b'name="assets"', response.data)
        self.assertNotIn(b'name="zip_file"', response.data)

    @patch("app.pipeline.fake.complete")
    def test_upload_decorates_and_repeated_upload_hits_cache(self, complete):
        complete.return_value = (
            "THEME: pumpkin-patch\nACCENT: #ff7a1a\nPLACE: bat @ top-right"
        )

        first = self._post_upload()
        first_job = self._wait_for_job(first)
        second = self._post_upload()
        second_job = self._wait_for_job(second)

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
        self._wait_for_job(response)

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

    @patch("app.pipeline.fake.complete")
    def test_zip_upload_decorates_and_caches_by_contents(self, complete):
        complete.return_value = (
            "THEME: pumpkin-patch\nACCENT: #ff7a1a\nPLACE: bat @ top-right"
        )
        archive_bytes = _zip_bytes({
            "site/index.html": UPLOAD_HTML,
            "site/site.css": UPLOAD_CSS,
            "site/lantern.png": UPLOAD_PNG,
        })

        first = self.client.post(
            "/decorate",
            data={
                "uploads": (io.BytesIO(archive_bytes), "site.zip"),
                "intensity": "medium",
            },
            content_type="multipart/form-data",
        )
        first_job = self._wait_for_job(first)
        second = self.client.post(
            "/decorate",
            data={
                "uploads": (io.BytesIO(archive_bytes), "site.zip"),
                "intensity": "medium",
            },
            content_type="multipart/form-data",
        )
        second_job = self._wait_for_job(second)

        self.assertEqual(first.status_code, 303)
        self.assertEqual(second.status_code, 303)
        self.assertEqual(first_job["source_id"], second_job["source_id"])
        self.assertFalse(first_job["cache_hit"])
        self.assertTrue(second_job["cache_hit"])
        self.assertIn("data-uploaded-stylesheet", first_job["original_html"])
        self.assertIn("data:image/png;base64,", first_job["original_html"])
        self.assertEqual(complete.call_count, 1)

    def test_zip_route_reports_bad_archive_and_rejects_mixed_inputs(self):
        invalid_archive = self.client.post(
            "/decorate",
            data={
                "uploads": (io.BytesIO(b"not zip"), "site.zip"),
                "intensity": "medium",
            },
            content_type="multipart/form-data",
        )
        mixed_inputs = self.client.post(
            "/decorate",
            data={
                "uploads": [
                    (io.BytesIO(_zip_bytes({"index.html": UPLOAD_HTML})), "site.zip"),
                    (io.BytesIO(UPLOAD_HTML), "index.html"),
                ],
                "intensity": "medium",
            },
            content_type="multipart/form-data",
        )

        self.assertEqual(invalid_archive.status_code, 400)
        self.assertIn(b"invalid or damaged", invalid_archive.data)
        self.assertEqual(mixed_inputs.status_code, 400)
        self.assertIn(b"either one ZIP file", mixed_inputs.data)

    @patch("app.pipeline.fake.complete")
    def test_regenerate_uses_new_variant_and_original_snapshot_is_available(self, complete):
        complete.return_value = "PLACE: bat @ top-right"
        initial = self._post_upload()
        first = self._wait_for_job(initial)
        first_id = initial.headers["Location"].rsplit("/", 1)[-1]

        original_page = self.client.get(f"/render/{first_id}?view=original")
        regenerated = self.client.post(f"/regenerate/{first_id}")
        second = self._wait_for_job(regenerated)

        self.assertEqual(original_page.status_code, 200)
        self.assertNotIn("hw-root", original_page.get_data(as_text=True))
        self.assertEqual(regenerated.status_code, 303)
        self.assertEqual(second["variant"], first["variant"] + 1)
        self.assertEqual(second["source_id"], first["source_id"])
        self.assertFalse(second["cache_hit"])
        self.assertEqual(complete.call_count, 2)

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
