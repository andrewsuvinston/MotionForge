"""Planner: text prompt -> validated scene plan JSON."""
from __future__ import annotations

import logging
import re

from .llm import LLMClient, LLMError

log = logging.getLogger("motionforge.planner")

PLANNER_SYSTEM = """You are the planning module of MotionForge, a motion-graphics video agent.
Convert the user's request into a JSON scene plan for a code-animated explainer video.

Return ONLY a JSON object with this exact schema:
{
  "title": "short video title",
  "ratio": "16:9" | "9:16" | "1:1",
  "duration": <total seconds, number>,
  "palette": {"bg": "#hex", "surface": "#hex", "primary": "#hex", "accent": "#hex",
              "text": "#hex", "muted": "#hex"},
  "fonts": {"display": "Segoe UI", "mono": "Consolas"},
  "scenes": [
    {"id": 1, "name": "hook", "duration": <seconds>,
     "goal": "one sentence: the single idea of this scene",
     "headline": "max 8 words", "sub": "max 6 words or empty string",
     "visual": "title|bits|bars|line|counter|icons|arrows|steps|outro",
     "data": {"labels": [...], "values": [...]}   // only for bars/line/counter, small numbers
    }
  ]
}

Rules:
- 3 to 6 scenes. Scene durations MUST sum exactly to the requested total duration.
- Each scene: ONE idea, at most ~12 words of on-screen text total (headline + sub).
- First scene hooks the viewer, last scene is a takeaway/outro.
- Choose a modern dark or light palette with strong contrast (text vs bg WCAG >= 7).
- Fonts must be system fonts only (Segoe UI, Arial, Consolas, Georgia, Verdana, Trebuchet MS).
- Prefer concrete visuals: real numbers, small charts, step diagrams, inline-SVG icons.
- Keep chart data tiny (3-6 bars/points) and values simple.
- No prose outside the JSON."""


def _words(s: str) -> int:
    return len(re.findall(r"\S+", s or ""))


def validate_plan(plan: dict, ratio: str, duration: float) -> dict:
    """Normalize/repair a plan so the rest of the pipeline can trust it."""
    if not isinstance(plan, dict) or not isinstance(plan.get("scenes"), list) or not plan["scenes"]:
        raise ValueError("plan has no scenes")
    plan["ratio"] = ratio
    plan["duration"] = float(duration)
    plan.setdefault("title", "MotionForge video")
    pal = plan.get("palette") or {}
    defaults = {"bg": "#0B1220", "surface": "#16213A", "primary": "#22D3EE",
                "accent": "#F59E0B", "text": "#F8FAFC", "muted": "#94A3B8"}
    for k, v in defaults.items():
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", str(pal.get(k, ""))):
            pal[k] = v
    plan["palette"] = pal
    fonts = plan.get("fonts") or {}
    plan["fonts"] = {"display": fonts.get("display") or "Segoe UI",
                     "mono": fonts.get("mono") or "Consolas"}

    scenes = []
    for i, sc in enumerate(plan["scenes"][:6], start=1):
        if not isinstance(sc, dict):
            continue
        sc = dict(sc)
        sc["id"] = i
        sc["name"] = str(sc.get("name") or f"scene_{i}")[:40]
        sc["goal"] = str(sc.get("goal") or "")[:300]
        sc["headline"] = str(sc.get("headline") or "").strip()[:90]
        sc["sub"] = str(sc.get("sub") or "").strip()[:70]
        # Trim to ~12 words total.
        while _words(sc["headline"]) + _words(sc["sub"]) > 12 and sc["sub"]:
            sc["sub"] = " ".join(sc["sub"].split()[:-1])
        while _words(sc["headline"]) > 12:
            sc["headline"] = " ".join(sc["headline"].split()[:-1])
        if sc.get("visual") not in {"title", "bits", "bars", "line", "counter", "icons", "arrows", "steps", "outro"}:
            sc["visual"] = "title"
        try:
            sc["duration"] = max(1.5, float(sc.get("duration", 4)))
        except (TypeError, ValueError):
            sc["duration"] = 4.0
        scenes.append(sc)
    if not scenes:
        raise ValueError("no usable scenes in plan")

    # Rescale durations so they sum exactly to the requested total.
    total = sum(s["duration"] for s in scenes)
    scale = duration / total
    acc = 0.0
    for i, sc in enumerate(scenes):
        if i == len(scenes) - 1:
            sc["duration"] = round(duration - acc, 3)
        else:
            sc["duration"] = round(sc["duration"] * scale, 3)
            acc += sc["duration"]
    plan["scenes"] = scenes
    return plan


def offline_plan(prompt: str, ratio: str, duration: float) -> dict:
    """Deterministic fallback plan when no LLM is available."""
    topic = re.sub(r"\b(\d+\s*(second|sec|s|minute)s?)\b", "", prompt, flags=re.I)
    topic = re.sub(r"\b(9:16|16:9|1:1|vertical|video|explainer|on|about|how|the|a|an)\b", "", topic, flags=re.I)
    topic = " ".join(topic.split())[:40].strip(" ,.") or "the topic"
    n = 4 if duration >= 16 else 3
    per = duration / n
    scenes = [
        {"id": 1, "name": "hook", "duration": per, "goal": f"Introduce {topic}",
         "headline": topic.title()[:60], "sub": "Let's break it down", "visual": "title"},
        {"id": 2, "name": "idea", "duration": per, "goal": "Show the core mechanism",
         "headline": "The core idea", "sub": "Step by step", "visual": "steps"},
        {"id": 3, "name": "numbers", "duration": per, "goal": "Make it concrete with numbers",
         "headline": "See it in numbers", "sub": "", "visual": "bars",
         "data": {"labels": ["1", "2", "4", "8"], "values": [1, 2, 4, 8]}},
        {"id": 4, "name": "outro", "duration": per, "goal": "Takeaway",
         "headline": "Now you know", "sub": topic.title()[:40], "visual": "outro"},
    ][:n]
    return validate_plan({"title": topic.title(), "scenes": scenes}, ratio, duration)


def make_plan(llm: LLMClient, prompt: str, ratio: str, duration: float) -> dict:
    user = (f"Create a scene plan.\nRequest: {prompt}\n"
            f"Aspect ratio: {ratio}\nTotal duration: exactly {duration} seconds.")
    try:
        plan = llm.chat_json(
            [{"role": "system", "content": PLANNER_SYSTEM}, {"role": "user", "content": user}],
            llm.cfg["models"]["generator_model"], label="plan", temperature=0.6,
        )
        plan = validate_plan(plan, ratio, duration)
        log.info("Plan: %d scenes, %.1fs total", len(plan["scenes"]), duration)
        return plan
    except (LLMError, ValueError) as exc:
        log.warning("LLM planning failed (%s); using deterministic offline plan", exc)
        return offline_plan(prompt, ratio, duration)
