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
    return {
        "PROVIDER": provider,
        "PROVIDER_BASE_URL": os.getenv("PROVIDER_BASE_URL", "").strip(),
        "PROVIDER_API_KEY": os.getenv("PROVIDER_API_KEY", ""),
        "MODEL_NAME": os.getenv("MODEL_NAME", "").strip(),
        "MODEL_TIMEOUT_S": _positive_int("MODEL_TIMEOUT_S", 25),
        "FETCH_TIMEOUT_S": _positive_int("FETCH_TIMEOUT_S", 12),
        "MAX_PAGE_BYTES": _positive_int("MAX_PAGE_BYTES", 3 * 1024 * 1024),
        "MAX_REDIRECTS": _positive_int("MAX_REDIRECTS", 5),
        "MAX_UPLOAD_HTML_BYTES": _positive_int("MAX_UPLOAD_HTML_BYTES", 2 * 1024 * 1024),
        "MAX_UPLOAD_TOTAL_BYTES": _positive_int("MAX_UPLOAD_TOTAL_BYTES", 8 * 1024 * 1024),
        "MAX_UPLOAD_ARCHIVE_BYTES": _positive_int("MAX_UPLOAD_ARCHIVE_BYTES", 8 * 1024 * 1024),
        "UPLOAD_CACHE_MAX_BYTES": _positive_int("UPLOAD_CACHE_MAX_BYTES", 16 * 1024 * 1024),
        "MAX_UPLOAD_FILES": _positive_int("MAX_UPLOAD_FILES", 32),
    }
