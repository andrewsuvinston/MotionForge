"""Layout engine, occupancy, narration fit and plan-vs-render consistency tests."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.consistency import answer_in_text, check_rendered, check_storyboard
from core.layout import (compute_layout, css_variables, merge_intervals,
                         occupancy_ok, occupancy_ratio, scale_for_frame,
                         vertical_stack_plan)
from core.script import (build_storyboard, distribute_durations, fit_narration,
                         _hook_hero)

VIDEO = {
    "safe_top": 0.08, "safe_bottom": 0.15, "headline_px": 84, "body_px": 52,
    "caption_px": 50, "min_font_px": 48,
}


def base_puzzle():
    return {
        "type": "number_series", "terms": [3, 7, 15, 31, 63], "answer": 127,
        "loop_terms": [2, 6, 12, 20, 30],
    }


def storyboard():
    return {
        "duration": 35.0,
        "scenes": [
            {"id": 1, "tag": "HOOK", "duration": 5.0,
             "narration": "What comes next?", "props": {"terms": [3, 7, 15, 31, 63]}},
            {"id": 2, "tag": "PATTERN", "duration": 7.0,
             "narration": "Look at the gaps.", "props": {"terms": [3, 7, 15, 31, 63]}},
            {"id": 3, "tag": "YOUR TURN", "duration": 6.0,
             "narration": "Lock it in.", "props": {}},
            {"id": 4, "tag": "SOLUTION", "duration": 9.0,
             "narration": "The next number is one hundred twenty-seven.",
             "props": {"answer": "127"}},
            {"id": 5, "tag": "ANSWER", "duration": 4.0,
             "narration": "One hundred twenty-seven.", "props": {"answer": "127"}},
            {"id": 6, "tag": "LOOP", "duration": 4.0,
             "narration": "Your turn.", "props": {"terms": [2, 6, 12, 20, 30]}},
        ],
    }


# ---------------------------------------------------------------- layout
def test_layout_safe_areas_and_fonts():
    layout = compute_layout(1080, 1920, VIDEO)
    assert layout.safe_top == round(1920 * 0.08)
    assert layout.safe_bottom == round(1920 * 0.15)
    assert layout.content_top == layout.safe_top
    assert layout.content_bottom == 1920 - layout.safe_bottom
    assert layout.headline_px == 84
    assert layout.body_px == 52
    assert layout.caption_px == 50
    assert layout.content_height == 1920 - layout.safe_top - layout.safe_bottom


def test_layout_fonts_scale_with_frame():
    small = compute_layout(540, 960, VIDEO)
    assert small.headline_px == round(84 * 540 / 1080)
    assert small.body_px == round(52 * 540 / 1080)
    assert scale_for_frame(84, 1080) == 84


def test_css_variables_include_every_size():
    css = css_variables(compute_layout(1080, 1920, VIDEO))
    for token in ("--safe-top", "--safe-bottom", "--headline", "--body",
                  "--caption", "--min-font", "--gutter", "--gap"):
        assert token in css


def test_occupancy_union_and_floor():
    rects = [{"y": 154, "h": 700, "w": 900}, {"y": 800, "h": 400, "w": 900, "opacity": 1.0},
             {"y": 820, "h": 300, "w": 900, "opacity": 0.0}]
    ratio = occupancy_ratio(rects, 1920)
    assert abs(ratio - 1046 / 1920) < 1e-6
    ok, measured = occupancy_ok(rects, 1920, 0.5)
    assert ok and measured == ratio


def test_occupancy_below_floor():
    ok, ratio = occupancy_ok([{"y": 0, "h": 600, "w": 900}], 1920, 0.55)
    assert not ok and ratio < 0.55


def test_merge_intervals_and_stack():
    assert merge_intervals([(0, 10), (5, 20), (30, 40)]) == [(0, 20), (30, 40)]
    plan = vertical_stack_plan(3, 900, 30)
    assert len(plan) == 3
    assert plan[0]["y"] == 0 and plan[-1]["y"] + plan[-1]["height"] <= 900


# ---------------------------------------------------------------- narration
def test_distribute_durations_respects_minimum_and_total():
    durations = distribute_durations(12.0, [5, 7, 6, 9, 4, 4])
    assert all(d >= 2.0 for d in durations)
    assert abs(sum(durations) - 12.0) < 1e-6
    long = distribute_durations(35.0, [5, 7, 6, 9, 4, 4])
    assert all(d >= 2.0 for d in long) and abs(sum(long) - 35.0) < 1e-6


def test_fit_narration_keeps_answer_sentence():
    text = ("The gaps are the odd numbers. Twenty-six plus eleven is thirty-seven. "
            "The answer is thirty-seven.")
    fitted = fit_narration(text, 2.0, 2.5)
    assert "thirty-seven" in fitted
    assert len(fitted.split()) <= max(6, int(round(2.0 * 2.5)))


def test_hook_hero_for_non_series_types():
    assert _hook_hero({"type": "percentage", "payload": {"percent": 25, "base": 80}}) == "25% of 80"
    assert _hook_hero({"type": "ratio", "payload": {"ratio": [3, 4]}}) == "3 : 4"
    assert _hook_hero({"type": "river"}) == "WOLF · GOAT · CABBAGE"


def test_storyboard_loop_has_follow_footer():
    concept = {"id": "series_trap", "name": "Number Series Trap"}
    hook = {"best": {"text": "What comes next?", "badge": "SPOT THE PATTERN"},
            "variants": []}
    sb = build_storyboard(base_puzzle(), concept, hook, 35.0, {"video": {"wps": 2.5}})
    loop = sb["scenes"][-1]
    assert loop["tag"] == "LOOP"
    assert "Follow" in loop["props"]["swipe"]
    assert sb["scenes"][0]["props"]["terms"] == base_puzzle()["terms"]


# ---------------------------------------------------------------- consistency
def test_clean_storyboard_has_no_problems():
    assert check_storyboard(storyboard(), base_puzzle(), {"video": {"wps": 2.5}}) == []


def test_answer_mismatch_detected():
    sb = storyboard()
    sb["scenes"][3]["props"]["answer"] = "126"
    codes = {p["code"] for p in check_storyboard(sb, base_puzzle(), {"video": {}})}
    assert "answer_mismatch" in codes


def test_terms_mismatch_detected():
    sb = storyboard()
    sb["scenes"][1]["props"]["terms"] = [3, 7, 15, 31, 64]
    codes = {p["code"] for p in check_storyboard(sb, base_puzzle(), {"video": {}})}
    assert "terms_mismatch" in codes


def test_missing_answer_narration_detected():
    sb = storyboard()
    sb["scenes"][3]["narration"] = "Multiply by two and add one."
    codes = {p["code"] for p in check_storyboard(sb, base_puzzle(), {"video": {}})}
    assert "narration_missing_answer" in codes


def test_dense_narration_warning():
    sb = storyboard()
    sb["scenes"][0]["duration"] = 1.0
    sb["scenes"][0]["narration"] = "one two three four five six"
    probs = check_storyboard(sb, base_puzzle(), {"video": {"wps": 2.5}})
    assert "narration_too_dense" in {p["code"] for p in probs}


def test_answer_in_text_accepts_words_and_digits():
    assert answer_in_text(127, "The answer is 127.")
    assert answer_in_text(127, "one hundred twenty-seven")
    assert not answer_in_text(127, "The answer is 126.")


def test_rendered_script_undefined_ignored(tmp_path):
    html = ("<html><body><h1>What comes next?</h1>"
            "<script>const x = o.dy === undefined ? 40 : o.dy;</script></body></html>")
    p = tmp_path / "scene.html"
    p.write_text(html, encoding="utf-8")
    probs = check_rendered([p], base_puzzle(), {"scenes": [{"tag": "HOOK"}]})
    assert "bad_value" not in {x["code"] for x in probs}


def test_rendered_visible_nan_detected(tmp_path):
    html = "<html><body><h1>Score NaN</h1></body></html>"
    p = tmp_path / "scene.html"
    p.write_text(html, encoding="utf-8")
    probs = check_rendered([p], base_puzzle(), {"scenes": [{"tag": "HOOK"}]})
    assert "bad_value" in {x["code"] for x in probs}
