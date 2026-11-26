"""Judge panel gates and budget-manager behaviour."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.analytics import record_run, summary
from core.budget import BudgetManager
from core.judges import deterministic_panel, score_hook

CFG = {"quality": {"gate": {"min_judge": 7.0, "min_hook": 8.0, "max_rounds": 5,
                            "min_improvement": 0.3}},
       "video": {"wps": 2.5, "min_occupancy": 0.55, "max_sentence_words": 14,
                 "max_words_scene": 10}}


def storyboard():
    return {
        "duration": 35.0,
        "hook": {
            "chosen": "Only 1 in 10 can solve this?",
            "best": {"text": "Only 1 in 10 can solve this?",
                     "badge": "TRY THIS", "score": 7.0},
            "variants": [],
        },
        "loop_ending": [2, 6, 12, 20, 30],
        "scenes": [
            {"id": 1, "tag": "HOOK", "duration": 5.0,
             "narration": "What comes next?", "props": {}},
            {"id": 2, "tag": "PATTERN", "duration": 7.0,
             "narration": "Look at the gaps.", "props": {}},
            {"id": 3, "tag": "YOUR TURN", "duration": 6.0,
             "narration": "Lock it in.", "props": {}},
            {"id": 4, "tag": "SOLUTION", "duration": 9.0,
             "narration": "The answer is one hundred twenty-seven.", "props": {}},
            {"id": 5, "tag": "ANSWER", "duration": 4.0,
             "narration": "One hundred twenty-seven.", "props": {}},
            {"id": 6, "tag": "LOOP", "duration": 4.0,
             "narration": "Your turn.", "props": {}},
        ],
    }


def checks(occupancy=0.70, problems=None):
    return [{"scene": i, "occupancy": occupancy, "problems": problems or []}
            for i in range(1, 7)]


VERIFIED = {"verified_by_code": True, "code_ok": True, "answer": 127,
            "code_reason": "unique solution 127"}
AUDIO = {"voiceover": True, "music": "generated", "target_lufs": -14}


def test_hook_score_meets_gate():
    assert score_hook(storyboard()) >= 8.0


def test_panel_passes_when_all_evidence_is_strong():
    panel = deterministic_panel(storyboard(), VERIFIED, checks(), AUDIO, CFG)
    assert panel["scores"]["correctness"] == 10.0
    assert panel["scores"]["hook"] >= 8.0
    assert panel["scores"]["visual"] >= 7.0
    assert panel["passed"] and all(panel["gates"].values())


def test_panel_fails_on_weak_hook():
    sb = storyboard()
    sb["hook"]["chosen"] = "Can you solve this?"
    sb["hook"]["best"] = {"text": "Can you solve this?", "badge": "", "score": 3.0}
    panel = deterministic_panel(sb, VERIFIED, checks(), AUDIO, CFG)
    assert not panel["gates"]["hook_at_least_min"]
    assert not panel["passed"]


def test_panel_fails_on_unverified_correctness():
    panel = deterministic_panel(storyboard(), {"verified_by_code": False, "code_ok": False},
                                checks(), AUDIO, CFG)
    assert panel["scores"]["correctness"] < 10
    assert not panel["gates"]["correctness_perfect"]


def test_panel_fails_on_unmeasured_visual():
    panel = deterministic_panel(storyboard(), VERIFIED, [], AUDIO, CFG)
    assert panel["scores"]["visual"] < 7.0
    assert not panel["passed"]


def test_panel_penalises_layout_errors():
    bad = checks(occupancy=0.60, problems=[{"code": "overlap", "severity": "error"}])
    good = deterministic_panel(storyboard(), VERIFIED, checks(occupancy=0.60), AUDIO, CFG)
    worse = deterministic_panel(storyboard(), VERIFIED, bad, AUDIO, CFG)
    assert worse["scores"]["visual"] < good["scores"]["visual"]


# ---------------------------------------------------------------- budget
def test_budget_limits_and_persistence(tmp_path):
    cfg = {"budget": {"daily_request_limit": 3, "max_requests_per_run": 2,
                      "max_cost_usd": 0.5, "cache_enabled": True}}
    b = BudgetManager(cfg, tmp_path, run_id="run1")
    assert b.can_call() and b.remaining_today() == 3
    b.record("puzzle", "model", tokens=10, cost=0.01)
    assert b.run_calls == 1 and b.daily_used == 1
    assert b.can_call()
    b.record("hooks", "model", tokens=10, cost=0.01)
    assert b.remaining_run() == 0 and not b.can_call()
    # A fresh manager sees the persisted daily total.
    b2 = BudgetManager(cfg, tmp_path, run_id="run2")
    assert b2.daily_used == 2 and b2.remaining_today() == 1
    snap = b2.snapshot()
    assert snap["daily_limit"] == 3 and snap["run_requests"] == 0


def test_budget_cache_hits_do_not_consume_requests(tmp_path):
    cfg = {"budget": {"daily_request_limit": 5, "max_requests_per_run": 5,
                      "max_cost_usd": 1.0, "cache_enabled": True}}
    b = BudgetManager(cfg, tmp_path)
    b.put_cached("abc", "hello", "model")
    assert b.get_cached("abc") == "hello"
    assert b.cache_hits == 1
    b.record("puzzle", "model", cached=True)
    assert b.run_calls == 0 and b.daily_used == 0


def test_budget_estimate_warns_when_over_limit(tmp_path, caplog):
    cfg = {"budget": {"daily_request_limit": 2, "max_requests_per_run": 1,
                      "max_cost_usd": 1.0, "cache_enabled": False}}
    b = BudgetManager(cfg, tmp_path)
    assert not b.estimate("puzzle", 3)
    assert b.estimates["puzzle"] == 3


def test_budget_bar_and_snapshot(tmp_path):
    cfg = {"budget": {"daily_request_limit": 10, "max_requests_per_run": 10,
                      "max_cost_usd": 1.0, "cache_enabled": False}}
    b = BudgetManager(cfg, tmp_path)
    b.record("concept", "model", cost=0.02)
    bar = b.bar()
    assert "1/10" in bar and "[" in bar
    assert b.snapshot()["run_cost_usd"] == 0.02


# ---------------------------------------------------------------- analytics
def test_analytics_resume_does_not_double_count(tmp_path):
    report = {"run_id": "r1", "concept": "series_trap", "puzzle_type": "number_series",
              "duration": 35, "quality": "preview"}
    judge = {"overall": 9.0, "passed": True, "concept": "series_trap"}
    record_run(tmp_path, report, judge)
    record_run(tmp_path, report, judge)
    data = summary(tmp_path)
    assert data["runs"] == 1
    assert data["concepts"][0]["runs"] == 1
    assert data["concepts"][0]["avg_overall"] == 9.0
    assert data["concepts"][0]["gate_passes"] == 1


def test_analytics_tracks_multiple_runs(tmp_path):
    for i, score in enumerate((8.0, 9.0), start=1):
        record_run(tmp_path, {"run_id": f"r{i}", "concept": "series_trap",
                              "duration": 35, "quality": "preview"},
                   {"overall": score, "passed": True, "concept": "series_trap"})
    data = summary(tmp_path)
    assert data["runs"] == 2
    assert data["concepts"][0]["avg_overall"] == 8.5
    assert data["concepts"][0]["retention_proxy"] == 0.85
