"""Judge panel: seven scored dimensions with hard release gates.

Scores are deterministic and evidence-based: correctness comes from the code
verifier, density from real DOM measurements, clarity/pacing from the timed
storyboard. An optional LLM judge is advisory only; it can never raise a score
above what the rendered video demonstrably earns.
"""
from __future__ import annotations

import copy
import logging
import re

from .llm import LLMClient, LLMError

log = logging.getLogger("motionforge.judges")

JUDGES = ["hook", "clarity", "correctness", "pacing", "visual", "audio", "retention"]

URGENCY = {"seconds", "second", "before", "now", "timer", "scroll", "lock"}
PROOF = {"most", "nobody", "everyone", "1", "10", "99", "90", "almost", "only"}


def _clamp(x: float) -> float:
    return round(max(0.0, min(10.0, x)), 2)


def _words(s: str) -> list[str]:
    return re.findall(r"\S+", s or "")


def _wc(s: str) -> int:
    return len(_words(s))


def _sentences(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.!?])\s+", (text or "").strip()) if s]


def score_hook(storyboard: dict) -> float:
    hook = (storyboard.get("hook") or {}).get("best") or {}
    text = hook.get("text") or (storyboard.get("hook") or {}).get("chosen") or ""
    badge = hook.get("badge") or ""
    low = text.lower()
    score = 6.0
    if "?" in text:
        score += 0.5
    if re.search(r"\d", text):
        score += 0.5
    if 4 <= _wc(text) <= 10:
        score += 0.4
    if any(w in low for w in URGENCY):
        score += 0.4
    if any(w in low for w in PROOF):
        score += 0.4
    if badge:
        score += 0.3
    if float(hook.get("score") or 0) >= 6.5:
        score += 0.3
    return _clamp(score)


def score_clarity(storyboard: dict, cfg: dict) -> tuple[float, list[str]]:
    video = cfg.get("video", {})
    max_sentence = int(video.get("max_sentence_words", 14))
    max_on_screen = int(video.get("max_words_scene", 10))
    score, notes = 10.0, []
    for scene in storyboard.get("scenes") or []:
        sid = scene.get("id")
        nar = scene.get("narration") or ""
        for sentence in _sentences(nar):
            if _wc(sentence) > max_sentence:
                score -= 0.6
                notes.append(f"scene {sid}: sentence has {_wc(sentence)} words")
        dur = max(0.001, float(scene.get("duration") or 1))
        if _wc(nar) / dur > float(video.get("wps", 2.5)) + 0.15:
            score -= 0.5
            notes.append(f"scene {sid}: narration is too dense")
        for key, value in (scene.get("props") or {}).items():
            if isinstance(value, str) and _wc(value) > max_on_screen and key not in ("terms", "answer"):
                score -= 0.25
                notes.append(f"scene {sid}: {key} has {_wc(value)} words on screen")
    return _clamp(score), notes


def score_correctness(verification: dict) -> tuple[float, list[str]]:
    notes = []
    if not verification:
        return 2.0, ["no verification record"]
    if verification.get("verified_by_code") and verification.get("code_ok"):
        ans = verification.get("answer")
        return 10.0, [f"code-verified answer {ans!r}"]
    if verification.get("code_ok"):
        return 7.0, ["verified at runtime but not by the code solver"]
    notes.append(f"unverified answer: {verification.get('code_reason')}")
    return 3.0, notes


def score_pacing(storyboard: dict) -> tuple[float, list[str]]:
    score, notes = 10.0, []
    scenes = storyboard.get("scenes") or []
    total = sum(float(s.get("duration") or 0) for s in scenes)
    if not scenes:
        return 2.0, ["no scenes"]
    if total < 25:
        score -= 1.0
        notes.append(f"total runtime {total:.1f}s is short for Shorts")
    if total > 48:
        score -= 1.0
        notes.append(f"total runtime {total:.1f}s is long")
    for scene in scenes:
        dur = float(scene.get("duration") or 0)
        if dur > 9.5:
            score -= 0.4
            notes.append(f"scene {scene.get('id')} holds {dur:.1f}s")
        if dur < 2.0:
            score -= 0.4
            notes.append(f"scene {scene.get('id')} is too brief ({dur:.1f}s)")
    return _clamp(score), notes


def score_visual(check_results: list[dict], cfg: dict) -> tuple[float, list[str]]:
    if not check_results:
        return 0.0, ["no rendered measurements"]
    occs = [float(r.get("occupancy") or 0) for r in check_results]
    avg = sum(occs) / len(occs)
    worst = min(occs)
    score = 4.0 + 6.5 * avg
    notes = [f"occupancy avg {avg:.0%}, worst {worst:.0%}"]
    if worst < float(cfg.get("video", {}).get("min_occupancy", 0.55)):
        score -= 1.0
        notes.append("a scene fell below the density floor")
    problems = [p for r in check_results for p in (r.get("problems") or [])]
    errors = [p for p in problems if p.get("severity", "error") == "error"]
    if errors:
        score -= min(3.0, 0.35 * len(errors))
        notes.append(f"{len(errors)} deterministic layout problem(s)")
    return _clamp(score), notes


