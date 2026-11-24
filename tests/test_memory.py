"""Unit tests for core.memory (lessons, dedup, selection, pruning, approval)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.memory import Memory

CFG = {"memory": {"top_lessons": 8, "max_approved_examples": 2, "prune_after_seen": 6}}


def make_memory(tmp_path):
    return Memory(tmp_path / "memory", CFG)


def test_add_and_persist(tmp_path):
    m = make_memory(tmp_path)
    lid, merged = m.add_lesson("title overlapped chart", "absolute positioning",
                               "Keep title and chart in separate flex rows.", "layout")
    assert not merged and lid.startswith("L")
    m2 = Memory(tmp_path / "memory", CFG)
    assert any(l["id"] == lid for l in m2.lessons)


def test_dedup_merges_similar_lessons(tmp_path):
    m = make_memory(tmp_path)
    id1, _ = m.add_lesson("title text overlaps the chart bars", "no spacing",
                          "Keep title and chart in separate flex rows with a gap.", "layout")
    id2, merged = m.add_lesson("title text overlaps chart bars again", "no spacing",
                               "Keep title and chart in separate flex rows with a gap.", "layout")
    assert merged and id1 == id2
    assert len(m.lessons) == 1
    assert m.lessons[0]["times_seen"] == 2


def test_different_category_not_merged(tmp_path):
    m = make_memory(tmp_path)
    m.add_lesson("text too small", "tiny font", "Keep all text above 2.6vmin.", "typography")
    _, merged = m.add_lesson("text too small", "tiny font", "Keep all text above 2.6vmin.", "contrast")
    assert not merged and len(m.lessons) == 2


def test_select_lessons_relevance(tmp_path):
    m = make_memory(tmp_path)
    m.add_lesson("chart bars clipped", "layout", "Give charts enough height inside the stage.", "layout")
    m.add_lesson("binary counter unreadable", "contrast",
                 "Use bright accent color for binary counter digits.", "contrast")
    picked = m.select_lessons("how binary numbers work with a counter", k=1)
    assert len(picked) == 1
    assert "binary" in picked[0]["rule"]


def test_bump_helped_and_prune(tmp_path):
    m = make_memory(tmp_path)
    lid, _ = m.add_lesson("p1", "c", "Never let text touch the screen edge.", "layout")
    dead, _ = m.add_lesson("p2", "c", "Avoid purple gradients on dark backgrounds.", "style")
    m.bump_helped([lid])
    assert m.lessons[0]["times_helped"] == 1
    for _ in range(6):
        m.add_lesson("p2", "c", "Avoid purple gradients on dark backgrounds.", "style")
    removed = m.prune()
    assert dead in removed and lid not in removed
    assert all(l["id"] != dead for l in m.lessons)


def test_rules_block_format(tmp_path):
    m = make_memory(tmp_path)
    m.add_lesson("p", "c", "Use safe margins of at least 7vmin.", "layout")
    block = m.rules_block(m.lessons)
    assert "Rules learned from past mistakes" in block
    assert "[layout] Use safe margins" in block


def test_approve_run_and_examples(tmp_path):
    run = tmp_path / "runs" / "run_x"
    (run / "scenes").mkdir(parents=True)
    (run / "scenes" / "scene_01.html").write_text("<html><body>good</body></html>", encoding="utf-8")
    (run / "plan.json").write_text(json.dumps({"prompt": "test prompt", "ratio": "9:16"}), encoding="utf-8")
    m = make_memory(tmp_path)
    n = m.approve_run(run)
    assert n == 1
    examples = m.approved_examples(limit=2)
    assert any(e["name"] == "run_x" and "good" in e["html"] for e in examples)
    assert any(e["meta"].get("prompt") == "test prompt" for e in examples)


def test_seed_example_bootstrap(tmp_path):
    m = make_memory(tmp_path)
    examples = m.approved_examples()
    assert examples, "seed example should be bootstrapped from templates"
    assert "setTime" in examples[0]["html"]


def test_corrupt_lessons_file_recovers(tmp_path):
    root = tmp_path / "memory"
    root.mkdir()
    (root / "lessons.json").write_text("{not json", encoding="utf-8")
    m = Memory(root, CFG)
    assert m.lessons == []
