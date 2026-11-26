"""Plan-vs-render consistency checks.

These catch the class of bug where the plan says one number but the rendered
scene (or the narration) says another. They are pure functions and run before
encoding, so a mismatch never ships silently.
"""
from __future__ import annotations

import re
from pathlib import Path

ONES = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine",
        "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen",
        "seventeen", "eighteen", "nineteen"]
TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]


def int_to_words(n: int) -> str:
    n = int(n)
    if n < 0:
        return "minus " + int_to_words(-n)
    if n < 20:
        return ONES[n]
    if n < 100:
        t, o = divmod(n, 10)
        return TENS[t] + (("-" + ONES[o]) if o else "")
    if n < 1000:
        h, rest = divmod(n, 100)
        return ONES[h] + " hundred" + ((" " + int_to_words(rest)) if rest else "")
    if n < 1_000_000:
        th, rest = divmod(n, 1000)
        return int_to_words(th) + " thousand" + ((" " + int_to_words(rest)) if rest else "")
    return str(n)


def words(text: str) -> list[str]:
    return re.findall(r"\S+", text or "")


def word_count(text: str) -> int:
    return len(words(text))


def sentences(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.!?])\s+", (text or "").strip()) if s]


def answer_in_text(answer, text: str) -> bool:
    if answer is None:
        return False
    if isinstance(answer, (list, tuple)):
        return all(answer_in_text(a, text) for a in answer)
    low = (text or "").lower()
    if isinstance(answer, (int, float)):
        if re.search(rf"(?<!\d){re.escape(str(int(answer)))}(?!\d)", low):
            return True
        return int_to_words(int(answer)).lower() in low
    return str(answer).lower() in low


def _problem(code: str, message: str, severity: str = "error") -> dict:
    return {"code": code, "message": message, "severity": severity}


def _prop_strings(props: dict, skip: set[str] | None = None) -> list[tuple[str, str]]:
    skip = skip or set()
    out = []

    def walk(value, path):
        if isinstance(value, dict):
            for k, v in value.items():
                walk(v, f"{path}.{k}" if path else k)
        elif isinstance(value, list):
            for i, v in enumerate(value):
                walk(v, f"{path}[{i}]")
        elif isinstance(value, str):
            out.append((path, value))

    walk(props or {}, "")
    return [(p, s) for p, s in out if p.split(".")[0].split("[")[0] not in skip]


