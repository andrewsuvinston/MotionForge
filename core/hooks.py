"""Six hook variants per Short, scored locally; the winner opens the video.

The hook must be short, concrete, and create a curiosity gap. The loop ending
reuses the same psychological pattern so the Short can replay seamlessly.
"""
from __future__ import annotations

import logging
import re

from .llm import LLMClient, LLMError

log = logging.getLogger("motionforge.hooks")

URGENCY = {"seconds", "second", "before", "now", "timer", "scroll"}
PROOF = {"most", "nobody", "everyone", "1", "10", "99", "90", "almost"}


def _words(s: str) -> int:
    return len(re.findall(r"\S+", s or ""))


def _score(text: str, concept: dict) -> float:
    score = 3.0 + float(concept.get("base", 8.0)) / 10.0
    low = text.lower()
    if re.search(r"\d", text):
        score += 1.0
    if "?" in text:
        score += 0.8
    if any(w in low for w in URGENCY):
        score += 0.6
    if any(w in low for w in PROOF):
        score += 0.8
    if 4 <= _words(text) <= 10:
        score += 0.6
    score -= max(0, _words(text) - 10) * 0.25
    return round(score, 3)


def deterministic_variants(concept: dict, puzzle: dict) -> list[dict]:
    answer = puzzle.get("answer")
    terms = puzzle.get("terms") or []
    first = terms[0] if terms else ""
    last = terms[-1] if terms else ""
    angle = concept.get("hook_angle") or "Can you solve this?"
    variants = [
        {"id": "social_proof", "text": angle if angle.startswith(("Only", "Most", "90")) else
         "Only 1 in 10 gets this right.", "badge": "ONLY 1 IN 10 GETS THIS"},
        {"id": "last_step", "text": "Most people miss the last step.",
         "badge": "MOST PEOPLE MISS THIS"},
        {"id": "time_pressure", "text": "You have 5 seconds. What comes next?",
         "badge": "5 SECOND CHALLENGE"},
        {"id": "hidden_rule", "text": "The gaps hide the rule. Can you see it?",
         "badge": "FIND THE HIDDEN RULE"},
        {"id": "single_rule", "text": "One rule solves it. Find it.",
         "badge": "ONE RULE · ONE ANSWER"},
        {"id": "scroll_stop", "text": "Try this before you scroll.",
         "badge": "TRY THIS BEFORE YOU SCROLL"},
    ]
    if first != "" and last != "":
        shown = [str(t) for t in terms[:4]]
        while len(shown) > 2:
            candidate = f"{', '.join(shown)}... what comes next?"
            if _words(candidate) <= 10:
                break
            shown = shown[:-1]
        variants.append({
            "id": "sequence_tease",
            "text": f"{', '.join(shown)}... what comes next?",
            "badge": "SPOT THE PATTERN",
        })
    for v in variants:
        v["score"] = _score(v["text"], concept)
    return variants


def maybe_llm_variants(llm: LLMClient | None, concept: dict, puzzle: dict) -> list[dict]:
    if llm is None:
        return []
    prompt = (
        "Write 6 short YouTube Shorts hook lines for this puzzle. Each must be <= 10 words, "
        "create curiosity, and avoid clickbait that is false. Return ONLY a JSON array of "
        'strings. Puzzle type: ' + str(puzzle.get("type")) + ". Terms: " +
        str(puzzle.get("terms") or puzzle.get("statement") or "")
    )
    try:
        data = llm.chat_json(
            [{"role": "system", "content": "You write precise, punchy puzzle hooks."},
             {"role": "user", "content": prompt}],
            label="hook_variants", tier="cheap", stage="hooks", max_tokens=400, temperature=0.8,
        )
        if not isinstance(data, list):
            return []
        out = []
        for i, text in enumerate(data[:8]):
            if not isinstance(text, str) or not text.strip():
                continue
            text = " ".join(text.split())[:120]
            out.append({"id": f"llm_{i}", "text": text,
                        "badge": text.upper()[:42], "score": _score(text, concept) + 0.15})
        return out
    except (LLMError, ValueError) as exc:
        log.warning("LLM hook generation failed (%s); using local variants", exc)
        return []


def generate_hooks(concept: dict, puzzle: dict, llm: LLMClient | None = None) -> dict:
    variants = deterministic_variants(concept, puzzle) + maybe_llm_variants(llm, concept, puzzle)
    variants.sort(key=lambda v: v["score"], reverse=True)
    best = variants[0]
    log.info("Hook: %r (score %.2f, %d variants)", best["text"], best["score"], len(variants))
    return {"best": best, "variants": variants}
