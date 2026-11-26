"""Analytics: record run outcomes and feed them back into concept selection.

No invented channel data. Until real retention is imported, the judge score is a
clearly-labelled proxy. Import a JSON file of run_id -> {retention, completion}
to replace the proxy.
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path

log = logging.getLogger("motionforge.analytics")


def _path(root: Path) -> Path:
    return Path(root) / "memory" / "analytics.json"


def _load(root: Path) -> dict:
    p = _path(root)
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except (json.JSONDecodeError, OSError):
            pass
    return {"updated": None, "runs": [], "concepts": {}, "imported": {}}


def record_run(root: Path, report: dict, judge: dict, package: dict | None = None) -> dict:
    root = Path(root)
    data = _load(root)
    concept = (judge.get("concept") or report.get("concept")
               or (package or {}).get("concept") or "unknown")
    overall = float(judge.get("overall") or 0.0)
    entry = {
        "run_id": report.get("run_id"),
        "concept": concept,
        "puzzle_type": report.get("puzzle_type"),
        "overall": overall,
        "gate_passed": bool(judge.get("passed")),
        "duration": report.get("duration"),
        "quality": report.get("quality"),
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    runs = data.setdefault("runs", [])
    existing = next((r for r in runs if r.get("run_id") == entry["run_id"]), None)
    if existing is not None:
        existing.update(entry)
    else:
        runs.append(entry)

    # Deduplicate resumed runs and rebuild concept aggregates from scratch so a
    # resume never double-counts a run.
    unique: dict[str, dict] = {}
    for r in runs:
        unique[str(r.get("run_id"))] = r
    runs = list(unique.values())
    data["runs"] = runs

    stats_map: dict[str, dict] = {}
    for r in runs:
        cid = r.get("concept") or "unknown"
        s = stats_map.setdefault(cid, {"runs": 0, "sum_overall": 0.0,
                                       "sum_completion": 0.0, "gate_passes": 0})
        s["runs"] += 1
        s["sum_overall"] += float(r.get("overall") or 0.0)
        s["sum_completion"] += min(1.0, float(r.get("duration") or 0.0) / 35.0)
        s["gate_passes"] += 1 if r.get("gate_passed") else 0
    concepts = {}
    for cid, s in stats_map.items():
        n = max(1, s["runs"])
        concepts[cid] = {
            "runs": s["runs"],
            "sum_overall": round(s["sum_overall"], 3),
            "avg_overall": round(s["sum_overall"] / n, 3),
            "avg_completion": round(s["sum_completion"] / n, 3),
            "retention_proxy": round(s["sum_overall"] / n / 10.0, 3),
            "gate_passes": s["gate_passes"],
        }
    # Real imported metrics override the judge proxy per concept.
    for run_id, metrics in (data.get("imported") or {}).items():
        run = next((r for r in runs if r.get("run_id") == run_id), None)
        if run:
            stats = concepts.setdefault(run.get("concept") or "unknown", {})
            stats["retention"] = metrics.get("retention")
            stats["completion"] = metrics.get("completion")
    data["concepts"] = concepts
    data["updated"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    _path(root).parent.mkdir(parents=True, exist_ok=True)
    _path(root).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    log.info("Analytics: recorded %s (%s, overall %.2f)", entry["run_id"], concept, overall)
    return data


def import_metrics(root: Path, source: Path) -> dict:
    """Merge real channel metrics: {run_id: {retention: 0..1, completion: 0..1}}."""
    incoming = json.loads(Path(source).read_text(encoding="utf-8"))
    if not isinstance(incoming, dict):
        raise ValueError("analytics import must be a JSON object keyed by run_id")
    data = _load(root)
    imported = data.setdefault("imported", {})
    for run_id, metrics in incoming.items():
        if isinstance(metrics, dict):
            imported[str(run_id)] = {
                "retention": max(0.0, min(1.0, float(metrics.get("retention", 0) or 0))),
                "completion": max(0.0, min(1.0, float(metrics.get("completion", 0) or 0))),
            }
    # Apply imported metrics to the per-concept averages.
    for run_id, metrics in imported.items():
        run = next((r for r in data.get("runs", []) if r.get("run_id") == run_id), None)
        if not run:
            continue
        stats = data.setdefault("concepts", {}).setdefault(run["concept"], {})
        stats["retention"] = metrics["retention"]
        stats["completion"] = metrics["completion"]
    data["updated"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    _path(root).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return data


def summary(root: Path) -> dict:
    data = _load(root)
    concepts = []
    for cid, stats in (data.get("concepts") or {}).items():
        concepts.append({"concept": cid, **stats})
    concepts.sort(key=lambda c: c.get("avg_overall", 0), reverse=True)
    return {
        "updated": data.get("updated"),
        "runs": len(data.get("runs") or []),
        "concepts": concepts,
        "imported": len(data.get("imported") or {}),
        "note": "retention_proxy = judge overall / 10 until real analytics are imported",
    }
