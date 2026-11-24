"""Unit tests for core.checks (pure logic, synthetic DOM measurements)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.checks import Problem, contrast_ratio, parse_color, run_checks

CFG = {"checks": {
    "min_font_ratio": 0.022, "min_contrast_large": 3.0, "min_contrast_small": 4.5,
    "overlap_threshold": 0.2, "blank_stddev": 2.0, "blank_max_colors": 8,
    "edge_tolerance_px": 4,
}}


def el(idx=0, text="Hello", x=100, y=100, w=400, h=80, opacity=1.0, font=48,
       color="#F8FAFC", bg="#0B1220", path=None, parent=-1, ox=0, oy=0, weight="700"):
    return {
        "idx": idx, "parentTextIdx": parent, "path": path if path is not None else [0, idx],
        "tag": "DIV", "id": f"el{idx}", "cls": "", "text": text,
        "x": x, "y": y, "w": w, "h": h, "opacity": opacity, "fontSize": font,
        "fontWeight": weight, "color": color, "bg": bg, "overflowX": ox, "overflowY": oy,
    }


def measurement(elements, vw=1080, vh=1920, duration=5.0, has_settime=True):
    return {"vw": vw, "vh": vh, "elements": elements, "duration": duration, "hasSetTime": has_settime}


def codes(problems):
    return {p.code for p in problems}


def test_clean_scene_passes():
    m = measurement([el(0, "Title", y=200), el(1, "Caption", y=600, font=36)])
    assert run_checks(m, 5.0, [], [], CFG) == []


def test_offscreen_detected():
    m = measurement([el(0, x=1000, w=400)])  # right edge 1400 > 1080
    assert "offscreen" in codes(run_checks(m, 5.0, [], [], CFG))


def test_invisible_offscreen_ignored():
    m = measurement([el(0, x=-500, opacity=0.0)])  # mid slide-in, invisible
    assert "offscreen" not in codes(run_checks(m, 5.0, [], [], CFG))


def test_overlap_detected():
    m = measurement([el(0, "AAA", x=100, y=100, w=300, h=80),
                     el(1, "BBB", x=120, y=110, w=300, h=80)])
    assert "overlap" in codes(run_checks(m, 5.0, [], [], CFG))


def test_nested_elements_not_flagged_as_overlap():
    parent = el(0, "Outer", x=100, y=100, w=400, h=100, path=[0, 0])
    child = el(1, "Inner", x=110, y=110, w=200, h=60, path=[0, 0, 0], parent=0)
    assert "overlap" not in codes(run_checks(measurement([parent, child]), 5.0, [], [], CFG))


def test_low_contrast_detected():
    m = measurement([el(0, color="#777777", bg="#888888")])
    assert "low_contrast" in codes(run_checks(m, 5.0, [], [], CFG))


def test_small_font_detected():
    # min font = 1080 * 0.022 = 23.76px
    m = measurement([el(0, font=16)])
    assert "small_font" in codes(run_checks(m, 5.0, [], [], CFG))


def test_container_overflow_detected():
    m = measurement([el(0, ox=30)])
    assert "text_overflow" in codes(run_checks(m, 5.0, [], [], CFG))


def test_duration_mismatch():
    m = measurement([el(0)], duration=4.0)
    assert "duration_mismatch" in codes(run_checks(m, 5.0, [], [], CFG))


def test_missing_settime():
    m = measurement([el(0)], has_settime=False)
    assert "missing_settime" in codes(run_checks(m, 5.0, [], [], CFG))


def test_console_errors_reported():
    m = measurement([el(0)])
    probs = run_checks(m, 5.0, ["TypeError: x is null", "TypeError: x is null"], [], CFG)
    assert [p.code for p in probs].count("console_error") == 1  # deduped


def test_blank_frame_detected_only_after_settle():
    m = measurement([el(0)])
    early = [{"fraction": 0.02, "stddev": 0.0, "colors": 1}]
    late = [{"fraction": 0.75, "stddev": 0.0, "colors": 1}]
    assert "blank_frame" not in codes(run_checks(m, 5.0, [], early, CFG))
    assert "blank_frame" in codes(run_checks(m, 5.0, [], late, CFG))


def test_contrast_ratio_known_values():
    assert abs(contrast_ratio("#000000", "#FFFFFF") - 21.0) < 0.01
    assert contrast_ratio("#FFFFFF", "#FFFFFF") == 1.0
    assert contrast_ratio("rgb(0,0,0)", "rgb(255,255,255)") > 20


def test_parse_color_formats():
    assert parse_color("#fff") == (255, 255, 255, 1.0)
    assert parse_color("rgba(10, 20, 30, 0.5)") == (10, 20, 30, 0.5)
    assert parse_color("transparent")[3] == 0.0


def test_problem_serialization():
    p = Problem("overlap", "msg", scene=2)
    d = p.to_dict()
    assert d["code"] == "overlap" and d["scene"] == 2
