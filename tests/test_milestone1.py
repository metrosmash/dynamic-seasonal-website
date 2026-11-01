from __future__ import annotations

import io
import time
import socket
import unittest
import urllib.error
from unittest.mock import patch
from urllib.parse import urlsplit

from app import create_app
from app.content.themes import select_theme
from app.pipeline import decorate_page
from app.providers.openai_compat import complete as complete_openai_compat
from app.steps.load_page import FetchError, _request_once, load_page
from app.steps.prepare_html import prepare_html
from app.steps.validate_input import URLValidationError, validate_public_url


HTML_PAGE = (
    "<!doctype html><html><head><title>Public sample</title></head>"
    "<body><main><h1>Sample headline</h1><p>Readable public content.</p></main></body></html>"
)


def _dns_record(ip: str):
    family = socket.AF_INET6 if ":" in ip else socket.AF_INET
    return (family, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (ip, 0))


class URLValidationTests(unittest.TestCase):
    def test_rejects_non_http_schemes_user_info_and_nonstandard_ports(self):
        for url in (
            "file:///etc/passwd",
            "ftp://example.com/",
            "https://user:pass@example.com/",
            "https://example.com:444/",
        ):
            with self.subTest(url=url), self.assertRaises(URLValidationError):
                validate_public_url(url)

    def test_rejects_overlong_url(self):
        with self.assertRaises(URLValidationError):
            validate_public_url("https://example.com/" + "a" * 2048)

    def test_rejects_loopback_and_private_ip_literals(self):
        for url in (
            "http://127.0.0.1/",
            "http://10.2.3.4/",
            "http://169.254.169.254/",
            "http://[::1]/",
        ):
            with self.subTest(url=url), self.assertRaises(URLValidationError):
                validate_public_url(url)

    @patch("app.steps.validate_input.socket.getaddrinfo")
    def test_rejects_hostname_if_any_dns_answer_is_non_public(self, getaddrinfo):
        getaddrinfo.return_value = [
            _dns_record("93.184.216.34"),
            _dns_record("127.0.0.1"),
        ]

        with self.assertRaisesRegex(URLValidationError, "publicly routable"):
            validate_public_url("https://example.com/")

    @patch("app.steps.validate_input.socket.getaddrinfo")
    def test_returns_all_public_addresses(self, getaddrinfo):
        getaddrinfo.return_value = [
            _dns_record("93.184.216.34"),
            _dns_record("2606:2800:220:1:248:1893:25c8:1946"),
        ]

        _, addresses = validate_public_url("https://example.com/")

        self.assertEqual(addresses, [
            "93.184.216.34",
            "2606:2800:220:1:248:1893:25c8:1946",
        ])


class PageLoadingTests(unittest.TestCase):
    @patch("app.steps.load_page._request_once")
    @patch("app.steps.load_page.validate_public_url")
    def test_loads_html_and_returns_final_url(self, validate, request_once):
        validate.return_value = (urlsplit("https://example.com/page"), ["93.184.216.34"])
        request_once.return_value = (200, None, HTML_PAGE.encode(), "text/html; charset=utf-8")

        html, final_url = load_page("https://example.com/page")

        self.assertIn("Sample headline", html)
        self.assertEqual(final_url, "https://example.com/page")

    @patch("app.steps.load_page._request_once")
    @patch("app.steps.load_page.validate_public_url")
    def test_revalidates_redirect_destination_before_request(self, validate, request_once):
        validate.side_effect = [
            (urlsplit("https://public.example/"), ["93.184.216.34"]),
            URLValidationError("private destination blocked"),
        ]
        request_once.return_value = (302, "http://127.0.0.1/admin", None, "")

        with self.assertRaisesRegex(FetchError, "private destination blocked"):
            load_page("https://public.example/")

        self.assertEqual(request_once.call_count, 1)

    @patch("app.steps.load_page._request_once")
    @patch("app.steps.load_page.validate_public_url")
    def test_rejects_non_html_response(self, validate, request_once):
        validate.return_value = (urlsplit("https://example.com/file"), ["93.184.216.34"])
        request_once.return_value = (200, None, b"not html", "application/pdf")

        with self.assertRaisesRegex(FetchError, "did not return an HTML page"):
            load_page("https://example.com/file")

    def test_rejects_script_only_page_after_preparation(self):
        with self.assertRaisesRegex(ValueError, "no readable HTML text"):
            prepare_html("<html><body><script>document.write('later')</script></body></html>", "https://example.com")

    @patch("app.steps.load_page._PinnedHTTPSConnection")
    def test_http_failure_is_reported(self, connection_class):
        connection = connection_class.return_value
        connection.getresponse.return_value.status = 404
        connection.getresponse.return_value.read.return_value = b"not found"

        with self.assertRaisesRegex(FetchError, "HTTP 404"):
            _request_once(
                "https://example.com/missing",
                ["93.184.216.34"],
                timeout=2,
                max_bytes=1024,
            )

    @patch("app.steps.load_page._PinnedHTTPSConnection")
    def test_content_length_over_limit_is_rejected_before_body_read(self, connection_class):
        response = connection_class.return_value.getresponse.return_value
        response.status = 200
        response.getheader.side_effect = lambda name, default=None: {
            "Content-Type": "text/html",
            "Content-Encoding": "identity",
            "Content-Length": "2048",
        }.get(name, default)

        with self.assertRaisesRegex(FetchError, "page limit"):
            _request_once(
                "https://example.com/large",
                ["93.184.216.34"],
                timeout=2,
                max_bytes=1024,
            )

        response.read.assert_not_called()


