from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from app import create_app
from app.config import load_config
from app.pipeline import decorate_page
from app.steps.load_page import FetchError


HTML = "<html><body><h1>Fallback test</h1></body></html>"
FALLBACK_DESIGN = "PLACE: bat @ top-right"


def _wait(client, job_id: str) -> dict:
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        status = client.get(f"/status/{job_id}").get_json()
        if status["status"] in {"done", "error"}:
            return status
        time.sleep(0.01)
    raise AssertionError(f"job {job_id} did not finish")


def _decorate() -> dict[str, str]:
    return decorate_page(
        HTML,
        source_url="https://example.test/",
        intensity="medium",
        provider="openai_compat",
        provider_base_url="https://primary.example/v1",
        provider_api_key="primary-test-key",
        model_name="primary-model",
        model_timeout=1,
        fallback_provider="openai_compat",
        fallback_provider_base_url="https://fallback.example/v1",
        fallback_provider_api_key="fallback-test-key",
        fallback_model_name="fallback-model",
    )


@patch("app.pipeline.openai_compat.complete")
def test_fallback_provider_is_used_when_primary_provider_fails(complete):
    complete.side_effect = [
        FetchError("primary unavailable"),
        FALLBACK_DESIGN,
    ]

    result = _decorate()

    assert complete.call_count == 2
    assert complete.call_args_list[0].kwargs["base_url"] == "https://primary.example/v1"
    assert complete.call_args_list[1].kwargs["base_url"] == "https://fallback.example/v1"
    assert complete.call_args_list[1].kwargs["api_key"] == "fallback-test-key"
    assert result["design_mode"] == "fallback AI design"
    assert "fallback provider was used" in result["warning"]
    assert 'data-hw-slot="top-right"' in result["html"]


@patch("app.pipeline.openai_compat.complete")
def test_fallback_provider_is_tried_after_primary_repair_is_unusable(complete):
    complete.side_effect = [
        "unstructured primary output",
        "still unstructured after repair",
        FALLBACK_DESIGN,
    ]

    result = _decorate()

    assert complete.call_count == 3
    assert complete.call_args_list[-1].kwargs["base_url"] == "https://fallback.example/v1"
    assert result["design_mode"] == "fallback AI design"


@patch("app.pipeline.openai_compat.complete")
@patch("app.pipeline.fake.complete")
def test_both_llms_failing_uses_fake_provider_as_tertiary_fallback(fake_complete, complete):
    complete.side_effect = FetchError("provider unavailable")
    fake_complete.return_value = FALLBACK_DESIGN

    result = _decorate()

    assert complete.call_count == 2
    assert fake_complete.call_count == 1
    assert result["design_mode"] == "fake provider fallback"
    assert "sample provider supplied a design" in result["warning"]
    assert 'data-hw-slot="top-right"' in result["html"]


@patch("app.pipeline.openai_compat.complete")
@patch("app.pipeline.fake.complete")
def test_fake_provider_failure_uses_code_only_as_final_fallback(fake_complete, complete):
    complete.side_effect = FetchError("provider unavailable")
    fake_complete.side_effect = FetchError("sample provider unavailable")

    result = _decorate()

    assert complete.call_count == 2
    assert fake_complete.call_count == 1
    assert result["design_mode"] == "code-only design"
    assert "sample provider" in result["warning"]
    assert "provider unavailable" in result["warning"]
    assert 'data-hw-added="decoration"' in result["html"]


@patch("app.pipeline.openai_compat.complete")
def test_primary_failure_without_configured_secondary_uses_code_only(complete):
    complete.side_effect = FetchError("primary unavailable")
    result = decorate_page(
        HTML,
        source_url="https://example.test/",
        intensity="medium",
        provider="openai_compat",
        provider_base_url="https://primary.example/v1",
        provider_api_key="",
        model_name="primary-model",
        model_timeout=1,
    )

    assert complete.call_count == 1
    assert result["design_mode"] == "fake provider fallback"
    assert "sample provider supplied a design" in result["warning"]


@patch("app.pipeline.fake.complete")
@patch("app.pipeline.openai_compat.complete")
def test_fake_can_be_configured_as_secondary_without_duplicate_attempts(
    complete, fake_complete
):
    complete.side_effect = FetchError("primary unavailable")
    fake_complete.return_value = FALLBACK_DESIGN

    result = decorate_page(
        HTML,
        source_url="https://example.test/",
        intensity="medium",
        provider="openai_compat",
        provider_base_url="https://primary.example/v1",
        provider_api_key="",
        model_name="primary-model",
        model_timeout=1,
        fallback_provider="fake",
    )

    assert complete.call_count == 1
    assert fake_complete.call_count == 1
    assert result["design_mode"] == "fake provider fallback"


@patch("app.pipeline.openai_compat.complete")
@patch("app.load_page")
def test_app_uses_server_configured_fallback_without_persisting_its_key(load, complete):
    load.return_value = (HTML, "https://example.test/")
    complete.side_effect = [
        FetchError("primary unavailable"),
        FALLBACK_DESIGN,
    ]
    fallback_secret = "server-fallback-test-key"
    app = create_app({
        "TESTING": True,
        "PROVIDER": "openai_compat",
        "PROVIDER_BASE_URL": "https://primary.example/v1",
        "PROVIDER_API_KEY": "",
        "MODEL_NAME": "primary-model",
        "FALLBACK_PROVIDER": "openai_compat",
        "FALLBACK_PROVIDER_BASE_URL": "https://fallback.example/v1",
        "FALLBACK_PROVIDER_API_KEY": fallback_secret,
        "FALLBACK_MODEL_NAME": "fallback-model",
    })
    client = app.test_client()
    response = client.post(
        "/decorate",
        data={"url": "https://example.test/", "provider_api_key": "transient-primary-key"},
    )
    job_id = response.headers["Location"].rsplit("/", 1)[-1]
    status = _wait(client, job_id)

    assert response.status_code == 303
    assert status["status"] == "done"
    assert complete.call_args_list[0].kwargs["api_key"] == "transient-primary-key"
    assert complete.call_args_list[1].kwargs["api_key"] == fallback_secret
    job = app.config["JOBS"][job_id]
    assert fallback_secret not in repr(job)
    assert fallback_secret not in repr(list(app.config["RESULT_CACHE"].keys()))


def test_fallback_provider_requires_endpoint_and_model(monkeypatch, tmp_path):
    monkeypatch.setenv("FALLBACK_PROVIDER", "openai_compat")
    monkeypatch.setenv("FALLBACK_PROVIDER_BASE_URL", "")
    monkeypatch.setenv("FALLBACK_MODEL_NAME", "")

    with pytest.raises(ValueError, match="FALLBACK_PROVIDER_BASE_URL"):
        load_config(tmp_path)
