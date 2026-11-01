from __future__ import annotations

import json
import urllib.error
import urllib.request

from app.steps.load_page import FetchError


def complete(
    prompt: str,
    *,
    base_url: str,
    api_key: str,
    model: str,
    temperature: float,
    max_tokens: int,
    timeout_s: int,
) -> str:
    if not base_url or not model:
        raise ValueError("OpenAI-compatible provider requires PROVIDER_BASE_URL and MODEL_NAME.")
    endpoint = base_url.rstrip("/")
    if not endpoint.endswith("/chat/completions"):
        endpoint += "/chat/completions"
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(endpoint, data=body, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            payload = json.loads(response.read(1024 * 1024).decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            body_text = exc.read(4096).decode("utf-8", errors="replace")
        finally:
            exc.close()
        if api_key:
            body_text = body_text.replace(api_key, "[REDACTED]")
        raise FetchError(f"AI provider returned HTTP {exc.code}: {body_text[:300]}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise FetchError("AI provider could not be reached before the timeout.") from exc
    except json.JSONDecodeError as exc:
        raise FetchError("AI provider returned an invalid response.") from exc
    try:
        content = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise FetchError("AI provider response did not contain a chat completion.") from exc
    if not isinstance(content, str):
        raise FetchError("AI provider returned non-text content.")
    return content
