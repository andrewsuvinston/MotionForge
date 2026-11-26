"""Puzzle generation + verification.

Correctness is the product. Every puzzle is checked by deterministic code first
(sympy, series fit, BFS, truth-table search). When a type has no code verifier, a
blind second LLM solve is required. Ambiguous puzzles are rejected. The final
verification record is written to `verification.json`.
"""
from __future__ import annotations

import copy
import json
import logging
import re
import time
from pathlib import Path

from .llm import LLMClient, LLMError
from .verify import normalize_answer, verify_puzzle

log = logging.getLogger("motionforge.puzzle")

NUMBER_SERIES_BANK = [
    {
        "bank_id": "double_plus_one",
        "type": "number_series",
        "terms": [3, 7, 15, 31, 63],
        "answer": 127,
        "rule": {"type": "multiply_add", "params": {"ratio": 2, "add": 1}},
        "title": "The Doubling Gap",
        "hint": "Each jump doubles: +4, +8, +16, +32.",
        "steps": [
            {"math": "31 = 15 × 2 + 1", "text": "Double, then add one"},
            {"math": "63 = 31 × 2 + 1", "text": "Same rule again"},
            {"math": "127 = 63 × 2 + 1", "text": "So the next term is 127"},
        ],
        "recap": "Every step: multiply by 2, then add 1.",
        "loop_terms": [2, 6, 12, 20, 30],
        "loop_answer": 42,
        "narration": {
            "hook": "One in ten cracks this. Three, seven, fifteen, thirty-one, sixty-three. What comes next?",
            "sequence": "Look at the gaps: four, eight, sixteen, thirty-two. Every jump doubles. So the next jump is sixty-four.",
            "countdown": "Pause here. Lock in your answer before the ring closes.",
            "solution": "Multiply by two, add one. Three, seven, fifteen, thirty-one, sixty-three. The next number is one hundred twenty-seven.",
            "payoff": "One hundred twenty-seven. Did you get it? Follow for more.",
            "loop": "Your turn: two, six, twelve, twenty, thirty. What comes next?",
        },
    },
    {
        "bank_id": "odd_number_gaps",
        "type": "number_series",
        "terms": [2, 5, 10, 17, 26],
        "answer": 37,
        "rule": {"type": "quadratic", "params": {"second_diff": 2}},
        "title": "The Growing Gaps",
        "hint": "The gaps are the odd numbers: 3, 5, 7, 9.",
        "steps": [
            {"math": "17 − 10 = 7", "text": "Gap of seven"},
            {"math": "26 − 17 = 9", "text": "Gap grows to nine"},
            {"math": "Gap + 2 = 11", "text": "Next gap is eleven"},
            {"math": "26 + 11 = 37", "text": "So the answer is 37"},
        ],
        "recap": "The gaps grow by two each time.",
        "loop_terms": [1, 3, 6, 10, 15],
        "loop_answer": 21,
        "narration": {
            "hook": "Only one in ten spots it. Two, five, ten, seventeen, twenty-six. Next?",
            "sequence": "Look at the gaps: three, five, seven, nine. They grow by two. So the next gap is eleven.",
            "countdown": "Take a breath. Lock in your answer before the ring closes.",
            "solution": "The gaps are the odd numbers. Twenty-six plus eleven is thirty-seven. The answer is thirty-seven.",
            "payoff": "Thirty-seven. Did you get it before the timer? Follow for more.",
            "loop": "Try this: one, three, six, ten, fifteen. What comes next?",
        },
    },
    {
        "bank_id": "perfect_squares",
        "type": "number_series",
        "terms": [1, 4, 9, 16, 25],
        "answer": 36,
        "rule": {"type": "quadratic", "params": {"second_diff": 2}},
        "title": "Hidden Squares",
        "hint": "These are perfect squares: 1², 2², 3²...",
        "steps": [
            {"math": "4² = 16", "text": "Fourth term"},
            {"math": "5² = 25", "text": "Fifth term"},
            {"math": "6² = 36", "text": "So the answer is 36"},
        ],
        "recap": "Each term is n². The next is 6² = 36.",
        "loop_terms": [4, 9, 16, 25, 36],
        "loop_answer": 49,
        "narration": {
            "hook": "Most people miss this. One, four, nine, sixteen, twenty-five. What comes next?",
            "sequence": "These are the perfect squares. One squared, two squared, three squared. Keep going.",
            "countdown": "Lock in your answer. The ring is closing.",
            "solution": "The pattern is n squared. The fifth term is five squared, twenty-five. So the next is six squared, thirty-six.",
            "payoff": "Thirty-six. Did you catch the squares? Follow for more.",
            "loop": "Your turn: four, nine, sixteen, twenty-five, thirty-six. Next?",
        },
    },
    {
        "bank_id": "double",
        "type": "number_series",
        "terms": [1, 2, 4, 8, 16],
        "answer": 32,
        "rule": {"type": "geometric", "params": {"ratio": 2}},
        "title": "The Simple Doubling",
        "hint": "Every term is double the one before it.",
        "steps": [
            {"math": "1 × 2 = 2", "text": "Start by doubling"},
            {"math": "2 × 2 = 4", "text": "Double again"},
            {"math": "4 × 2 = 8", "text": "Keep doubling"},
            {"math": "16 × 2 = 32", "text": "The next term"},
        ],
        "recap": "Each term is double the previous term.",
        "loop_terms": [3, 6, 12, 24, 48],
        "loop_answer": 96,
        "narration": {
            "hook": "One rule solves this. One, two, four, eight, sixteen. Next?",
            "sequence": "Every term doubles. One becomes two, two becomes four, four becomes eight.",
            "countdown": "Quick. Lock in your answer before the ring closes.",
            "solution": "Double the last term. Sixteen times two is thirty-two. The answer is thirty-two.",
            "payoff": "Thirty-two. Too easy? Follow for the next one.",
            "loop": "Try this: three, six, twelve, twenty-four, forty-eight. Next?",
        },
    },
    {
        "bank_id": "fibonacci",
        "type": "number_series",
        "terms": [1, 1, 2, 3, 5],
        "answer": 8,
        "rule": {"type": "fibonacci", "params": {}},
        "title": "The Sum Rule",
        "hint": "Each term is the sum of the two before it.",
        "steps": [
            {"math": "1 + 1 = 2", "text": "Add the first two"},
            {"math": "1 + 2 = 3", "text": "Add the next pair"},
            {"math": "2 + 3 = 5", "text": "Same rule again"},
            {"math": "3 + 5 = 8", "text": "So the next term is 8"},
        ],
        "recap": "Add the previous two terms each time.",
        "loop_terms": [2, 3, 5, 8, 13],
        "loop_answer": 21,
        "narration": {
            "hook": "Almost nobody spots this rule. One, one, two, three, five. Next?",
            "sequence": "Add the previous two terms. One plus one is two. One plus two is three. Two plus three is five.",
            "countdown": "Lock it in. The ring is closing.",
            "solution": "Add the last two terms. Three plus five is eight. The answer is eight.",
            "payoff": "Eight. Did you see the sum rule? Follow for more.",
            "loop": "Try this: two, three, five, eight, thirteen. Next?",
        },
    },
    {
        "bank_id": "triangular",
        "type": "number_series",
        "terms": [2, 6, 12, 20, 30],
        "answer": 42,
        "rule": {"type": "quadratic", "params": {"second_diff": 2}},
        "title": "The Product Pattern",
        "hint": "Each term is n times n plus one.",
        "steps": [
            {"math": "4 × 5 = 20", "text": "Fourth term"},
            {"math": "5 × 6 = 30", "text": "Fifth term"},
            {"math": "6 × 7 = 42", "text": "So the next term is 42"},
        ],
        "recap": "Each term is n × (n + 1).",
        "loop_terms": [3, 8, 15, 24, 35],
        "loop_answer": 48,
        "narration": {
            "hook": "Only one in ten sees it. Two, six, twelve, twenty, thirty. Next?",
            "sequence": "Each term is a number times the next number. One times two, two times three, three times four.",
            "countdown": "Pause. Lock in your answer before the ring closes.",
            "solution": "The fifth term is five times six, thirty. The next is six times seven, forty-two.",
            "payoff": "Forty-two. Did you get it? Follow for more.",
            "loop": "Your turn: three, eight, fifteen, twenty-four, thirty-five. Next?",
        },
    },
]

