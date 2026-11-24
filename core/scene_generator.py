"""Scene generator: plan scene -> one self-contained deterministic HTML file.

Injects the MF helper library, learned lessons, and approved few-shot examples.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from .llm import LLMClient, LLMError

log = logging.getLogger("motionforge.generator")

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"

GENERATOR_SYSTEM = """You are the scene generator of MotionForge, a senior motion designer who writes
code-animated HTML scenes rendered frame-by-frame by a headless browser.

You output ONE complete, self-contained HTML document (starting with <!DOCTYPE html>) and nothing else.

HARD CONTRACT (violations break the renderer):
1. Define window.SCENE_DURATION = <exact seconds given in the task>.
2. Define window.setTime(t) (t in seconds, 0..SCENE_DURATION) that sets the EXACT visual state
   for that moment. Pure function of t: NO setTimeout/setInterval/requestAnimationFrame,
   NO CSS animations or transitions. It must work when called with times in any order.
3. Call setTime(0) at the end of the script.
4. ZERO network requests: no external fonts, images, scripts or styles. Inline CSS, inline SVG only.
5. A helper library is already injected and available as window.MF (do not redefine it):
   MF.seg(t,start,dur,ease?) -> eased 0..1 progress
   MF.reveal(el,t,start,dur,{dx,dy,scale,ease}?)  fade+slide/scale in
   MF.fade(el,t,start,dur,from?,to?)
   MF.pop(el,t,start,dur)  overshoot scale-in
   MF.stagger(els,t,start,each,dur,opts?)
   MF.counter(el,t,start,dur,from,to,{decimals,prefix,suffix}?)
   MF.bars(els,t,start,each,dur)  grow bars (set transform-origin:bottom in CSS)
   MF.drawPath(svgPathEl,t,start,dur)  progressive stroke draw
   MF.exit(el,t,start,dur,{dy}?)
   MF.envelope(t,duration,fadeIn?,fadeOut?) -> 0..1; apply to root #stage opacity for transitions
   Easings: outCubic, inOutCubic, outQuint, outExpo, outBack, inOutSine. NEVER linear.

DESIGN QUALITY BAR:
- Use the given palette and fonts exactly; consistent with the whole video.
- Size everything with vmin/vw/vh units so it works at any aspect ratio. Body: margin 0, overflow hidden.
- Root #stage fills the viewport (100% width/height), flex-centered, padding >= 7vmin (safe margins).
- Large readable text: headlines ~7vmin, body >= 3.4vmin, nothing below 2.6vmin. Max 2 font families.
- Generous spacing (gap >= 3vmin), one idea per scene, max ~12 words of text.
- Staggered reveals with smooth easing; elements settle by 60% of the scene and hold.
- Keep ALL visible elements fully inside the viewport at all times once revealed;
  slide-in distances small (<= 6vmin). No overlapping text blocks.
- Strong contrast: text vs background WCAG >= 4.5. Muted text only for secondary captions.
- Charts: few elements, thick strokes, rounded corners, value labels, inline SVG or divs.
- Icons: simple inline SVG strokes (stroke-width >= 6 at viewBox 100) or geometric CSS shapes.
- Apply MF.envelope to #stage opacity so scenes fade in/out cleanly."""

FIX_SYSTEM = GENERATOR_SYSTEM + """

You are now FIXING an existing scene. You receive the current HTML and a list of detected problems
(from DOM measurements and a vision reviewer). Return the COMPLETE fixed HTML document.
Keep the same idea, palette, SCENE_DURATION and the setTime contract. Fix every listed problem.
Do not introduce new text or clutter while fixing."""


def _strip_external(html: str) -> str:
    """Remove anything that would trigger a network request."""
    html = re.sub(r"<script[^>]*\bsrc\s*=[^>]*>\s*</script>", "", html, flags=re.I)
    html = re.sub(r"<link[^>]*\bhref\s*=\s*[\"']https?:[^>]*>", "", html, flags=re.I)
    html = re.sub(r"@import\s+url\([^)]*\)\s*;?", "", html, flags=re.I)
    html = re.sub(r"url\(\s*[\"']?https?:[^)]*\)", "none", html, flags=re.I)
    html = re.sub(r"\b(?:src|href)\s*=\s*[\"']https?:[^\"']*[\"']", "", html, flags=re.I)
    return html


