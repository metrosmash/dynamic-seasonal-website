from __future__ import annotations


def complete(prompt: str, *, temperature: float, max_tokens: int, timeout_s: float) -> str:
    del prompt, temperature, max_tokens, timeout_s
    return """THEME: pumpkin-patch
ACCENT: #ff7a1a
PLACE: moon @ top-right"""
