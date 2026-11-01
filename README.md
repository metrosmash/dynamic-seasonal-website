# Halloween Website Decorator

The app accepts a public website URL or uploaded website files, applies a deterministic Halloween theme and validated decorations, then displays an isolated preview. The model supplies decoration placement, an optional accent, and optional CSS flourishes; a `tinycss2` allowlist sanitizer filters model CSS before it is applied. Ten curated themes have tested light and dark palettes. External page assets may still fail to load, remote JavaScript is removed, and pages that require login or JavaScript rendering are not supported yet.

Design-response parsing and HTML summarization live in `app/parser.py`; prompt construction lives in `app/brief.py`. Theme palettes and seeded selection live in `app/content/themes.py`, intensity budgets in `app/content/tiers.py`, and decoration metadata in `app/content/decor_catalog.py`. Each decoration has a standalone SVG asset in `app/content/decor/`, loaded by the catalog as a package resource. The web app and benchmark script share the design modules.

The homepage has one multi-file upload field: select one `.html`/`.htm` file with optional CSS and PNG, JPG, GIF, or WebP assets, or select one ZIP archive containing them. Do not mix a ZIP with separately selected files. ZIPs must contain exactly one HTML file and only supported asset types; their contents are read in memory and never extracted to disk. Matching stylesheet and image filenames are embedded into the preview; referenced files that are not uploaded are reported as warnings. Uploads are limited by `MAX_UPLOAD_HTML_BYTES`, `MAX_UPLOAD_TOTAL_BYTES`, `MAX_UPLOAD_ARCHIVE_BYTES`, and `MAX_UPLOAD_FILES`. Repeated identical uploads reuse a bounded in-memory result cache; the cache is cleared when the server restarts.

Decoration work runs in a bounded two-worker queue with progress polling and a 60-second default deadline. Requests use an in-memory per-IP token bucket plus a global daily cap. A user-supplied provider API key is accepted with a request and kept only in the worker's transient memory; it is not stored in jobs, logs, or plaintext cache keys. Use HTTPS when exposing the app, since the key is sent to the server for that request. The result page supports an original snapshot and a regenerate action; jobs and caches are process-local.

## Run locally

```powershell
python -m venv halloween_env
.\halloween_env\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
python run.py
```

Open `http://127.0.0.1:5000`. The default provider is `fake`, so the demo works without model credentials. To use the configured OpenAI-compatible provider, set `PROVIDER=openai_compat`, `PROVIDER_BASE_URL`, and `MODEL_NAME` in your local `.env`; set `PROVIDER_API_KEY` there or enter a per-request primary key in the form. An optional secondary OpenAI-compatible endpoint is enabled with `FALLBACK_PROVIDER=openai_compat`, `FALLBACK_PROVIDER_BASE_URL`, `FALLBACK_MODEL_NAME`, and optionally `FALLBACK_PROVIDER_API_KEY`. Set `FALLBACK_PROVIDER=fake` to skip a second LLM and use the built-in fake provider immediately after the primary fails. Otherwise, if both configured LLMs fail or return unusable design output, the app tries the deterministic built-in fake provider from the earlier implementation, followed by code-only design as the final safety net. The secondary LLM key is server-configured, never submitted by the browser, and both provider credential fingerprints are hashed in cache keys. Never commit `.env`.

## Fetching and preview safety

- Only HTTP(S) pages on ports 80 or 443 are accepted.
- The app resolves each host, rejects non-public addresses, pins the connection to a validated IP, and repeats validation for every redirect.
- Responses must be HTML and are bounded by a decoded-byte limit and timeout.
- The preview response uses a restrictive Content Security Policy with `script-src 'none'` and `sandbox`; its iframe has no script or same-origin permissions.
- This is a local hackathon prototype, not yet hardened for public multi-user deployment. Rate limits and jobs are process-local, and distributed storage, CSRF protections, monitoring, and deployment-specific proxy configuration still require review before public exposure.

## Tests

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest
```

## Milestone 5: matrix and demo

Run the local fixture/tier matrix with canned fake-provider outputs:

```powershell
python scripts/matrix.py --provider fake --output docs/matrix-results.md --json-output docs/matrix-results.json
```

The matrix checks visible text, links, sanitized model CSS, render security headers, and decoration budgets across five fixtures and all three tiers. Use `python scripts/matrix.py --provider openai_compat --baseline docs/matrix-results.json` for an explicitly requested live-provider comparison. The demo startup script warms three medium-intensity fixture uploads in its in-memory cache before serving:

```powershell
python scripts/demo.py
```

See [docs/runbook.md](docs/runbook.md) for the demo sequence, provider/network fallbacks, and manual recording checklist.
