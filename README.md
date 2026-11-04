# Seasonal Website (dynamic seasonal redesign demo)

A proof-of-concept site that redesigns itself for the season. The demo content is a
fictional **Sample Café** (Home, Menu, About, Contact) written as clearly placeholder
text — no real addresses, phone numbers, prices, or claims.

Pick a season (Christmas, Halloween, Workers' Day, Children's Day, Eid al-Fitr (Sallah),
or your own) and an agent redesigns the café's colors, typography, layout, decorations,
and copy. Only one season is active at a time; Back/Forward steps through the last few
versions, and **Reset to original** restores the preserved copy in `seasonal/original/`.

This demo uses toggles. A real system would trigger seasonal redesigns from a calendar
(e.g. automatically on December 1 for Christmas) instead of user clicks.

## Get started

The project is tested with Python 3.14.

In PowerShell, from the project folder:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
python run.py
```

Open [http://127.0.0.1:5000](http://127.0.0.1:5000). The default `fake` provider uses a
built-in designer, so the demo works with no API key.

## How it works

Each toggle sends the season name plus the current site source
(`seasonal/site/index.html`, `style.css`, `script.js`) to the agent with the redesign
instruction in `app/seasonal.py`. With `PROVIDER=openai_compat` (or fallback) configured
in `.env`, the prompt goes to the OpenAI-compatible LLM, which must return the three
files as JSON:

```dotenv
PROVIDER=openai_compat
PROVIDER_BASE_URL=https://your-provider.example/v1
MODEL_NAME=your-model
PROVIDER_API_KEY=
```

Returned files are validated (HTML must keep the nav, all four sections, and the contact
form; CSS and JS must be syntactically valid) before replacing the current version.
Invalid files keep the previous version and show an error, while an unreachable LLM
falls back to the built-in designer with a visible warning. The agent can only write the
three files inside `seasonal/site/`.

## How to test

Install the test dependencies once:

```powershell
python -m pip install -r requirements-dev.txt
```

Run the automated test suite:

```powershell
python -m pytest -q
```

## Run with Docker

Build and run the container from the repository folder:

```powershell
docker build -t seasonal-website .
docker run --rm -p 127.0.0.1:10000:10000 -e PROVIDER=fake seasonal-website
```

Open [http://localhost:10000](http://localhost:10000). The Docker build excludes `.env`.
The container runs Gunicorn as a non-root user. For Render, deploy using Docker and set
provider credentials in Render's environment settings.

## Proof-of-concept limitations

- The banner and toggle controls live in a shell page outside the redesigned files, so
  they survive every season; the café itself renders in a sandboxed iframe.
- Version history is in-memory: a restart clears it and the working copy is re-seeded
  from the preserved original when files are missing.
- The built-in designer reuses one layout with seasonal palettes, decorations, and copy
  rather than a fully free redesign; a live LLM gets the same brief with full creative
  freedom within the guardrails.
- JS validation uses `node --check` when Node is installed, otherwise a
  delimiter-balance check.
- This is a prototype, not hardened for public multi-user production. Review proxy
  settings, CSRF protections, monitoring, and shared storage before exposing it.
