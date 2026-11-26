"""Concept engine: eight formats, keyword scoring, topic history, analytics bias.

The concept decides the format (number series, truth/lies, crossing, ...) and the
promise of the Short. Selection is deterministic and cheap; the LLM can refine
copy later but never decides correctness.
"""
from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path

log = logging.getLogger("motionforge.concepts")

CONCEPTS = [
    {
        "id": "series_trap", "name": "Number Series Trap", "puzzle_type": "number_series",
        "keywords": ["number", "series", "sequence", "pattern", "missing", "next", "math"],
        "base": 8.8, "promise": "One hidden rule most people miss.",
        "hook_angle": "Only 1 in 10 gets it right.",
        "visual": "sequence",
    },
    {
        "id": "truth_grid", "name": "Truth & Lies", "puzzle_type": "truth_lies",
        "keywords": ["truth", "liar", "lie", "logic", "statement", "who"],
        "base": 8.4, "promise": "One statement is false. Find it.",
        "hook_angle": "One of them is lying.",
        "visual": "suspects",
    },
    {
        "id": "river_crossing", "name": "River Crossing", "puzzle_type": "river",
        "keywords": ["river", "crossing", "bridge", "torch", "wolf", "goat", "boat"],
        "base": 8.1, "promise": "A classic constraint puzzle, solved step by step.",
        "hook_angle": "Most people sink the boat on the first move.",
        "visual": "clues",
    },
    {
        "id": "percent_trap", "name": "Percentage Trap", "puzzle_type": "percentage",
        "keywords": ["percent", "percentage", "discount", "increase", "decrease"],
        "base": 8.0, "promise": "The obvious answer is usually wrong.",
        "hook_angle": "90% get this percentage wrong.",
        "visual": "bars",
    },
    {
        "id": "work_rate", "name": "Work & Rate", "puzzle_type": "time_work",
        "keywords": ["work", "rate", "days", "hours", "pipes", "together"],
        "base": 7.9, "promise": "Two workers, one job, one clean shortcut.",
        "hook_angle": "The shortcut saves ten seconds.",
        "visual": "steps",
    },
    {
        "id": "ratio_split", "name": "Ratio Split", "puzzle_type": "ratio",
        "keywords": ["ratio", "share", "split", "proportion", "divide"],
        "base": 7.8, "promise": "Split the total without guessing.",
        "hook_angle": "The total is not the answer.",
        "visual": "bars",
    },
    {
        "id": "algebra_trick", "name": "Algebra Trick", "puzzle_type": "algebra",
        "keywords": ["algebra", "equation", "solve", "variable", "x"],
        "base": 7.7, "promise": "Undo the operations in the right order.",
        "hook_angle": "One move solves the whole equation.",
        "visual": "equation",
    },
    {
        "id": "odd_one_out", "name": "Odd One Out", "puzzle_type": "number_series",
        "keywords": ["odd", "spot", "difference", "visual", "find"],
        "base": 7.5, "promise": "One item does not belong.",
        "hook_angle": "Almost nobody spots it on the first pass.",
        "visual": "sequence",
    },
]

CONCEPT_BY_ID = {c["id"]: c for c in CONCEPTS}


def _tokens(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", (text or "").lower()) if len(w) > 2}


def load_topic_history(root: Path, limit: int = 20) -> list[str]:
    path = Path(root) / "memory" / "topics.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return [str(x) for x in data[-limit:]]
    except (json.JSONDecodeError, OSError):
        pass
    return []


def record_topic(root: Path, concept_id: str, limit: int = 20):
    path = Path(root) / "memory" / "topics.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    history = load_topic_history(root, limit=limit)
    history.append(concept_id)
    path.write_text(json.dumps(history[-limit:], indent=2), encoding="utf-8")


def _analytics_bonus(root: Path, concept_id: str) -> float:
    path = Path(root) / "memory" / "analytics.json"
    if not path.exists():
        return 0.0
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        stats = (data.get("concepts") or {}).get(concept_id) or {}
        runs = int(stats.get("runs", 0))
        if runs == 0:
            return 0.0
        retention = float(stats.get("retention", stats.get("retention_proxy", 0.0)) or 0.0)
        completion = float(stats.get("completion", stats.get("avg_completion", 0.0)) or 0.0)
        confidence = min(1.0, runs / 3.0)
        return min(1.2, (0.6 * retention + 0.6 * completion) * confidence)
    except (json.JSONDecodeError, OSError, ValueError):
        return 0.0


def score_concepts(prompt: str, root: Path) -> list[dict]:
    """Score all eight concepts for a prompt. Pure-ish (reads history/analytics)."""
    tokens = _tokens(prompt)
    history = load_topic_history(root, limit=30)
    scored = []
    for concept in CONCEPTS:
        keywords = set(concept["keywords"])
        matches = len(tokens & keywords)
        score = concept["base"] + 1.4 * matches
        score += _analytics_bonus(root, concept["id"])
        # Avoid repeating the exact same format too often in a series.
        recent = history[-4:]
        score -= 0.45 * recent.count(concept["id"])
        scored.append({**concept, "score": round(score, 3),
                       "keyword_matches": sorted(tokens & keywords)})
    scored.sort(key=lambda c: c["score"], reverse=True)
    return scored


def choose_concept(prompt: str, root: Path) -> dict:
    scored = score_concepts(prompt, root)
    best = scored[0]
    log.info("Concept: %s (%.2f) | alternatives: %s", best["name"], best["score"],
             ", ".join(f"{c['id']}={c['score']}" for c in scored[1:4]))
    return best


def naive_concept_for_type(puzzle_type: str) -> dict:
    for concept in CONCEPTS:
        if concept["puzzle_type"] == puzzle_type:
            return concept
    return CONCEPTS[0]
