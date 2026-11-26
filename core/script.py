"""Storyboard: verified puzzle + concept + hook -> timed, mobile-first scene JSON.

The storyboard is deterministic. Every beat has a job, a duration, a component,
structured props, and narration that fits the ~2.5 words/second budget.
"""
from __future__ import annotations

import logging
import re

log = logging.getLogger("motionforge.script")

BEAT_WEIGHTS = [5.0, 7.0, 6.0, 9.0, 4.0, 4.0]
MIN_SCENE = 2.0


def _words(text: str) -> list[str]:
    return re.findall(r"\S+", text or "")


def _wc(text: str) -> int:
    return len(_words(text))


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", (text or "").strip()) if s.strip()]


def fit_narration(text: str, duration: float, wps: float = 2.5) -> str:
    """Keep the narration inside the wps budget, preserving the final sentence."""
    budget = max(6, int(round(duration * wps)))
    parts = _sentences(text)
    if not parts:
        return ""
    kept: list[str] = []
    total = 0
    for sentence in reversed(parts):
        w = _wc(sentence)
        if not kept or total + w <= budget:
            kept.insert(0, sentence)
            total += w
    return " ".join(kept)


def distribute_durations(total: float, weights: list[float]) -> list[float]:
    """Split the runtime so every beat gets its minimum and the rest is weighted.

    A plain proportional split then clamp can starve short runs (a 12s video used
    to produce a 1.87s beat). Reserving the minimum first guarantees no beat is
    below MIN_SCENE and keeps the total exact.
    """
    n = len(weights)
    if n == 0:
        return []
    total = max(float(total), n * MIN_SCENE)
    weight_sum = sum(w for w in weights if w > 0) or float(n)
    extra = total - n * MIN_SCENE
    raw = [MIN_SCENE + extra * (max(0.0, w) / weight_sum) for w in weights]
    raw = [round(x, 3) for x in raw]
    # Absorb rounding drift into the longest beat, never below the minimum.
    drift = round(total - sum(raw), 3)
    if drift:
        longest = max(range(n), key=lambda i: raw[i])
        raw[longest] = round(raw[longest] + drift, 3)
    return [round(x, 3) for x in raw]


def _narration(puzzle: dict, key: str, fallback: str) -> str:
    data = puzzle.get("narration") or {}
    return data.get(key) or fallback


def _trim_on_screen(value, max_words: int = 10, key: str = ""):
    """Trim long on-screen strings while preserving structured values."""
    if isinstance(value, dict):
        return {k: _trim_on_screen(v, max_words, k) for k, v in value.items()}
    if isinstance(value, list):
        return [_trim_on_screen(v, max_words, key) for v in value]
    if isinstance(value, str) and key not in ("terms", "answer", "math", "left", "right"):
        words = _words(value)
        if len(words) > max_words:
            return " ".join(words[:max_words]).rstrip(".,;:") + "…"
    return value


def _terms_text(puzzle: dict) -> str:
    terms = puzzle.get("terms") or []
    return ", ".join(str(t) for t in terms)


def _hook_hero(puzzle: dict) -> str:
    """Compact puzzle hero for the hook card when there is no number series."""
    ptype = puzzle.get("type")
    if ptype == "percentage":
        payload = puzzle.get("payload") or {}
        return f"{payload.get('percent')}% of {payload.get('base')}"
    if ptype == "ratio":
        payload = puzzle.get("payload") or {}
        return " : ".join(str(x) for x in (payload.get("ratio") or []))
    if ptype == "algebra":
        equation = (puzzle.get("payload") or {}).get("equation") or ""
        return equation.replace("*", "").replace(" ", "")
    if ptype == "arithmetic":
        return (puzzle.get("payload") or {}).get("expression") or "?"
    if ptype == "time_work":
        times = (puzzle.get("payload") or {}).get("times") or []
        return " + ".join(f"{t}d" for t in times) or "?"
    if ptype == "river":
        return "WOLF · GOAT · CABBAGE"
    if ptype == "truth_lies":
        count = len(puzzle.get("people") or puzzle.get("payload", {}).get("people") or [])
        return f"{count or 2} SPEAKERS · 1 LIAR"
    return (puzzle.get("title") or "?").upper()


def _solution_steps(puzzle: dict) -> list[dict]:
    steps = puzzle.get("steps") or []
    out = []
    for s in steps[:4]:
        if isinstance(s, dict):
            out.append({"math": str(s.get("math") or ""), "text": str(s.get("text") or "")})
    if not out:
        out = [{"math": str(puzzle.get("answer", "")), "text": "That is the answer"}]
    return out


