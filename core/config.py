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
        "cheap_model": "nvidia/nemotron-3.5-lightning:free",
    },
    "llm": {
        "base_url": "https://openrouter.ai/api/v1",
        "max_retries": 2,
        "timeout_seconds": 240,
        "max_tokens": 6000,
        "temperature": 0.7,
    },
    "budget": {
        "daily_request_limit": 50,
        "max_requests_per_run": 24,
        "max_cost_usd": 0.10,
        "cache_enabled": True,
    },
    "quality": {
        "default": "preview",
        "preview": {"width": 540, "height": 960, "fps": 15},
        "final": {"width": 1080, "height": 1920, "fps": 30},
        "gate": {"min_judge": 7.0, "min_hook": 8.0, "max_rounds": 5, "min_improvement": 0.3},
    },
    "video": {
        "safe_top": 0.08, "safe_bottom": 0.15, "min_occupancy": 0.55,
        "headline_px": 84, "body_px": 52, "min_font_px": 40,
        "max_words_scene": 10, "wps": 2.5, "max_sentence_words": 14,
        "pace_change_seconds": 2.5, "fps": 30, "preview_fps": 15,
    },
    "audio": {
        "tts_enabled": True, "tts_voice": "en-US-GuyNeural", "tts_rate": "+8%",
        "target_lufs": -14, "music_volume": 0.18, "sfx_volume": 0.5, "sfx_enabled": True,
    },
    "judges": {
        "vision_model": "nvidia/nemotron-3.5-super-vl:free",
        "text_model": "nvidia/nemotron-3.5-lightning:free",
        "frames_per_round": 12, "enabled": True,
    },
    "checks": {
        "min_font_ratio": 0.045,
        "min_contrast_large": 3.0,
        "min_contrast_small": 4.5,
        "overlap_threshold": 0.2,
        "blank_stddev": 2.0,
        "blank_max_colors": 8,
        "edge_tolerance_px": 4,
    },
    "loop": {
        "max_iterations": 3,
        "sample_fractions": [0.02, 0.25, 0.5, 0.75, 0.98],
        "vision_review": False,
    },
    "memory": {
        "top_lessons": 8, "max_approved_examples": 2,
        "prune_after_seen": 6, "topic_history_limit": 10,
    },
    "series": {
        "default_ratio": "9:16", "default_duration": 35, "default_quality": "preview",
    },
    "cleanup": {
        "keep_last_n_runs": 3,
        "auto_delete_frames": True,
        "auto_delete_temp_audio": True,
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
    cfg_path = path or (PROJECT_ROOT / "config.yaml")
    data = {}
    if cfg_path.exists():
        data = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    cfg = _merge(DEFAULTS, data)

    for env_path in (PROJECT_ROOT / ".env", PROJECT_ROOT.parent / ".env", Path.cwd() / ".env"):
        if env_path.exists():
            load_dotenv(env_path, override=False)
    cfg["api_key"] = os.environ.get("OPENROUTER_API_KEY", "").strip()
    return cfg


def resolution_for(cfg: dict, ratio: str) -> tuple[int, int]:
    resolutions = {
        "16:9": (1920, 1080),
        "9:16": (1080, 1920),
        "1:1": (1080, 1080),
    }
    if ratio not in resolutions:
        raise ValueError(f"Unsupported ratio {ratio!r}. Choose from {list(resolutions)}")
    return resolutions[ratio]
