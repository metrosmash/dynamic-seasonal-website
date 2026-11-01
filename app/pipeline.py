from __future__ import annotations

from app.brief import build_prompt
from app.content.fallback import code_only_design
from app.content.themes import select_theme
from app.parser import parse_design_response, summarize_html
from app.providers import fake
from app.providers import openai_compat
from app.steps.load_page import FetchError
from app.steps.assemble import assemble_page
from app.steps.sanitize_css import sanitize_css


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
    source_id: str | None = None,
) -> dict[str, str]:
    summary = summarize_html(source_html)
    theme = select_theme(source_id or source_url, intensity, variant)
    prompt = build_prompt(summary, intensity, theme.id)
    warning = ""
    design_mode = "AI design"

    def request_design(request_prompt: str) -> str:
        if provider == "fake":
            return fake.complete(
                request_prompt,
                temperature=0.5,
                max_tokens=350,
                timeout_s=model_timeout,
            )
        if provider == "openai_compat":
            return openai_compat.complete(
                request_prompt,
                base_url=provider_base_url,
                api_key=provider_api_key,
                model=model_name,
                temperature=0.5,
                max_tokens=350,
                timeout_s=model_timeout,
            )
        raise ValueError("Unsupported provider configuration.")

    response = ""
    if provider == "none":
        design_mode = "code-only design"
    elif provider == "fake":
        try:
            response = request_design(prompt)
            design_mode = "sample provider"
        except (FetchError, ValueError) as exc:
            design_mode = "code-only design"
            warning = f"Sample design unavailable ({exc}); showing the built-in {theme.id} design."
    elif provider == "openai_compat":
        try:
            response = request_design(prompt)
        except (FetchError, ValueError) as exc:
            design_mode = "code-only design"
            warning = f"AI design unavailable ({exc}); showing the built-in {theme.id} design instead."
    else:
        raise ValueError("Unsupported provider configuration.")

    design = parse_design_response(response, intensity)
    if provider != "none" and design_mode != "code-only design" and not design.compliant:
        repaired = False
        try:
            repaired_response = request_design(
                prompt
                + "\nThe previous response was not parseable. Return one valid PLACE line "
                + "using only the listed catalog and slots. Output only the required labels."
            )
            repaired_design = parse_design_response(repaired_response, intensity)
            if repaired_design.compliant:
                design = repaired_design
                repaired = True
            else:
                design = code_only_design(theme.id, intensity)
        except (FetchError, ValueError):
            design = code_only_design(theme.id, intensity)
        if not repaired:
            design_mode = "code-only design"
            warning = warning or (
                f"The AI response was not usable; showing the built-in {theme.id} design."
            )
    elif not design.placements:
        design = code_only_design(theme.id, intensity)

    if provider != "none" and not design.compliant:
        design_mode = "code-only design"
        warning = warning or (
            f"The AI response did not include a supported decoration; showing the built-in "
            f"{theme.id} design."
        )
    sanitized_css = sanitize_css(design.css, intensity)
    if sanitized_css.dropped_rules or sanitized_css.rejected:
        warning = warning or (
            "Some model-suggested CSS was removed because it did not meet the safety rules."
        )
    placements = design.placements

    decorated = assemble_page(
        source_html,
        source_url=source_url,
        accent=design.accent,
        placements=placements,
        theme_id=theme.id,
        intensity=intensity,
        model_css=sanitized_css.css,
    )
    return {
        "html": decorated,
        "theme": theme.id,
        "design_mode": design_mode,
        "warning": warning,
    }
