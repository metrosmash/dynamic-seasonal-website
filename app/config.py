from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


def _positive_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a positive integer.") from exc
    if parsed < 1:
        raise ValueError(f"{name} must be a positive integer.")
    return parsed


def _switch(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def load_config(root: Path) -> dict[str, object]:
    load_dotenv(root / ".env")
    provider = os.getenv("PROVIDER", "fake").strip().lower()
    if provider not in {"fake", "none", "openai_compat"}:
        raise ValueError("PROVIDER must be fake, none, or openai_compat.")
    fallback_provider = os.getenv("FALLBACK_PROVIDER", "none").strip().lower()
    if fallback_provider not in {"none", "fake", "openai_compat"}:
        raise ValueError("FALLBACK_PROVIDER must be none, fake, or openai_compat.")
    fallback_base_url = os.getenv("FALLBACK_PROVIDER_BASE_URL", "").strip()
    fallback_model_name = os.getenv("FALLBACK_MODEL_NAME", "").strip()
    if fallback_provider == "openai_compat" and not (
        fallback_base_url and fallback_model_name
    ):
        raise ValueError(
            "FALLBACK_PROVIDER_BASE_URL and FALLBACK_MODEL_NAME are required "
            "when FALLBACK_PROVIDER=openai_compat."
        )
    harness_provider = os.getenv("HARNESS_PROVIDER", "auto").strip().lower()
    if harness_provider not in {"auto", "local", "browserbase"}:
        raise ValueError("HARNESS_PROVIDER must be auto, local, or browserbase.")
    browserbase_base_url = os.getenv(
        "BROWSERBASE_BASE_URL", "https://api.browserbase.com"
    ).strip().rstrip("/")
    if not browserbase_base_url.startswith("https://"):
        raise ValueError("BROWSERBASE_BASE_URL must be an https:// URL.")
    if harness_provider == "browserbase" and not os.getenv("BROWSERBASE_API_KEY", ""):
        raise ValueError(
            "BROWSERBASE_API_KEY is required when HARNESS_PROVIDER=browserbase."
        )
    return {
        "PROVIDER": provider,
        "PROVIDER_BASE_URL": os.getenv("PROVIDER_BASE_URL", "").strip(),
        "PROVIDER_API_KEY": os.getenv("PROVIDER_API_KEY", ""),
        "MODEL_NAME": os.getenv("MODEL_NAME", "").strip(),
        "FALLBACK_PROVIDER": fallback_provider,
        "FALLBACK_PROVIDER_BASE_URL": fallback_base_url,
        "FALLBACK_PROVIDER_API_KEY": os.getenv("FALLBACK_PROVIDER_API_KEY", ""),
        "FALLBACK_MODEL_NAME": fallback_model_name,
        "MODEL_TIMEOUT_S": _positive_int("MODEL_TIMEOUT_S", 25),
        "FETCH_TIMEOUT_S": _positive_int("FETCH_TIMEOUT_S", 12),
        "MAX_PAGE_BYTES": _positive_int("MAX_PAGE_BYTES", 3 * 1024 * 1024),
        "MAX_REDIRECTS": _positive_int("MAX_REDIRECTS", 5),
        "MAX_UPLOAD_HTML_BYTES": _positive_int("MAX_UPLOAD_HTML_BYTES", 2 * 1024 * 1024),
        "MAX_UPLOAD_TOTAL_BYTES": _positive_int("MAX_UPLOAD_TOTAL_BYTES", 8 * 1024 * 1024),
        "MAX_UPLOAD_ARCHIVE_BYTES": _positive_int("MAX_UPLOAD_ARCHIVE_BYTES", 8 * 1024 * 1024),
        "UPLOAD_CACHE_MAX_BYTES": _positive_int("UPLOAD_CACHE_MAX_BYTES", 16 * 1024 * 1024),
        "MAX_UPLOAD_FILES": _positive_int("MAX_UPLOAD_FILES", 32),
        "JOB_WORKERS": _positive_int("JOB_WORKERS", 2),
        "MAX_PENDING_JOBS": _positive_int("MAX_PENDING_JOBS", 8),
        "JOB_DEADLINE_S": _positive_int("JOB_DEADLINE_S", 60),
        "RATE_LIMIT_BURST": _positive_int("RATE_LIMIT_BURST", 10),
        "RATE_LIMIT_WINDOW_S": _positive_int("RATE_LIMIT_WINDOW_S", 60),
        "DAILY_REQUEST_LIMIT": _positive_int("DAILY_REQUEST_LIMIT", 5000),
        "MAX_STORED_JOBS": _positive_int("MAX_STORED_JOBS", 500),
        "HARNESS_PROVIDER": harness_provider,
        "BROWSERBASE_API_KEY": os.getenv("BROWSERBASE_API_KEY", ""),
        "BROWSERBASE_PROJECT_ID": os.getenv("BROWSERBASE_PROJECT_ID", "").strip(),
        "BROWSERBASE_BASE_URL": browserbase_base_url,
        "BROWSERBASE_TIMEOUT_S": _positive_int("BROWSERBASE_TIMEOUT_S", 60),
        "HARNESS_ALLOW_JS": _switch("HARNESS_ALLOW_JS", False),
        "AGENT_MAX_ITERATIONS": _positive_int("AGENT_MAX_ITERATIONS", 3),
        "AGENT_MAX_MESSAGE_CHARS": _positive_int("AGENT_MAX_MESSAGE_CHARS", 2000),
    }
