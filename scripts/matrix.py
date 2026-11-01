from __future__ import annotations

import argparse
import io
import json
import re
import sys
import time
from pathlib import Path
from unittest.mock import patch

import tinycss2
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import create_app
from app.content.tiers import TIERS


FIXTURES = (
    "halloween_article",
    "blog_post",
    "documentation_page",
    "messy_page",
    "script_only_page",
)
TIERS_TO_TEST = ("low", "medium", "high")
MATRIX_SELECTOR = ".hw-matrix-safety-probe"
HIDING_PROPERTIES = {"clip", "clip-path", "height", "text-indent"}


def _normalized_text(html: str) -> tuple[str, list[tuple[str, str]]]:
    soup = BeautifulSoup(html, "html.parser")
    for generated in soup.select("[data-hw-added]"):
        generated.decompose()
    body = soup.body or soup
    text = re.sub(r"\s+", " ", body.get_text(" ", strip=True))
    links = [
        (
            str(link.get("href", "")),
            re.sub(r"\s+", " ", link.get_text(" ", strip=True)),
        )
        for link in body.find_all("a")
    ]
    return text, links


def _matrix_css_is_safe(html: str, tier: str, *, expect_probe: bool) -> bool:
    soup = BeautifulSoup(html, "html.parser")
    theme_style = soup.select_one('style[data-hw-added="theme"]')
    if theme_style is None:
        return False
    rules = tinycss2.parse_stylesheet(
        theme_style.string or "",
        skip_comments=True,
        skip_whitespace=True,
    )
    found_probe = False
    for rule in rules:
        if rule.type != "qualified-rule":
            continue
        selector = tinycss2.serialize(rule.prelude).strip()
        if MATRIX_SELECTOR not in selector:
            continue
        found_probe = True
        declarations = tinycss2.parse_declaration_list(
            rule.content,
            skip_comments=True,
            skip_whitespace=True,
        )
        for declaration in declarations:
            if declaration.type != "declaration":
                continue
            value = tinycss2.serialize(declaration.value).strip().lower()
            if declaration.lower_name in HIDING_PROPERTIES:
                return False
            if declaration.lower_name == "display" and value == "none":
                return False
            if declaration.lower_name == "visibility" and value == "hidden":
                return False
            if declaration.lower_name == "opacity":
                try:
                    if float(value) < 0.6:
                        return False
                except ValueError:
                    return False
    return not expect_probe or found_probe


def _headers_are_safe(response, *, is_render: bool) -> bool:
    csp = response.headers.get("Content-Security-Policy", "").lower()
    valid = (
        "script-src 'none'" in csp
        and response.headers.get("X-Content-Type-Options") == "nosniff"
        and response.headers.get("Referrer-Policy") == "no-referrer"
    )
    return valid and (not is_render or "sandbox" in csp)


def _wait_for_job(client, job_id: str, timeout_s: int) -> dict[str, str]:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        response = client.get(f"/status/{job_id}")
        if response.status_code != 200:
            raise RuntimeError(f"status endpoint returned HTTP {response.status_code}")
        status = response.get_json()
        if status["status"] in {"done", "error"}:
            return status
        time.sleep(0.02)
    raise TimeoutError("matrix job did not finish before its deadline")


def _run_case(app, fixture_name: str, tier: str, provider: str) -> dict[str, object]:
    fixture_path = ROOT / "fixtures" / "matrix" / f"{fixture_name}.html"
    design_path = ROOT / "fixtures" / "matrix" / "designs" / f"{fixture_name}.txt"
    source_html = fixture_path.read_bytes()
    canned_response = design_path.read_text(encoding="utf-8")
    client = app.test_client()
    start = time.monotonic()

    def submit():
        return client.post(
            "/decorate",
            data={
                "intensity": tier,
                "uploads": (io.BytesIO(source_html), fixture_path.name),
            },
            content_type="multipart/form-data",
        )

    if provider == "fake":
        with patch("app.pipeline.fake.complete", return_value=canned_response):
            submitted = submit()
            return _evaluate_case(
                app, client, submitted, fixture_name, tier, start, provider
            )
    submitted = submit()
    return _evaluate_case(app, client, submitted, fixture_name, tier, start, provider)


