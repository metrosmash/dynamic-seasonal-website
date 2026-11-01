from __future__ import annotations

import io
import urllib.error
from unittest.mock import MagicMock, Mock, patch

import pytest

from app.providers.openai_compat import ProviderError, complete


def _http_error(status: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        "https://provider.example/v1/chat/completions",
        status,
        "provider error",
        {"Retry-After": "0"},
        io.BytesIO(b'{"error":"transient"}'),
    )


@patch("app.providers.openai_compat.time.sleep")
@patch("app.providers.openai_compat.urllib.request.urlopen")
def test_provider_retries_429_and_server_errors_twice(urlopen, _sleep):
    response = Mock()
    response.read.return_value = (
        b'{"choices":[{"message":{"content":"PLACE: bat @ top-right"}}]}'
    )
    context = MagicMock()
    context.__enter__.return_value = response
    urlopen.side_effect = [_http_error(429), _http_error(503), context]

    result = complete(
        "prompt",
        base_url="https://provider.example/v1",
        api_key="key",
        model="model",
        temperature=0,
        max_tokens=50,
        timeout_s=2,
    )

    assert result == "PLACE: bat @ top-right"
    assert urlopen.call_count == 3


@patch("app.providers.openai_compat.time.sleep")
@patch("app.providers.openai_compat.urllib.request.urlopen")
def test_provider_does_not_retry_client_errors(urlopen, _sleep):
    urlopen.side_effect = _http_error(401)

    with pytest.raises(ProviderError) as raised:
        complete(
            "prompt",
            base_url="https://provider.example/v1",
            api_key="key",
            model="model",
            temperature=0,
            max_tokens=50,
            timeout_s=2,
        )

    assert raised.value.status_code == 401
    assert urlopen.call_count == 1
