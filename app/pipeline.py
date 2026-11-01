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
    fallback_provider: str = "none",
    fallback_provider_base_url: str = "",
    fallback_provider_api_key: str = "",
    fallback_model_name: str = "",
    variant: int = 0,
    source_id: str | None = None,
) -> dict[str, str]:
    summary = summarize_html(source_html)
    theme = select_theme(source_id or source_url, intensity, variant)
    prompt = build_prompt(summary, intensity, theme.id)
    warning = ""
    design_mode = "AI design"
    if provider not in {"fake", "none", "openai_compat"}:
        raise ValueError("Unsupported provider configuration.")

    def request_design(
        request_prompt: str,
        *,
        selected_provider: str,
        base_url: str,
        api_key: str,
        selected_model: str,
    ) -> str:
        if selected_provider == "fake":
            return fake.complete(
                request_prompt,
                temperature=0.5,
                max_tokens=350,
                timeout_s=model_timeout,
            )
        if selected_provider == "openai_compat":
            return openai_compat.complete(
                request_prompt,
                base_url=base_url,
                api_key=api_key,
                model=selected_model,
                temperature=0.5,
                max_tokens=350,
                timeout_s=model_timeout,
            )
        raise ValueError("Unsupported provider configuration.")

    if provider == "none":
        design_mode = "code-only design"
        design = code_only_design(theme.id, intensity)
    else:
        provider_chain = [
            (provider, provider_base_url, provider_api_key, model_name)
        ]
        if provider == "openai_compat" and fallback_provider != "none":
            provider_chain.append((
                fallback_provider,
                fallback_provider_base_url,
                fallback_provider_api_key,
                fallback_model_name,
            ))

        design = None
        failures: list[str] = []
        fake_attempted = False
        for provider_index, (
            selected_provider,
            base_url,
            api_key,
            selected_model,
        ) in enumerate(provider_chain):
            try:
                fake_attempted = fake_attempted or selected_provider == "fake"
                response = request_design(
                    prompt,
                    selected_provider=selected_provider,
                    base_url=base_url,
                    api_key=api_key,
                    selected_model=selected_model,
                )
                candidate = parse_design_response(response, intensity)
                if not candidate.compliant:
                    repaired_response = request_design(
                        prompt
                        + "\nThe previous response was not parseable. Return one valid PLACE line "
                        + "using only the listed catalog and slots. Output only the required labels.",
                        selected_provider=selected_provider,
                        base_url=base_url,
                        api_key=api_key,
                        selected_model=selected_model,
                    )
                    candidate = parse_design_response(repaired_response, intensity)
                if candidate.compliant:
                    design = candidate
                    if provider_index == 0:
                        design_mode = "sample provider" if provider == "fake" else "AI design"
                    else:
                        if selected_provider == "fake":
                            design_mode = "fake provider fallback"
                            warning = (
                                "The primary AI provider failed; the built-in sample provider "
                                "was used."
                            )
                        else:
                            design_mode = "fallback AI design"
                            warning = (
                                "The primary AI provider failed; the configured fallback provider "
                                "was used."
                            )
                    break
                failures.append(f"{selected_provider} returned an unusable design")
            except (FetchError, ValueError) as exc:
                failures.append(f"{selected_provider} failed ({exc})")

        if design is None:
            if provider == "openai_compat" and not fake_attempted:
                try:
                    fake_response = request_design(
                        prompt,
                        selected_provider="fake",
                        base_url="",
                        api_key="",
                        selected_model="",
                    )
                    fake_design = parse_design_response(fake_response, intensity)
                    if fake_design.compliant:
                        design = fake_design
                        design_mode = "fake provider fallback"
                        warning = (
                            "The configured AI providers failed or returned unusable designs; "
                            "the built-in sample provider supplied a design."
                        )
                except (FetchError, ValueError):
                    pass

            if design is None:
                design = code_only_design(theme.id, intensity)
                design_mode = "code-only design"
                if failures:
                    if provider == "openai_compat":
                        warning = (
                            f"Configured AI providers and the sample provider were unavailable "
                            f"or returned unusable designs ({'; '.join(failures)}); showing "
                            f"the built-in {theme.id} design."
                        )
                    elif provider == "fake":
                        warning = (
                            f"Sample design unavailable ({failures[0]}); showing the built-in "
                            f"{theme.id} design."
                        )
                    else:
                        warning = (
                            f"AI design unavailable ({failures[0]}); showing the built-in "
                            f"{theme.id} design instead."
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
