from __future__ import annotations

import json
import time
import urllib.error
import urllib.request


class ProviderError(Exception):
    def __init__(self, message: str, *, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


MAX_RETRIES = 2


def _chat(
    messages: list[dict],
    *,
    base_url: str,
    api_key: str,
    model: str,
    temperature: float,
    max_tokens: int,
    timeout_s: int,
    tools: list[dict] | None = None,
) -> dict:
    """Post a chat-completions request and return the assistant message."""
    if not base_url or not model:
        raise ValueError("OpenAI-compatible provider requires PROVIDER_BASE_URL and MODEL_NAME.")
    endpoint = base_url.rstrip("/")
    if not endpoint.endswith("/chat/completions"):
        endpoint += "/chat/completions"
    payload: dict = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    body = json.dumps(payload).encode("utf-8")
    request_headers = {"Content-Type": "application/json"}
    if api_key:
        request_headers["Authorization"] = "Bearer " + api_key
    request = urllib.request.Request(endpoint, data=body, headers=request_headers)
    request_deadline = time.monotonic() + timeout_s
    for attempt in range(MAX_RETRIES + 1):
        remaining = request_deadline - time.monotonic()
        if remaining <= 0:
            raise ProviderError("AI provider could not be reached before the timeout.")
        try:
            with urllib.request.urlopen(request, timeout=remaining) as response:
                payload = json.loads(response.read(1024 * 1024).decode("utf-8"))
            break
        except urllib.error.HTTPError as exc:
            try:
                body_text = exc.read(4096).decode("utf-8", errors="replace")
                retry_after = exc.headers.get("Retry-After", "")
            finally:
                exc.close()
            if api_key:
                body_text = body_text.replace(api_key, "[REDACTED]")
            retryable = exc.code == 429 or 500 <= exc.code <= 599
            if retryable and attempt < MAX_RETRIES:
                try:
                    delay = min(max(float(retry_after), 0), 2, remaining)
                except ValueError:
                    delay = min(0.25 * (2 ** attempt), 1, remaining)
                time.sleep(delay)
                continue
            raise ProviderError(
                f"AI provider returned HTTP {exc.code}: {body_text[:300]}",
                status_code=exc.code,
            ) from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise ProviderError("AI provider could not be reached before the timeout.") from exc
        except json.JSONDecodeError as exc:
            raise ProviderError("AI provider returned an invalid response.") from exc
    else:
        raise ProviderError("AI provider did not return a response.")
    try:
        message = payload["choices"][0]["message"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ProviderError("AI provider response did not contain a chat completion.") from exc
    if not isinstance(message, dict):
        raise ProviderError("AI provider returned non-text content.")
    return message


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
    """Call an OpenAI-compatible chat-completions endpoint and return the text."""
    message = _chat(
        [{"role": "user", "content": prompt}],
        base_url=base_url,
        api_key=api_key,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout_s=timeout_s,
    )
    content = message.get("content")
    if not isinstance(content, str):
        raise ProviderError("AI provider returned non-text content.")
    return content


def complete_with_tools(
    messages: list[dict],
    *,
    base_url: str,
    api_key: str,
    model: str,
    temperature: float,
    max_tokens: int,
    timeout_s: int,
    tools: list[dict],
) -> dict:
    """Chat call that may return tool calls; returns the assistant message as-is."""
    return _chat(
        messages,
        base_url=base_url,
        api_key=api_key,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout_s=timeout_s,
        tools=tools,
    )
