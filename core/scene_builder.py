"""Turn a storyboard into scene HTML using the deterministic scaffold."""
from __future__ import annotations

import json
import logging
from pathlib import Path

from .captions import captions_for_scene
from .layout import compute_layout
from .scaffold import build_scene_html, load_motion_js

log = logging.getLogger("motionforge.scenes")

PALETTE = {
    "bg": "#070B18", "surface": "#111A2E", "surface2": "#16213A",
    "primary": "#22D3EE", "accent": "#FACC15", "danger": "#EF4444",
    "text": "#F8FAFC", "muted": "#94A3B8",
}


def build_scene_specs(storyboard: dict, cfg: dict, width: int, height: int) -> list[dict]:
    layout = compute_layout(width, height, cfg.get("video", {}))
    specs = []
    for scene in storyboard.get("scenes") or []:
        spec = dict(scene)
        duration = float(spec.get("duration") or 4.0)
        spec["captions"] = captions_for_scene(spec.get("narration", ""), duration)
        spec["layout"] = layout
        specs.append(spec)
    return specs


def write_scene_files(specs: list[dict], scenes_dir: Path, motion_js: str | None = None,
                      palette: dict | None = None) -> list[Path]:
    scenes_dir = Path(scenes_dir)
    scenes_dir.mkdir(parents=True, exist_ok=True)
    motion_js = motion_js if motion_js is not None else load_motion_js()
    palette = palette or PALETTE
    paths = []
    total = len(specs)
    for i, spec in enumerate(specs, start=1):
        layout = spec.get("layout") or compute_layout(1080, 1920, {})
        html = build_scene_html(spec, motion_js, layout, palette,
                                tag=spec.get("tag", ""), index=i, total=total)
        path = scenes_dir / f"scene_{i:02d}.html"
        path.write_text(html, encoding="utf-8")
        paths.append(path)
        log.info("Scene %d/%d %s -> %s (%.2fs)", i, total, spec.get("tag"),
                 path.name, spec.get("duration", 0))
    (scenes_dir / "scenes.json").write_text(
        json.dumps([{k: v for k, v in s.items() if k != "layout"} for s in specs],
                   indent=2, ensure_ascii=False), encoding="utf-8")
    return paths


def load_scene_specs(scenes_dir: Path) -> list[dict]:
    path = Path(scenes_dir) / "scenes.json"
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []


def render_scene_again(spec: dict, path: Path, motion_js: str, palette: dict,
                       index: int, total: int) -> Path:
    layout = spec.get("layout") or compute_layout(1080, 1920, {})
    html = build_scene_html(spec, motion_js, layout, palette,
                            tag=spec.get("tag", ""), index=index, total=total)
    Path(path).write_text(html, encoding="utf-8")
    return Path(path)