def check_storyboard(storyboard: dict, puzzle: dict, cfg: dict) -> list[dict]:
    problems: list[dict] = []
    video = cfg.get("video", {})
    wps = float(video.get("wps", 2.5))
    max_sentence = int(video.get("max_sentence_words", 14))
    max_on_screen = int(video.get("max_words_scene", 10))
    scenes = storyboard.get("scenes") or []

    total = sum(float(s.get("duration", 0)) for s in scenes)
    expected = float(storyboard.get("duration", total))
    if abs(total - expected) > 0.1:
        problems.append(_problem("duration_mismatch",
                                 f"scenes sum to {total:.2f}s but video duration is {expected:.2f}s"))

    for scene in scenes:
        sid = scene.get("id")
        duration = max(0.001, float(scene.get("duration", 0)))
        narration = scene.get("narration", "") or ""
        wps_actual = word_count(narration) / duration
        if wps_actual > wps + 0.1:
            problems.append(_problem(
                "narration_too_dense",
                f"scene {sid}: {wps_actual:.2f} words/s > {wps:.2f} budget", "warning"))
        for sentence in sentences(narration):
            if word_count(sentence) > max_sentence:
                problems.append(_problem(
                    "sentence_too_long",
                    f"scene {sid}: sentence has {word_count(sentence)} words > {max_sentence}"))
        props = scene.get("props") or {}
        for path, value in _prop_strings(props, skip={"terms"}):
            if path.startswith(("answer", "kicker")) and len(words(value)) > 6:
                continue
            if word_count(value) > max_on_screen:
                problems.append(_problem(
                    "onscreen_text_too_long",
                    f"scene {sid}: {path} has {word_count(value)} words > {max_on_screen}"))

    by_tag = {s.get("tag"): s for s in scenes}
    answer = puzzle.get("answer")

    sol = by_tag.get("SOLUTION")
    if sol:
        sol_answer = (sol.get("props") or {}).get("answer")
        if sol_answer is not None and str(sol_answer).strip() != str(answer).strip():
            problems.append(_problem(
                "answer_mismatch",
                f"solution scene says {sol_answer!r} but verified answer is {answer!r}"))
        if not answer_in_text(answer, sol.get("narration", "")):
            problems.append(_problem(
                "narration_missing_answer",
                f"solution narration does not state the verified answer {answer!r}"))
    else:
        problems.append(_problem("missing_solution", "storyboard has no SOLUTION scene"))

    payoff = by_tag.get("ANSWER")
    if payoff:
        pay_answer = (payoff.get("props") or {}).get("answer")
        if pay_answer is not None and str(pay_answer).strip() != str(answer).strip():
            problems.append(_problem(
                "answer_mismatch",
                f"payoff scene says {pay_answer!r} but verified answer is {answer!r}"))
    else:
        problems.append(_problem("missing_payoff", "storyboard has no ANSWER/payoff scene"))

    if puzzle.get("type") == "number_series":
        terms = puzzle.get("terms") or []
        pattern = by_tag.get("PATTERN")
        hook = by_tag.get("HOOK")
        if pattern:
            prop_terms = (pattern.get("props") or {}).get("terms")
            if prop_terms is not None and [str(t) for t in prop_terms] != [str(t) for t in terms]:
                problems.append(_problem(
                    "terms_mismatch",
                    f"pattern scene terms {prop_terms} != verified terms {terms}"))
        if hook:
            prop_terms = (hook.get("props") or {}).get("terms")
            if prop_terms is not None and [str(t) for t in prop_terms] != [str(t) for t in terms]:
                problems.append(_problem(
                    "terms_mismatch", f"hook scene terms {prop_terms} != verified terms {terms}"))
        loop = by_tag.get("LOOP")
        if loop:
            loop_terms = (loop.get("props") or {}).get("terms") or []
            if [str(t) for t in loop_terms] == [str(t) for t in terms]:
                problems.append(_problem("loop_repeats_puzzle",
                                         "loop ending repeats the same sequence as the hook"))

    return problems


def check_rendered(scene_paths: list[Path], puzzle: dict, storyboard: dict) -> list[dict]:
    """Check the actual scene HTML: setTime contract, answer/terms presence, no NaN."""
    problems: list[dict] = []
    answer = puzzle.get("answer")
    scene_tags = [s.get("tag") for s in (storyboard.get("scenes") or [])]
    for i, path in enumerate(scene_paths):
        try:
            html = Path(path).read_text(encoding="utf-8")
        except OSError as exc:
            problems.append(_problem("scene_unreadable", f"{path}: {exc}"))
            continue
        tag = scene_tags[i] if i < len(scene_tags) else f"scene {i + 1}"
        if "window.setTime" not in html:
            problems.append(_problem("missing_settime", f"{tag}: window.setTime is missing"))
        if "window.SCENE_DURATION" not in html:
            problems.append(_problem("missing_duration", f"{tag}: SCENE_DURATION is missing"))
        # The motion library deliberately contains `undefined` guards, so only
        # inspect the rendered markup, never the script/style blocks.
        visible = re.sub(r"<script\b[^>]*>.*?</script>", " ", html, flags=re.S | re.I)
        visible = re.sub(r"<style\b[^>]*>.*?</style>", " ", visible, flags=re.S | re.I)
        if "undefined" in visible or "NaN" in visible:
            problems.append(_problem("bad_value", f"{tag}: rendered HTML contains undefined/NaN"))
        if tag in ("SOLUTION", "ANSWER"):
            if not answer_in_text(answer, html):
                problems.append(_problem("answer_not_rendered",
                                         f"{tag}: verified answer {answer!r} is not in the HTML"))
        if tag == "PATTERN" and puzzle.get("type") == "number_series":
            for term in puzzle.get("terms") or []:
                if not re.search(rf"(?<!\d){re.escape(str(term))}(?!\d)", html):
                    problems.append(_problem("term_not_rendered",
                                             f"{tag}: term {term} is not in the HTML"))
    return problems


def dedupe(problems: list[dict]) -> list[dict]:
    seen, out = set(), []
    for p in problems:
        key = (p.get("code"), p.get("message"))
        if key not in seen:
            seen.add(key)
            out.append(p)
    return out