class HTMLPreparationTests(unittest.TestCase):
    def test_removes_active_content_and_rewrites_relative_resources(self):
        page = """<html><head><base href="/assets/"><meta http-equiv="refresh" content="0;url=/next"></head>
<body onload="bad()"><script>alert(1)</script><h1>Visible title</h1>
<img src="photo.png" onerror="bad()"><a href="javascript:alert(1)">Unsafe link</a>
<a href="story">Story</a></body></html>"""

        prepared = prepare_html(page, "https://site.example/path/page.html")

        self.assertNotIn("<script", prepared)
        self.assertNotIn("onload", prepared)
        self.assertNotIn("onerror", prepared)
        self.assertNotIn("<base", prepared)
        self.assertNotIn("http-equiv=\"refresh\"", prepared)
        self.assertNotIn("javascript:", prepared)
        self.assertIn('src="https://site.example/assets/photo.png"', prepared)
        self.assertIn('href="https://site.example/assets/story"', prepared)
        self.assertIn("noopener", prepared)

    def test_rewrites_srcset_and_css_urls_using_base_href(self):
        page = """<html><head><base href="https://cdn.example/assets/">
<style>.hero { background-image: url("../images/bg.png"); }
.icon { background-image: url('//images.example/icon.svg'); }</style></head>
<body><img srcset="small.png 1x, //cdn.example/large.png 2x">
<img srcset="data:image/png;base64,abc 1x, large.png 2x">
<div style="background: url('tile.png')"></div>
<a href="?view=full">Query</a><a href="#section">Section</a></body></html>"""

        prepared = prepare_html(page, "https://site.example/path/page.html")

        self.assertIn("https://cdn.example/assets/small.png 1x", prepared)
        self.assertIn("https://cdn.example/large.png 2x", prepared)
        self.assertIn("data:image/png;base64,abc 1x", prepared)
        self.assertIn("https://cdn.example/assets/large.png 2x", prepared)
        self.assertIn("https://cdn.example/images/bg.png", prepared)
        self.assertIn("https://images.example/icon.svg", prepared)
        self.assertIn("https://cdn.example/assets/tile.png", prepared)
        self.assertIn('href="https://cdn.example/assets/?view=full"', prepared)
        self.assertIn('href="#section"', prepared)

    def test_drops_malformed_url_attributes_without_crashing(self):
        prepared = prepare_html(
            '<html><body><h1>Readable</h1><a href="http://[invalid">Broken</a></body></html>',
            "https://site.example/",
        )

        self.assertIn("Broken", prepared)
        self.assertNotIn("href=", prepared)


class FlaskSliceTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app({
            "TESTING": True,
            "PROVIDER": "fake",
            "JOBS": {},
        })
        self.client = self.app.test_client()

    def _wait_for_job(self, job_id):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            status = self.client.get(f"/status/{job_id}").json["status"]
            if status in {"done", "error"}:
                return status
            time.sleep(0.01)
        self.fail(f"job {job_id} did not finish")

    def test_home_and_health(self):
        home = self.client.get("/")
        health = self.client.get("/health")

        self.assertEqual(home.status_code, 200)
        self.assertIn(b"public website URL", home.data)
        self.assertEqual(health.json, {"status": "ok"})
        self.assertEqual(health.headers["X-Content-Type-Options"], "nosniff")

    @patch("app.load_page")
    def test_post_decorate_redirects_to_sandboxed_preview(self, load):
        load.return_value = (HTML_PAGE, "https://example.com/")

        response = self.client.post(
            "/decorate",
            data={"url": "https://example.com/", "intensity": "medium"},
        )

        self.assertEqual(response.status_code, 303)
        job_id = response.headers["Location"].rsplit("/", 1)[-1]
        self.assertEqual(self._wait_for_job(job_id), "done")
        result = self.client.get(response.headers["Location"])
        self.assertEqual(result.status_code, 200)
        self.assertIn(b'sandbox="allow-popups allow-popups-to-escape-sandbox"', result.data)

        render_url = result.get_data(as_text=True).split('src="', 1)[1].split('"', 1)[0]
        rendered = self.client.get(render_url)
        self.assertEqual(rendered.status_code, 200)
        csp = rendered.headers["Content-Security-Policy"]
        self.assertIn("script-src 'none'", csp)
        self.assertIn("sandbox", csp)
        self.assertIn("hw-added", rendered.get_data(as_text=True))
        self.assertNotIn("<script", rendered.get_data(as_text=True))

    @patch("app.load_page")
    def test_fetch_error_is_shown_to_user(self, load):
        load.side_effect = FetchError("private destination blocked")

        response = self.client.post(
            "/decorate",
            data={"url": "https://example.com/", "intensity": "medium"},
        )

        self.assertEqual(response.status_code, 303)
        job_id = response.headers["Location"].rsplit("/", 1)[-1]
        self.assertEqual(self._wait_for_job(job_id), "error")
        result = self.client.get(response.headers["Location"])
        self.assertIn(b"private destination blocked", result.data)

    def test_unknown_render_job_is_not_found(self):
        self.assertEqual(self.client.get("/render/missing").status_code, 404)


class PipelineTests(unittest.TestCase):
    def test_fake_provider_generates_a_themed_page_without_model_credentials(self):
        result = decorate_page(
            HTML_PAGE,
            source_url="https://example.com/",
            intensity="medium",
            provider="fake",
            provider_base_url="",
            provider_api_key="",
            model_name="",
            model_timeout=1,
        )

        self.assertEqual(result["theme"], select_theme("https://example.com/", "medium").id)
        self.assertEqual(result["design_mode"], "sample provider")
        self.assertIn("var(--hw-bg)", result["html"])
        self.assertIn('data-hw-slot="top-right"', result["html"])
        self.assertIn('data-hw-added="banner"', result["html"])
        self.assertIn("Decorated version of", result["html"])

    @patch("app.pipeline.fake.complete")
    def test_valid_model_placements_are_applied(self, complete):
        complete.return_value = """THEME: pumpkin-patch
ACCENT: #ff7a1a
PLACE: crow @ header
PLACE: candle @ footer"""

        result = decorate_page(
            HTML_PAGE,
            source_url="https://example.com/",
            intensity="medium",
            provider="fake",
            provider_base_url="",
            provider_api_key="",
            model_name="",
            model_timeout=1,
        )

        self.assertIn('data-hw-slot="header"', result["html"])
        self.assertIn('data-hw-slot="footer"', result["html"])
        self.assertEqual(result["warning"], "")

    @patch("app.providers.openai_compat.urllib.request.urlopen")
    def test_openai_compatible_provider_sends_configured_bearer_key(self, urlopen):
        response = urlopen.return_value.__enter__.return_value
        response.read.return_value = (
            b'{"choices":[{"message":{"content":"PLACE: moon @ top-right"}}]}'
        )

        complete_openai_compat(
            "prompt",
            base_url="https://provider.example/v1/",
            api_key="local-test-key",
            model="test-model",
            temperature=0.5,
            max_tokens=50,
            timeout_s=2,
        )

        sent_request = urlopen.call_args.args[0]
        self.assertEqual(sent_request.get_header("Authorization"), "Bearer local-test-key")

    @patch("app.providers.openai_compat.urllib.request.urlopen")
    def test_openai_compatible_provider_redacts_key_from_error_body(self, urlopen):
        body = b'{"error":{"message":"bad key local-test-secret"}}'
        urlopen.side_effect = urllib.error.HTTPError(
            "https://provider.example/v1/chat/completions",
            400,
            "Bad Request",
            {},
            io.BytesIO(body),
        )

        with self.assertRaises(FetchError) as raised:
            complete_openai_compat(
                "prompt",
                base_url="https://provider.example/v1/",
                api_key="local-test-secret",
                model="test-model",
                temperature=0.5,
                max_tokens=50,
                timeout_s=2,
            )

        self.assertIn("[REDACTED]", str(raised.exception))
        self.assertNotIn("local-test-secret", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
