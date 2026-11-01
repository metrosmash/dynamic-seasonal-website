from __future__ import annotations

from app.brief import build_prompt
from app.content.themes import select_theme
from app.parser import parse_design_response, summarize_html
from app.providers import fake
from app.providers import openai_compat
from app.steps.load_page import FetchError
from app.steps.assemble import assemble_page


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
    variant: int = 0,
) -> dict[str, str]:
    summary = summarize_html(source_html)
    theme = select_theme(source_url, intensity, variant)
    prompt = build_prompt(summary, intensity, theme.id)
    warning = ""
    design_mode = "AI design"

    if provider == "none":
        response = ""
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
            response = ""
            design_mode = "code-only design"
            warning = f"AI design unavailable ({exc}); showing the built-in {theme.id} design instead."
    else:
        raise ValueError("Unsupported provider configuration.")

    design = parse_design_response(response, intensity)
    placements = design.placements
    if not placements:
        placements = theme.defaults[intensity]
    if not design.compliant and provider not in {"none"}:
        design_mode = "code-only design"
        warning = warning or (
            f"The AI response did not include a supported decoration; showing the built-in "
            f"{theme.id} design."
        )

    decorated = assemble_page(
        source_html,
        source_url=source_url,
        accent=design.accent,
        placements=placements,
        theme_id=theme.id,
        intensity=intensity,
    )
    return {
        "html": decorated,
        "theme": theme.id,
        "design_mode": design_mode,
        "warning": warning,
    }