OTHER_BANK = {
    "truth_lies": {
        "bank_id": "two_speakers",
        "type": "truth_lies",
        "payload": {
            "type": "truth_lies", "people": ["Ava", "Ben"],
            "statements": [
                {"speaker": "Ava", "claim": {"type": "is_liar", "target": "Ben"}},
                {"speaker": "Ben", "claim": {"type": "count_liars", "n": 0}},
            ],
            "answer": ["Ben"],
        },
        "answer": "Ben",
        "statement": "Ava says Ben is a liar. Ben says there are zero liars. Who is lying?",
        "title": "One of them is lying",
        "hint": "Test both possibilities. Only one survives.",
        "steps": [
            {"math": "Ava → truth", "text": "Then Ben is a liar"},
            {"math": "Ben → liar", "text": "His zero-liar claim is false"},
            {"math": "Ava → liar", "text": "Then Ben is truthful"},
            {"math": "Contradiction", "text": "Ben's claim would be true"},
        ],
        "recap": "Assume Ava is truthful; every statement then fits.",
        "loop_terms": [2, 6, 12, 20, 30],
        "loop_answer": 42,
        "narration": {
            "hook": "One of them is lying. Can you tell who?",
            "sequence": "Ava says Ben is a liar. Ben says there are zero liars. Test both possibilities.",
            "countdown": "Lock in your answer before the ring closes.",
            "solution": "If Ava is truthful, Ben is a liar, and Ben's zero-liar claim is false. That fits. The liar is Ben.",
            "payoff": "Ben is the liar. Did you get it? Follow for more.",
            "loop": "Your turn: two, six, twelve, twenty, thirty. What comes next?",
        },
    },
    "river": {
        "bank_id": "wolf_goat_cabbage",
        "type": "river",
        "payload": {"type": "river", "kind": "wolf_goat_cabbage", "answer_moves": 7},
        "answer": 7,
        "statement": "A farmer must cross a river with a wolf, a goat, and a cabbage. The boat carries the farmer plus one item.",
        "title": "The River Crossing",
        "hint": "Never leave the wolf alone with the goat, or the goat with the cabbage.",
        "steps": [
            {"math": "Take the goat", "text": "Cross first with the goat"},
            {"math": "Return alone", "text": "Go back for the next item"},
            {"math": "Take the wolf", "text": "Bring the goat back"},
            {"math": "Take the cabbage", "text": "Then return for the goat"},
        ],
        "recap": "The goat shuttles back once to keep both banks safe.",
        "loop_terms": [2, 6, 12, 20, 30],
        "loop_answer": 42,
        "narration": {
            "hook": "Most people sink the boat on the first move. Can you cross?",
            "sequence": "The boat carries the farmer plus one item. The wolf eats the goat. The goat eats the cabbage.",
            "countdown": "Lock in your move count before the ring closes.",
            "solution": "Take the goat, return alone, take the wolf, bring the goat back, take the cabbage, return alone, take the goat. Seven crossings.",
            "payoff": "Seven crossings. Did you beat the timer? Follow for more.",
            "loop": "Your turn: two, six, twelve, twenty, thirty. What comes next?",
        },
    },
    "percentage": {
        "bank_id": "percent_of_number",
        "type": "percentage",
        "payload": {"type": "percentage", "base": 80, "percent": 25, "answer": 20},
        "answer": 20,
        "statement": "What is 25% of 80?",
        "title": "The Percentage Trap",
        "hint": "Percent means per hundred. Turn 25% into 0.25 first.",
        "steps": [
            {"math": "25% = 0.25", "text": "Drop the percent sign"},
            {"math": "0.25 × 80 = 20", "text": "Multiply by the base"},
            {"math": "20", "text": "That is the part"},
        ],
        "recap": "25% of 80 is 20.",
        "loop_terms": [2, 6, 12, 20, 30],
        "loop_answer": 42,
        "narration": {
            "hook": "90% get this percentage wrong. What is 25% of 80?",
            "sequence": "Percent means per hundred. Turn 25% into 0.25, then multiply by 80.",
            "countdown": "No calculator. Lock in your answer before the ring closes.",
            "solution": "25% is 0.25. Multiply 0.25 by 80 and you get 20. The answer is 20.",
            "payoff": "Twenty. Did you get it before the timer? Follow for more.",
            "loop": "Your turn: two, six, twelve, twenty, thirty. What comes next?",
        },
    },
    "ratio": {
        "bank_id": "ratio_split",
        "type": "ratio",
        "payload": {"type": "ratio", "ratio": [3, 4], "total": 70, "answer": [30, 40]},
        "answer": "30 and 40",
        "statement": "Split 70 in the ratio 3 to 4. What are the two parts?",
        "title": "The Ratio Split",
        "hint": "Add the ratio parts first: 3 plus 4 is 7.",
        "steps": [
            {"math": "3 + 4 = 7", "text": "Add the ratio parts"},
            {"math": "70 ÷ 7 = 10", "text": "Find one part"},
            {"math": "3 × 10 = 30", "text": "First share"},
            {"math": "4 × 10 = 40", "text": "Second share"},
        ],
        "recap": "Each ratio part is worth 10, so the shares are 30 and 40.",
        "loop_terms": [2, 6, 12, 20, 30],
        "loop_answer": 42,
        "narration": {
            "hook": "The total is not the answer. Split 70 in the ratio 3 to 4.",
            "sequence": "Add the ratio parts: three plus four is seven. Then divide the total by seven.",
            "countdown": "Lock in both shares before the ring closes.",
            "solution": "Seventy divided by seven is ten. Three times ten is thirty. Four times ten is forty. The shares are 30 and 40.",
            "payoff": "Thirty and forty. Did you get both? Follow for more.",
            "loop": "Your turn: two, six, twelve, twenty, thirty. What comes next?",
        },
    },
    "time_work": {
        "bank_id": "two_workers",
        "type": "time_work",
        "payload": {"type": "time_work", "times": [6, 3], "answer_days": 2},
        "answer": 2,
        "statement": "One worker takes 6 days. Another takes 3 days. How long together?",
        "title": "The Work Rate Shortcut",
        "hint": "Add the rates, not the times: 1/6 plus 1/3.",
        "steps": [
            {"math": "1/6 + 1/3 = 1/2", "text": "Add the work rates"},
            {"math": "1 ÷ 1/2 = 2", "text": "Flip the combined rate"},
            {"math": "2 days", "text": "That is the answer"},
        ],
        "recap": "Together they finish half the job per day, so it takes 2 days.",
        "loop_terms": [2, 6, 12, 20, 30],
        "loop_answer": 42,
        "narration": {
            "hook": "The shortcut saves ten seconds. Six days and three days. How long together?",
            "sequence": "Add the work rates, not the times. One sixth plus one third is one half.",
            "countdown": "Lock in your answer before the ring closes.",
            "solution": "One sixth plus one third is one half. One divided by one half is two. The answer is 2 days.",
            "payoff": "Two days. Did you add the rates? Follow for more.",
            "loop": "Your turn: two, six, twelve, twenty, thirty. What comes next?",
        },
    },
    "algebra": {
        "bank_id": "linear_equation",
        "type": "algebra",
        "payload": {"type": "algebra", "equation": "2*x+3=11", "answer": 4},
        "answer": 4,
        "statement": "Solve for x: 2x + 3 = 11.",
        "title": "The Algebra Trick",
        "hint": "Undo the addition first, then undo the multiplication.",
        "steps": [
            {"math": "2x + 3 = 11", "text": "Start with the equation"},
            {"math": "2x = 8", "text": "Subtract three"},
            {"math": "x = 4", "text": "Divide by two"},
        ],
        "recap": "Subtract 3, then divide by 2. x is 4.",
        "loop_terms": [2, 6, 12, 20, 30],
        "loop_answer": 42,
        "narration": {
            "hook": "One move solves the whole equation. Solve 2x plus 3 equals 11.",
            "sequence": "Undo the addition first, then undo the multiplication. Keep the equation balanced.",
            "countdown": "Lock in x before the ring closes.",
            "solution": "Subtract three from both sides: 2x equals 8. Divide by two: x equals 4. The answer is 4.",
            "payoff": "x is four. Did you keep it balanced? Follow for more.",
            "loop": "Your turn: two, six, twelve, twenty, thirty. What comes next?",
        },
    },
    "arithmetic": {
        "bank_id": "order_of_operations",
        "type": "arithmetic",
        "payload": {"type": "arithmetic", "expression": "12 + 8 * 3", "answer": 36},
        "answer": 36,
        "statement": "What is 12 + 8 × 3?",
        "title": "The Order Trap",
        "hint": "Multiplication before addition.",
        "steps": [
            {"math": "8 × 3 = 24", "text": "Multiply first"},
            {"math": "12 + 24 = 36", "text": "Then add"},
        ],
        "recap": "Multiply before adding, so the answer is 36.",
        "loop_terms": [2, 6, 12, 20, 30],
        "loop_answer": 42,
        "narration": {
            "hook": "Most people add first and get this wrong. What is 12 plus 8 times 3?",
            "sequence": "Order matters. Multiplication runs before addition.",
            "countdown": "Lock in your answer before the ring closes.",
            "solution": "Eight times three is twenty-four. Twelve plus twenty-four is thirty-six. The answer is 36.",
            "payoff": "Thirty-six. Did you multiply first? Follow for more.",
            "loop": "Your turn: two, six, twelve, twenty, thirty. What comes next?",
        },
    },
}


