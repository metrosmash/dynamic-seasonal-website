# Demo runbook

## Before the demo

1. Use the same computer, network, and `.env` configuration planned for the presentation.
2. Verify `.env` has `PROVIDER=fake` for the deterministic demo, or `PROVIDER=openai_compat` with a reachable compatible primary provider and valid `PROVIDER_BASE_URL` and `MODEL_NAME` for an AI demo. Set `PROVIDER_API_KEY` or enter a per-request primary key in the form. For automatic secondary LLM failover, configure `FALLBACK_PROVIDER=openai_compat`, `FALLBACK_PROVIDER_BASE_URL`, `FALLBACK_MODEL_NAME`, and optionally `FALLBACK_PROVIDER_API_KEY`. Set `FALLBACK_PROVIDER=fake` to use the deterministic sample provider directly after primary failure instead. Never add `.env` to source control.
3. In PowerShell, start the app with pre-warming enabled:

   ```powershell
   .\halloween_env\Scripts\python.exe scripts\demo.py
   ```

   The command decorates the three demo uploads at medium intensity, checks the render security header, confirms that a repeat upload hits the in-memory cache, and then starts the server. Keep this process running; the cache is process-local and disappears when it stops.
4. Open `http://127.0.0.1:5000` and verify the homepage loads. Do one live uncached upload after cache pre-warming to demonstrate the full path.
5. Record a screen capture of a complete successful run and keep a local backup. Store the recording outside source control unless the team explicitly wants it committed.
6. Ask someone who did not write this runbook to follow it once and note any unclear steps.

## Demo order

Use the upload picker and set intensity to **Medium** for each page:

1. `fixtures\matrix\halloween_article.html` — article text and placement around headings.
2. `fixtures\matrix\blog_post.html` — blog layout and decoration.
3. `fixtures\matrix\documentation_page.html` — code block, navigation link, and multiple sections.

Then show one uncached upload or use the result page's regenerate action. The matrix-only messy and script-only pages are useful for explaining limits, but are not part of the polished three-page sequence.

## If something fails

- **Primary provider unavailable or returns unusable output:** if a secondary endpoint is configured, the app tries it, then tries the built-in fake provider, and finally uses the code-only design if needed. The fake provider is deterministic and is not another LLM. For a fully offline deterministic demo, set `PROVIDER=none` and `FALLBACK_PROVIDER=none`, then restart.
- **Network unavailable:** these demo pages are uploaded local fixtures, so page fetching is not needed. Start the server and use the exact same fixture files and medium intensity to get the pre-warmed in-memory results. If the machine or process was restarted, run the pre-warming command again. Remote fonts may not load; system fallback fonts are used.
- **Queue or page error:** restart the server, confirm the `.env` values, and retry once. If it persists, use the screen capture as the backup and record the error rather than improvising a live provider change.
- **No cached result:** the cache is lost on restart and keyed by the exact uploaded page, provider settings, intensity, credential fingerprint, and variant. Re-run the pre-warming command and upload the original fixture unchanged.

## Verification commands

Run the local fake-provider matrix without network access:

```powershell
.\halloween_env\Scripts\python.exe scripts\matrix.py --provider fake --output docs\matrix-results.md --json-output docs\matrix-results.json
```

For a configured live-provider comparison, preserve the fake report as the baseline and run:

```powershell
.\halloween_env\Scripts\python.exe scripts\matrix.py --provider openai_compat --baseline docs\matrix-results.json --output docs\matrix-openai-results.md
```

The live command sends the fixture page contents to the configured provider and may incur provider usage charges. Run it only when that provider call is intended. A provider-free reliability check is available with `--provider none`.

The last fake-provider matrix measured about 0.027–0.291 seconds per case in the local Flask test client. This is not a real-provider or presentation-machine measurement; repeat the timing on the demo machine with the intended provider before promising an end-to-end response time.

## Known limits

- The page is reconstructed from static HTML; JavaScript-only pages and login-gated pages are not supported.
- Remote resources may be unavailable, and previews intentionally block scripts.
- Jobs and cache are process-local. Restarting the process clears both.
- Rate limiting and background work are intended for a local prototype, not a multi-process public deployment.
- The screen capture and an independent run-through of this runbook are manual demo-preparation steps and are not included in the repository.
