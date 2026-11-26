"""Packaging: titles, description, hashtags, tags, pinned comment and thumbnails."""
from __future__ import annotations

import json
import logging
import textwrap
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

log = logging.getLogger("motionforge.packaging")

BG_DARK = (7, 11, 24)
SURFACE = (17, 26, 46)
CYAN = (34, 211, 238)
YELLOW = (250, 204, 21)
RED = (239, 68, 68)
WHITE = (248, 250, 252)
MUTED = (148, 163, 184)

FONT_CANDIDATES = [
    r"C:\Windows\Fonts\segoeuib.ttf",
    r"C:\Windows\Fonts\arialbd.ttf",
    r"C:\Windows\Fonts\segoeui.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, size)
        except (OSError, ValueError):
            continue
    return ImageFont.load_default()


def _center_text(draw: ImageDraw.ImageDraw, xy, text: str, font, fill):
    box = draw.textbbox((0, 0), text, font=font)
    x = xy[0] - (box[2] - box[0]) / 2
    draw.text((x, xy[1]), text, font=font, fill=fill)
    return box[3] - box[1]


def _mm_text(draw: ImageDraw.ImageDraw, xy, text: str, font, fill):
    """Draw text centred on both axes and return its bounding box."""
    box = draw.textbbox((0, 0), text, font=font)
    draw.text(xy, text, font=font, fill=fill, anchor="mm")
    return box


def _fit_font(draw, text: str, max_width: int, start: int, minimum: int = 40):
    size = start
    while size > minimum:
        font = _font(size)
        box = draw.textbbox((0, 0), text, font=font)
        if box[2] - box[0] <= max_width:
            return font
        size -= 6
    return _font(minimum)


def _fit_font_box(draw, text: str, max_width: int, max_height: int,
                  start: int, minimum: int = 40):
    """Largest font that fits inside both a width and a height budget."""
    size = start
    while size > minimum:
        font = _font(size)
        box = draw.textbbox((0, 0), text, font=font)
        if box[2] - box[0] <= max_width and box[3] - box[1] <= max_height:
            return font
        size -= 6
    return _font(minimum)


def _vertical_thumb(path: Path, answer: str, badge: str, line: str, label: str, title: str):
    W, H = 1080, 1920
    img = Image.new("RGB", (W, H), BG_DARK)
    draw = ImageDraw.Draw(img)
    # Layered glows.
    for r in range(900, 0, -18):
        a = int(38 * (1 - r / 900))
        draw.ellipse([W - 260 - r, -220 - r, W - 260 + r, -220 + r],
                     fill=(7 + a // 3, 11 + a, 24 + a))
    for r in range(820, 0, -20):
        a = int(30 * (1 - r / 820))
        draw.ellipse([180 - r, H - 240 - r, 180 + r, H - 240 + r],
                     fill=(7 + a, 11 + a // 2, 24))
    # Badge pill.
    badge_text = badge.upper()
    badge_font = _fit_font(draw, badge_text, 860, 56)
    bbox = draw.textbbox((0, 0), badge_text, font=badge_font)
    bw, bh = bbox[2] - bbox[0], bbox[3] - bbox[1]
    pad_x, pad_y = 42, 26
    x0, y0 = (W - bw - 2 * pad_x) // 2, 150
    y1 = y0 + bh + 2 * pad_y + 12
    draw.rounded_rectangle([x0, y0, x0 + bw + 2 * pad_x, y1],
                           radius=999, fill=(18, 44, 58), outline=CYAN, width=4)
    _mm_text(draw, (W / 2, (y0 + y1) / 2), badge_text, badge_font, (165, 243, 252))
    # Label and puzzle line.
    _mm_text(draw, (W / 2, 340), label.upper(), _font(54), MUTED)
    term_text = line
    term_font = _fit_font(draw, term_text, 940, 78, 40)
    _mm_text(draw, (W / 2, 445), term_text, term_font, WHITE)
    # Answer panel: fit both width and height so digits stay inside the frame.
    px0, py0, px1, py1 = 95, 700, W - 95, 1260
    draw.rounded_rectangle([px0, py0, px1, py1], radius=48,
                           fill=(28, 24, 12), outline=YELLOW, width=6)
    answer_text = str(answer)
    big = _fit_font_box(draw, answer_text, px1 - px0 - 120, 330, 300, 100)
    _mm_text(draw, (W / 2, py0 + 235), answer_text, big, YELLOW)
    _mm_text(draw, (W / 2, py1 - 105), "THE ANSWER", _font(46), (226, 232, 240))
    # CTA and title.
    cta = "CAN YOU SOLVE IT?"
    cta_font = _fit_font(draw, cta, 920, 92, 56)
    _mm_text(draw, (W / 2, 1440), cta, cta_font, WHITE)
    sub_font = _fit_font(draw, title, 900, 48, 32)
    _mm_text(draw, (W / 2, 1560), title, sub_font, (165, 243, 252))
    # Footer.
    draw.rounded_rectangle([70, 1720, W - 70, 1820], radius=50, fill=(250, 204, 21))
    _mm_text(draw, (W / 2, 1770), "ANSWER IN THE PINNED COMMENT", _font(44), (11, 18, 32))
    img.save(path, quality=94)


def _horizontal_thumb(path: Path, answer: str, badge: str, line: str, label: str, title: str):
    W, H = 1280, 720
    img = Image.new("RGB", (W, H), BG_DARK)
    draw = ImageDraw.Draw(img)
    for r in range(700, 0, -16):
        a = int(34 * (1 - r / 700))
        draw.ellipse([W - 200 - r, -180 - r, W - 200 + r, -180 + r],
                     fill=(7 + a // 3, 11 + a, 24 + a))
    # Left answer panel.
    draw.rounded_rectangle([60, 90, 560, 630], radius=44, fill=(28, 24, 12), outline=YELLOW, width=6)
    answer_text = str(answer)
    big = _fit_font_box(draw, answer_text, 420, 280, 280, 100)
    _mm_text(draw, (310, 330), answer_text, big, YELLOW)
    _mm_text(draw, (310, 555), "THE ANSWER", _font(46), (226, 232, 240))
    # Right copy.
    badge_text = badge.upper()
    f_badge = _fit_font(draw, badge_text, 540, 50, 30)
    draw.rounded_rectangle([620, 92, 1220, 196], radius=52, fill=(18, 44, 58), outline=CYAN, width=4)
    _mm_text(draw, (920, 144), badge_text, f_badge, (165, 243, 252))
    term_text = line
    term_font = _fit_font(draw, term_text, 560, 68, 34)
    _mm_text(draw, (920, 285), term_text, term_font, WHITE)
    f_cta = _fit_font(draw, "CAN YOU SOLVE IT?", 560, 84, 48)
    _mm_text(draw, (920, 420), "CAN YOU SOLVE IT?", f_cta, WHITE)
    wrapped = textwrap.wrap(title, width=30)[:2]
    f_sub = _font(40)
    for i, line in enumerate(wrapped):
        _mm_text(draw, (920, 520 + i * 52), line, f_sub, MUTED)
    img.save(path, quality=94)


TYPE_LABELS = {
    "number_series": "NUMBER SERIES",
    "truth_lies": "TRUTH & LIES",
    "river": "RIVER CROSSING",
    "percentage": "PERCENTAGE",
    "ratio": "RATIOS",
    "time_work": "TIME & WORK",
    "algebra": "ALGEBRA",
    "arithmetic": "ORDER OF OPERATIONS",
}

TYPE_HASHTAGS = {
    "number_series": ["#numberseries", "#findthepattern"],
    "truth_lies": ["#logicpuzzle", "#riddles"],
    "river": ["#riddles", "#logicpuzzles"],
    "percentage": ["#percentages", "#mathstricks"],
    "ratio": ["#ratios", "#aptitude"],
    "time_work": ["#timeandwork", "#aptitude"],
    "algebra": ["#algebra", "#maths"],
    "arithmetic": ["#bodmas", "#maths"],
}


def _puzzle_line(puzzle: dict) -> str:
    """A short, thumbnail-safe line describing the puzzle (no answer)."""
    terms = [str(t) for t in (puzzle.get("terms") or [])]
    if terms:
        return ", ".join(terms) + ", ?"
    if puzzle.get("type") == "river":
        return "WOLF · GOAT · CABBAGE"
    statement = (puzzle.get("statement") or puzzle.get("title") or "").strip()
    words = statement.split()
    if len(words) > 7:
        statement = " ".join(words[:7]).rstrip(".,;:") + "…"
    return statement or "CAN YOU SOLVE IT?"


def _label(puzzle: dict) -> str:
    return TYPE_LABELS.get(puzzle.get("type") or "", "PUZZLE")


def _titles(storyboard: dict, puzzle: dict, concept: dict) -> list[str]:
    terms = [str(t) for t in (puzzle.get("terms") or [])]
    hook = (storyboard.get("hook") or {}).get("chosen") or "Can you solve it?"
    name = concept.get("name") or "Puzzle"
    label = _label(puzzle).title()
    out = []
    if terms:
        out.append(f"{', '.join(terms)}, ? — Only 1 in 10 Spots the Rule")
    else:
        out.append(f"Only 1 in 10 Can Solve This {label} Puzzle")
    out.append(f"Only 1 in 10 Can Solve This {name}")
    out.append(f"{hook} (5 Second Challenge)")
    out.append(f"Can You Crack This {label} Puzzle Before the Timer?")
    out.append(f"This {name} Looks Easy — Until You See the Rule")
    unique: list[str] = []
    for t in out:
        if t not in unique:
            unique.append(t)
    return unique[:5]


def _description(storyboard: dict, puzzle: dict, judge: dict) -> str:
    hook = (storyboard.get("hook") or {}).get("chosen") or "Can you solve this?"
    line = _puzzle_line(puzzle)
    label = _label(puzzle).title()
    return (
        f"{hook}\n\n"
        f"The {label.lower()} puzzle: {line}\n"
        "Pause the video, lock in your answer, then watch the rule unfold step by step. "
        "The answer is verified by a code solver — no guesswork.\n\n"
        "Comment your answer before the timer ends. Follow for a new logic puzzle every day.\n\n"
        "Answer in the pinned comment."
    )


def _hashtags(puzzle: dict | None = None) -> list[str]:
    base = ["#shorts", "#puzzle", "#aptitude", "#logicalreasoning",
            "#maths", "#brainteaser", "#challenge", "#quiz", "#reasoning",
            "#viral"]
    extra = TYPE_HASHTAGS.get((puzzle or {}).get("type") or "", [])
    out = []
    for tag in base + extra:
        if tag not in out:
            out.append(tag)
    return out[:12]


def _tags() -> list[str]:
    return ["number series", "logic puzzle", "aptitude test", "math puzzle",
            "brain teaser", "reasoning questions", "shorts challenge",
            "find the pattern", "competitive exam", "iq test", "math tricks",
            "puzzle shorts", "answer explained"]


def package_run(run_dir: Path, storyboard: dict, puzzle: dict, verification: dict,
                judge: dict, audio_report: dict | None, cfg: dict,
                video_path: Path | None, concept: dict | None = None,
                series_info: dict | None = None) -> dict:
    run_dir = Path(run_dir)
    concept = concept or {"id": storyboard.get("concept"), "name": storyboard.get("concept_name")}
    answer = puzzle.get("answer")
    badge = ((storyboard.get("hook") or {}).get("best") or {}).get("badge") or "ONLY 1 IN 10 GETS THIS"
    line = _puzzle_line(puzzle)
    label = _label(puzzle)
    title = _titles(storyboard, puzzle, concept)[0]
    assets = run_dir / "package"
    assets.mkdir(parents=True, exist_ok=True)
    vertical = assets / "thumbnail_1080x1920.jpg"
    horizontal = assets / "thumbnail_1280x720.jpg"
    try:
        _vertical_thumb(vertical, answer, badge, line, label, title)
        _horizontal_thumb(horizontal, answer, badge, line, label, title)
        thumbnails = {"vertical": str(vertical), "horizontal": str(horizontal)}
    except Exception as exc:  # noqa: BLE001
        log.warning("Thumbnail generation failed (%s)", exc)
        thumbnails = {"vertical": None, "horizontal": None}

    package = {
        "schema_version": 1,
        "run_id": run_dir.name,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "prompt": storyboard.get("prompt"),
        "title": title,
        "titles": _titles(storyboard, puzzle, concept),
        "description": _description(storyboard, puzzle, judge),
        "hashtags": _hashtags(puzzle),
        "tags": _tags(),
        "pinned_comment": (
            f"The answer is {answer}. Did you get it before the timer? "
            f"The rule: {puzzle.get('recap') or 'apply the same step to the last term.'} "
            "Tell me which step almost tricked you."
        ),
        "thumbnails": thumbnails,
        "video": str(video_path) if video_path else None,
        "ratio": storyboard.get("ratio") or cfg.get("series", {}).get("default_ratio", "9:16"),
        "duration": storyboard.get("duration"),
        "concept": concept.get("id"),
        "puzzle_type": puzzle.get("type"),
        "answer": answer,
        "verification": {
            "verified_by_code": verification.get("verified_by_code"),
            "code_ok": verification.get("code_ok"),
            "reason": verification.get("code_reason"),
        },
        "scores": judge.get("scores"),
        "overall_score": judge.get("overall"),
        "gate_passed": judge.get("passed"),
        "audio": {
            "voiceover": bool((audio_report or {}).get("voiceover")),
            "music": (audio_report or {}).get("music"),
            "target_lufs": (audio_report or {}).get("target_lufs"),
        },
        "series": series_info,
        "disclosure": (
            "Scores are deterministic, evidence-based evaluations of the rendered frames. "
            "Retention and analytics values are projections until real channel data is imported."
        ),
    }
    (run_dir / "package.json").write_text(json.dumps(package, indent=2, ensure_ascii=False),
                                         encoding="utf-8")
    log.info("Packaged: %d titles | %d hashtags | thumbnails=%s",
             len(package["titles"]), len(package["hashtags"]), bool(thumbnails["vertical"]))
    return package
