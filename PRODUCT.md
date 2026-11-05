# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Concept evaluators: stakeholders judging whether a website that redesigns itself for
each season is worth pursuing. They click seasonal toggles, inspect the resulting
redesigns, and assess the concept's viability.

## Product Purpose

Demonstrate that a website can automatically redesign itself for each season or
occasion. The demo proves the loop — occasion selected, agent redesigns the site within
guardrails, validated result goes live — as a stepping stone to a production system.
Success means an evaluator grasps the concept and its production path within minutes.

## Positioning

Seasonal redesigns produced by an AI agent with creative freedom, applied automatically
when a calendar occasion arrives — not hand-built per-season themes switched by hand.

## Operating Context

Evaluators run the app locally (`python run.py`), open the page, and use toggle buttons
that stand in for the production calendar. Each toggle sends the season plus the site's
current HTML, CSS, and JavaScript to the agent; validated files replace the live version,
with history stepping and reset to the preserved original.

## Capabilities and Constraints

- Preset seasons plus free-text occasions; one season active at a time; last five
  versions kept; reset to the preserved original.
- Agent output must keep the navigation, all four sections (Home, Menu, About, Contact),
  and a working contact form; placeholder-only content (no real addresses, prices, or
  claims); WCAG AA contrast; phone-usable.
- The agent may only write the three site files; invalid output keeps the previous
  version with an error.
- Undecided: production calendar-integration design, multi-user persistence, hosting model.

## Brand Commitments

None. Sample Café is fictional and all copy stays clearly placeholder; no real brand,
voice, or assets exist.

## Evidence on Hand

Working demo in this repo (`python run.py` → http://127.0.0.1:5000); automated suite
(`python -m pytest -q`). No testimonials, customers, benchmarks, or press — future work
must not fabricate any.

## Product Principles

1. The occasion triggers the redesign; human clicks are only the demo's stand-in for the calendar.
2. Agent creativity is bounded by guardrails: structure, function, and placeholder honesty survive every season.
3. Every state stays explainable: banner, history, and reset keep the demo legible.
4. Prove the production path, not just the effect: validation and fallbacks are part of the demo.

## Accessibility & Inclusion

WCAG AA minimum text contrast, established in the agent brief and verified for the
built-in seasonal palettes.
