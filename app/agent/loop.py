from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.agent import TOOL_HELP, AgentPlan, parse_agent_response
from app.brief import build_prompt
from app.harness import BaseHarness, HarnessSnapshot
from app.parser import summarize_html
from app.providers import fake, openai_compat
from app.steps.load_page import FetchError


@dataclass(frozen=True)
class AgentIteration:
    response: str
    applied: tuple[str, ...]
    warnings: tuple[str, ...]
    note: str
    done: bool


@dataclass(frozen=True)
class AgentResult:
    snapshot: HarnessSnapshot
    iterations: tuple[AgentIteration, ...]
    warning: str
    design_mode: str


def _clean_instruction(instruction: str, max_chars: int) -> str:
    cleaned = "".join(
        char for char in (instruction or "") if char == "\n" or ord(char) >= 32
    ).strip()
    return cleaned[:max_chars]


def build_agent_prompt(
    summary: dict[str, Any],
    intensity: str,
    theme_id: str,
    instruction: str,
    history: tuple[str, ...] = (),
) -> str:
    base = build_prompt(summary, intensity, theme_id)
    parts = [base, "", TOOL_HELP]
    if instruction:
        parts += ["", f"User request: {instruction}"]
    if history:
        parts += ["", "Previous turns (most recent last):"] + [
            f"- {turn[:280]}" for turn in history[-4:]
        ]
    parts += [
        "",
        "Edit the page through the tools above. Reply with labelled lines only.",
    ]
    return "\n".join(parts)


def _request(
    prompt: str,
    *,
    provider: str,
    base_url: str,
    api_key: str,
    model: str,
    timeout_s: int,
) -> str:
    if provider == "fake":
        return fake.complete(prompt, temperature=0.5, max_tokens=350, timeout_s=timeout_s)
    if provider == "openai_compat":
        return openai_compat.complete(
            prompt,
            base_url=base_url,
            api_key=api_key,
            model=model,
            temperature=0.5,
            max_tokens=600,
            timeout_s=timeout_s,
        )
    raise ValueError("Unsupported provider configuration.")


def run_agent(
    harness: BaseHarness,
    *,
    source_html: str,
    intensity: str,
    theme_id: str,
    instruction: str,
    provider: str,
    provider_base_url: str,
    provider_api_key: str,
    model_name: str,
    fallback_provider: str = "none",
    fallback_provider_base_url: str = "",
    fallback_provider_api_key: str = "",
    fallback_model_name: str = "",
    model_timeout: int = 25,
    max_iterations: int = 3,
    max_message_chars: int = 2000,
    history: tuple[str, ...] = (),
) -> AgentResult:
    """Run up to max_iterations agent turns against the harness."""
    if provider not in {"fake", "openai_compat"}:
        raise ValueError("Unsupported provider configuration.")
    cleaned = _clean_instruction(instruction, max_message_chars)
    chain = [(provider, provider_base_url, provider_api_key, model_name)]
    if provider == "openai_compat" and fallback_provider != "none":
        chain.append((
            fallback_provider,
            fallback_provider_base_url,
            fallback_provider_api_key,
            fallback_model_name,
        ))

    summary = summarize_html(source_html)
    iterations: list[AgentIteration] = []
    warnings: list[str] = []
    turns = list(history)
    design_mode = "sample provider" if provider == "fake" else "AI agent"

    for _ in range(max(1, max_iterations)):
        prompt = build_agent_prompt(summary, intensity, theme_id, cleaned, tuple(turns))
        plan: AgentPlan | None = None
        plan_response = ""
        failures: list[str] = []
        for selected, base_url, api_key, model in chain:
            try:
                response = _request(
                    prompt,
                    provider=selected,
                    base_url=base_url,
                    api_key=api_key,
                    model=model,
                    timeout_s=model_timeout,
                )
            except (FetchError, ValueError) as exc:
                failures.append(f"{selected} failed ({exc})")
                continue
            candidate = parse_agent_response(response, intensity)
            if candidate.edits or candidate.done:
                plan = candidate
                plan_response = response[:2000]
                if selected != provider:
                    design_mode = "fallback AI agent"
                    warnings.append(
                        "The primary AI provider failed; the fallback was used."
                    )
                break
            failures.append(f"{selected} returned no usable edits")
        if plan is None:
            warnings.append(
                "The AI provider returned no usable edits"
                + (f" ({'; '.join(failures)})" if failures else "")
                + "."
            )
            break
        applied: list[str] = []
        turn_warnings: list[str] = []
        for edit in plan.edits:
            warning = harness.apply(edit)
            applied.append(edit.kind)
            if warning:
                turn_warnings.append(warning)
        if plan.note:
            turns.append(plan.note)
        iterations.append(AgentIteration(
            response=plan_response,
            applied=tuple(applied),
            warnings=tuple(turn_warnings),
            note=plan.note,
            done=plan.done,
        ))
        snapshot = harness.snapshot()
        theme_id = snapshot.theme_id
        summary = summarize_html(snapshot.html)
        if plan.done:
            break

    return AgentResult(
        snapshot=harness.snapshot(),
        iterations=tuple(iterations),
        warning=" ".join(warnings),
        design_mode=design_mode,
    )
