"""Configuration loading for MotionForge."""
from __future__ import annotations

import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent

DEFAULTS = {
    "models": {
        "generator_model": "anthropic/claude-sonnet-5.5",
        "reviewer_model": "nvidia/nemotron-3.5-super-vl:free",
        "fallback_model": "qwen/qwen4-max",
        "free_model": "nvidia/nemotron-3.5-lightning:free",
    },
    "llm": {
        "base_url": "https://openrouter.ai/api/v1",
        "max_retries": 3,
        "timeout_seconds": 300,
        "max_tokens": 8000,
        "temperature": 0.7,
    },
    "render": {
        "fps": 30,
        "preview_fps": 15,
        "resolutions": {"16:9": [1920, 1080], "9:16": [1080, 1920], "1:1": [1080, 1080]},
    },
    "loop": {
        "max_iterations": 4,
        "sample_fractions": [0.02, 0.25, 0.5, 0.75, 0.98],
        "vision_review": True,
    },
    "checks": {
        "min_font_ratio": 0.022,
        "min_contrast_large": 3.0,
        "min_contrast_small": 4.5,
        "overlap_threshold": 0.2,
        "blank_stddev": 2.0,
        "blank_max_colors": 8,
        "edge_tolerance_px": 4,
    },
    "memory": {
        "top_lessons": 8,
        "max_approved_examples": 2,
        "prune_after_seen": 6,
    },
}


def _merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config(path: Path | None = None) -> dict:
    """Load config.yaml merged over defaults, and .env files for the API key."""
    cfg_path = path or (PROJECT_ROOT / "config.yaml")
    data = {}
    if cfg_path.exists():
        data = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    cfg = _merge(DEFAULTS, data)

    # Look for .env in the project dir, its parent, and the cwd.
    for env_path in (PROJECT_ROOT / ".env", PROJECT_ROOT.parent / ".env", Path.cwd() / ".env"):
        if env_path.exists():
            load_dotenv(env_path, override=False)
    cfg["api_key"] = os.environ.get("OPENROUTER_API_KEY", "").strip()
    return cfg


def resolution_for(cfg: dict, ratio: str) -> tuple[int, int]:
    resolutions = cfg["render"]["resolutions"]
    if ratio not in resolutions:
        raise ValueError(f"Unsupported ratio {ratio!r}. Choose from {list(resolutions)}")
    w, h = resolutions[ratio]
    return int(w), int(h)
