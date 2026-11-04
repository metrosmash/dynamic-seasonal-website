from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

from app.harness import BaseHarness, HarnessEdit, HarnessError, HarnessSnapshot
from app.harness.local import LocalHarness


def _redact(text: str, api_key: str) -> str:
    return text.replace(api_key, "[REDACTED]") if api_key else text


def _request_json(
    method: str,
    url: str,
    api_key: str,
    payload: dict | None = None,
    timeout: int = 20,
) -> dict:
    body = json.dumps(payload or {}).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        url,
        data=body,
        method=method,
        headers={
            "Content-Type": "application/json",
            "x-bb-api-key": api_key,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read(256 * 1024).decode("utf-8")
    except urllib.error.HTTPError as exc:
        try:
            detail = exc.read(2048).decode("utf-8", errors="replace")
        finally:
            exc.close()
        raise HarnessError(
            f"Browserbase returned HTTP {exc.code}: {_redact(detail[:300], api_key)}"
        ) from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise HarnessError("Could not reach Browserbase.") from exc
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HarnessError("Browserbase returned an invalid response.") from exc
    if not isinstance(parsed, dict):
        raise HarnessError("Browserbase returned an unexpected response.")
    return parsed


def create_session(
    base_url: str,
    api_key: str,
    project_id: str,
    session_timeout_s: int,
    *,
    request_timeout: int = 20,
) -> dict:
    payload: dict[str, object] = {"timeout": session_timeout_s}
    if project_id:
        payload["projectId"] = project_id
    return _request_json(
        "POST", f"{base_url}/v1/sessions", api_key, payload, request_timeout
    )


def fetch_debug_urls(
    base_url: str, api_key: str, session_id: str, *, request_timeout: int = 20
) -> dict:
    quoted = urllib.parse.quote(session_id, safe="")
    return _request_json(
        "GET", f"{base_url}/v1/sessions/{quoted}/debug", api_key, None, request_timeout
    )


def release_session(
    base_url: str, api_key: str, session_id: str, *, request_timeout: int = 10
) -> None:
    quoted = urllib.parse.quote(session_id, safe="")
    try:
        _request_json(
            "DELETE",
            f"{base_url}/v1/sessions/{quoted}",
            api_key,
            None,
            request_timeout,
        )
    except HarnessError:
        pass


def to_data_url(html: str, max_bytes: int = 1_500_000) -> str:
    """Build a data: URL so the snapshot can be opened in a remote session.

    Used by operators and by a future Playwright/CDP driver; the v1 harness
    never navigates the remote browser by itself.
    """
    encoded = html.encode("utf-8")
    if len(encoded) > max_bytes:
        raise HarnessError("Snapshot is too large for a data URL.")
    return "data:text/html;charset=utf-8," + urllib.parse.quote(html)


class BrowserbaseHarness(BaseHarness):
    """Isolated cloud rendering around the validated local edit logic.

    v1 scope: agent edits are validated and assembled locally (same rules as
    the static pipeline), while a short-lived Browserbase session provides an
    isolated renderer plus a live-view URL for watching the page. DOM
    interaction over CDP/Playwright is the documented next step and needs the
    optional ``browserbase`` + ``playwright`` packages; it is not required.
    """

    name = "browserbase"

    def __init__(self, config: dict) -> None:
        api_key = str(config.get("BROWSERBASE_API_KEY", ""))
        if not api_key:
            raise HarnessError("BROWSERBASE_API_KEY is required for this harness.")
        self._config = config
        self._edits = LocalHarness()
        self._session_id = ""
        self._connect_url = ""
        self._live_view_url = ""
        self._debug_fetched = False

    @property
    def session_id(self) -> str:
        return self._session_id

    def load(
        self,
        source_html: str,
        source_url: str,
        theme_id: str,
        intensity: str,
    ) -> None:
        self._edits.load(source_html, source_url, theme_id, intensity)
        self.ensure_session()

    def ensure_session(self) -> str:
        if self._session_id:
            return self._session_id
        session = create_session(
            str(self._config.get("BROWSERBASE_BASE_URL", "")),
            str(self._config.get("BROWSERBASE_API_KEY", "")),
            str(self._config.get("BROWSERBASE_PROJECT_ID", "")),
            int(self._config.get("BROWSERBASE_TIMEOUT_S", 60)),
        )
        session_id = str(session.get("id", ""))
        if not session_id:
            raise HarnessError("Browserbase did not return a session id.")
        self._session_id = session_id
        self._connect_url = str(session.get("connectUrl", ""))
        return self._session_id

    def live_view_url(self) -> str:
        if self._live_view_url or self._debug_fetched or not self._session_id:
            return self._live_view_url
        self._debug_fetched = True
        try:
            debug = fetch_debug_urls(
                str(self._config.get("BROWSERBASE_BASE_URL", "")),
                str(self._config.get("BROWSERBASE_API_KEY", "")),
                self._session_id,
            )
        except HarnessError:
            return ""
        self._live_view_url = str(
            debug.get("debuggerFullscreenUrl", "") or debug.get("debuggerUrl", "")
        )
        return self._live_view_url

    def apply(self, edit: HarnessEdit) -> str:
        return self._edits.apply(edit)

    def snapshot(self) -> HarnessSnapshot:
        base = self._edits.snapshot()
        return HarnessSnapshot(
            html=base.html,
            theme_id=base.theme_id,
            placements=base.placements,
            css=base.css,
            warning=base.warning,
            live_view_url=self.live_view_url(),
            session_id=self._session_id,
            harness=self.name,
        )

    def close(self) -> None:
        if self._session_id:
            release_session(
                str(self._config.get("BROWSERBASE_BASE_URL", "")),
                str(self._config.get("BROWSERBASE_API_KEY", "")),
                self._session_id,
            )
        self._session_id = ""
        self._connect_url = ""
        self._live_view_url = ""
        self._debug_fetched = False
        self._edits.close()
