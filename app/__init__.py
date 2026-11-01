from __future__ import annotations

import hashlib
from collections import OrderedDict
from pathlib import Path
from urllib.parse import quote
from uuid import uuid4

from flask import Flask, abort, jsonify, redirect, render_template, request, url_for
from werkzeug.exceptions import RequestEntityTooLarge

from app.config import load_config
from app.pipeline import decorate_page
from app.steps.load_page import FetchError, load_page
from app.steps.inline_upload import UploadError, inline_upload, safe_filename, unpack_upload_zip
from app.steps.prepare_html import prepare_html


ROOT = Path(__file__).resolve().parents[1]


def create_app(test_config: dict | None = None) -> Flask:
    app = Flask(__name__, template_folder="../templates", static_folder="../static")
    app.config.update(load_config(ROOT))
    if test_config:
        app.config.update(test_config)
    app.config["JOBS"] = {}
    app.config["UPLOAD_CACHE"] = OrderedDict()
    app.config["MAX_CONTENT_LENGTH"] = (
        max(app.config["MAX_UPLOAD_ARCHIVE_BYTES"], app.config["MAX_UPLOAD_TOTAL_BYTES"])
        + 1024 * 1024
    )

    @app.errorhandler(RequestEntityTooLarge)
    def request_too_large(_error):
        return render_template(
            "index.html",
            error="The uploaded files exceed the configured total size limit.",
            submitted_url="",
        ), 413

    @app.after_request
    def add_app_security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        if request.endpoint != "render_page":
            response.headers.setdefault(
                "Content-Security-Policy",
                "default-src 'self'; style-src 'self'; img-src 'self' data:; "
                "script-src 'none'; object-src 'none'; base-uri 'none'; "
                "frame-ancestors 'self'",
            )
        return response

    @app.get("/")
    def index():
        return render_template("index.html", error=None, submitted_url="")

    @app.post("/decorate")
    def decorate():
        source_url = request.form.get("url", "").strip()
        intensity = request.form.get("intensity", "medium")
        if intensity not in {"low", "medium", "high"}:
            return render_template(
                "index.html",
                error="Choose a valid decoration intensity.",
                submitted_url=source_url,
            ), 400
        html_upload = request.files.get("html_file")
        zip_upload = request.files.get("zip_file")
        asset_uploads = request.files.getlist("assets")
        has_html_upload = bool(html_upload and html_upload.filename)
        has_zip_upload = bool(zip_upload and zip_upload.filename)
        provided_assets = [item for item in asset_uploads if item.filename]
        source_id = ""
        upload_warnings: tuple[str, ...] = ()
        if has_html_upload or has_zip_upload:
            if source_url:
                return render_template(
                    "index.html",
                    error="Use either a public URL or a file upload, not both.",
                    submitted_url=source_url,
                ), 400
            if has_zip_upload and (has_html_upload or provided_assets):
                return render_template(
                    "index.html",
                    error="Upload either one ZIP file or separate HTML and asset files, not both.",
                    submitted_url="",
                ), 400
            try:
                if has_zip_upload:
                    if not zip_upload.filename.lower().endswith(".zip"):
                        raise UploadError("Upload a ZIP archive ending in .zip.")
                    archive_bytes = zip_upload.stream.read(
                        app.config["MAX_UPLOAD_ARCHIVE_BYTES"] + 1
                    )
                    if len(archive_bytes) > app.config["MAX_UPLOAD_ARCHIVE_BYTES"]:
                        raise UploadError(
                            f"The ZIP file exceeds the {app.config['MAX_UPLOAD_ARCHIVE_BYTES']}-byte limit."
                        )
                    uploaded_files = unpack_upload_zip(
                        archive_bytes,
                        max_html_bytes=app.config["MAX_UPLOAD_HTML_BYTES"],
                        max_total_bytes=app.config["MAX_UPLOAD_TOTAL_BYTES"],
                        max_files=app.config["MAX_UPLOAD_FILES"],
                    )
                    html_name = uploaded_files.html_name
                    html_bytes = uploaded_files.html_bytes
                    assets = uploaded_files.assets
                else:
                    if len(provided_assets) + 1 > app.config["MAX_UPLOAD_FILES"]:
                        raise UploadError(
                            f"Upload no more than {app.config['MAX_UPLOAD_FILES']} files at once."
                        )
                    html_name = safe_filename(html_upload.filename)
                    html_bytes = html_upload.stream.read(
                        app.config["MAX_UPLOAD_HTML_BYTES"] + 1
                    )
                    assets = {}
                    consumed_bytes = len(html_bytes)
                    if consumed_bytes > app.config["MAX_UPLOAD_HTML_BYTES"]:
                        raise UploadError(
                            f"The HTML file exceeds the {app.config['MAX_UPLOAD_HTML_BYTES']}-byte limit."
                        )
                    for uploaded in provided_assets:
                        safe_name = safe_filename(uploaded.filename)
                        if any(existing.casefold() == safe_name.casefold() for existing in assets):
                            raise UploadError(
                                f"More than one uploaded file has the name {safe_name}."
                            )
                        remaining = app.config["MAX_UPLOAD_TOTAL_BYTES"] - consumed_bytes
                        content = uploaded.stream.read(remaining + 1)
                        consumed_bytes += len(content)
                        if consumed_bytes > app.config["MAX_UPLOAD_TOTAL_BYTES"]:
                            raise UploadError(
                                "The uploaded files exceed the configured total size limit."
                            )
                        assets[safe_name] = content
                upload = inline_upload(
                    html_name,
                    html_bytes,
                    assets,
                    max_html_bytes=app.config["MAX_UPLOAD_HTML_BYTES"],
                    max_total_bytes=app.config["MAX_UPLOAD_TOTAL_BYTES"],
                )
                source_id = upload.source_id
                upload_warnings = upload.warnings
                source_html = upload.html
                source_url = ""
                base_url = f"https://uploaded.local/{quote(html_name)}"
                final_url = ""
            except UploadError as exc:
                return render_template(
                    "index.html",
                    error=str(exc),
                    submitted_url="",
                ), 400
            except OSError as exc:
                return render_template(
                    "index.html",
                    error=f"Could not read the uploaded files: {exc}",
                    submitted_url="",
                ), 400
        elif provided_assets:
            return render_template(
                "index.html",
                error="Upload an HTML file together with CSS or image assets.",
                submitted_url=source_url,
            ), 400
        elif not source_url:
            return render_template(
                "index.html",
                error="Enter a public website URL or choose an HTML file to upload.",
                submitted_url="",
            ), 400
        else:
            try:
                source_html, final_url = load_page(
                    source_url,
                    timeout=app.config["FETCH_TIMEOUT_S"],
                    max_bytes=app.config["MAX_PAGE_BYTES"],
                    max_redirects=app.config["MAX_REDIRECTS"],
                )
            except FetchError as exc:
                return render_template(
                    "index.html",
                    error=str(exc),
                    submitted_url=source_url,
                ), 400
            base_url = final_url
            source_id = hashlib.sha256(final_url.encode("utf-8")).hexdigest()

        try:
            safe_source = prepare_html(source_html, base_url)
        except ValueError as exc:
            return render_template(
                "index.html",
                error=str(exc),
                submitted_url=source_url or "",
            ), 400

        provider = app.config["PROVIDER"]
        model_name = app.config["MODEL_NAME"]
        cache_key = (
            source_id, intensity, provider, model_name, app.config["PROVIDER_BASE_URL"]
        )
        cache = app.config["UPLOAD_CACHE"]
        result = None
        cache_hit = False
        if (has_html_upload or has_zip_upload) and cache_key in cache:
            result = cache[cache_key]
            cache.move_to_end(cache_key)
            cache_hit = True
        if result is None:
            try:
                result = decorate_page(
                    safe_source,
                    source_url=final_url,
                    intensity=intensity,
                    provider=provider,
                    provider_base_url=app.config["PROVIDER_BASE_URL"],
                    provider_api_key=app.config["PROVIDER_API_KEY"],
                    model_name=model_name,
                    model_timeout=app.config["MODEL_TIMEOUT_S"],
                    source_id=source_id,
                )
            except ValueError as exc:
                return render_template(
                    "index.html",
                    error=str(exc),
                    submitted_url=source_url or "",
                ), 400
            if has_html_upload or has_zip_upload:
                result_size = len(result["html"].encode("utf-8"))
                if result_size <= app.config["UPLOAD_CACHE_MAX_BYTES"]:
                    while cache and sum(
                        entry[1] for entry in cache.values()
                    ) + result_size > app.config["UPLOAD_CACHE_MAX_BYTES"]:
                        cache.popitem(last=False)
                    cache[cache_key] = (
                        result,
                        result_size,
                    )
        else:
            result = result[0]

        warning_parts = [result["warning"]] if result["warning"] else []
        warning_parts.extend(upload_warnings)
        warning = " ".join(warning_parts)
        job_id = uuid4().hex
        app.config["JOBS"][job_id] = {
            "source_url": final_url,
            "original_html": safe_source,
            "decorated_html": result["html"],
            "theme": result["theme"],
            "intensity": intensity,
            "design_mode": result["design_mode"],
            "warning": warning,
            "source_id": source_id,
            "cache_hit": cache_hit,
        }
        return redirect(url_for("result_page", job_id=job_id), code=303)

    @app.get("/result/<job_id>")
    def result_page(job_id: str):
        job = app.config["JOBS"].get(job_id)
        if job is None:
            abort(404)
        view = request.args.get("view", "decorated")
        if view not in {"decorated", "original"}:
            abort(400)
        return render_template("result.html", job=job, job_id=job_id, view=view)

    @app.get("/render/<job_id>")
    def render_page(job_id: str):
        job = app.config["JOBS"].get(job_id)
        if job is None:
            abort(404)
        view = request.args.get("view", "decorated")
        if view not in {"decorated", "original"}:
            abort(400)
        html = job["decorated_html"] if view == "decorated" else job["original_html"]
        response = app.response_class(html, content_type="text/html; charset=utf-8")
        response.headers["Content-Security-Policy"] = (
            "default-src 'none'; script-src 'none'; style-src 'unsafe-inline' https:; "
            "img-src https: data:; font-src https: data:; media-src https: data:; "
            "connect-src 'none'; frame-src 'none'; object-src 'none'; form-action 'none'; "
            "base-uri 'none'; sandbox allow-popups allow-popups-to-escape-sandbox"
        )
        return response

    @app.get("/health")
    def health():
        return jsonify(status="ok")

    return app