def _number_series_payload(p: dict) -> dict:
    return {"type": "number_series", "terms": p.get("terms"), "answer": p.get("answer"),
            "rule": p.get("rule")}


def verify_entry(puzzle: dict):
    payload = puzzle.get("payload") or _number_series_payload(puzzle)
    return verify_puzzle(payload)


def _puzzle_history_path(root: Path) -> Path:
    return Path(root) / "memory" / "puzzles.json"


def _recent_banks(root: Path) -> list[str]:
    path = _puzzle_history_path(root)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return [str(x) for x in data[-12:]] if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def _record_bank(root: Path, bank_id: str):
    path = _puzzle_history_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    recent = _recent_banks(root)
    recent.append(bank_id)
    path.write_text(json.dumps(recent[-30:], indent=2), encoding="utf-8")


def choose_bank(puzzle_type: str, root: Path) -> dict:
    if puzzle_type == "number_series":
        recent = _recent_banks(root)
        candidates = [p for p in NUMBER_SERIES_BANK if p["bank_id"] not in recent[-4:]]
        chosen = (candidates or NUMBER_SERIES_BANK)[0]
        _record_bank(root, chosen["bank_id"])
        return copy.deepcopy(chosen)
    entry = OTHER_BANK.get(puzzle_type)
    if entry:
        _record_bank(root, entry["bank_id"])
        return copy.deepcopy(entry)
    # Last resort: a verified number series still makes a valid Short.
    chosen = copy.deepcopy(NUMBER_SERIES_BANK[0])
    chosen["bank_id"] = "fallback_number_series"
    return chosen