def _suspects_from_payload(puzzle: dict) -> list[dict]:
    payload = puzzle.get("payload") or {}
    people = payload.get("people") or []
    statements = payload.get("statements") or []
    by_speaker = {s.get("speaker"): s for s in statements}
    chars = ["detective", "suspect", "assistant"]
    exprs = ["thinking", "neutral", "happy"]
    out = []
    for i, person in enumerate(people[:3]):
        st = by_speaker.get(person) or {}
        claim = st.get("claim") or {}
        ctype = claim.get("type")
        if ctype == "is_liar":
            line = f"{claim.get('target')} is a liar."
        elif ctype == "is_truth":
            line = f"{claim.get('target')} tells the truth."
        elif ctype == "count_liars":
            line = f"Exactly {claim.get('n')} liars."
        elif ctype == "count_truth":
            line = f"Exactly {claim.get('n')} truth-tellers."
        else:
            line = "One of us is lying."
        out.append({"name": person, "line": line, "character": chars[i % 3],
                    "expression": exprs[i % 3]})
    return out


def _clue_props(puzzle: dict) -> list[dict]:
    ptype = puzzle.get("type")
    if ptype == "river":
        return [
            {"icon": "1", "text": "The boat carries the farmer plus one item."},
            {"icon": "2", "text": "Wolf and goat alone: the goat is eaten."},
            {"icon": "3", "text": "Goat and cabbage alone: the cabbage is eaten."},
            {"icon": "4", "text": "Count every single crossing."},
        ]
    return [
        {"icon": "1", "text": puzzle.get("hint") or "Read every clue carefully."},
        {"icon": "2", "text": "Test one assumption at a time."},
        {"icon": "3", "text": "Reject any case that contradicts a clue."},
        {"icon": "4", "text": "Only one answer survives."},
    ]


def _beat2(puzzle: dict, concept: dict) -> tuple[str, dict]:
    ptype = puzzle.get("type")
    if ptype == "number_series":
        return "sequence", {
            "title": "Find the pattern", "terms": puzzle.get("terms") or [],
            "hint": puzzle.get("hint") or "Look at how each jump changes.",
            "chip": "FIND THE PATTERN", "micro": f"{len(puzzle.get('terms') or [])} TERMS · 1 RULE",
            "show_missing": True,
        }
    if ptype == "truth_lies":
        return "suspects", {
            "title": "One of them is lying",
            "suspects": _suspects_from_payload(puzzle),
        }
    if ptype == "river":
        return "clue_cards", {"title": "The rules", "clues": _clue_props(puzzle)}
    if ptype in ("percentage", "ratio"):
        payload = puzzle.get("payload") or {}
        if ptype == "ratio":
            ratio = payload.get("ratio") or [3, 4]
            return "bars", {
                "title": "Split the total",
                "labels": [f"{r} parts" for r in ratio],
                "values": ratio,
            }
        return "equation", {
            "title": "Find the part",
            "left": f"{payload.get('percent', 25)}% of {payload.get('base', 80)}",
            "right": "?",
            "answer": f"{puzzle.get('answer')}",
            "hint": puzzle.get("hint") or "Turn the percent into a decimal.",
        }
    if ptype == "algebra":
        payload = puzzle.get("payload") or {}
        equation = str(payload.get("equation") or "2*x+3=11")
        left, _, right = equation.partition("=")
        return "equation", {
            "title": "Solve for x", "left": left.replace("*", ""), "right": right,
            "answer": f"x = {puzzle.get('answer')}", "hint": puzzle.get("hint") or "Undo the operations.",
        }
    return "text", {
        "title": puzzle.get("title") or "The puzzle",
        "body": puzzle.get("statement") or puzzle.get("hint") or "",
        "bullets": [s.get("text", "") for s in (puzzle.get("steps") or [])[:3]],
    }


def _beat4(puzzle: dict, concept: dict) -> tuple[str, dict]:
    ptype = puzzle.get("type")
    if ptype == "number_series":
        return "solution_steps", {
            "title": "Here is the trick",
            "steps": _solution_steps(puzzle),
            "answer": str(puzzle.get("answer", "")),
            "recap": puzzle.get("recap") or "Apply the same rule.",
        }
    if ptype == "truth_lies":
        return "solution_steps", {
            "title": "Test the assumptions",
            "steps": _solution_steps(puzzle),
            "answer": str(puzzle.get("answer", "")),
            "recap": puzzle.get("recap") or "Only one assignment survives.",
        }
    if ptype == "river":
        return "clue_cards", {
            "title": "The safe sequence",
            "clues": [{"icon": str(i + 1), "text": s.get("text", "")}
                      for i, s in enumerate(_solution_steps(puzzle))],
        }
    if ptype == "percentage":
        payload = puzzle.get("payload") or {}
        return "solution_steps", {
            "title": "Here is the trick",
            "steps": [
                {"math": f"{payload.get('percent')}% = {float(payload.get('percent', 0)) / 100:g}",
                 "text": "Turn the percent into a decimal"},
                {"math": f"{float(payload.get('percent', 0)) / 100:g} × {payload.get('base')} = {puzzle.get('answer')}",
                 "text": "Multiply to get the part"},
            ],
            "answer": str(puzzle.get("answer", "")),
            "recap": puzzle.get("recap") or "Percent means per hundred.",
        }
    return "solution_steps", {
        "title": "Here is the trick",
        "steps": _solution_steps(puzzle),
        "answer": str(puzzle.get("answer", "")),
        "recap": puzzle.get("recap") or "Apply the rule to the last term.",
    }


