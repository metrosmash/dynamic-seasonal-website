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
    }
