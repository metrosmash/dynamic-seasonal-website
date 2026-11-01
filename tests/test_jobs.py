from __future__ import annotations

import time
from unittest.mock import patch

from app import create_app


def _wait(client, job_id: str) -> dict:
    deadline = time.monotonic() + 4
    while time.monotonic() < deadline:
        job = client.get(f"/status/{job_id}").json
        if job["status"] in {"done", "error"}:
            return job
        time.sleep(0.01)
    raise AssertionError(f"job {job_id} did not finish")


def test_job_deadline_becomes_a_visible_error():
    app = create_app({
        "TESTING": True,
        "PROVIDER": "fake",
        "JOB_DEADLINE_S": 1,
        "FETCH_TIMEOUT_S": 1,
    })
    client = app.test_client()

    def slow_fetch(*_args, **_kwargs):
        time.sleep(1.05)
        return "<html><body><h1>Page</h1></body></html>", "https://example.com/"

    with patch("app.load_page", side_effect=slow_fetch):
        response = client.post(
            "/decorate",
            data={"url": "https://example.com/", "intensity": "medium"},
        )
        job_id = response.headers["Location"].rsplit("/", 1)[-1]
        status = _wait(client, job_id)

    result = client.get(response.headers["Location"])
    assert status["status"] == "error"
    assert "time limit" in result.get_data(as_text=True)
    assert client.get(f"/render/{job_id}").status_code == 409


def test_full_job_queue_returns_a_friendly_429():
    app = create_app({"TESTING": True, "PROVIDER": "fake"})

    class FullPool:
        def submit(self, _function):
            return None

    app.config["JOB_POOL"] = FullPool()
    response = app.test_client().post(
        "/decorate",
        data={"url": "https://example.com/", "intensity": "medium"},
    )

    assert response.status_code == 429
    assert b"queue is full" in response.data
    assert app.config["JOBS"] == {}


def test_rate_limiter_returns_429_with_retry_after():
    app = create_app({
        "TESTING": True,
        "PROVIDER": "fake",
        "RATE_LIMIT_BURST": 1,
        "RATE_LIMIT_WINDOW_S": 60,
    })
    client = app.test_client()

    first = client.post("/decorate", data={"intensity": "bad"})
    second = client.post("/decorate", data={"intensity": "medium"})

    assert first.status_code == 400
    assert second.status_code == 429
    assert int(second.headers["Retry-After"]) > 0
