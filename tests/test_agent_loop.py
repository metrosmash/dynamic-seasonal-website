from __future__ import annotations

import time
import unittest
from unittest.mock import patch

from app import create_app
from app.agent import parse_agent_response
from app.agent.loop import run_agent
from app.harness.local import LocalHarness


HTML_PAGE = (
    "<!doctype html><html><head><title>Public sample</title></head>"
    "<body><main><h1>Sample headline</h1><h2>Section</h2><p>Readable public content.</p></main></body></html>"
)


def _harness() -> LocalHarness:
    harness = LocalHarness()
    harness.load(HTML_PAGE, "https://example.com/", "pumpkin-patch", "medium")
    return harness


class AgentParseTests(unittest.TestCase):
    def test_parses_tools_note_and_done(self):
        plan = parse_agent_response(
            "THEME: pumpkin-patch\nACCENT: #ff7a1a\nPLACE: crow @ header\n"
            "NOTE: added a crow\nDONE: yes\n",
            "medium",
        )
        self.assertTrue(plan.done)
        self.assertEqual(plan.note, "added a crow")
        self.assertEqual(
            [edit.kind for edit in plan.edits], ["theme", "accent", "placements"]
        )

    def test_reset_is_first_edit(self):
        plan = parse_agent_response("RESET: yes\nPLACE: crow @ header\n", "medium")
        self.assertEqual([edit.kind for edit in plan.edits], ["reset", "placements"])
        self.assertFalse(plan.done)

    def test_non_text_input_is_safe(self):
        plan = parse_agent_response(None, "medium")  # type: ignore[arg-type]
        self.assertEqual(plan.edits, ())
        self.assertFalse(plan.done)


class AgentLoopTests(unittest.TestCase):
    def test_fake_provider_iterates_and_assembles(self):
        result = run_agent(
            _harness(),
            source_html=HTML_PAGE,
            intensity="medium",
            theme_id="pumpkin-patch",
            instruction="more spooky",
            provider="fake",
            provider_base_url="",
            provider_api_key="",
            model_name="",
            max_iterations=2,
        )
        self.assertEqual(len(result.iterations), 2)
        self.assertIn("hw-added", result.snapshot.html)
        self.assertNotIn("<script", result.snapshot.html)
        self.assertEqual(result.design_mode, "sample provider")

    @patch("app.agent.loop.fake.complete")
    def test_done_stops_early(self, complete):
        complete.return_value = "PLACE: crow @ header\nNOTE: all set\nDONE: yes\n"
        result = run_agent(
            _harness(),
            source_html=HTML_PAGE,
            intensity="medium",
            theme_id="pumpkin-patch",
            instruction="",
            provider="fake",
            provider_base_url="",
            provider_api_key="",
            model_name="",
            max_iterations=3,
        )
        self.assertEqual(len(result.iterations), 1)
        self.assertTrue(result.iterations[0].done)
        self.assertEqual(result.snapshot.placements, (("crow", "header"),))

    @patch("app.agent.loop.fake.complete")
    def test_unusable_response_stops_with_warning(self, complete):
        complete.return_value = "hello there"
        result = run_agent(
            _harness(),
            source_html=HTML_PAGE,
            intensity="medium",
            theme_id="pumpkin-patch",
            instruction="",
            provider="fake",
            provider_base_url="",
            provider_api_key="",
            model_name="",
            max_iterations=3,
        )
        self.assertEqual(result.iterations, ())
        self.assertIn("no usable edits", result.warning)


class AgentRoutesTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app({
            "TESTING": True,
            "PROVIDER": "fake",
            "JOBS": {},
        })
        self.client = self.app.test_client()

    def _wait_for_job(self, job_id):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            status = self.client.get(f"/status/{job_id}").json["status"]
            if status in {"done", "error"}:
                return status
            time.sleep(0.01)
        self.fail(f"job {job_id} did not finish")

    def _start_agent_job(self):
        with patch("app.load_page", return_value=(HTML_PAGE, "https://example.com/")):
            response = self.client.post(
                "/agent",
                data={
                    "url": "https://example.com/",
                    "intensity": "medium",
                    "instruction": "more pumpkins",
                },
            )
        self.assertEqual(response.status_code, 303)
        job_id = response.headers["Location"].rsplit("/", 1)[-1]
        self.assertEqual(self._wait_for_job(job_id), "done")
        return job_id

    def test_agent_run_shows_timeline_chat_and_download(self):
        job_id = self._start_agent_job()
        result = self.client.get(f"/result/{job_id}")
        self.assertEqual(result.status_code, 200)
        body = result.get_data(as_text=True)
        self.assertIn("agent-timeline", body)
        self.assertIn("Ask the agent for changes", body)
        self.assertIn(f"/download/{job_id}", body)
        self.assertIn("Harness:", body)

    def test_snapshot_and_download(self):
        job_id = self._start_agent_job()
        snapshot = self.client.get(f"/agent/{job_id}/snapshot")
        self.assertEqual(snapshot.status_code, 200)
        payload = snapshot.json
        self.assertEqual(payload["status"], "done")
        self.assertEqual(payload["harness"], "local")
        self.assertTrue(payload["iterations"])
        download = self.client.get(f"/download/{job_id}")
        self.assertEqual(download.status_code, 200)
        self.assertIn("attachment", download.headers["Content-Disposition"])
        self.assertIn("hw-added", download.get_data(as_text=True))

    def test_message_follow_up_creates_new_job(self):
        job_id = self._start_agent_job()
        with patch("app.load_page", return_value=(HTML_PAGE, "https://example.com/")):
            response = self.client.post(
                f"/agent/{job_id}/message", data={"message": "add a ghost"}
            )
        self.assertEqual(response.status_code, 303)
        new_job_id = response.headers["Location"].rsplit("/", 1)[-1]
        self.assertNotEqual(new_job_id, job_id)
        self.assertEqual(self._wait_for_job(new_job_id), "done")

    def test_message_requires_finished_agent_job(self):
        with patch("app.load_page", return_value=(HTML_PAGE, "https://example.com/")):
            response = self.client.post(
                "/decorate",
                data={"url": "https://example.com/", "intensity": "medium"},
            )
        job_id = response.headers["Location"].rsplit("/", 1)[-1]
        self.assertEqual(self._wait_for_job(job_id), "done")
        follow_up = self.client.post(f"/agent/{job_id}/message", data={"message": "hi"})
        self.assertEqual(follow_up.status_code, 409)
        self.assertEqual(self.client.get(f"/agent/{job_id}/snapshot").status_code, 404)

    def test_agent_rejected_in_code_only_mode(self):
        app = create_app({"TESTING": True, "PROVIDER": "none", "JOBS": {}})
        client = app.test_client()
        response = client.post(
            "/agent", data={"url": "https://example.com/", "intensity": "medium"}
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn(b"code-only", response.data)


if __name__ == "__main__":
    unittest.main()
