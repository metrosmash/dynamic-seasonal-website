"""Turns a list of (decoration, slot) choices into planned placements and HTML.

Flow: parse the model text -> plan_placements() (validate, apply the tier budget,
decide which items animate) -> render_decoration() for each -> render_root().
The assembler inserts the results; nothing here touches the original page.
"""
from __future__ import annotations

from dataclasses import dataclass

from .decor_catalog import DECORATIONS, is_valid_placement, load_decoration_svg, split_slot
from .tiers import TIERS

OVERLAY_SLOTS = {"top-left", "top-right", "margin-left", "margin-right", "float"}
MAX_FLOATERS = 3
FLOAT_LANES_VH = (14, 38, 62, 26, 50, 74)


@dataclass(frozen=True)
class Planned:
    name: str
    slot: str            # normalised, e.g. "before-h2:2"
    base: str            # slot without index, e.g. "before-h2"
    index: int | None    # N for before-h2:N
    animated: bool       # gets its own motion (floaters always do)
    slot_index: int      # 0, 1, 2... within the same slot (stacks margin items)
    float_index: int     # lane number for floaters, else 0
    stack_offset_px: int  # vertical offset for decorations sharing a top corner

    @property
    def overlay(self) -> bool:
        return self.base in OVERLAY_SLOTS


def plan_placements(
    placements: list[tuple[str, str]],
    tier: str,
    h2_count: int | None = None,
) -> tuple[list[Planned], list[str]]:
    """Validate and budget the placements. Model order wins; extras are dropped."""
    settings = TIERS[tier]
    planned: list[Planned] = []
    warnings: list[str] = []
    seen: set[tuple[str, str]] = set()
    slot_counts: dict[str, int] = {}
    corner_offsets: dict[str, int] = {}
    animated_used = 0
    floaters = 0

    for name, slot in placements:
        name = name.strip().lower()
        base, index = split_slot(slot)
        if base == "before-h2" and index is None:
            index = 1
        norm = f"{base}:{index}" if base == "before-h2" else base

        if not is_valid_placement(name, norm, tier):
            warnings.append(f"dropped {name!r} @ {slot!r}: not allowed at tier {tier}")
            continue
        if base == "before-h2" and h2_count is not None and index > h2_count:
            warnings.append(f"dropped {name!r} @ {norm}: page has {h2_count} h2")
            continue
        if (name, norm) in seen:
            continue
        if len(planned) >= settings["max_decorations"]:
            warnings.append(f"dropped {name!r} @ {norm}: over the {settings['max_decorations']} budget")
            continue
        if base == "float":
            if floaters >= MAX_FLOATERS:
                warnings.append(f"dropped {name!r} @ float: over the {MAX_FLOATERS} floater limit")
                continue
            float_index, floaters = floaters, floaters + 1
        else:
            float_index = 0

        has_motion = bool(DECORATIONS[name]["animation"])
        if base == "float":
            animated = has_motion          # floaters do not use the animation budget
        elif has_motion and animated_used < settings["animations"]:
            animated, animated_used = True, animated_used + 1
        else:
            animated = False

        seen.add((name, norm))
        slot_index = slot_counts.get(base, 0)
        slot_counts[base] = slot_index + 1
        stack_offset_px = corner_offsets.get(base, 0) if base in {"top-left", "top-right"} else 0
        if base in {"top-left", "top-right"}:
            corner_offsets[base] = stack_offset_px + DECORATIONS[name]["size"] + 8
        planned.append(
            Planned(name, norm, base, index, animated, slot_index, float_index, stack_offset_px)
        )

    return planned, warnings


def render_decoration(p: Planned) -> str:
    entry = DECORATIONS[p.name]
    classes = ["hw-deco", f"hw-{p.name}", f"hw-slot-{p.base}"]
    style = [f"--hw-size:{entry['size']}px", f"--hw-n:{p.slot_index}"]
    if p.base in {"top-left", "top-right"}:
        style.append(f"--hw-stack-offset:{p.stack_offset_px}px")

    if p.animated:
        classes.append("hw-on-" + entry["animation"].removeprefix("hw-"))
    if p.base == "float":
        k = p.float_index
        classes.append("hw-float")
        if k % 2:
            classes.append("hw-float-rev")
        style += [
            f"--hw-y:{FLOAT_LANES_VH[k % len(FLOAT_LANES_VH)]}vh",
            f"--hw-dur:{22 + 5 * k}s",
            f"--hw-delay:-{7 * k}s",   # negative: already mid-flight on load
        ]

    deco = (
        f'<div class="{" ".join(classes)}" data-hw-added="decoration" '
        f'data-hw-slot="{p.slot}" style="{";".join(style)}">'
        f'<div class="hw-inner" data-hw-added>{load_decoration_svg(p.name)}</div></div>'
    )
    if p.overlay:
        return deco
    return f'<div class="hw-inline hw-inline-{p.base}" data-hw-added aria-hidden="true">{deco}</div>'


def render_overlays(tier: str) -> str:
    if not TIERS[tier]["overlays"]:
        return ""
    return '<div class="hw-fog" data-hw-added></div><div class="hw-vignette" data-hw-added></div>'


def render_root(planned: list[Planned], tier: str) -> str:
    """The fixed container holding every overlay-slot decoration (and the high-tier overlays)."""
    inner = render_overlays(tier) + "".join(render_decoration(p) for p in planned if p.overlay)
    return f'<div class="hw-root" aria-hidden="true" data-hw-added>{inner}</div>' if inner else ""
