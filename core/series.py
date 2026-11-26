"""Series, batch and resume helpers: repeatable Shorts production runs."""
from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path

from .config import PROJECT_ROOT
from .pipeline import create_video

log = logging.getLogger("motionforge.series")

STATE = PROJECT_ROOT / "memory" / "series.json"


def _load_state() -> dict:
    if STATE.exists():
        try:
            data = json.loads(STATE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except (json.JSONDecodeError, OSError):
            pass
    return {"series": {}}


def _save_state(state: dict):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


def series_status() -> dict:
    return _load_state()


def next_episode(name: str) -> int:
    state = _load_state()
    return int((state.get("series", {}).get(name) or {}).get("episodes", 0)) + 1


def record_episode(name: str, topic: str, run_id: str, episode: int, prompt: str):
    state = _load_state()
    entry = state.setdefault("series", {}).setdefault(name, {
        "topic": topic, "episodes": 0, "runs": [],
    })
    entry["topic"] = topic
    entry["episodes"] = max(int(entry.get("episodes", 0)), episode)
    entry["runs"].append({"episode": episode, "run_id": run_id, "prompt": prompt,
                          "ts": time.strftime("%Y-%m-%dT%H:%M:%S")})
    entry["updated"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    _save_state(state)


def _episode_prompt(topic: str, episode: int) -> str:
    angles = [
        "make the rule surprising but solvable in one pass",
        "use a different rule family than the previous episode",
        "hide the rule behind a second-order change",
        "keep the arithmetic mental-math friendly",
        "end with a harder loop puzzle",
    ]
    return f"{topic} — episode {episode}, {angles[(episode - 1) % len(angles)]}"


def create_series(cfg: dict, name: str, topic: str, count: int = 3,
                  ratio: str | None = None, duration: float | None = None,
                  quality: str | None = None, offline: bool = False,
                  use_llm: bool = True, no_tts: bool = False) -> list[dict]:
    ratio = ratio or cfg.get("series", {}).get("default_ratio", "9:16")
    duration = float(duration or cfg.get("series", {}).get("default_duration", 35))
    quality = quality or cfg.get("series", {}).get("default_quality", "preview")
    start = next_episode(name)
    reports = []
    for episode in range(start, start + max(1, count)):
        prompt = _episode_prompt(topic, episode)
        log.info("Series %r episode %d/%d: %s", name, episode, start + count - 1, prompt)
        report = create_video(cfg, prompt, ratio=ratio, duration=duration, quality=quality,
                              offline=offline, use_llm=use_llm, no_tts=no_tts,
                              series_info={"name": name, "episode": episode})
        record_episode(name, topic, report["run_id"], episode, prompt)
        reports.append(report)
    return reports


def batch_create(cfg: dict, prompts: list[str], ratio: str | None = None,
                 duration: float | None = None, quality: str | None = None,
                 offline: bool = False, use_llm: bool = True,
                 no_tts: bool = False) -> list[dict]:
    reports = []
    for i, prompt in enumerate(prompts, start=1):
        log.info("Batch %d/%d: %s", i, len(prompts), prompt)
        reports.append(create_video(cfg, prompt, ratio=ratio or "9:16",
                                    duration=float(duration or 35), quality=quality or "preview",
                                    offline=offline, use_llm=use_llm, no_tts=no_tts))
    return reports


def load_prompts(path: Path) -> list[str]:
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        data = json.loads(text)
        if isinstance(data, list):
            return [str(x) for x in data if str(x).strip()]
        if isinstance(data, dict) and isinstance(data.get("prompts"), list):
            return [str(x) for x in data["prompts"] if str(x).strip()]
        raise ValueError("JSON batch file must be a list or {'prompts': [...]}")
    return [line.strip() for line in text.splitlines()
            if line.strip() and not line.strip().startswith("#")]


def resume_run(cfg: dict, run_id: str, offline: bool = False,
               use_llm: bool = True, no_tts: bool = False) -> dict:
    run_dir = PROJECT_ROOT / "runs" / run_id
    if not run_dir.exists():
        raise FileNotFoundError(f"Unknown run: {run_id}")
    report = create_video(cfg, "", resume_dir=run_dir, offline=offline,
                          use_llm=use_llm, no_tts=no_tts)
    return report