def build_storyboard(puzzle: dict, concept: dict, hook: dict, duration: float,
                     cfg: dict) -> dict:
    wps = float(cfg.get("video", {}).get("wps", 2.5))
    best_hook = (hook or {}).get("best") or {}
    badge = best_hook.get("badge") or "ONLY 1 IN 10 GETS THIS"
    hook_text = best_hook.get("text") or concept.get("hook_angle") or "Can you solve this?"
    terms = puzzle.get("terms") or []
    ptype = puzzle.get("type")
    loop_terms = puzzle.get("loop_terms") or []
    answer = puzzle.get("answer")
    label = "NUMBER SERIES · CAN YOU CRACK IT?" if ptype == "number_series" else \
        f"{concept.get('name', 'PUZZLE').upper()} · CAN YOU SOLVE IT?"

    durations = distribute_durations(duration, BEAT_WEIGHTS)

    hook_props = {
        "badge": badge, "question": "What comes next?" if ptype == "number_series" else "Can you solve it?",
        "terms": terms, "number": _hook_hero(puzzle),
        "hint": "You have 5 seconds.", "label": label,
        "micro": f"{len(terms)} TERMS · ONE RULE" if terms else "ONE RULE · ONE ANSWER",
    }
    b2c, b2p = _beat2(puzzle, concept)
    b4c, b4p = _beat4(puzzle, concept)

    countdown_title = "Your turn. Lock it in."
    countdown_prompt = "Comment before the ring closes"
    payoff_teaser = (f"Next: {', '.join(str(t) for t in loop_terms)}..." if loop_terms
                     else "Follow for the next puzzle.")

    raw_scenes = [
        {"component": "hook_question", "props": hook_props, "tag": "HOOK",
         "narration": _narration(puzzle, "hook", hook_text + " Here is the puzzle.")},
        {"component": b2c, "props": b2p, "tag": "PATTERN",
         "narration": _narration(puzzle, "sequence", "Look at the terms and find the rule.")},
        {"component": "countdown", "tag": "YOUR TURN",
         "props": {"seconds": 5, "title": countdown_title, "prompt": countdown_prompt},
         "narration": _narration(puzzle, "countdown", "Lock in your answer before the ring closes.")},
        {"component": b4c, "props": b4p, "tag": "SOLUTION",
         "narration": _narration(puzzle, "solution", f"The answer is {answer}.")},
        {"component": "payoff", "tag": "ANSWER",
         "props": {"answer": str(answer), "kicker": "THE ANSWER IS",
                   "recap": "Did you get it before the timer?", "teaser": payoff_teaser},
         "narration": _narration(puzzle, "payoff", f"{answer}. Did you get it? Follow for more.")},
        {"component": "hook_question", "tag": "LOOP",
         "props": {"badge": "YOUR TURN", "question": "What comes next?",
                   "terms": loop_terms, "hint": "Answer in the comments.",
                   "label": "LOOP PUZZLE · NEW SEQUENCE", "micro": "NO TIMER · JUST LOGIC",
                   "swipe": "Follow for the next puzzle"},
         "narration": _narration(puzzle, "loop", "Your turn. What comes next?")},
    ]

    scenes = []
    max_on_screen = int(cfg.get("video", {}).get("max_words_scene", 10))
    for i, (scene, dur) in enumerate(zip(raw_scenes, durations), start=1):
        scene = dict(scene)
        scene["id"] = i
        scene["name"] = scene["tag"].lower().replace(" ", "_")
        scene["duration"] = dur
        scene["title"] = scene.get("title") or scene["tag"].title()
        scene["narration"] = fit_narration(scene.get("narration", ""), dur, wps)
        scene["props"] = _trim_on_screen(dict(scene.get("props") or {}), max_on_screen)
        scenes.append(scene)

    storyboard = {
        "title": puzzle.get("title") or "Can you solve it?",
        "concept": concept.get("id"),
        "concept_name": concept.get("name"),
        "puzzle_type": ptype,
        "hook": {"chosen": hook_text, "badge": badge, "best": best_hook,
                 "variants": (hook or {}).get("variants", [])},
        "duration": duration,
        "loop_ending": loop_terms,
        "scenes": scenes,
    }
    log.info("Storyboard: %d scenes | durations %s | hook=%r",
             len(scenes), [s["duration"] for s in scenes], hook_text)
    return storyboard