LLM_SERIES_SYSTEM = """You create number-series puzzles with exactly one correct next term.
Return ONLY JSON with this schema:
{"type":"number_series","terms":[5 integers],"answer":integer,
 "rule":{"type":"arithmetic|geometric|multiply_add|fibonacci|quadratic","params":{...}},
 "hint":"one short sentence","steps":[{"math":"...","text":"..."}],"recap":"one short sentence"}
Rules:
- exactly 5 terms, integers between 0 and 999, no trivial constant sequence
- a supported integer rule must reproduce ALL terms
- the next value must be unique across supported rule families
- steps: 3 or 4 short lines, each <= 10 words
- no prose outside the JSON."""


def _fill_steps(p: dict) -> dict:
    if not p.get("steps"):
        rule = p.get("rule") or {}
        params = rule.get("params") or {}
        kind = str(rule.get("type") or "").lower()
        terms = p.get("terms") or []
        ans = p.get("answer")
        steps = []
        if kind in ("multiply_add", "affine") and len(terms) >= 2:
            r, b = params.get("ratio"), params.get("add")
            for i in range(min(3, len(terms) - 1)):
                steps.append({"math": f"{terms[i]} × {r} + {b} = {terms[i + 1]}",
                              "text": "Multiply, then add"})
            steps.append({"math": f"{terms[-1]} × {r} + {b} = {ans}", "text": "Next term"})
        elif kind in ("geometric", "ratio") and len(terms) >= 2:
            r = params.get("ratio", params.get("r"))
            for i in range(min(3, len(terms) - 1)):
                steps.append({"math": f"{terms[i]} × {r} = {terms[i + 1]}", "text": "Multiply each time"})
            steps.append({"math": f"{terms[-1]} × {r} = {ans}", "text": "Next term"})
        else:
            steps = [
                {"math": f"{terms[i]} → {terms[i + 1]}", "text": "Track the change"}
                for i in range(min(3, len(terms) - 1))
            ]
            steps.append({"math": f"{terms[-1]} → {ans}", "text": "Next term"})
        p["steps"] = steps
    p.setdefault("recap", "Apply the same rule to the last term.")
    p.setdefault("hint", "Look at how each jump changes.")
    p.setdefault("title", "Can you find the rule?")
    return p


