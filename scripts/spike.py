#!/usr/bin/env python3
"""Benchmark an OpenAI-compatible model's Halloween design suggestions."""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
import urllib.error
import urllib.request
from dotenv import load_dotenv
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.brief import build_prompt
from app.parser import DesignResult, TIERS, parse_design_response, summarize_html


DEFAULT_PAGE = ROOT / "fixtures" / "spike_sample.html"
DEFAULT_REPORT = ROOT / "docs" / "spike-results.md"
MAX_PAGE_BYTES = 2 * 1024 * 1024

# saving the .env variables to the environ
load_dotenv()

@dataclass(frozen=True)
class CallResult:
    temperature: float
    run: int
    latency_s: float
    input_tokens: int | None
    output_tokens: int | None
    design: DesignResult | None
    error: str | None
    raw_text: str | None


def summarize_page(page_path: Path) -> tuple[str, dict[str, Any]]:
    raw = page_path.read_bytes()
    if len(raw) > MAX_PAGE_BYTES:
        raise ValueError(f"Sample page exceeds the {MAX_PAGE_BYTES}-byte limit: {page_path}")
    text = raw.decode("utf-8", errors="replace")
    return text, summarize_html(text, page_path.stem)


def _endpoint(base_url: str) -> str:
    base = base_url.rstrip("/")
    return base if base.endswith("/chat/completions") else f"{base}/chat/completions"


def call_model(
    prompt: str,
    *,
    base_url: str,
    api_key: str,
    model: str,
    temperature: float,
    max_tokens: int,
    timeout_s: float,
) -> tuple[str, int | None, int | None]:
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    if api_key:
        headers["Authorization"] = "Bearer " + api_key
    request = urllib.request.Request(_endpoint(base_url), data=body, headers=headers)
    with urllib.request.urlopen(request, timeout=timeout_s) as response:
        payload = json.loads(response.read().decode("utf-8"))
    content = payload["choices"][0]["message"]["content"]
    if not isinstance(content, str):
        raise ValueError("Provider returned non-text message content")
    usage = payload.get("usage") or {}
    input_tokens = usage.get("prompt_tokens", usage.get("input_tokens"))
    output_tokens = usage.get("completion_tokens", usage.get("output_tokens"))
    return content, input_tokens, output_tokens


def _error_label(error: Exception, api_key: str = "") -> str:
    if isinstance(error, urllib.error.HTTPError):
        try:
            response_body = error.read(4096).decode("utf-8", errors="replace")
            payload = json.loads(response_body)
            message = _provider_error_message(payload)
        except (OSError, json.JSONDecodeError):
            message = None
        finally:
            error.close()
        if isinstance(message, str) and message:
            message = " ".join(message.split())
            if api_key:
                message = message.replace(api_key, "[REDACTED]")
            return f"HTTP {error.code}: {message[:300]}"
        return f"HTTP {error.code}"
    if isinstance(error, TimeoutError):
        return "timeout"
    if isinstance(error, urllib.error.URLError):
        return "timeout" if isinstance(error.reason, TimeoutError) else "connection error"
    if isinstance(error, (KeyError, IndexError, json.JSONDecodeError)):
        return "invalid provider response"
    return type(error).__name__


