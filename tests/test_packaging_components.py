"""Packaging, visual components, audio synthesis and storyboard integration tests."""
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.audio import generate_chime, generate_music, generate_tick, generate_whoosh
from core.characters import EXPRESSIONS, PALETTES, character_svg
from core.components import COMPONENTS, render_component
from core.packaging import package_run

PUZZLE = {
    "type": "number_series", "terms": [3, 7, 15, 31, 63], "answer": 127,
    "recap": "Multiply by 2, then add 1.",
}

STORYBOARD = {
    "prompt": "number series puzzle, 35 seconds",
    "ratio": "9:16",
    "duration": 35.0,
    "concept": "series_trap",
    "concept_name": "Number Series Trap",
    "hook": {"chosen": "Only 1 in 10 can solve this?",
             "best": {"text": "Only 1 in 10 can solve this?", "badge": "ONLY 1 IN 10"}},
    "scenes": [],
}

VERIFICATION = {"verified_by_code": True, "code_ok": True, "code_reason": "unique 127"}
JUDGE = {"scores": {"hook": 8.4, "visual": 8.2}, "overall": 8.3, "passed": True}
AUDIO = {"voiceover": True, "music": "generated", "target_lufs": -14}
CFG = {"series": {"default_ratio": "9:16"}}


def test_all_components_render():
    assert len(COMPONENTS) == 15
    for name in COMPONENTS:
        rendered = render_component(name, {})
        assert rendered.html and len(rendered.html) > 40, name


def test_characters_exist():
    assert len(PALETTES) == 3
    for kind in PALETTES:
        for expression in EXPRESSIONS:
            svg = character_svg(kind, expression)
            assert "<svg" in svg and "</svg>" in svg and len(svg) > 500


def test_audio_generators_are_audible():
    music = generate_music(2.0)
    assert len(music) == 2 * 44100
    assert float(np.max(np.abs(music))) > 0.05
    for clip in (generate_whoosh(), generate_chime(), generate_tick()):
        assert len(clip) > 0 and float(np.max(np.abs(clip))) > 0.01


def test_package_writes_metadata_and_thumbnails(tmp_path):
    package = package_run(tmp_path, STORYBOARD, PUZZLE, VERIFICATION, JUDGE, AUDIO, CFG,
                          None)
    path = tmp_path / "package.json"
    assert path.exists()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert len(data["titles"]) == 5
    assert 8 <= len(data["hashtags"]) <= 12
    assert len(data["tags"]) >= 8
    assert str(PUZZLE["answer"]) in data["pinned_comment"]
    assert data["answer"] == 127 and data["verification"]["verified_by_code"] is True
    assert data["gate_passed"] is True
    vertical = Path(data["thumbnails"]["vertical"])
    horizontal = Path(data["thumbnails"]["horizontal"])
    assert vertical.exists() and vertical.stat().st_size > 5000
    assert horizontal.exists() and horizontal.stat().st_size > 5000
    # Both thumbnail sizes are advertised correctly.
    from PIL import Image
    assert Image.open(vertical).size == (1080, 1920)
    assert Image.open(horizontal).size == (1280, 720)
    assert package["title"] == data["title"]


def test_package_handles_non_series_puzzle(tmp_path):
    puzzle = {
        "type": "percentage", "answer": 20, "statement": "What is 25% of 80?",
        "title": "The Percentage Trap", "recap": "25% of 80 is 20.",
        "payload": {"percent": 25, "base": 80, "answer": 20},
    }
    storyboard = dict(STORYBOARD, prompt="percentage discount puzzle",
                      concept="percent_trap", concept_name="Percentage Trap")
    package = package_run(tmp_path, storyboard, puzzle, VERIFICATION, JUDGE, AUDIO, CFG, None)
    assert all("Number Series" not in t for t in package["titles"])
    assert any("Percentage" in t for t in package["titles"])
    assert "#percentages" in package["hashtags"]
    assert 8 <= len(package["hashtags"]) <= 12
    vertical = Path(package["thumbnails"]["vertical"])
    assert vertical.exists() and vertical.stat().st_size > 5000