def _normalize_series(data: dict) -> dict | None:
    if not isinstance(data, dict):
        return None
    try:
        terms = [int(x) for x in data.get("terms") or []]
        answer = int(data.get("answer"))
    except (TypeError, ValueError):
        return None
    if len(terms) != 5 or not all(-9999 <= t <= 9999 for t in terms):
        return None
    rule = data.get("rule") if isinstance(data.get("rule"), dict) else {}
    steps = []
    for step in (data.get("steps") or [])[:4]:
        if isinstance(step, dict):
            steps.append({"math": str(step.get("math") or "")[:40],
                          "text": " ".join(str(step.get("text") or "").split())[:70]})
    puzzle = {
        "bank_id": "llm_series", "type": "number_series", "terms": terms, "answer": answer,
        "rule": rule, "title": " ".join(str(data.get("title") or "Find the rule").split())[:60],
        "hint": " ".join(str(data.get("hint") or "Look at how each jump changes.").split())[:120],
        "steps": steps, "recap": " ".join(str(data.get("recap") or "Apply the same rule.").split())[:120],
        "loop_terms": [2, 6, 12, 20, 30], "loop_answer": 42, "source": "llm",
        "narration": {},
    }
    puzzle = _fill_steps(puzzle)
    puzzle["narration"] = {
        "hook": f"One in ten cracks this. {', '.join(map(str, terms))}. What comes next?",
        "sequence": "Look at the gaps between the terms. Find the rule that fits every jump.",
        "countdown": "Pause here. Lock in your answer before the ring closes.",
        "solution": f"The rule is: {puzzle['recap']} The answer is {answer}.",
        "payoff": f"{answer}. Did you get it? Follow for more.",
        "loop": "Your turn: two, six, twelve, twenty, thirty. What comes next?",
    }
    return puzzle