def _provider_error_message(payload: Any) -> str | None:
    if isinstance(payload, str):
        return payload
    if isinstance(payload, list):
        for item in payload:
            message = _provider_error_message(item)
            if message:
                return message
        return None
    if not isinstance(payload, dict):
        return None

    for key in ("message", "detail", "error_description"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value

    for key in ("error", "errors"):
        if key in payload:
            message = _provider_error_message(payload[key])
            if message:
                return message
    return None


def run_spike(
    prompt: str,
    *,
    base_url: str,
    api_key: str,
    model: str,
    temperatures: list[float],
    runs: int,
    timeout_s: float,
    max_tokens: int,
    tier: str,
) -> list[CallResult]:
    results: list[CallResult] = []
    for temperature in temperatures:
        for run in range(1, runs + 1):
            started = time.perf_counter()
            try:
                text, input_tokens, output_tokens = call_model(
                    prompt,
                    base_url=base_url,
                    api_key=api_key,
                    model=model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    timeout_s=timeout_s,
                )
                result = CallResult(
                    temperature, run, time.perf_counter() - started,
                    input_tokens, output_tokens,
                    parse_design_response(text, tier), None, text,
                )
            except (
                urllib.error.URLError,
                TimeoutError,
                ValueError,
                KeyError,
                IndexError,
            ) as error:
                result = CallResult(
                    temperature, run, time.perf_counter() - started,
                    None, None, None, _error_label(error, api_key), None,
                )
            results.append(result)
            status = "error" if result.error else (
                "compliant" if result.design and result.design.compliant else "not compliant"
            )
            print(
                f"temperature={temperature:g} run={run}/{runs} "
                f"latency={result.latency_s:.2f}s status={status}",
                flush=True,
            )
    return results


def _format_optional_mean(values: list[int]) -> str:
    return f"{statistics.mean(values):.1f}" if values else "n/a"


def render_report(
    results: list[CallResult],
    *,
    model: str,
    tier: str,
    temperatures: list[float],
    runs: int,
    page_path: Path,
) -> str:
    lines = [
        "# Milestone 0 spike results",
        "",
        f"- Generated: {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
        f"- Sample page: `{page_path.name}`",
        f"- Model: `{model}`",
        f"- Intensity: `{tier}`",
        f"- Runs per temperature: {runs}",
        f"- Temperatures: {', '.join(f'{value:g}' for value in temperatures)}",
        "",
        "## Results",
        "",
        "| Temperature | Successful | Compliant | Compliance | p50 latency (s) | Max latency (s) | Mean input tokens | Mean output tokens |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for temperature in temperatures:
        group = [item for item in results if item.temperature == temperature]
        successful = [item for item in group if not item.error]
        compliant = [
            item for item in successful if item.design and item.design.compliant
        ]
        latencies = [item.latency_s for item in successful]
        input_tokens = [
            item.input_tokens for item in successful if item.input_tokens is not None
        ]
        output_tokens = [
            item.output_tokens for item in successful if item.output_tokens is not None
        ]
        p50 = f"{statistics.median(latencies):.2f}" if latencies else "n/a"
        maximum = f"{max(latencies):.2f}" if latencies else "n/a"
        rate = f"{len(compliant) / len(successful):.0%}" if successful else "n/a"
        lines.append(
            f"| {temperature:g} | {len(successful)}/{len(group)} | "
            f"{len(compliant)}/{len(successful)} | {rate} | {p50} | {maximum} | "
            f"{_format_optional_mean(input_tokens)} | "
            f"{_format_optional_mean(output_tokens)} |"
        )

    lines.extend(["", "## Run details", ""])
    for item in results:
        lines.append(
            f"### Temperature {item.temperature:g}, run {item.run}: "
            f"{'error: ' + item.error if item.error else 'completed'}"
        )
        lines.append(f"- Latency: {item.latency_s:.2f}s")
        lines.append(f"- Input/output tokens: {item.input_tokens or 'n/a'} / {item.output_tokens or 'n/a'}")
        if item.design:
            lines.append(f"- Format compliant: {'yes' if item.design.compliant else 'no'}")
            if item.design.issues:
                lines.append(f"- Parser notes: {', '.join(item.design.issues)}")
        if item.raw_text:
            lines.extend(["", "Response:", ""])
            lines.extend(f"    {line}" for line in item.raw_text.splitlines())
        lines.append("")

    lines.extend([
        "## Human quality review",
        "",
        "Review the responses above against the sample page and the reference stylesheet. "
        "Record whether placements feel appropriate, CSS suggestions are useful, and "
        "whether the result would be readable.",
        "",
        "- Visual quality notes: _pending review_",
        "- Model/provider decision: _pending review_",
        "- Prompt/output-format decision: _pending review_",
    ])
    return "\n".join(lines) + "\n"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--page", type=Path, default=DEFAULT_PAGE, help="Local HTML sample")
    parser.add_argument("--output", type=Path, default=DEFAULT_REPORT, help="Markdown report path")
    parser.add_argument("--model", default=os.getenv("MODEL_NAME"), help="Model name (or MODEL_NAME)")
    parser.add_argument(
        "--base-url",
        default=os.getenv("PROVIDER_BASE_URL"),
        help="OpenAI-compatible API base URL (or PROVIDER_BASE_URL)",
    )
    parser.add_argument(
        "--temperatures", nargs="+", type=float, default=[0.5, 0.8],
        help="Temperatures to test (default: 0.5 0.8)",
    )
    parser.add_argument("--runs", type=int, default=10, help="Calls per temperature (default: 10)")
    parser.add_argument("--timeout", type=float, default=25, help="Per-call timeout in seconds")
    parser.add_argument("--max-tokens", type=int, default=350, help="Maximum generated tokens")
    parser.add_argument("--tier", choices=TIERS, default="medium", help="Design intensity")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print the generated prompt; do not make provider calls or write a report",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.runs < 1:
        print("--runs must be at least 1", file=sys.stderr)
        return 2
    if args.timeout <= 0 or args.max_tokens < 1:
        print("--timeout and --max-tokens must be positive", file=sys.stderr)
        return 2
    if not args.temperatures or any(not 0 <= value <= 2 for value in args.temperatures):
        print("temperatures must be between 0 and 2", file=sys.stderr)
        return 2
    try:
        _, summary = summarize_page(args.page)
    except (OSError, ValueError) as error:
        print(f"Could not read sample page: {error}", file=sys.stderr)
        return 2
    prompt = build_prompt(summary, args.tier)

    if args.dry_run:
        print(prompt)
        return 0
    if not args.model or not args.base_url:
        print(
            "Set MODEL_NAME and PROVIDER_BASE_URL, or pass --model and --base-url. "
            "Set PROVIDER_API_KEY for providers that require authentication.",
            file=sys.stderr,
        )
        return 2

    results = run_spike(
        prompt,
        base_url=args.base_url,
        api_key=os.environ.get("PROVIDER_API_KEY", ""),
        model=args.model,
        temperatures=args.temperatures,
        runs=args.runs,
        timeout_s=args.timeout,
        max_tokens=args.max_tokens,
        tier=args.tier,
    )
    report = render_report(
        results,
        model=args.model,
        tier=args.tier,
        temperatures=args.temperatures,
        runs=args.runs,
        page_path=args.page,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report, encoding="utf-8")
    print(f"Report written to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