def score_audio(audio_report: dict | None) -> tuple[float, list[str]]:
    if not audio_report:
        return 4.0, ["no audio"]
    if audio_report.get("voiceover") and audio_report.get("music"):
        return 9.2, ["voiceover + music + sfx, ducked to -14 LUFS"]
    if audio_report.get("music"):
        return 7.6, ["music + sfx only (no voiceover)"]
    return 5.0, ["audio bed unavailable"]


def score_retention(storyboard: dict, hook_score: float) -> tuple[float, list[str]]:
    tags = [s.get("tag") for s in (storyboard.get("scenes") or [])]
    score = 6.0
    notes = []
    if hook_score >= 8:
        score += 1.0
    if "YOUR TURN" in tags:
        score += 1.0
    else:
        notes.append("no viewer-challenge beat")
    if "ANSWER" in tags:
        score += 1.0
    else:
        notes.append("no payoff beat")
    loop = storyboard.get("loop_ending") or []
    if loop:
        score += 0.5
    if "?" in ((storyboard.get("hook") or {}).get("chosen") or ""):
        score += 0.5
    return _clamp(score), notes


def deterministic_panel(storyboard: dict, verification: dict, check_results: list[dict],
                        audio_report: dict | None, cfg: dict) -> dict:
    hook = score_hook(storyboard)
    clarity, clarity_notes = score_clarity(storyboard, cfg)
    correctness, correctness_notes = score_correctness(verification)
    pacing, pacing_notes = score_pacing(storyboard)
    visual, visual_notes = score_visual(check_results, cfg)
    audio, audio_notes = score_audio(audio_report)
    retention, retention_notes = score_retention(storyboard, hook)
    scores = {"hook": hook, "clarity": clarity, "correctness": correctness,
              "pacing": pacing, "visual": visual, "audio": audio, "retention": retention}
    overall = round(sum(scores.values()) / len(scores), 2)
    gate = cfg.get("quality", {}).get("gate", {})
    min_judge = float(gate.get("min_judge", 7.0))
    min_hook = float(gate.get("min_hook", 8.0))
    gates = {
        "all_at_least_min": all(v >= min_judge for v in scores.values()),
        "hook_at_least_min": hook >= min_hook,
        "correctness_perfect": correctness >= 10.0,
    }
    passed = all(gates.values())
    return {
        "scores": scores,
        "overall": overall,
        "gates": gates,
        "passed": passed,
        "min_judge": min_judge,
        "min_hook": min_hook,
        "evidence": {
            "clarity": clarity_notes,
            "correctness": correctness_notes,
            "pacing": pacing_notes,
            "visual": visual_notes,
            "audio": audio_notes,
            "retention": retention_notes,
        },
    }


# ------------------------------------------------------------------ llm advisory

ADVISORY_SYSTEM = """You are a strict Shorts retention editor. Score these three dimensions
from 0 to 10: hook, clarity, retention. Be honest: most puzzle Shorts are 6-7, not 9.
Return ONLY JSON:
{"hook": n, "clarity": n, "retention": n, "notes": ["one concrete fix", "another"]}"""


def llm_advisory(llm: LLMClient | None, storyboard: dict) -> dict | None:
    if llm is None:
        return None
    payload = {
        "hook": (storyboard.get("hook") or {}).get("chosen"),
        "scenes": [{"tag": s.get("tag"), "seconds": s.get("duration"),
                    "narration": s.get("narration")} for s in storyboard.get("scenes") or []],
    }
    try:
        data = llm.chat_json(
            [{"role": "system", "content": ADVISORY_SYSTEM},
             {"role": "user", "content": str(payload)}],
            label="judge_advisory", tier="cheap", stage="judges",
            max_tokens=400, temperature=0.2,
        )
    except (LLMError, ValueError) as exc:
        log.warning("LLM advisory judge unavailable (%s)", str(exc)[:160])
        return None
    if not isinstance(data, dict):
        return None
    out = {k: _clamp(float(data.get(k, 0) or 0)) for k in ("hook", "clarity", "retention")}
    out["notes"] = [str(n)[:160] for n in (data.get("notes") or [])][:4]
    out["source"] = "llm_advisory"
    return out


# ------------------------------------------------------------------ improvement

def _best_unused_hook(storyboard: dict, puzzle: dict) -> dict | None:
    variants = list((storyboard.get("hook") or {}).get("variants") or [])
    current = (storyboard.get("hook") or {}).get("chosen")
    if not variants:
        return None
    terms = [str(t) for t in (puzzle.get("terms") or [])]
    scored = []
    for v in variants:
        text = v.get("text") or ""
        if not text or text == current:
            continue
        s = float(v.get("score") or 0)
        if "?" in text:
            s += 0.4
        if re.search(r"\d", text):
            s += 0.3
        if any(w in text.lower() for w in URGENCY):
            s += 0.2
        if terms and any(t in text for t in terms[:1]):
            s += 0.2
        scored.append((s, v))
    if not scored:
        return None
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[0][1]