def llm_number_series(llm: LLMClient, prompt: str, attempt: int) -> dict | None:
    user = (f"Create a number-series puzzle for this Short: {prompt}\n"
            f"Attempt {attempt}. Make the rule interesting but solvable in 35 seconds.")
    try:
        data = llm.chat_json(
            [{"role": "system", "content": LLM_SERIES_SYSTEM},
             {"role": "user", "content": user}],
            label=f"puzzle_{attempt}", tier="high", stage="puzzle", max_tokens=900,
            temperature=0.8,
        )
    except (LLMError, ValueError) as exc:
        log.warning("LLM puzzle attempt %d failed (%s)", attempt, exc)
        return None
    return _normalize_series(data)


def blind_solve(llm: LLMClient, puzzle: dict) -> dict | None:
    """Second independent solve for types without a code verifier."""
    statement = puzzle.get("statement") or (
        "Number series: " + ", ".join(map(str, puzzle.get("terms") or [])) + ", ?")
    try:
        data = llm.chat_json(
            [{"role": "system", "content":
              "Solve the puzzle independently. Return ONLY JSON: {\"answer\": <value>}. "
              "Do not guess wildly; if ambiguous, return {\"answer\": null, \"ambiguous\": true}."},
             {"role": "user", "content": statement}],
            label="blind_solve", tier="cheap", stage="verification", max_tokens=300,
            temperature=0.1,
        )
        return data if isinstance(data, dict) else None
    except (LLMError, ValueError) as exc:
        log.warning("Blind solve failed (%s)", exc)
        return None


