# Agent harness

Agent mode gives the model more autonomy than the one-shot pipeline: instead of
a single design response, the agent makes several DOM+CSS edits inside a
harness, and the user steers it with chat follow-ups, Lovable-style.

## How it works

1. The page is fetched and prepared exactly like a normal job
   (`prepare_html` strips scripts, event handlers, and iframes).
2. A harness loads the script-free HTML. The agent may only change theme,
   accent, placements, and sanitized CSS through validated tools
   (`app/agent/__init__.py`). Raw HTML and JS are never accepted.
3. Each turn is assembled with the existing theme/decor pipeline
   (`assemble_page`), so output keeps the same safety properties: allowlisted
   model CSS, no page scripts, sandboxed iframe preview with a restrictive CSP.
4. The result page shows an iteration timeline, a chat box for follow-ups, and
   a download link for the decorated HTML.

## Backends

`HARNESS_PROVIDER` selects the backend:

- `local` (default when no Browserbase key is set): in-process harness in
  `app/harness/local.py`. No network, deterministic, used by tests.
- `browserbase`: creates a short-lived cloud session via the Sessions API for
  isolated rendering plus a live-view URL. Edits are still validated locally
  in v1; the session id and `debuggerFullscreenUrl` are stored on the job.
- `auto`: Browserbase when `BROWSERBASE_API_KEY` is set, else local. A failed
  cloud session falls back to local with a visible warning.

## Browserbase setup

```dotenv
HARNESS_PROVIDER=auto
BROWSERBASE_API_KEY=your-key
BROWSERBASE_PROJECT_ID=your-project-id
BROWSERBASE_BASE_URL=https://api.browserbase.com
BROWSERBASE_TIMEOUT_S=60
```

Only REST calls are used (`POST /v1/sessions`, `GET /v1/sessions/{id}/debug`,
`DELETE /v1/sessions/{id}` over `BROWSERBASE_BASE_URL`), so no new Python
dependencies are required. Pointing `BROWSERBASE_BASE_URL` at another
Browserbase-compatible endpoint keeps the client working unchanged. The
optional `browserbase` + `playwright` packages are the documented path for
driving the remote page over CDP later; `to_data_url()` in
`app/harness/browserbase.py` already builds a loadable snapshot URL for that.

## Agent loop

`app/agent/loop.py` runs up to `AGENT_MAX_ITERATIONS` turns (default 3). Each
turn reuses the configured LLM provider chain (primary, then fallback), parses
the line-based tool format (`THEME`/`ACCENT`/`PLACE`/`CSS`, plus `RESET`,
`NOTE`, `DONE`), and applies edits through the harness. Invalid edits are
skipped with a warning instead of failing the job.

Relevant settings:

```dotenv
AGENT_MAX_ITERATIONS=3
AGENT_MAX_MESSAGE_CHARS=2000
```

## Full-JS sandbox (not enabled)

`app/harness/js_sandbox.py` is the extension point. `HARNESS_ALLOW_JS` defaults
to `0` and `run_js()` fails closed: even when admitted, it refuses until a
Browserbase CDP executor that runs snippets with network disabled is
implemented behind it. Never execute agent JS in the app process.

## Routes

- `POST /agent`: start an agent job (same URL/upload fields plus `instruction`).
- `POST /agent/<job_id>/message`: chat follow-up on a finished agent job.
- `GET /agent/<job_id>/snapshot`: JSON status, iterations, and live-view URL.
- `GET /download/<job_id>`: download the decorated HTML file.
