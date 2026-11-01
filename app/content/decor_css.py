"""Static CSS for decorations: slot layout, colors, animations, overlays.

This is our own CSS, so it is not passed through the model-CSS sanitizer.
Rules:
- Every `animation` / `@keyframes` lives inside the no-preference media block.
  Under `prefers-reduced-motion: reduce` nothing moves (and floaters are hidden).
- Keep the page-reset layer written with :where(...) so these class rules always win.
"""
from __future__ import annotations

from .tiers import TIERS

BASE_CSS = """
.hw-root{position:fixed;inset:0;z-index:10;overflow:hidden;pointer-events:none}
.hw-deco{position:absolute;width:var(--hw-size,72px);color:var(--hw-accent,currentColor);
  pointer-events:none;line-height:0}
.hw-deco svg{display:block;width:100%;height:auto}
.hw-inner{display:block}

/* overlay slots (children of .hw-root) */
.hw-slot-top-left{top:var(--hw-stack-offset,0);left:0}
.hw-slot-top-right{top:var(--hw-stack-offset,0);right:0}
.hw-slot-margin-left{left:6px;top:calc(18vh + var(--hw-n,0) * 22vh)}
.hw-slot-margin-right{right:6px;top:calc(18vh + var(--hw-n,0) * 22vh)}
.hw-slot-float{top:var(--hw-y,20vh);left:0;opacity:.85}

/* inline slots (own blocks between existing elements) */
.hw-inline{display:block;margin:1.25rem 0;text-align:center;line-height:0;pointer-events:none}
.hw-inline-header{text-align:right}
.hw-inline .hw-deco{position:relative;display:inline-block}

/* colors: shapes take the theme accent; "cut-outs" take the page background */
.hw-cut{fill:var(--hw-bg,#111)}
.hw-cut-stroke{stroke:var(--hw-bg,#111)}
.hw-light{fill:#ffd45e}
.hw-pumpkin{color:var(--hw-pumpkin,#e8731a)}
.hw-moon{filter:drop-shadow(0 0 8px currentColor)}

/* a corner web is a full web pushed so only one quadrant shows */
.hw-cobweb{opacity:.55}
.hw-cobweb svg{stroke-width:2}
.hw-slot-top-left.hw-cobweb .hw-inner{transform:translate(-50%,-50%)}
.hw-slot-top-right.hw-cobweb .hw-inner{transform:translate(50%,-50%)}
.hw-inline .hw-cobweb .hw-inner{transform:none}

/* spiders hang from the top edge, slightly in from the corner */
.hw-slot-top-left.hw-spider{left:24px}
.hw-slot-top-right.hw-spider{right:24px}

/* never cover content on narrow screens */
@media (max-width:900px){
  .hw-slot-margin-left,.hw-slot-margin-right{display:none}
}
@media (prefers-reduced-motion:reduce){
  .hw-slot-float{display:none}
}
"""

MOTION_CSS = """
@media (prefers-reduced-motion:no-preference){
  /* bat: wings fold about the shoulders */
  .hw-on-flap .hw-wing{transform-box:fill-box}
  .hw-on-flap .hw-wing-l{transform-origin:100% 50%;animation:hw-flap-l .45s ease-in-out infinite alternate}
  .hw-on-flap .hw-wing-r{transform-origin:0 50%;animation:hw-flap-r .45s ease-in-out infinite alternate}

  /* ghost, and anything floating, bobs gently */
  .hw-on-bob .hw-inner,.hw-float .hw-inner{animation:hw-bob 3.6s ease-in-out infinite alternate}

  /* spider swings from its thread */
  .hw-on-sway .hw-inner{transform-origin:50% 0;animation:hw-sway 3.2s ease-in-out infinite alternate}

  /* pumpkin glows and its face brightens */
  .hw-on-glow .hw-inner{animation:hw-glow 3s ease-in-out infinite alternate}
  .hw-on-glow .hw-light{animation:hw-light 3s ease-in-out infinite alternate}

  /* candle flame flickers (two flames, out of step) */
  .hw-on-flicker .hw-flame{transform-box:fill-box;transform-origin:50% 100%;animation:hw-flicker 1.7s ease-in-out infinite}
  .hw-on-flicker .hw-flame-in{animation-duration:1.2s;animation-delay:-.4s}

  /* floaters cross the viewport; --hw-y, --hw-dur, --hw-delay are set per item */
  .hw-float{animation:hw-drift var(--hw-dur,26s) linear var(--hw-delay,0s) infinite}
  .hw-float-rev{animation-name:hw-drift-rev}

  @keyframes hw-flap-l{from{transform:rotate(16deg)}to{transform:rotate(-12deg)}}
  @keyframes hw-flap-r{from{transform:rotate(-16deg)}to{transform:rotate(12deg)}}
  @keyframes hw-bob{from{transform:translateY(0) rotate(-1.5deg)}to{transform:translateY(-8px) rotate(1.5deg)}}
  @keyframes hw-sway{from{transform:rotate(-8deg)}to{transform:rotate(8deg)}}
  @keyframes hw-glow{from{filter:drop-shadow(0 0 2px currentColor)}to{filter:drop-shadow(0 0 12px currentColor)}}
  @keyframes hw-light{from{opacity:.7}to{opacity:1}}
  @keyframes hw-flicker{
    0%,100%{transform:scale(1,1);opacity:1}
    18%{transform:scale(.93,1.07);opacity:.9}
    37%{transform:scale(1.05,.95);opacity:1}
    56%{transform:scale(.95,1.08);opacity:.85}
    78%{transform:scale(1.03,.97);opacity:.95}
  }
  @keyframes hw-drift{from{transform:translateX(-25vw)}to{transform:translateX(125vw)}}
  @keyframes hw-drift-rev{from{transform:translateX(125vw)}to{transform:translateX(-25vw)}}
  @keyframes hw-fog{from{opacity:.10}to{opacity:.22}}
  .hw-fog{animation:hw-fog 9s ease-in-out infinite alternate}
}
"""

# High tier only. Kept faint and at the edges so body text stays readable.
OVERLAY_CSS = """
.hw-fog{position:absolute;left:0;right:0;bottom:0;height:30vh;opacity:.16;
  background:linear-gradient(to top,var(--hw-fog,rgba(220,225,235,.9)),transparent)}
.hw-vignette{position:absolute;inset:0;
  background:radial-gradient(ellipse at center,transparent 62%,rgba(0,0,0,.35) 100%)}
"""


def decoration_css(tier: str) -> str:
    settings = TIERS[tier]
    parts = [BASE_CSS]
    if settings["overlays"]:
        parts.append(OVERLAY_CSS)
    if settings["animations"] > 0:
        parts.append(MOTION_CSS)
    return "\n".join(part.strip() for part in parts) + "\n"
