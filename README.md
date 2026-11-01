# Halloween Website Decorator

The Milestone 1 vertical slice accepts a public website URL, fetches its static HTML, applies a code-controlled Halloween theme and one supported decoration, then displays an isolated preview. The model supplies design suggestions; the app validates and applies them. This slice currently renders one moon or pumpkin in the top-right corner and ignores model-generated CSS until the sanitizer milestone. Remote JavaScript is removed. Pages that require login or JavaScript rendering are not supported yet.

Design-response parsing and HTML summarization live in `app/parser.py`; prompt construction lives in `app/brief.py`. The web app and benchmark script share these modules.

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
