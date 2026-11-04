from __future__ import annotations

import hashlib
import json
import logging
import time
import threading
from collections import OrderedDict
from pathlib import Path
from urllib.parse import quote
from uuid import uuid4

from flask import Flask, abort, jsonify, redirect, render_template, request, url_for
from werkzeug.exceptions import RequestEntityTooLarge

from app.agent.loop import run_agent
from app.config import load_config
from app.content.themes import select_theme
from app.harness import HarnessError, create_harness
from app.harness.local import LocalHarness
from app.job_pool import BoundedJobPool
from app.pipeline import decorate_page
from app.rate_limit import RequestLimiter
from app.steps.load_page import FetchError, load_page
from app.steps.inline_upload import UploadError, inline_upload, safe_filename, unpack_upload_zip
from app.steps.prepare_html import prepare_html


ROOT = Path(__file__).resolve().parents[1]
LOGGER = logging.getLogger("halloween.jobs")


class JobDeadlineExceeded(TimeoutError):
    pass


class _SourceError(ValueError):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


def _log_step(job_id: str, step: str, started_at: float, outcome: str) -> None:
    LOGGER.info(json.dumps({
        "job_id": job_id,
        "step": step,
        "duration_ms": round((time.monotonic() - started_at) * 1000),
        "outcome": outcome,
    }, separators=(",", ":")))


