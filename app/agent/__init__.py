from __future__ import annotations

import re
from dataclasses import dataclass

from app.harness import HarnessEdit
from app.parser import parse_design_response


@dataclass(frozen=True)
class AgentPlan:
    edits: tuple[HarnessEdit, ...]
    done: bool
    note: str


TOOL_HELP = """Agent tools (output plain labelled lines only):
THEME: <theme-id> (optional; keep the assigned theme unless asked to change it)
ACCENT: #rrggbb (optional)
PLACE: <decoration> @ <slot> (one per line; replaces all placements)
CSS: (optional block after a line containing only "CSS:")
RESET: yes (optional; restore theme defaults before other edits)
NOTE: <one short line for the user> (optional)
DONE: yes (when the page matches the request and needs no more edits)"""


def parse_agent_response(text: str, tier: str) -> AgentPlan:
    """Parse one agent turn into validated harness edits."""
    if not isinstance(text, str):
        return AgentPlan((), False, "")
    design = parse_design_response(text, tier)
    edits: list[HarnessEdit] = []
    reset = bool(re.search(r"^\s*RESET:\s*yes\s*$", text, re.I | re.M))
    if reset:
        edits.append(HarnessEdit(kind="reset"))
    if design.theme:
        edits.append(HarnessEdit(kind="theme", theme_id=design.theme))
    if design.accent:
        edits.append(HarnessEdit(kind="accent", accent=design.accent))
    if design.placements:
        edits.append(HarnessEdit(kind="placements", placements=design.placements))
    if design.css.strip():
        edits.append(HarnessEdit(kind="css", css=design.css))
    done = bool(re.search(r"^\s*DONE:\s*yes\s*$", text, re.I | re.M))
    notes = re.findall(r"^\s*NOTE:\s*(.*?)\s*$", text, re.I | re.M)
    note = notes[-1][:280] if notes else ""
    return AgentPlan(tuple(edits), done, note)
