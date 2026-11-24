"""The full MotionForge loop: plan -> generate -> render samples -> check -> review -> fix -> encode."""
from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path

from tqdm import tqdm

from .checks import Problem, run_checks
from .config import PROJECT_ROOT, resolution_for
from .fallback_scenes import build_scene_html
from .llm import LLMClient, LLMError
from .memory import Memory, CATEGORIES
from .planner import make_plan
from .renderer import Renderer
from .reviewer import review_scenes
from .scene_generator import SceneGenerator

log = logging.getLogger("motionforge.pipeline")

# Heuristic lessons when the LLM cannot summarize a fix.
HEURISTIC_LESSONS = {
    "text_overflow": ("Text overflowed its container", "Copy too long or font too large for the box",
                      "Shorten the copy or reduce the font size so text fits its container.", "layout"),
    "offscreen": ("An element was positioned off-screen", "Absolute positioning or oversized layout",
                  "Keep every visible element fully inside the viewport with safe margins.", "layout"),
    "overlap": ("Text blocks overlapped each other", "Elements stacked without enough spacing",
                "Space text blocks apart so no two visible text blocks overlap.", "layout"),
    "low_contrast": ("Text had low contrast against the background", "Muted color used for primary text",
                     "Use palette text color on background with WCAG contrast of at least 4.5.", "contrast"),
    "small_font": ("Text was too small to read on mobile", "Font size below the readability floor",
                   "Keep all text at or above 2.6vmin so it stays readable on mobile.", "typography"),
    "blank_frame": ("A frame rendered blank", "Reveal timings start too late or opacity never rises",
                    "Start reveals early enough that content is visible by mid-scene.", "animation"),
    "console_error": ("JavaScript errored during rendering", "Bug in the scene script",
                      "Guard DOM lookups and keep setTime free of runtime errors.", "technical"),
    "missing_settime": ("Scene lacked window.setTime", "Contract not followed",
                        "Always define deterministic window.setTime(t) and SCENE_DURATION.", "technical"),
    "duration_mismatch": ("Scene duration did not match the plan", "Wrong SCENE_DURATION constant",
                          "Set SCENE_DURATION to exactly the planned scene duration.", "technical"),
    "vision": ("Visual design problem found by review", "Layout or style issue",
               "Keep scenes uncluttered with aligned elements and generous spacing.", "style"),
}

LESSON_SYSTEM = """You convert fixed quality-assurance problems into ONE reusable lesson for a
motion-graphics HTML scene generator. Return ONLY JSON:
{"problem": "what went wrong", "cause": "likely root cause",
 "rule": "one short imperative sentence the generator must follow in future scenes",
 "category": "layout|contrast|typography|animation|content|style|technical"}
The rule must be general (not about this specific video), concrete and actionable."""


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:28] or "video"


def _summarize_lesson(llm: LLMClient, problems: list[Problem], scene: dict) -> dict:
    """LLM lesson from fixed problems; heuristic fallback on failure."""
    try:
        listing = "\n".join(f"- [{p.code}] {p.message}" for p in problems[:10])
        data = llm.chat_json(
            [{"role": "system", "content": LESSON_SYSTEM},
             {"role": "user", "content": f"Scene goal: {scene['goal']}\nFixed problems:\n{listing}"}],
            llm.cfg["models"]["generator_model"], label=f"lesson_scene_{scene['id']}",
            max_tokens=500, temperature=0.3,
        )
        if isinstance(data, dict) and data.get("rule"):
            return data
    except (LLMError, ValueError) as exc:
        log.warning("Lesson LLM call failed (%s); using heuristic lesson", exc)
    code = problems[0].code if problems else "vision"
    problem, cause, rule, category = HEURISTIC_LESSONS.get(code, HEURISTIC_LESSONS["vision"])
    return {"problem": problem, "cause": cause, "rule": rule, "category": category}


