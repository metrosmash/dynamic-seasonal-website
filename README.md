# Halloween Website Decorator

The app accepts a public website URL, fetches its static HTML, applies a deterministic Halloween theme and validated decorations, then displays an isolated preview. The model supplies decoration placement and an optional accent; the app enforces tier budgets and applies the changes. Ten curated themes have tested light and dark palettes. External page assets may still fail to load, model-generated CSS is not applied until the sanitizer milestone, and remote JavaScript is removed. Pages that require login or JavaScript rendering are not supported yet.

Design-response parsing and HTML summarization live in `app/parser.py`; prompt construction lives in `app/brief.py`. Theme palettes and seeded selection live in `app/content/themes.py`, intensity budgets in `app/content/tiers.py`, and decoration metadata in `app/content/decor_catalog.py`. Each decoration has a standalone SVG asset in `app/content/decor/`, loaded by the catalog as a package resource. The web app and benchmark script share the design modules.

The homepage also accepts one `.html`/`.htm` file with optional CSS and PNG, JPG, GIF, or WebP assets, either as individual files or in one ZIP archive. ZIPs must contain exactly one HTML file and only supported asset types; their contents are read in memory and never extracted to disk. Matching stylesheet and image filenames are embedded into the preview; referenced files that are not uploaded are reported as warnings. Uploads are limited by `MAX_UPLOAD_HTML_BYTES`, `MAX_UPLOAD_TOTAL_BYTES`, `MAX_UPLOAD_ARCHIVE_BYTES`, and `MAX_UPLOAD_FILES`. Repeated identical uploads reuse a bounded in-memory result cache; the cache is cleared when the server restarts.

## Run locally

```powershell
python -m venv halloween_env
.\halloween_env\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
python run.py
```

Open `http://127.0.0.1:5000`. The default provider is `fake`, so the demo works without model credentials. To use the configured OpenAI-compatible provider, set `PROVIDER=openai_compat`, `PROVIDER_BASE_URL`, `MODEL_NAME`, and `PROVIDER_API_KEY` in your local `.env`. Never commit `.env`.

## Fetching and preview safety

- Only HTTP(S) pages on ports 80 or 443 are accepted.
- The app resolves each host, rejects non-public addresses, pins the connection to a validated IP, and repeats validation for every redirect.
- Responses must be HTML and are bounded by a decoded-byte limit and timeout.
- The preview response uses a restrictive Content Security Policy with `script-src 'none'` and `sandbox`; its iframe has no script or same-origin permissions.
- This is a local hackathon prototype, not yet hardened for public multi-user deployment. Rate limits, bounded jobs/cache, CSS sanitization, and persistent storage are later milestones.

## Tests

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest
```