def create_app(test_config: dict | None = None) -> Flask:
    app = Flask(__name__, template_folder="../templates", static_folder="../static")
    app.config.update(load_config(ROOT))
    if test_config:
        app.config.update(test_config)
    app.config["JOBS"] = {}
    app.config["RESULT_CACHE"] = OrderedDict()
    app.config["UPLOAD_CACHE"] = app.config["RESULT_CACHE"]
    app.config["CACHE_BYTES"] = 0
    app.config["CACHE_LOCK"] = threading.RLock()
    app.config["JOBS_LOCK"] = threading.RLock()
    app.config["JOB_POOL"] = BoundedJobPool(
        workers=app.config["JOB_WORKERS"],
        max_pending=app.config["MAX_PENDING_JOBS"],
    )
    app.config["REQUEST_LIMITER"] = RequestLimiter(
        burst=app.config["RATE_LIMIT_BURST"],
        refill_seconds=app.config["RATE_LIMIT_WINDOW_S"],
        daily_limit=app.config["DAILY_REQUEST_LIMIT"],
    )
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

    def parse_source() -> tuple[str, str | None, str, str, tuple[str, ...]]:
        """Read the posted URL or uploaded files; shared by single and agent modes."""
        source_url = request.form.get("url", "").strip()
        uploads = [item for item in request.files.getlist("uploads") if item.filename]
        zip_uploads = []
        html_uploads = []
        provided_assets = []
        for item in uploads:
            filename = item.filename.lower()
            if filename.endswith(".zip"):
                zip_uploads.append(item)
            elif filename.endswith((".html", ".htm")):
                html_uploads.append(item)
            else:
                provided_assets.append(item)
        has_zip_upload = bool(zip_uploads)
        has_upload = bool(uploads)
        upload_warnings: tuple[str, ...] = ()
        html_source: str | None = None
        base_url = ""
        source_id = ""
        if uploads:
            if source_url:
                raise _SourceError("Use either a public URL or a file upload, not both.")
            if has_zip_upload and len(uploads) != 1:
                raise _SourceError(
                    "Upload either one ZIP file or separate HTML and asset files, not both."
                )
            try:
                if has_zip_upload:
                    zip_upload = zip_uploads[0]
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
                    if len(html_uploads) != 1:
                        if len(html_uploads) > 1:
                            raise UploadError("Upload exactly one HTML file.")
                        if provided_assets:
                            asset_extensions = {".css", ".png", ".jpg", ".jpeg", ".gif", ".webp"}
                            if all(
                                "." + item.filename.rsplit(".", 1)[-1].lower() in asset_extensions
                                for item in provided_assets
                            ):
                                raise UploadError(
                                    "Upload an HTML file together with CSS or image assets."
                                )
                        raise UploadError("Choose a main file ending in .html or .htm, or one ZIP archive.")
                    if len(provided_assets) + 1 > app.config["MAX_UPLOAD_FILES"]:
                        raise UploadError(
                            f"Upload no more than {app.config['MAX_UPLOAD_FILES']} files at once."
                        )
                    html_upload = html_uploads[0]
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
                upload_warnings = upload.warnings
                html_source = upload.html
                source_url = ""
                source_id = upload.source_id
                base_url = f"https://uploaded.local/{quote(html_name)}"
            except UploadError as exc:
                raise _SourceError(str(exc)) from exc
            except OSError as exc:
                raise _SourceError(f"Could not read the uploaded files: {exc}") from exc
        elif not source_url:
            raise _SourceError("Enter a public website URL or choose an HTML file to upload.")
        return source_url, html_source, base_url, source_id, upload_warnings

    def enqueue_job(
        *,
        request_url: str,
        html_source: str | None,
        base_url: str,
        source_id: str,
        intensity: str,
        provider_api_key: str,
        upload_warnings: tuple[str, ...] = (),
        variant: int = 0,
        mode: str = "single",
        instruction: str = "",
        history: tuple[str, ...] = (),
    ) -> str | None:
        jobs = app.config["JOBS"]
        job_id = uuid4().hex
        job = {
            "status": "queued",
            "progress": "Waiting for a worker",
            "source_url": request_url,
            "intensity": intensity,
            "variant": variant,
            "warning": "",
            "error": "",
            "upload_warnings": upload_warnings,
            "mode": mode,
            "instruction": instruction,
        }
        with app.config["JOBS_LOCK"]:
            if len(jobs) >= app.config["MAX_STORED_JOBS"]:
                terminal_job = next(
                    (
                        existing_id for existing_id, existing_job in jobs.items()
                        if existing_job["status"] in {"done", "error"}
                    ),
                    None,
                )
                if terminal_job is None:
                    return None
                jobs.pop(terminal_job, None)
            jobs[job_id] = job

        def execute() -> None:
            started_at = time.monotonic()
            deadline = started_at + app.config["JOB_DEADLINE_S"]
            current_step = "fetch"
            step_started = started_at

            def ensure_time() -> int:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise JobDeadlineExceeded("The decoration job exceeded its time limit.")
                return max(1, int(remaining))

            def execute_agent_mode() -> None:
                nonlocal current_step, step_started
                ensure_time()
                job["progress"] = "Agent is editing the page in the harness"
                current_step = "agent"
                step_started = time.monotonic()
                max_iterations = app.config["AGENT_MAX_ITERATIONS"]
                per_call_timeout = max(
                    1,
                    min(
                        app.config["MODEL_TIMEOUT_S"],
                        ensure_time() // max(1, max_iterations),
                    ),
                )
                theme = select_theme(source_key, intensity, variant)
                harness_warning = ""
                harness = None
                try:
                    try:
                        harness = create_harness(app.config)
                        harness.load(safe_source, final_url, theme.id, intensity)
                    except HarnessError as exc:
                        harness = LocalHarness()
                        harness.load(safe_source, final_url, theme.id, intensity)
                        harness_warning = (
                            f"Cloud harness unavailable ({exc}); used the local harness."
                        )
                    agent_result = run_agent(
                        harness,
                        source_html=safe_source,
                        intensity=intensity,
                        theme_id=theme.id,
                        instruction=instruction,
                        provider=app.config["PROVIDER"],
                        provider_base_url=app.config["PROVIDER_BASE_URL"],
                        provider_api_key=provider_api_key,
                        model_name=app.config["MODEL_NAME"],
                        fallback_provider=app.config["FALLBACK_PROVIDER"],
                        fallback_provider_base_url=app.config["FALLBACK_PROVIDER_BASE_URL"],
                        fallback_provider_api_key=app.config["FALLBACK_PROVIDER_API_KEY"],
                        fallback_model_name=app.config["FALLBACK_MODEL_NAME"],
                        model_timeout=per_call_timeout,
                        max_iterations=max_iterations,
                        max_message_chars=app.config["AGENT_MAX_MESSAGE_CHARS"],
                        history=history,
                    )
                    snapshot = agent_result.snapshot
                finally:
                    if harness is not None:
                        harness.close()
                _log_step(job_id, "agent", step_started, "ok")
                warning_parts = []
                if harness_warning:
                    warning_parts.append(harness_warning)
                if agent_result.warning:
                    warning_parts.append(agent_result.warning)
                warning_parts.extend(upload_warnings)
                job.update({
                    "status": "done",
                    "progress": "Preview ready",
                    "source_url": final_url,
                    "original_html": safe_source,
                    "decorated_html": snapshot.html,
                    "theme": snapshot.theme_id,
                    "design_mode": agent_result.design_mode,
                    "warning": " ".join(warning_parts),
                    "source_id": source_key,
                    "cache_hit": False,
                    "base_url": base_url or final_url,
                    "agent_history": [
                        *history,
                        *(item.note for item in agent_result.iterations if item.note),
                    ],
                    "agent_iterations": [
                        {
                            "applied": list(item.applied),
                            "warnings": list(item.warnings),
                            "note": item.note,
                            "done": item.done,
                        }
                        for item in agent_result.iterations
                    ],
                    "live_view_url": snapshot.live_view_url,
                    "harness": snapshot.harness,
                })
                _log_step(job_id, "job", started_at, "ok")

            try:
                job["status"] = "running"
                if html_source is None:
                    job["progress"] = "Fetching the page"
                    step_started = time.monotonic()
                    loaded_html, final_url = load_page(
                        request_url,
                        timeout=max(
                            1,
                            min(
                                app.config["FETCH_TIMEOUT_S"],
                                ensure_time() // (app.config["MAX_REDIRECTS"] + 1),
                            ),
                        ),
                        max_bytes=app.config["MAX_PAGE_BYTES"],
                        max_redirects=app.config["MAX_REDIRECTS"],
                    )
                    source_key = hashlib.sha256(
                        (final_url + "\0" + loaded_html).encode("utf-8")
                    ).hexdigest()
                    _log_step(job_id, "fetch", step_started, "ok")
                else:
                    loaded_html = html_source
                    final_url = request_url
                    source_key = source_id

                ensure_time()
                job["progress"] = "Preparing the page"
                current_step = "prepare"
                step_started = time.monotonic()
                safe_source = prepare_html(loaded_html, base_url or final_url or "https://uploaded.local/")
                _log_step(job_id, "prepare", step_started, "ok")

                if mode == "agent":
                    execute_agent_mode()
                    return

                current_step = "cache"
                step_started = time.monotonic()
                provider = app.config["PROVIDER"]
                provider_base_url = app.config["PROVIDER_BASE_URL"]
                model_name = app.config["MODEL_NAME"]
                fallback_provider = app.config["FALLBACK_PROVIDER"]
                fallback_base_url = app.config["FALLBACK_PROVIDER_BASE_URL"]
                fallback_model_name = app.config["FALLBACK_MODEL_NAME"]
                api_key_fingerprint = hashlib.sha256(
                    provider_api_key.encode("utf-8")
                ).hexdigest()
                fallback_api_key = app.config["FALLBACK_PROVIDER_API_KEY"]
                fallback_api_key_fingerprint = hashlib.sha256(
                    fallback_api_key.encode("utf-8")
                ).hexdigest()
                cache_key = (
                    source_key, intensity, provider, model_name, provider_base_url,
                    api_key_fingerprint, fallback_provider, fallback_model_name,
                    fallback_base_url, fallback_api_key_fingerprint, variant,
                )
                cache = app.config["RESULT_CACHE"]
                result = None
                with app.config["CACHE_LOCK"]:
                    cached = cache.get(cache_key)
                    if cached is not None:
                        cache.move_to_end(cache_key)
                        result = cached[0]
                cache_hit = result is not None
                _log_step(job_id, "cache", step_started, "hit" if cache_hit else "miss")
                if result is None:
                    ensure_time()
                    job["progress"] = "Choosing decorations and building the preview"
                    current_step = "design_and_assemble"
                    step_started = time.monotonic()
                    result = decorate_page(
                        safe_source,
                        source_url=final_url,
                        intensity=intensity,
                        provider=provider,
                        provider_base_url=provider_base_url,
                        provider_api_key=provider_api_key,
                        model_name=model_name,
                        fallback_provider=fallback_provider,
                        fallback_provider_base_url=fallback_base_url,
                        fallback_provider_api_key=fallback_api_key,
                        fallback_model_name=fallback_model_name,
                        model_timeout=max(
                            1,
                            min(
                                app.config["MODEL_TIMEOUT_S"],
                                ensure_time()
                                // (
                                    4
                                    if provider == "openai_compat"
                                    and fallback_provider != "none"
                                    else 2
                                ),
                            ),
                        ),
                        variant=variant,
                        source_id=source_key,
                    )
                    ensure_time()
                    _log_step(job_id, "design_and_assemble", step_started, "ok")
                    result_size = len(result["html"].encode("utf-8"))
                    if result_size <= app.config["UPLOAD_CACHE_MAX_BYTES"]:
                        with app.config["CACHE_LOCK"]:
                            if cache_key not in cache:
                                while (
                                    cache
                                    and app.config["CACHE_BYTES"] + result_size
                                    > app.config["UPLOAD_CACHE_MAX_BYTES"]
                                ):
                                    _, (_, removed_size) = cache.popitem(last=False)
                                    app.config["CACHE_BYTES"] -= removed_size
                                cache[cache_key] = (result, result_size)
                                app.config["CACHE_BYTES"] += result_size
                warning_parts = [result["warning"]] if result["warning"] else []
                warning_parts.extend(upload_warnings)
                job.update({
                    "status": "done",
                    "progress": "Preview ready",
                    "source_url": final_url,
                    "original_html": safe_source,
                    "decorated_html": result["html"],
                    "theme": result["theme"],
                    "design_mode": result["design_mode"],
                    "warning": " ".join(warning_parts),
                    "source_id": source_key,
                    "cache_hit": cache_hit,
                    "base_url": base_url or final_url,
                })
                _log_step(job_id, "job", started_at, "ok")
            except (FetchError, ValueError, OSError, JobDeadlineExceeded) as exc:
                _log_step(job_id, current_step, step_started, "error")
                job.update({
                    "status": "error",
                    "progress": "Preview could not be created",
                    "error": str(exc),
                })
                _log_step(job_id, "job", started_at, "error")
            except Exception:
                _log_step(job_id, current_step, step_started, "error")
                job.update({
                    "status": "error",
                    "progress": "Preview could not be created",
                    "error": "An unexpected error occurred while creating the preview.",
                })
                LOGGER.error(json.dumps({
                    "job_id": job_id,
                    "step": "job",
                    "outcome": "unexpected_error",
                }, separators=(",", ":")))

        try:
            future = app.config["JOB_POOL"].submit(execute)
        except RuntimeError:
            with app.config["JOBS_LOCK"]:
                jobs.pop(job_id, None)
            raise
        if future is None:
            with app.config["JOBS_LOCK"]:
                jobs.pop(job_id, None)
            return None
        return job_id

    @app.post("/decorate")
    def decorate():
        allowed, retry_after = app.config["REQUEST_LIMITER"].consume(
            request.remote_addr or "unknown"
        )
        if not allowed:
            response = app.make_response((
                render_template(
                    "index.html",
                    error="Too many decoration requests. Please wait and try again.",
                    submitted_url="",
                ),
                429,
            ))
            response.headers["Retry-After"] = str(retry_after)
            return response
        source_url = request.form.get("url", "").strip()
        transient_api_key = request.form.get("provider_api_key", "").strip()
        provider_api_key = transient_api_key or app.config["PROVIDER_API_KEY"]
        intensity = request.form.get("intensity", "medium")
        if intensity not in {"low", "medium", "high"}:
            return render_template(
                "index.html",
                error="Choose a valid decoration intensity.",
                submitted_url=source_url,
            ), 400
        try:
            source_url, html_source, base_url, source_id, upload_warnings = parse_source()
        except _SourceError as exc:
            return render_template(
                "index.html",
                error=str(exc),
                submitted_url=request.form.get("url", "").strip(),
            ), exc.status
        job_id = enqueue_job(
            request_url=source_url,
            html_source=html_source,
            base_url=base_url,
            source_id=source_id,
            intensity=intensity,
            provider_api_key=provider_api_key,
            upload_warnings=upload_warnings,
        )
        if job_id is None:
            return render_template(
                "index.html",
                error="The preview queue is full. Please wait a moment and try again.",
                submitted_url=source_url,
            ), 429
        return redirect(url_for("result_page", job_id=job_id), code=303)

    @app.post("/agent")
    def agent_start():
        allowed, retry_after = app.config["REQUEST_LIMITER"].consume(
            request.remote_addr or "unknown"
        )
        if not allowed:
            response = app.make_response((
                render_template(
                    "index.html",
                    error="Too many decoration requests. Please wait and try again.",
                    submitted_url="",
                ),
                429,
            ))
            response.headers["Retry-After"] = str(retry_after)
            return response
        if app.config["PROVIDER"] == "none":
            return render_template(
                "index.html",
                error="Agent mode needs an AI provider; the server is in code-only mode.",
                submitted_url=request.form.get("url", "").strip(),
            ), 400
        transient_api_key = request.form.get("provider_api_key", "").strip()
        provider_api_key = transient_api_key or app.config["PROVIDER_API_KEY"]
        intensity = request.form.get("intensity", "medium")
        if intensity not in {"low", "medium", "high"}:
            return render_template(
                "index.html",
                error="Choose a valid decoration intensity.",
                submitted_url=request.form.get("url", "").strip(),
            ), 400
        instruction = request.form.get("instruction", "").strip()[
            : app.config["AGENT_MAX_MESSAGE_CHARS"]
        ]
        try:
            source_url, html_source, base_url, source_id, upload_warnings = parse_source()
        except _SourceError as exc:
            return render_template(
                "index.html",
                error=str(exc),
                submitted_url=request.form.get("url", "").strip(),
            ), exc.status
        job_id = enqueue_job(
            request_url=source_url,
            html_source=html_source,
            base_url=base_url,
            source_id=source_id,
            intensity=intensity,
            provider_api_key=provider_api_key,
            upload_warnings=upload_warnings,
            mode="agent",
            instruction=instruction,
        )
        if job_id is None:
            return render_template(
                "index.html",
                error="The preview queue is full. Please wait a moment and try again.",
                submitted_url=source_url,
            ), 429
        return redirect(url_for("result_page", job_id=job_id), code=303)

    @app.post("/agent/<job_id>/message")
    def agent_message(job_id: str):
        allowed, retry_after = app.config["REQUEST_LIMITER"].consume(
            request.remote_addr or "unknown"
        )
        if not allowed:
            response = jsonify(error="Too many decoration requests. Please wait and try again.")
            response.status_code = 429
            response.headers["Retry-After"] = str(retry_after)
            return response
        previous = app.config["JOBS"].get(job_id)
        if previous is None:
            abort(404)
        if previous.get("mode") != "agent" or previous["status"] != "done":
            abort(409)
        message = request.form.get("message", "").strip()
        if not message:
            return redirect(url_for("result_page", job_id=job_id), code=303)
        new_job_id = enqueue_job(
            request_url=previous["source_url"],
            html_source=previous["original_html"],
            base_url=previous.get("base_url", ""),
            source_id=previous["source_id"],
            intensity=previous["intensity"],
            provider_api_key=(
                request.form.get("provider_api_key", "").strip()
                or app.config["PROVIDER_API_KEY"]
            ),
            upload_warnings=tuple(previous.get("upload_warnings", ())),
            variant=previous["variant"],
            mode="agent",
            instruction=message[: app.config["AGENT_MAX_MESSAGE_CHARS"]],
            history=tuple(previous.get("agent_history", ())),
        )
        if new_job_id is None:
            return jsonify(error="The preview queue is full. Please wait and try again."), 429
        return redirect(url_for("result_page", job_id=new_job_id), code=303)

    @app.get("/agent/<job_id>/snapshot")
    def agent_snapshot(job_id: str):
        job = app.config["JOBS"].get(job_id)
        if job is None or job.get("mode") != "agent":
            abort(404)
        return jsonify(
            status=job["status"],
            progress=job["progress"],
            theme=job.get("theme", ""),
            design_mode=job.get("design_mode", ""),
            harness=job.get("harness", ""),
            live_view_url=job.get("live_view_url", ""),
            iterations=job.get("agent_iterations", []),
            warning=job.get("warning", ""),
            error=job.get("error", ""),
        )

    @app.get("/download/<job_id>")
    def download(job_id: str):
        job = app.config["JOBS"].get(job_id)
        if job is None:
            abort(404)
        if job["status"] != "done":
            abort(409)
        safe_id = "".join(char for char in job_id if char.isalnum())[:64] or "preview"
        response = app.response_class(
            job["decorated_html"], content_type="text/html; charset=utf-8"
        )
        response.headers["Content-Disposition"] = (
            f'attachment; filename="halloween-preview-{safe_id}.html"'
        )
        return response

    @app.get("/result/<job_id>")
    def result_page(job_id: str):
        job = app.config["JOBS"].get(job_id)
        if job is None:
            abort(404)
        view = request.args.get("view", "decorated")
        if view not in {"decorated", "original"}:
            abort(400)
        return render_template("result.html", job=job, job_id=job_id, view=view)

    @app.get("/status/<job_id>")
    def job_status(job_id: str):
        job = app.config["JOBS"].get(job_id)
        if job is None:
            abort(404)
        return jsonify(status=job["status"], progress=job["progress"], error=job["error"])

    @app.post("/regenerate/<job_id>")
    def regenerate(job_id: str):
        allowed, retry_after = app.config["REQUEST_LIMITER"].consume(
            request.remote_addr or "unknown"
        )
        if not allowed:
            response = jsonify(error="Too many decoration requests. Please wait and try again.")
            response.status_code = 429
            response.headers["Retry-After"] = str(retry_after)
            return response
        previous = app.config["JOBS"].get(job_id)
        if previous is None:
            abort(404)
        if previous["status"] != "done":
            abort(409)
        new_job_id = enqueue_job(
            request_url=previous["source_url"],
            html_source=previous["original_html"],
            base_url=previous.get("base_url", ""),
            source_id=previous["source_id"],
            intensity=previous["intensity"],
            provider_api_key=(
                request.form.get("provider_api_key", "").strip()
                or app.config["PROVIDER_API_KEY"]
            ),
            upload_warnings=tuple(previous.get("upload_warnings", ())),
            variant=previous["variant"] + 1,
        )
        if new_job_id is None:
            return jsonify(error="The preview queue is full. Please wait and try again."), 429
        return redirect(url_for("result_page", job_id=new_job_id), code=303)

    @app.get("/render/<job_id>")
    def render_page(job_id: str):
        job = app.config["JOBS"].get(job_id)
        if job is None:
            abort(404)
        if job["status"] != "done":
            abort(409)
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