def create_video(cfg: dict, prompt: str, ratio: str = "16:9", duration: float = 30.0,
                 preview: bool = False, voiceover: Path | None = None,
                 music: Path | None = None, no_review: bool = False,
                 offline: bool = False, max_iterations: int | None = None) -> dict:
    run_id = time.strftime("%Y%m%d_%H%M%S") + "_" + _slug(prompt)
    run_dir = PROJECT_ROOT / "runs" / run_id
    (run_dir / "scenes" / "history").mkdir(parents=True, exist_ok=True)
    (run_dir / "frames").mkdir(parents=True, exist_ok=True)

    fh = logging.FileHandler(run_dir / "run.log", encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s"))
    logging.getLogger("motionforge").addHandler(fh)

    llm_cfg = dict(cfg)
    if offline:
        llm_cfg["api_key"] = ""
    llm = LLMClient(llm_cfg, log_dir=run_dir / "llm_logs")
    memory = Memory(PROJECT_ROOT / "memory", cfg)
    generator = SceneGenerator(llm)
    max_it = max_iterations or int(cfg["loop"]["max_iterations"])
    use_vision = bool(cfg["loop"]["vision_review"]) and not no_review and not llm.offline
    width, height = resolution_for(cfg, ratio)
    fps = int(cfg["render"]["preview_fps"] if preview else cfg["render"]["fps"])

    log.info("Run %s | %s | %ss | %s | %dx%d @%dfps%s", run_id, ratio, duration,
             "preview" if preview else "final", width, height, fps,
             " | OFFLINE" if llm.offline else "")

    # 1. Plan
    plan = make_plan(llm, prompt, ratio, duration)
    plan["prompt"] = prompt
    (run_dir / "plan.json").write_text(json.dumps(plan, indent=2, ensure_ascii=False), encoding="utf-8")

    scene_reports = []
    lessons_added: list[str] = []
    final_scenes: list[tuple[Path, float]] = []

    with Renderer(cfg, ratio, preview) as renderer:
        # 2-7. Per-scene self-correcting loop
        for scene in tqdm(plan["scenes"], desc="Scenes", unit="scene"):
            sid = scene["id"]
            scene_dir = run_dir / "scenes"
            html_path = scene_dir / f"scene_{sid:02d}.html"
            lessons = memory.select_lessons(prompt + " " + scene["goal"])
            lesson_ids = [l["id"] for l in lessons]
            rules_block = memory.rules_block(lessons)
            examples = memory.approved_examples()
            srep = {"id": sid, "name": scene["name"], "duration": scene["duration"],
                    "iterations": 0, "problems_found": [], "unresolved": [],
                    "lessons_added": [], "lessons_helped": [], "used_fallback": False}

            # Initial generation (LLM, or deterministic fallback).
            try:
                if llm.offline:
                    raise LLMError("offline mode")
                html = generator.generate(scene, plan, lessons, examples, rules_block)
            except LLMError as exc:
                log.warning("Scene %s generation failed (%s); using built-in template", sid, exc)
                html = build_scene_html(scene, plan, generator.motion_js)
                srep["used_fallback"] = True

            problems_by_it: dict[int, list[Problem]] = {}
            passed = False
            best: tuple[int, int, str] | None = None   # (n_problems, iteration, html) renderable only
            FATAL = {"missing_settime", "console_error"}
            for it in range(1, max_it + 1):
                srep["iterations"] = it
                html_path.write_text(html, encoding="utf-8")
                (scene_dir / "history" / f"scene_{sid:02d}_it{it}.html").write_text(html, encoding="utf-8")

                sample_dir = run_dir / "frames" / f"scene_{sid:02d}" / f"it{it}"
                sample = renderer.capture_samples(html_path, scene["duration"], sample_dir)
                problems: list[Problem] = []
                if sample.load_error:
                    problems.append(Problem("console_error", f"Scene failed to load: {sample.load_error[:200]}"))
                if sample.measurements:
                    for measurement in sample.measurements:
                        problems += run_checks(measurement, scene["duration"], [],
                                               sample.frame_stats, cfg, plan["palette"]["bg"])
                else:
                    problems.append(Problem("missing_settime",
                                            "window.setTime(t) is not defined or scene failed to render"))
                for err in list(dict.fromkeys(sample.console_errors))[:5]:
                    problems.append(Problem("console_error", f"JavaScript error: {err[:200]}"))
                # dedupe
                seen, uniq = set(), []
                for p in problems:
                    if (p.code, p.message) not in seen:
                        seen.add((p.code, p.message))
                        uniq.append(p)
                problems = uniq

                # Vision review only once automatic checks are clean.
                if not problems and use_vision:
                    vision = review_scenes(llm, [(scene, sample.frames)], cfg["models"]["reviewer_model"])
                    problems += [p for p in vision if p.scene in (0, sid)]

                for p in problems:
                    p.scene = sid
                problems_by_it[it] = problems
                srep["problems_found"].append(
                    {"iteration": it, "problems": [p.to_dict() for p in problems]})
                if not any(p.code in FATAL for p in problems) and \
                   (best is None or len(problems) < best[0]):
                    best = (len(problems), it, html)

                if not problems:
                    passed = True
                    if it == 1 and lesson_ids and not srep["used_fallback"]:
                        memory.bump_helped(lesson_ids)
                        srep["lessons_helped"] = lesson_ids
                    log.info("Scene %s passed on iteration %d", sid, it)
                    break
                log.info("Scene %s iteration %d: %d problems", sid, it, len(problems))
                if it == max_it:
                    srep["unresolved"] = [p.to_dict() for p in problems]
                    log.warning("Scene %s still has %d problems after %d iterations; keeping best effort",
                                sid, len(problems), max_it)
                    break
                # Fix via generator; fall back to built-in template if the LLM fails
                # or makes no progress (identical HTML).
                try:
                    if llm.offline:
                        raise LLMError("offline mode")
                    fixed = generator.fix(html, problems[:12], scene, plan)
                    if fixed.strip() == html.strip():
                        log.warning("Scene %s: fix returned identical HTML; using built-in template", sid)
                        fixed = build_scene_html(scene, plan, generator.motion_js)
                        srep["used_fallback"] = True
                    html = fixed
                except LLMError as exc:
                    log.warning("Scene %s fix failed (%s); using built-in template", sid, exc)
                    html = build_scene_html(scene, plan, generator.motion_js)
                    srep["used_fallback"] = True

            # Never send a non-renderable scene to the final render.
            if not passed:
                if best is not None and best[1] != srep["iterations"]:
                    log.info("Scene %s: restoring best renderable iteration %d (%d problems)",
                             sid, best[1], best[0])
                    html = best[2]
                    html_path.write_text(html, encoding="utf-8")
                    srep["unresolved"] = [p.to_dict() for p in problems_by_it[best[1]]]
                elif best is None:
                    log.warning("Scene %s: no renderable iteration; rescuing with built-in template", sid)
                    html = build_scene_html(scene, plan, generator.motion_js)
                    html_path.write_text(html, encoding="utf-8")
                    srep["used_fallback"] = True
                    sample = renderer.capture_samples(
                        html_path, scene["duration"],
                        run_dir / "frames" / f"scene_{sid:02d}" / "rescue")
                    rescue_problems: list[Problem] = []
                    for measurement in sample.measurements:
                        rescue_problems += run_checks(measurement, scene["duration"],
                                                      sample.console_errors, sample.frame_stats,
                                                      cfg, plan["palette"]["bg"])
                    if sample.load_error or not sample.measurements:
                        rescue_problems.append(Problem("missing_settime", "Rescue template failed to render"))
                    srep["unresolved"] = [p.to_dict() for p in rescue_problems]
                    if not rescue_problems:
                        passed = True
                        log.info("Scene %s rescued by built-in template", sid)

            # Learn from problems that were found and then fixed.
            fixed_codes = [p for it, probs in problems_by_it.items() if it < srep["iterations"]
                           for p in probs]
            if passed and fixed_codes:
                lesson = _summarize_lesson(llm, fixed_codes, scene)
                lid, merged = memory.add_lesson(lesson.get("problem", ""), lesson.get("cause", ""),
                                                lesson.get("rule", ""), lesson.get("category", "style"))
                srep["lessons_added"].append(lid)
                lessons_added.append(lid)

            scene_reports.append(srep)
            final_scenes.append((html_path, scene["duration"]))

        # 8. Final render + encode
        log.info("Rendering final video: %d scenes", len(final_scenes))
        frames_dir = run_dir / "frames" / "final"
        n_frames = renderer.render_frames(final_scenes, frames_dir)
        out_path = run_dir / "final.mp4"
        renderer.encode(frames_dir, out_path, voiceover=voiceover, music=music)

    pruned = memory.prune()
    memory.save()

    report = {
        "run_id": run_id,
        "prompt": prompt,
        "ratio": ratio,
        "duration": duration,
        "preview": preview,
        "fps": fps,
        "resolution": [width, height],
        "frames_rendered": n_frames,
        "models": cfg["models"],
        "offline": llm.offline,
        "scenes": scene_reports,
        "totals": {
            "iterations": sum(s["iterations"] for s in scene_reports),
            "problems_found": sum(len(pf["problems"]) for s in scene_reports for pf in s["problems_found"]),
            "unresolved": sum(len(s["unresolved"]) for s in scene_reports),
            "lessons_added": len(lessons_added),
            "lessons_pruned": len(pruned),
        },
        "output": str(out_path),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    (run_dir / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    logging.getLogger("motionforge").removeHandler(fh)
    fh.close()
    llm.close()
    return report
