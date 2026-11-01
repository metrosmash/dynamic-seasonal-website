from __future__ import annotations

from app.brief import build_prompt
from app.parser import parse_design_response, summarize_html
from app.providers import fake
from app.providers import openai_compat
from app.steps.load_page import FetchError
from app.steps.assemble import assemble_page

MILESTONE1_PLACEMENTS = {"top-right"}


def decorate_page(
    source_html: str,
    *,
    source_url: str,
    intensity: str,
    provider: str,
    provider_base_url: str,
    provider_api_key: str,
    model_name: str,
    model_timeout: int,
) -> dict[str, str]:
    summary = summarize_html(source_html)
    prompt = build_prompt(summary, intensity)
    warning = ""
    design_mode = "AI design"

    if provider == "none":
        response = "THEME: pumpkin-patch\nACCENT: #ff7a1a\nPLACE: moon @ top-right"
        design_mode = "code-only design"
    elif provider == "fake":
        response = fake.complete(
            prompt,
            temperature=0.5,
            max_tokens=350,
            timeout_s=model_timeout,
        )
        design_mode = "sample provider"
    elif provider == "openai_compat":
        try:
            response = openai_compat.complete(
                prompt,
                base_url=provider_base_url,
                api_key=provider_api_key,
                model=model_name,
                temperature=0.5,
                max_tokens=350,
                timeout_s=model_timeout,
            )
        except (FetchError, ValueError) as exc:
            response = "THEME: pumpkin-patch\nACCENT: #ff7a1a\nPLACE: moon @ top-right"
            design_mode = "code-only design"
            warning = f"AI design unavailable ({exc}); showing the built-in Halloween design instead."
    else:
        raise ValueError("Unsupported provider configuration.")

    design = parse_design_response(response, intensity)
    if not design.compliant:
        design = parse_design_response(
            "THEME: pumpkin-patch\nACCENT: #ff7a1a\nPLACE: moon @ top-right",
            intensity,
        )
        design_mode = "code-only design"
        warning = "The AI response did not match the supported design format; showing the built-in design."

    theme = design.theme if design.theme == "pumpkin-patch" else "pumpkin-patch"
    accent = design.accent or "#ff7a1a"
    placement = next(
        (
            (name, slot)
            for name, slot in design.placements
            if name in {"moon", "pumpkin"} and slot in MILESTONE1_PLACEMENTS
        ),
        ("moon", "top-right"),
    )
    if placement == ("moon", "top-right") and not any(
        name == "moon" and slot == "top-right" for name, slot in design.placements
    ):
        warning = warning or (
            "This first version supports one moon or pumpkin decoration in the top-right corner; "
            "other model placements are not applied yet."
        )
    decorated = assemble_page(
        source_html,
        source_url=source_url,
        accent=accent,
        placement=placement,
        intensity=intensity,
    )
    return {
        "html": decorated,
        "theme": theme,
        "design_mode": design_mode,
        "warning": warning,
    }
