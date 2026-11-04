# Halloween Website Decorator

Turn a static website into a Halloween-themed preview. Enter a public website URL, or upload an HTML page with its CSS and images. The app preserves the original page content, adds a curated theme and decorations, and shows the result in an isolated preview.

> **What to expect:** This is a static-page preview, not a perfect copy. JavaScript is removed for safety, and pages that need JavaScript or a login may not work. Uploading the original CSS and images helps preserve the look.

## Get started

The project is tested with Python 3.14.

In PowerShell, from the project folder:

```powershell
python -m venv halloween_env
.\halloween_env\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
python run.py
```

Open [http://127.0.0.1:5000](http://127.0.0.1:5000). The default `fake` provider works without an API key, so you can try the app right away.

## Use the app

Choose one input method:

- **Website URL:** enter a public HTTP or HTTPS address.
- **Website files:** select one `.html` or `.htm` file and any related CSS or PNG, JPG, GIF, or WebP images.
- **ZIP archive:** select one ZIP containing exactly one HTML file plus optional supported assets. Do not mix a ZIP with separately selected files.

Choose a decoration intensity and submit. The result page lets you compare the decorated page with the original snapshot, and regenerate a variation. Uploaded assets are embedded in the preview when their filenames match references in the HTML or CSS. Unuploaded assets may not load.

For iterative edits, use **Decorate with agent**: the model edits the page over several turns inside a harness (local by default, Browserbase cloud when configured), and the result page offers chat follow-ups plus a download link. See [docs/agent-harness.md](docs/agent-harness.md).

## AI provider setup

The default provider is `fake`: a deterministic, built-in sample provider. To use an OpenAI-compatible LLM, set these values in your local `.env`:

```dotenv
PROVIDER=openai_compat
PROVIDER_BASE_URL=https://your-provider.example/v1
MODEL_NAME=your-model
PROVIDER_API_KEY=
```

You can put the primary key in `.env` or enter it in the form for one request. The app can also try a second OpenAI-compatible LLM:

```dotenv
FALLBACK_PROVIDER=openai_compat
FALLBACK_PROVIDER_BASE_URL=https://your-secondary-provider.example/v1
FALLBACK_MODEL_NAME=your-fallback-model
FALLBACK_PROVIDER_API_KEY=
```

Set `FALLBACK_PROVIDER=fake` to use the built-in sample provider directly after the primary fails. If the configured providers and sample provider cannot produce a valid design, the app uses its code-only design as a final fallback. Never commit `.env` or put API keys in the Docker image.

## How to test

Install the test dependencies once:

```powershell
python -m pip install -r requirements-dev.txt
```

Run the full automated test suite:

```powershell
python -m pytest -q
```

Run a focused test file while working on a specific feature:

```powershell
python -m pytest tests\test_provider_fallback.py -q
```

The fixture matrix checks five sample pages at all three decoration intensities. It uses canned responses and does not call an external AI service:

```powershell
python scripts\matrix.py --provider fake
```

For the built-in code-only mode, use `--provider none`. To compare behavior against a live OpenAI-compatible provider, configure `.env` and run:

```powershell
python scripts\matrix.py --provider openai_compat --baseline docs\matrix-results.json
```

The live matrix sends fixture page contents to the configured provider and may incur charges. Use it only when you intend to make those requests.

## Run with Docker

Build and run the container from the repository folder:

```powershell
docker build -t halloween-theme-cloner .
docker run --rm -p 0.0.0.0:10000:10000 -e PROVIDER=fake halloween-theme-cloner
```

Open [http://localhost:10000](http://localhost:10000). The `0.0.0.0` host binding publishes the port on all network interfaces; use `-p 127.0.0.1:10000:10000` instead to keep it local to your machine. For local development, Docker can read settings from `.env` at runtime:

```powershell
docker run --rm -p 10000:10000 --env-file .env halloween-theme-cloner
```

The Docker build excludes `.env`. The container runs Gunicorn as a non-root user with one worker. For Render, deploy using Docker and set provider credentials in Render's environment settings.

## Safety and deployment notes

- URL fetching accepts only public HTTP(S) sites on standard ports and revalidates redirects.
- Rendered pages have a restrictive Content Security Policy and run in a sandboxed preview; page scripts are removed.
- Model-suggested CSS is filtered through an allowlist sanitizer.
- Jobs, rate limits, and cached results are held in memory. A restart clears them, and running multiple app instances will not share them.
- This is a prototype, not yet hardened for public multi-user production. Review deployment-specific proxy settings, CSRF protections, monitoring, and shared storage before exposing it publicly.

## Seasonal redesign demo (proof of concept)

A fictional **Sample Café** site (Home, Menu, About, Contact; all placeholder text) that can be
redesigned per season from toggle buttons. Open it at `/seasonal` after starting the app:

```powershell
python run.py
```

Then open [http://127.0.0.1:5000/seasonal](http://127.0.0.1:5000/seasonal) and pick a preset season
(Christmas, Halloween, Workers' Day, Children's Day, Eid al-Fitr (Sallah)) or type your own.
Only one season is active at a time; use Back/Forward to step through the last few versions,
or **Reset to original** to restore the preserved copy in `seasonal/original/`.

This demo uses toggles. A real system would trigger seasonal redesigns from a calendar
(e.g. automatically on December 1 for Christmas) instead of user clicks.

How it works: each toggle sends the season name plus the current site source
(`seasonal/site/index.html`, `style.css`, `script.js`) to the agent with the redesign
instruction in `app/seasonal.py`. With the default `fake`/`none` providers a built-in
deterministic designer acts as the agent so the demo runs offline; with
`PROVIDER=openai_compat` (or fallback) configured, the same prompt goes to the
OpenAI-compatible LLM, which must return the three files as JSON. Returned files are
validated (HTML structure, CSS syntax, JS syntax) before replacing the current version;
invalid files keep the previous version and show an error, while an unreachable LLM
falls back to the built-in designer with a visible warning. The agent can only write the
three files inside `seasonal/site/`.

Proof-of-concept limitations: the banner/controls live in a shell page outside the
redesigned files so they survive every season; version history is in-memory (a restart
clears it); the built-in designer reuses one layout with seasonal palettes/copy rather
than a fully free redesign; JS validation uses `node --check` when Node is installed and
a delimiter-balance check otherwise; no real addresses, prices, or contact details exist
anywhere in the demo content.

Focused tests: `python -m pytest tests/test_seasonal.py -q`.

## Demo

Run the demo server with the three sample pages pre-warmed in its in-memory cache:

```powershell
python scripts\demo.py
```

See [docs/runbook.md](docs/runbook.md) for the demo sequence and recovery steps. The saved fake-provider matrix results are in [docs/matrix-results.md](docs/matrix-results.md).
