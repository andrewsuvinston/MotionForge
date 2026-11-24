"""Vision reviewer: sends sample frames to the reviewer model, gets structured problems."""
from __future__ import annotations

import base64
import io
import logging
from pathlib import Path

from PIL import Image

from .checks import Problem
from .llm import LLMClient, LLMError

log = logging.getLogger("motionforge.reviewer")

REVIEW_SYSTEM = """You are a meticulous motion-graphics QA reviewer for MotionForge.
You receive rendered frames from animated explainer scenes (each labeled with its scene id and
the fraction of the scene duration). Judge them like a senior design director.

Look for: clutter, bad alignment, ugly spacing, unreadable or tiny text, low contrast,
elements cut off at edges, overlapping elements, inconsistent style, empty/blank frames.

Return ONLY JSON: {"problems": [{"scene": <scene id number>, "issue": "what is wrong",
"severity": "high" | "medium" | "low", "fix": "concrete one-sentence fix"}]}

Rules:
- Only report REAL problems a viewer would notice. Do not invent issues.
- Use "low" for nitpicks; high/medium only for things that hurt clarity or looks.
- Frames mid-animation may show partially revealed elements; that is intentional, not a bug.
- If everything looks clean and professional, return {"problems": []}."""


def _image_data_url(path: Path, max_side: int = 768) -> str:
    with Image.open(path) as im:
        im = im.convert("RGB")
        im.thumbnail((max_side, max_side))
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=80)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def review_scenes(llm: LLMClient, scene_frames: list[tuple[dict, list[dict]]],
                  model: str) -> list[Problem]:
    """scene_frames: [(scene, [{fraction, path}, ...]), ...]. Returns vision Problems."""
    content: list[dict] = [{"type": "text", "text":
                            "Review these frames. Scene ids and time fractions are labeled above each image."}]
    n_images = 0
    for scene, frames in scene_frames:
        picked = [f for f in frames if f["fraction"] in (0.5, 0.75)] or frames[-1:]
        for fr in picked[:2]:
            if n_images >= 10:
                break
            content.append({"type": "text", "text":
                            f"Scene {scene['id']} ('{scene['name']}') at {fr['fraction']:.0%} of "
                            f"{scene['duration']}s. Headline should read: {scene['headline']!r}"})
            content.append({"type": "image_url", "image_url": {"url": _image_data_url(Path(fr["path"]))}})
            n_images += 1
    if n_images == 0:
        return []
    try:
        data = llm.chat_json(
            [{"role": "system", "content": REVIEW_SYSTEM}, {"role": "user", "content": content}],
            model, label="vision_review", max_tokens=2000, temperature=0.2,
        )
    except (LLMError, ValueError) as exc:
        log.warning("Vision review failed (%s); continuing with automatic checks only", exc)
        return []
    problems = []
    for item in (data.get("problems") or []) if isinstance(data, dict) else []:
        if not isinstance(item, dict):
            continue
        sev = str(item.get("severity", "medium")).lower()
        if sev == "low":
            continue
        try:
            scene_id = int(item.get("scene", 0))
        except (TypeError, ValueError):
            scene_id = 0
        problems.append(Problem(
            code="vision",
            message=f"{item.get('issue', 'visual problem')} — fix: {item.get('fix', 'improve layout')}",
            severity="error" if sev == "high" else "warning",
            scene=scene_id,
        ))
    log.info("Vision review: %d actionable problems", len(problems))
    return problems
