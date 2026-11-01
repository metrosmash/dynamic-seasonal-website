from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from flask import Flask, abort, jsonify, redirect, render_template, request, url_for

from app.config import load_config
from app.pipeline import decorate_page
from app.steps.load_page import FetchError, load_page
from app.steps.prepare_html import prepare_html


ROOT = Path(__file__).resolve().parents[1]


def create_app(test_config: dict | None = None) -> Flask:
    app = Flask(__name__, template_folder="../templates", static_folder="../static")
    app.config.update(load_config(ROOT))
    if test_config:
        app.config.update(test_config)
    app.config["JOBS"] = {}

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
        try:
            safe_source = prepare_html(source_html, final_url)
            result = decorate_page(
                safe_source,
                source_url=final_url,
                intensity=intensity,
                provider=app.config["PROVIDER"],
                provider_base_url=app.config["PROVIDER_BASE_URL"],
                provider_api_key=app.config["PROVIDER_API_KEY"],
                model_name=app.config["MODEL_NAME"],
                model_timeout=app.config["MODEL_TIMEOUT_S"],
            )
        except ValueError as exc:
            return render_template(
                "index.html",
                error=str(exc),
                submitted_url=source_url,
            ), 400

        job_id = uuid4().hex
        app.config["JOBS"][job_id] = {
            "source_url": final_url,
            "original_html": safe_source,
            "decorated_html": result["html"],
            "theme": result["theme"],
            "intensity": intensity,
            "design_mode": result["design_mode"],
            "warning": result["warning"],
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
