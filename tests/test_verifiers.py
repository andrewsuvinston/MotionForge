"""Unit tests for every code verifier, including wrong and ambiguous answers."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.verify import verify_puzzle


def kinds(result):
    return result.details.get("fits") or []


# ---------------------------------------------------------------- number series
def test_series_verified():
    r = verify_puzzle({"type": "number_series", "terms": [3, 7, 15, 31, 63],
                       "answer": 127})
    assert r.ok and r.verified and r.answer == 127


def test_series_wrong_answer_rejected():
    r = verify_puzzle({"type": "number_series", "terms": [3, 7, 15, 31, 63],
                       "answer": 128})
    assert not r.ok and r.verified and not r.ambiguity


def test_series_underdetermined_is_ambiguous():
    r = verify_puzzle({"type": "number_series", "terms": [3, 7, 15], "answer": 31})
    assert not r.ok and r.ambiguity


def test_series_wrong_stated_rule_rejected():
    r = verify_puzzle({"type": "number_series", "terms": [3, 7, 15, 31, 63],
                       "answer": 127,
                       "rule": {"type": "arithmetic", "params": {"diff": 4}}})
    assert not r.ok


# ---------------------------------------------------------------- arithmetic
def test_arithmetic_verified():
    r = verify_puzzle({"type": "arithmetic", "expression": "2 + 3 * 4", "answer": 14})
    assert r.ok and r.verified


def test_arithmetic_wrong_rejected():
    r = verify_puzzle({"type": "arithmetic", "expression": "2 + 3 * 4", "answer": 12})
    assert not r.ok


# ---------------------------------------------------------------- percentage
def test_percentage_verified():
    r = verify_puzzle({"type": "percentage", "base": 80, "percent": 25, "answer": 20})
    assert r.ok and r.verified


def test_percentage_wrong_rejected():
    r = verify_puzzle({"type": "percentage", "base": 80, "percent": 25, "answer": 25})
    assert not r.ok


# ---------------------------------------------------------------- ratio
def test_ratio_verified():
    r = verify_puzzle({"type": "ratio", "ratio": [3, 4], "total": 70,
                       "answer": [30, 40]})
    assert r.ok and r.verified


def test_ratio_wrong_rejected():
    r = verify_puzzle({"type": "ratio", "ratio": [3, 4], "total": 70,
                       "answer": [30, 30]})
    assert not r.ok


# ---------------------------------------------------------------- time & work
def test_time_work_verified():
    r = verify_puzzle({"type": "time_work", "times": [6, 3], "answer_days": 2})
    assert r.ok and r.verified


def test_time_work_wrong_rejected():
    r = verify_puzzle({"type": "time_work", "times": [6, 3], "answer_days": 2.5})
    assert not r.ok


# ---------------------------------------------------------------- algebra
def test_algebra_verified():
    r = verify_puzzle({"type": "algebra", "equation": "2*x+3=11", "answer": 4})
    assert r.ok and r.verified


def test_algebra_wrong_rejected():
    r = verify_puzzle({"type": "algebra", "equation": "2*x+3=11", "answer": 5})
    assert not r.ok


# ---------------------------------------------------------------- truth & lies
def test_truth_lies_verified():
    r = verify_puzzle({
        "type": "truth_lies", "people": ["Ava", "Ben"],
        "statements": [
            {"speaker": "Ava", "claim": {"type": "is_liar", "target": "Ben"}},
            {"speaker": "Ben", "claim": {"type": "count_liars", "n": 0}},
        ],
        "answer": ["Ben"],
    })
    assert r.ok and r.verified and r.answer == ["Ben"]


def test_truth_lies_wrong_rejected():
    r = verify_puzzle({
        "type": "truth_lies", "people": ["Ava", "Ben"],
        "statements": [
            {"speaker": "Ava", "claim": {"type": "is_liar", "target": "Ben"}},
            {"speaker": "Ben", "claim": {"type": "count_liars", "n": 0}},
        ],
        "answer": ["Ava"],
    })
    assert not r.ok


def test_truth_lies_ambiguous_rejected():
    # Two speakers accusing each other: both truth assignments survive.
    r = verify_puzzle({
        "type": "truth_lies", "people": ["Ava", "Ben"],
        "statements": [
            {"speaker": "Ava", "claim": {"type": "is_liar", "target": "Ben"}},
            {"speaker": "Ben", "claim": {"type": "is_liar", "target": "Ava"}},
        ],
        "answer": ["Ben"],
    })
    assert not r.ok and r.ambiguity


# ---------------------------------------------------------------- crossing
def test_river_verified():
    r = verify_puzzle({"type": "river", "kind": "wolf_goat_cabbage", "answer_moves": 7})
    assert r.ok and r.verified and r.answer == 7


def test_river_wrong_rejected():
    r = verify_puzzle({"type": "river", "kind": "wolf_goat_cabbage", "answer_moves": 6})
    assert not r.ok


def test_bridge_torch_verified():
    r = verify_puzzle({"type": "crossing", "kind": "bridge",
                       "times": [1, 2, 5, 10], "answer_time": 17})
    assert r.ok and r.verified and r.answer == 17


def test_bridge_torch_wrong_rejected():
    r = verify_puzzle({"type": "crossing", "kind": "bridge",
                       "times": [1, 2, 5, 10], "answer_time": 19})
    assert not r.ok


# ---------------------------------------------------------------- dispatch
def test_unknown_type_is_unverified():
    r = verify_puzzle({"type": "riddle", "answer": 1})
    assert not r.ok and not r.verified
