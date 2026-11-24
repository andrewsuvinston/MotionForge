"""Lessons memory: dedup, relevance selection, helped-tracking, pruning, approved examples."""
from __future__ import annotations

import json
import logging
import re
import shutil
import time
import uuid
from pathlib import Path

log = logging.getLogger("motionforge.memory")

CATEGORIES = {"layout", "contrast", "typography", "animation", "content", "style", "technical"}

STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "into", "when", "then",
    "than", "are", "was", "has", "have", "had", "not", "but", "its", "per",
    "use", "using", "make", "sure", "keep", "text", "element", "elements",
}


def _tokens(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", (text or "").lower())
            if len(w) > 2 and w not in STOPWORDS}


def _jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


class Memory:
    def __init__(self, root: Path, cfg: dict | None = None):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.lessons_path = self.root / "lessons.json"
        self.approved_dir = self.root / "approved"
        self.approved_dir.mkdir(parents=True, exist_ok=True)
        self.cfg = (cfg or {}).get("memory", {})
        self.lessons: list[dict] = []
        self._load()
        self._seed_example()

    # ---------------- persistence ----------------

    def _load(self):
        if self.lessons_path.exists():
            try:
                data = json.loads(self.lessons_path.read_text(encoding="utf-8"))
                self.lessons = [l for l in data if isinstance(l, dict) and l.get("rule")]
            except (json.JSONDecodeError, OSError) as exc:
                log.warning("Could not read lessons.json (%s); starting fresh", exc)
                self.lessons = []
        else:
            self.lessons = []

    def save(self):
        self.lessons_path.write_text(
            json.dumps(self.lessons, indent=2, ensure_ascii=False), encoding="utf-8")

    def _seed_example(self):
        """Bootstrap one hand-approved example so the first run has a few-shot reference."""
        if any(self.approved_dir.iterdir()):
            return
        example = Path(__file__).resolve().parent.parent / "templates" / "example_binary_scene.html"
        if example.exists():
            dest = self.approved_dir / "seed_example"
            dest.mkdir(exist_ok=True)
            shutil.copy(example, dest / "scene.html")
            (dest / "meta.json").write_text(json.dumps(
                {"prompt": "binary numbers explainer", "ratio": "9:16", "seed": True}, indent=2),
                encoding="utf-8")

    # ---------------- lessons ----------------

    def add_lesson(self, problem: str, cause: str, rule: str, category: str) -> tuple[str, bool]:
        """Add a lesson, merging into a similar existing one. Returns (id, merged)."""
        rule = " ".join((rule or "").split())[:200]
        if not rule:
            raise ValueError("empty rule")
        category = category if category in CATEGORIES else "style"
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        new_tokens = _tokens(rule + " " + problem)
        for lesson in self.lessons:
            if lesson.get("category") != category:
                continue
            old_tokens = _tokens(lesson.get("rule", "") + " " + lesson.get("problem", ""))
            if _jaccard(new_tokens, old_tokens) >= 0.55:
                lesson["times_seen"] = int(lesson.get("times_seen", 1)) + 1
                lesson["last_seen"] = now
                if cause and not lesson.get("cause"):
                    lesson["cause"] = cause
                self.save()
                log.info("Merged lesson %s (seen %d)", lesson["id"], lesson["times_seen"])
                return lesson["id"], True
        lesson = {
            "id": "L" + uuid.uuid4().hex[:8],
            "problem": (problem or "")[:400],
            "cause": (cause or "")[:400],
            "rule": rule,
            "category": category,
            "times_seen": 1,
            "times_helped": 0,
            "last_seen": now,
        }
        self.lessons.append(lesson)
        self.save()
        log.info("New lesson %s: %s", lesson["id"], rule)
        return lesson["id"], False

    def select_lessons(self, prompt: str, categories: list[str] | None = None,
                       k: int | None = None) -> list[dict]:
        """Pick the k most relevant lessons for a prompt."""
        k = k or int(self.cfg.get("top_lessons", 8))
        prompt_tokens = _tokens(prompt)
        cats = set(categories or [])
        scored = []
        for lesson in self.lessons:
            lt = _tokens(lesson.get("rule", "") + " " + lesson.get("problem", ""))
            score = 2.0 * len(prompt_tokens & lt)
            if lesson.get("category") in cats:
                score += 3.0
            score += 0.4 * min(int(lesson.get("times_seen", 1)), 6)
            score += 0.8 * int(lesson.get("times_helped", 0))
            scored.append((score, lesson))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [lesson for _, lesson in scored[:k]]

    def bump_helped(self, lesson_ids: list[str]):
        ids = set(lesson_ids)
        for lesson in self.lessons:
            if lesson["id"] in ids:
                lesson["times_helped"] = int(lesson.get("times_helped", 0)) + 1
        self.save()

    def prune(self) -> list[str]:
        """Drop lessons that were seen many times but never helped."""
        threshold = int(self.cfg.get("prune_after_seen", 6))
        removed = []
        kept = []
        for lesson in self.lessons:
            if int(lesson.get("times_seen", 0)) >= threshold and int(lesson.get("times_helped", 0)) == 0:
                removed.append(lesson["id"])
            else:
                kept.append(lesson)
        if removed:
            self.lessons = kept
            self.save()
            log.info("Pruned %d unhelpful lessons: %s", len(removed), removed)
        return removed

    def rules_block(self, lessons: list[dict]) -> str:
        if not lessons:
            return ""
        lines = ["Rules learned from past mistakes (follow ALL of them):"]
        lines += [f"- [{l['category']}] {l['rule']}" for l in lessons]
        return "\n".join(lines)

    # ---------------- approved examples ----------------

    def approved_examples(self, limit: int | None = None) -> list[dict]:
        limit = limit or int(self.cfg.get("max_approved_examples", 2))
        out = []
        dirs = sorted((d for d in self.approved_dir.iterdir() if d.is_dir()),
                      key=lambda d: d.stat().st_mtime, reverse=True)
        for d in dirs:
            htmls = sorted(d.glob("*.html"))
            if not htmls:
                continue
            meta = {}
            meta_path = d / "meta.json"
            if meta_path.exists():
                try:
                    meta = json.loads(meta_path.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    pass
            out.append({"name": d.name, "meta": meta,
                        "html": htmls[0].read_text(encoding="utf-8")})
            if len(out) >= limit:
                break
        return out

    def approve_run(self, run_dir: Path) -> int:
        """Copy a run's final scene HTML files into memory/approved/<run_id>/."""
        scenes_dir = Path(run_dir) / "scenes"
        htmls = sorted(scenes_dir.glob("scene_*.html"))
        if not htmls:
            raise FileNotFoundError(f"No scene files in {scenes_dir}")
        dest = self.approved_dir / Path(run_dir).name
        dest.mkdir(parents=True, exist_ok=True)
        for html in htmls:
            shutil.copy(html, dest / html.name)
        meta = {"approved_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
        plan_path = Path(run_dir) / "plan.json"
        if plan_path.exists():
            try:
                plan = json.loads(plan_path.read_text(encoding="utf-8"))
                meta.update({"prompt": plan.get("prompt"), "ratio": plan.get("ratio"),
                             "title": plan.get("title")})
            except json.JSONDecodeError:
                pass
        (dest / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
        return len(htmls)
