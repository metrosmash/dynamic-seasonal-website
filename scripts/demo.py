from __future__ import annotations

import argparse
import io
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import create_app


DEMO_FIXTURES = ("halloween_article", "blog_post", "documentation_page")
DEMO_TIER = "medium"


def _submit_fixture(client, fixture_path: Path):
    return client.post(
        "/decorate",
        data={
            "intensity": DEMO_TIER,
            "uploads": (io.BytesIO(fixture_path.read_bytes()), fixture_path.name),
        },
        content_type="multipart/form-data",
    )


def _wait_for_job(app, client, response):
    if response.status_code != 303:
        raise RuntimeError(f"Could not queue demo fixture (HTTP {response.status_code}).")
    job_id = response.headers["Location"].rsplit("/", 1)[-1]
    deadline = time.monotonic() + int(app.config["JOB_DEADLINE_S"]) + 5
    while time.monotonic() < deadline:
        status_response = client.get(f"/status/{job_id}")
        if status_response.status_code != 200:
            raise RuntimeError("The demo job status could not be read.")
        status = status_response.get_json()
        if status["status"] in {"done", "error"}:
            if status["status"] != "done":
                raise RuntimeError("A demo fixture failed to decorate.")
            return job_id
        time.sleep(0.02)
    raise TimeoutError("A demo fixture did not finish before its deadline.")


def prewarm_demo_cache(app) -> None:
    client = app.test_client()
    for fixture_name in DEMO_FIXTURES:
        fixture_path = ROOT / "fixtures" / "matrix" / f"{fixture_name}.html"
        started = time.monotonic()
        first_id = _wait_for_job(app, client, _submit_fixture(client, fixture_path))
        render = client.get(f"/render/{first_id}")
        csp = render.headers.get("Content-Security-Policy", "").lower()
        if render.status_code != 200 or "sandbox" not in csp:
            raise RuntimeError("A pre-warmed result did not pass the render safety check.")
        first_job = app.config["JOBS"][first_id]
        if first_job["cache_hit"]:
            raise RuntimeError("The first demo request unexpectedly hit the result cache.")

        cached_id = _wait_for_job(app, client, _submit_fixture(client, fixture_path))
        cached_job = app.config["JOBS"][cached_id]
        if not cached_job["cache_hit"]:
            raise RuntimeError("The repeated demo request did not hit the warmed cache.")
        print(
            f"Pre-warmed {fixture_name} ({DEMO_TIER}): "
            f"{time.monotonic() - started:.2f}s; repeated upload served from cache."
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Pre-warm the local demo cache and run the Halloween decorator."
    )
    parser.add_argument(
        "--no-prewarm",
        action="store_true",
        help="Start the app without decorating and caching the demo fixtures first.",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5000)
    args = parser.parse_args()

    app = create_app()
    if not args.no_prewarm:
        prewarm_demo_cache(app)
    app.run(host=args.host, port=args.port, debug=False)


if __name__ == "__main__":
    main()