def _evaluate_case(
    app,
    client,
    submitted,
    fixture_name: str,
    tier: str,
    start: float,
    provider: str,
):
    base = {
        "fixture": fixture_name,
        "tier": tier,
        "seconds": round(time.monotonic() - start, 3),
        "outcome": "failed",
        "text_preserved": False,
        "links_preserved": False,
        "css_safe": False,
        "headers": False,
        "decorations": None,
        "budget": TIERS[tier]["max_decorations"],
        "code_only": None,
        "passed": False,
        "issue": "",
    }
    if submitted.status_code != 303:
        base["issue"] = f"submit_http_{submitted.status_code}"
        return base

    job_id = submitted.headers["Location"].rsplit("/", 1)[-1]
    status = _wait_for_job(
        client,
        job_id,
        int(app.config["JOB_DEADLINE_S"]) + 5,
    )
    base["seconds"] = round(time.monotonic() - start, 3)
    result_page = client.get(f"/result/{job_id}")

    if fixture_name == "script_only_page":
        expected_rejection = (
            status["status"] == "error"
            and "no readable html text" in status.get("error", "").lower()
        )
        base.update({
            "outcome": "expected rejection" if expected_rejection else "unexpected result",
            "text_preserved": None,
            "links_preserved": None,
            "css_safe": None,
            "headers": _headers_are_safe(result_page, is_render=False),
            "passed": expected_rejection and _headers_are_safe(result_page, is_render=False),
            "issue": "" if expected_rejection else "script-only page was not rejected as expected",
        })
        return base

    if status["status"] != "done":
        base["outcome"] = "job error"
        base["issue"] = "provider or processing job returned an error"
        return base

    job = app.config["JOBS"][job_id]
    rendered = client.get(f"/render/{job_id}")
    original_text, original_links = _normalized_text(job["original_html"])
    result_text, result_links = _normalized_text(rendered.get_data(as_text=True))
    soup = BeautifulSoup(rendered.get_data(as_text=True), "html.parser")
    decorations = len(soup.select('[data-hw-added="decoration"]'))
    text_ok = original_text == result_text
    links_ok = original_links == result_links
    css_ok = _matrix_css_is_safe(
        rendered.get_data(as_text=True),
        tier,
        expect_probe=provider == "fake" and TIERS[tier]["css_chars"] > 0,
    )
    headers_ok = _headers_are_safe(rendered, is_render=True)
    budget_ok = 0 < decorations <= TIERS[tier]["max_decorations"]
    base.update({
        "outcome": "ok",
        "text_preserved": text_ok,
        "links_preserved": links_ok,
        "css_safe": css_ok,
        "headers": headers_ok,
        "decorations": decorations,
        "code_only": job["design_mode"] == "code-only design",
        "passed": text_ok and links_ok and css_ok and headers_ok and budget_ok,
    })
    if not base["passed"]:
        base["issue"] = "one or more matrix checks failed"
    return base


def run_matrix(provider: str) -> dict[str, object]:
    app = create_app({
        "TESTING": True,
        "PROVIDER": provider,
        "RATE_LIMIT_BURST": 1000,
        "DAILY_REQUEST_LIMIT": 1000,
        "MAX_STORED_JOBS": 100,
    })
    results = [
        _run_case(app, fixture, tier, provider)
        for fixture in FIXTURES
        for tier in TIERS_TO_TEST
    ]
    return {
        "provider": provider,
        "results": results,
    }


def _markdown_report(report: dict[str, object], baseline: dict[str, object] | None) -> str:
    results = report["results"]
    lines = [
        f"# Fixture matrix results ({report['provider']})",
        "",
        f"- Cases: {len(results)}",
        f"- Passing: {sum(bool(row['passed']) for row in results)}/{len(results)}",
        "",
        "| Fixture | Tier | Outcome | Text | Links | CSS safe | Headers | Decorations / budget | Code-only | Time (s) |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in results:
        decorations = (
            "n/a"
            if row["decorations"] is None
            else f"{row['decorations']} / {row['budget']}"
        )
        code_only = "n/a" if row["code_only"] is None else str(row["code_only"]).lower()
        checks = [
            "n/a" if row[key] is None else str(row[key]).lower()
            for key in ("text_preserved", "links_preserved", "css_safe", "headers")
        ]
        values = (
            row["fixture"],
            row["tier"],
            row["outcome"],
            *checks,
            decorations,
            code_only,
            row["seconds"],
        )
        lines.append("| " + " | ".join(str(value) for value in values) + " |")
    issues = [row for row in results if row["issue"]]
    if issues:
        lines.extend(["", "## Failures", ""])
        lines.extend(
            f"- `{row['fixture']}` at `{row['tier']}`: {row['issue']}"
            for row in issues
        )
    if baseline is not None:
        baseline_rows = {
            (row["fixture"], row["tier"]): row for row in baseline["results"]
        }
        lines.extend([
            "",
            f"## Comparison with {baseline['provider']} baseline",
            "",
            "| Fixture | Tier | Changed checks |",
            "|---|---|---|",
        ])
        compare_fields = (
            "outcome",
            "text_preserved",
            "links_preserved",
            "css_safe",
            "headers",
            "decorations",
            "code_only",
        )
        for row in results:
            key = (row["fixture"], row["tier"])
            reference = baseline_rows.get(key)
            if reference is None:
                changes = "no matching baseline"
            else:
                changed = [
                    field
                    for field in compare_fields
                    if reference.get(field) != row.get(field)
                ]
                changes = ", ".join(changed) if changed else "none"
            lines.append(f"| {row['fixture']} | {row['tier']} | {changes} |")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Halloween fixture/tier matrix.")
    parser.add_argument(
        "--provider",
        choices=("fake", "none", "openai_compat"),
        default="fake",
        help="Use canned fixture outputs, the built-in code-only mode, or the configured live provider.",
    )
    parser.add_argument("--output", type=Path, help="Write the Markdown report to this path.")
    parser.add_argument("--json-output", type=Path, help="Write machine-readable results to this path.")
    parser.add_argument("--baseline", type=Path, help="Compare results with a prior JSON matrix report.")
    args = parser.parse_args()

    report = run_matrix(args.provider)
    baseline = json.loads(args.baseline.read_text(encoding="utf-8")) if args.baseline else None
    markdown = _markdown_report(report, baseline)
    print(markdown, end="")
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(markdown, encoding="utf-8")
    if args.json_output:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(
            json.dumps(report, indent=2) + "\n",
            encoding="utf-8",
        )
    return 0 if all(row["passed"] for row in report["results"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