def postprocess_html(raw: str, scene: dict, motion_js: str) -> str:
    """Extract HTML from the reply, sanitize it, inject helpers + duration."""
    text = raw.strip()
    fence = re.search(r"```(?:html)?\s*(.*?)```", text, re.DOTALL)
    if fence and "<" in fence.group(1):
        text = fence.group(1).strip()
    start = text.lower().find("<!doctype")
    if start == -1:
        start = text.lower().find("<html")
    if start > 0:
        text = text[start:]
    if "<html" not in text.lower():
        # Model returned a fragment; wrap it.
        text = ("<!DOCTYPE html><html><head><meta charset='utf-8'></head><body>"
                + text + "</body></html>")
    text = _strip_external(text)

    injection = ("<script>\n" + motion_js + "\n</script>\n<script>window.SCENE_DURATION = "
                 + json.dumps(float(scene["duration"])) + ";</script>\n")
    m = re.search(r"<head[^>]*>", text, flags=re.I)
    if m:
        text = text[:m.end()] + "\n" + injection + text[m.end():]
    else:
        m = re.search(r"<html[^>]*>", text, flags=re.I)
        idx = m.end() if m else 0
        text = text[:idx] + "<head>" + injection + "</head>" + text[idx:]
    return text


def _scene_task(scene: dict, plan: dict) -> str:
    return (
        f"Video: {plan.get('title', '')} | ratio {plan['ratio']} | total {plan['duration']}s\n"
        f"Palette: {json.dumps(plan['palette'])}\n"
        f"Fonts: display='{plan['fonts']['display']}', mono='{plan['fonts']['mono']}' "
        f"(system font stacks only, e.g. \"{plan['fonts']['display']}\", Arial, sans-serif)\n"
        f"Scene {scene['id']} '{scene['name']}': duration EXACTLY {scene['duration']} seconds.\n"
        f"Goal: {scene['goal']}\n"
        f"Headline text: {scene['headline']!r}\n"
        f"Sub text: {scene['sub']!r}\n"
        f"Visual type: {scene['visual']}\n"
        f"Data: {json.dumps(scene.get('data') or {})}\n"
        "Write the complete HTML scene now. Remember: window.setTime(t), deterministic, offline, "
        "vmin-based sizing, safe margins, staggered eased reveals, MF.envelope on #stage."
    )


def _examples_block(examples: list[dict]) -> str:
    if not examples:
        return ""
    parts = ["Approved reference scenes (match this quality and structure):"]
    for ex in examples[:2]:
        html = ex["html"]
        if len(html) > 7000:
            html = html[:7000] + "\n<!-- truncated -->"
        parts.append(f"--- example '{ex['name']}' ---\n{html}")
    return "\n".join(parts)


class SceneGenerator:
    def __init__(self, llm: LLMClient, motion_js: str | None = None):
        self.llm = llm
        self.model = llm.cfg["models"]["generator_model"]
        self.motion_js = motion_js or (TEMPLATES_DIR / "motion.js").read_text(encoding="utf-8")

    def generate(self, scene: dict, plan: dict, lessons: list[dict],
                 examples: list[dict], rules_block: str = "") -> str:
        system = GENERATOR_SYSTEM
        if rules_block:
            system += "\n\n" + rules_block
        user = _scene_task(scene, plan)
        ex = _examples_block(examples)
        if ex:
            user = ex + "\n\n" + user
        raw = self.llm.chat(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            self.model, label=f"generate_scene_{scene['id']}", temperature=0.7,
        )
        html = postprocess_html(raw, scene, self.motion_js)
        if "setTime" not in html:
            log.warning("Scene %s: model omitted setTime; requesting repair", scene["id"])
            raw = self.llm.chat(
                [{"role": "system", "content": system},
                 {"role": "user", "content": user},
                 {"role": "assistant", "content": raw[:12000]},
                 {"role": "user", "content": "The HTML is missing window.setTime(t). Return the complete "
                  "fixed HTML with the deterministic setTime contract."}],
                self.model, label=f"generate_scene_{scene['id']}_repair", temperature=0.3,
            )
            html = postprocess_html(raw, scene, self.motion_js)
        return html

    def fix(self, html: str, problems: list, scene: dict, plan: dict) -> str:
        problem_lines = "\n".join(f"- [{p.code}] {p.message}" for p in problems)
        extra = ""
        if any(p.code == "missing_settime" for p in problems):
            extra = ("\nCRITICAL: window.setTime must be assigned at the TOP LEVEL of a classic "
                     "<script> (window.setTime = function(t){...}), NOT inside DOMContentLoaded, "
                     "NOT in a module script. Also set window.SCENE_DURATION.")
        user = (
            _scene_task(scene, plan)
            + "\n\nCURRENT HTML:\n" + html[:24000]
            + "\n\nDETECTED PROBLEMS (fix all of them):\n" + problem_lines + extra
            + "\n\nReturn the complete fixed HTML document only."
        )
        raw = self.llm.chat(
            [{"role": "system", "content": FIX_SYSTEM}, {"role": "user", "content": user}],
            self.model, label=f"fix_scene_{scene['id']}", temperature=0.4,
        )
        return postprocess_html(raw, scene, self.motion_js)