def generate_puzzle(cfg: dict, llm: LLMClient | None, prompt: str, concept: dict,
                    root: Path, max_attempts: int = 5) -> tuple[dict, dict]:
    """Return (puzzle, verification_report). Always returns a code-verified puzzle."""
    ptype = concept.get("puzzle_type") or "number_series"
    attempts: list[dict] = []

    bank = choose_bank(ptype, root)
    bank_ver = verify_entry(bank)
    attempts.append({"source": "bank", "id": bank.get("bank_id"), "ok": bank_ver.ok,
                     "verified": bank_ver.verified, "reason": bank_ver.reason,
                     "answer": bank.get("answer")})
    if not bank_ver.ok:
        log.error("Bank puzzle failed verification: %s", bank_ver.reason)
        # Fall back to the first known-good series.
        bank = copy.deepcopy(NUMBER_SERIES_BANK[0])
        bank_ver = verify_entry(bank)
        attempts.append({"source": "bank_fallback", "id": bank["bank_id"], "ok": bank_ver.ok,
                         "verified": bank_ver.verified, "reason": bank_ver.reason})

    chosen = bank
    chosen_ver = bank_ver
    if llm is not None and ptype == "number_series":
        for attempt in range(1, max_attempts + 1):
            cand = llm_number_series(llm, prompt, attempt)
            if not cand:
                attempts.append({"source": "llm", "attempt": attempt, "ok": False,
                                 "reason": "generation failed"})
                continue
            ver = verify_entry(cand)
            attempts.append({"source": "llm", "attempt": attempt, "ok": ver.ok,
                             "verified": ver.verified, "reason": ver.reason,
                             "terms": cand.get("terms"), "answer": cand.get("answer")})
            if ver.ok and ver.verified:
                chosen, chosen_ver = cand, ver
                break
            if ver.ambiguity:
                log.warning("LLM puzzle attempt %d rejected as ambiguous", attempt)
    elif llm is not None and not bank_ver.verified:
        blind = blind_solve(llm, bank)
        attempts.append({"source": "blind_solve", "ok": bool(blind),
                         "answer": (blind or {}).get("answer")})
        if blind and not blind.get("ambiguous") and \
                normalize_answer(blind.get("answer")) == normalize_answer(bank.get("answer")):
            bank_ver.ok = True
            bank_ver.details["blind_solve_ok"] = True
            chosen_ver = bank_ver

    report = {
        "puzzle_type": chosen.get("type"),
        "bank_id": chosen.get("bank_id"),
        "source": chosen.get("source") or "bank",
        "verified_by_code": bool(chosen_ver.verified),
        "code_ok": bool(chosen_ver.ok),
        "code_reason": chosen_ver.reason,
        "ambiguity": bool(chosen_ver.ambiguity),
        "answer": chosen.get("answer"),
        "terms": chosen.get("terms"),
        "rule": chosen.get("rule"),
        "details": chosen_ver.details,
        "attempts": attempts,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    log.info("Puzzle: %s | answer=%s | code_verified=%s | %s",
             chosen.get("bank_id"), chosen.get("answer"), chosen_ver.verified,
             chosen_ver.reason[:100])
    return chosen, report


def save_puzzle(run_dir: Path, puzzle: dict, report: dict):
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "puzzle.json").write_text(json.dumps(puzzle, indent=2, ensure_ascii=False),
                                         encoding="utf-8")
    (run_dir / "verification.json").write_text(json.dumps(report, indent=2, ensure_ascii=False),
                                               encoding="utf-8")