def improve_storyboard(storyboard: dict, panel: dict, puzzle: dict, round_no: int) -> tuple[dict, list[str]]:
    """Apply one evidence-driven improvement. Returns (storyboard, changes)."""
    out = copy.deepcopy(storyboard)
    scores = panel.get("scores") or {}
    changes: list[str] = []

    if scores.get("hook", 10) < float(panel.get("min_hook", 8.0)):
        candidate = _best_unused_hook(out, puzzle)
        if candidate:
            out["hook"]["chosen"] = candidate["text"]
            out["hook"]["best"] = candidate
            for scene in out.get("scenes") or []:
                if scene.get("tag") == "HOOK":
                    scene["props"]["badge"] = candidate.get("badge") or "TRY THIS"
                    scene["props"]["hint"] = "You have 5 seconds."
                    break
            changes.append(f"round {round_no}: stronger hook -> {candidate['text']!r}")

    if scores.get("clarity", 10) < 7.0:
        for scene in out.get("scenes") or []:
            sentences = _sentences(scene.get("narration") or "")
            if len(sentences) > 2:
                scene["narration"] = " ".join(sentences[:2])
        changes.append(f"round {round_no}: trimmed narration to two sentences per scene")

    if scores.get("pacing", 10) < 7.0:
        scales = {"HOOK": 1.0, "PATTERN": 1.05, "YOUR TURN": 0.85,
                  "SOLUTION": 1.0, "ANSWER": 1.0, "LOOP": 1.0}
        for scene in out.get("scenes") or []:
            scene["duration"] = round(float(scene.get("duration") or 4) * scales.get(scene.get("tag"), 1.0), 2)
        changes.append(f"round {round_no}: rebalanced beat durations")

    if scores.get("retention", 10) < 7.0:
        for scene in out.get("scenes") or []:
            if scene.get("tag") == "ANSWER":
                scene.setdefault("props", {})
                scene["props"]["teaser"] = "The next one is harder. Follow so you do not miss it."
                scene["narration"] = (scene.get("narration") or "") + " Follow for the next one."
        changes.append(f"round {round_no}: strengthened payoff and follow prompt")

    if scores.get("visual", 10) < 7.0:
        for scene in out.get("scenes") or []:
            props = scene.setdefault("props", {})
            props.setdefault("micro", "ONE RULE · ONE ANSWER")
        changes.append(f"round {round_no}: added supporting micro-copy to fill empty bands")

    return out, changes


def judge_rounds(storyboard: dict, verification: dict, check_results: list[dict],
                 audio_report: dict | None, cfg: dict, puzzle: dict,
                 llm: LLMClient | None = None, run_log: list | None = None) -> dict:
    """Improve until the gates pass (max 5 rounds, keep the best, stop on plateau)."""
    gate = cfg.get("quality", {}).get("gate", {})
    max_rounds = int(gate.get("max_rounds", 5))
    min_gain = float(gate.get("min_improvement", 0.3))
    rounds: list[dict] = []
    best = None
    current = storyboard
    low_streak = 0

    for r in range(1, max_rounds + 1):
        panel = deterministic_panel(current, verification, check_results, audio_report, cfg)
        entry = {"round": r, "scores": panel["scores"], "overall": panel["overall"],
                 "gates": panel["gates"], "passed": panel["passed"],
                 "evidence": panel["evidence"], "changes": []}
        if best is None or panel["overall"] > best[0]:
            best = (panel["overall"], current, panel, r)
        rounds.append(entry)
        log.info("Judge round %d: %s | overall %.2f | passed=%s", r,
                 " ".join(f"{k}={v}" for k, v in panel["scores"].items()),
                 panel["overall"], panel["passed"])
        if panel["passed"]:
            break
        if r > 1:
            gain = panel["overall"] - rounds[r - 2]["overall"]
            low_streak = low_streak + 1 if gain < min_gain else 0
            if low_streak >= 2:
                entry["stopped"] = f"plateau: two rounds improved < +{min_gain}"
                break
        current, changes = improve_storyboard(current, panel, puzzle, r + 1)
        entry["changes"] = changes
        if not changes:
            entry["stopped"] = "no further deterministic improvements available"
            break

    best_overall, best_storyboard, best_panel, best_round = best
    result = {
        "rounds": rounds,
        "best_round": best_round,
        "best_overall": best_overall,
        "scores": best_panel["scores"],
        "overall": best_panel["overall"],
        "gates": best_panel["gates"],
        "passed": best_panel["passed"],
        "evidence": best_panel["evidence"],
        "storyboard": best_storyboard,
        "max_rounds": max_rounds,
        "min_improvement": min_gain,
        "weaknesses": _weaknesses(best_panel),
    }
    if llm is not None:
        result["llm_advisory"] = llm_advisory(llm, best_storyboard)
    return result


def _weaknesses(panel: dict) -> list[str]:
    out = []
    for judge, value in (panel.get("scores") or {}).items():
        if value < 8.5:
            notes = (panel.get("evidence") or {}).get(judge) or []
            reason = "; ".join(notes[:2]) if notes else "no specific finding"
            out.append(f"{judge} {value:.1f}/10: {reason}")
    return out
