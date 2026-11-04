from __future__ import annotations

from pathlib import Path

from flask import Flask, jsonify, request

from app.config import load_config
from app.rate_limit import RequestLimiter
from app.seasonal import register_seasonal


ROOT = Path(__file__).resolve().parents[1]


def create_app(test_config: dict | None = None) -> Flask:
    app = Flask(__name__, template_folder="../templates", static_folder="../static")
    app.config.update(load_config(ROOT))
    if test_config:
        app.config.update(test_config)
    app.config["REQUEST_LIMITER"] = RequestLimiter(
        burst=app.config["RATE_LIMIT_BURST"],
        refill_seconds=app.config["RATE_LIMIT_WINDOW_S"],
        daily_limit=app.config["DAILY_REQUEST_LIMIT"],
    )

    @app.after_request
    def add_app_security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        if request.endpoint == "seasonal_preview":
            return response  # the preview sets its own sandboxed policy
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; style-src 'self'; img-src 'self' data:; "
            "script-src 'self'; frame-src 'self'; object-src 'none'; "
            "base-uri 'none'; frame-ancestors 'self'",
        )
        return response

    @app.get("/health")
    def health():
        return jsonify(status="ok")

    register_seasonal(app)

    return app
