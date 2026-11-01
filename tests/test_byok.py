from __future__ import annotations

import time
from unittest.mock import patch

from app import create_app


def _wait(client, job_id: str) -> dict:
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        job = client.get(f"/status/{job_id}").json
        if job["status"] in {"done", "error"}:
            return job
        time.sleep(0.01)
    raise AssertionError(f"job {job_id} did not finish")


@patch("app.pipeline.openai_compat.complete")
@patch("app.load_page")
def test_byok_is_used_for_one_request_and_never_saved_in_job(
    mock_load, mock_complete, caplog
):
    mock_load.return_value = (
        "<html><body><h1>Page</h1></body></html>",
        "https://example.com/",
    )
    mock_complete.return_value = "PLACE: bat @ top-right"
    app = create_app({
        "TESTING": True,
        "PROVIDER": "openai_compat",
        "PROVIDER_BASE_URL": "https://provider.example/v1",
        "MODEL_NAME": "test-model",
        "PROVIDER_API_KEY": "",
    })
    client = app.test_client()
    secret = "one-request-only-test-key"

    response = client.post(
        "/decorate",
        data={
            "url": "https://example.com/",
            "intensity": "medium",
            "provider_api_key": secret,
        },
    )
    job_id = response.headers["Location"].rsplit("/", 1)[-1]
    status = _wait(client, job_id)

    assert response.status_code == 303
    assert status["status"] == "done"
    assert mock_complete.call_args.kwargs["api_key"] == secret
    job = app.config["JOBS"][job_id]
    assert secret not in repr(job)
    assert all(secret not in repr(key) for key in app.config["UPLOAD_CACHE"])
    assert secret not in caplog.text
