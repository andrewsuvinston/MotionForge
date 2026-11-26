"""MotionForge Shorts pipeline: concept -> verified puzzle -> scenes -> judges -> package -> MP4.

The pipeline is deterministic-first. LLM calls are optional enrichment and every
stage has an offline fallback, so a preview render always completes. Each stage is
checkpointed so `resume` can continue an interrupted run without spending quota.
"""
from __future__ import annotations

import copy
import json
import logging
import re
import time
from pathlib import Path

from . import analytics
from .audio import build_audio
from .checks import Problem, run_checks
from .concepts import choose_concept
from .config import PROJECT_ROOT, resolution_for
from .consistency import answer_in_text, check_rendered, check_storyboard, dedupe
from .hooks import generate_hooks
from .judges import deterministic_panel, judge_rounds
from .llm import LLMClient
from .packaging import package_run
from .puzzle import generate_puzzle, save_puzzle
from .renderer import Renderer
from .scene_builder import build_scene_specs, load_scene_specs, render_scene_again, write_scene_files
from .script import build_storyboard
from .budget import BudgetManager
from .memory import Memory

log = logging.getLogger("motionforge.pipeline")

RESCUE_COMPONENT = "payoff"


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:32] or "video"


def _dump(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _load(path: Path, default=None):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


def _strip_layout(storyboard: dict) -> dict:
    sb = copy.deepcopy(storyboard)
    sb["scenes"] = [{k: v for k, v in s.items() if k != "layout"}
                    for s in sb.get("scenes") or []]
    return sb


def _checkpoint(run_dir: Path, stage: str, **extra):
    state = _load(run_dir / "checkpoint.json", {}) or {}
    state.update({"stage": stage, "updated": time.strftime("%Y-%m-%dT%H:%M:%S"), **extra})
    _dump(run_dir / "checkpoint.json", state)


def _trim_props(props: dict, max_words: int = 10) -> dict:
    out = copy.deepcopy(props or {})

    def walk(value, key=""):
        if isinstance(value, dict):
            return {k: walk(v, k) for k, v in value.items()}
        if isinstance(value, list):
            return [walk(v, key) for v in value]
        if isinstance(value, str) and key not in ("terms", "answer", "math", "left", "right", "badge"):
            words = re.findall(r"\S+", value)
            if len(words) > max_words:
                return " ".join(words[:max_words]).rstrip(".,;:") + "."
        return value

    return walk(out)


def _rescue_spec(spec: dict, puzzle: dict) -> dict:
    answer = str(puzzle.get("answer", ""))
    return {
        **spec,
        "component": RESCUE_COMPONENT,
        "props": {
            "answer": answer,
            "kicker": "THE ANSWER IS",
            "recap": "Verified by the code solver.",
            "teaser": "Follow for the next puzzle.",
        },
    }


def _measure_scene(renderer: Renderer, spec: dict, html_path: Path, cfg: dict,
                   scene_no: int) -> dict:
    sample = renderer.capture_samples(html_path, float(spec.get("duration") or 4.0),
                                      renderer.run_dir / "frames" / f"scene_{scene_no:02d}")
    problems: list[Problem] = []
    if sample.load_error:
        problems.append(Problem("console_error", f"Scene failed to load: {sample.load_error[:200]}"))
    if not sample.measurements:
        problems.append(Problem("missing_settime",
                                "window.setTime(t) is missing or the scene failed to render"))
    else:
        last = len(sample.measurements) - 1
        for i, measurement in enumerate(sample.measurements):
            problems += run_checks(measurement, float(spec.get("duration") or 4.0),
                                   sample.console_errors, sample.frame_stats, cfg,
                                   "#070B18", settled=(i == last))
    problems = [p for p in dedupe([p.to_dict() for p in problems])]
    occs = [m.get("occupancy") for m in sample.measurements if m.get("occupancy") is not None]
    return {
        "scene": scene_no,
        "tag": spec.get("tag"),
        "load_error": sample.load_error,
        "occupancy": max(occs) if occs else 0.0,
        "problems": problems,
        "console_errors": sample.console_errors[:5],
        "frames": sample.frames,
    }


def _render_and_repair(renderer: Renderer, specs: list[dict], puzzle: dict, cfg: dict,
                       scenes_dir: Path) -> tuple[list[dict], list[Problem]]:
    results: list[dict] = []
    for i, spec in enumerate(specs, start=1):
        path = scenes_dir / f"scene_{i:02d}.html"
        attempts = []
        best = None
        current = copy.deepcopy(spec)
        for attempt in range(1, 4):
            if attempt == 3:
                current = _rescue_spec(current, puzzle)
            elif attempt == 2:
                current["props"] = _trim_props(current.get("props") or {}, 10)
            path = render_scene_again(current, path, renderer.motion_js, renderer.palette,
                                      index=i, total=len(specs))
            result = _measure_scene(renderer, current, path, cfg, i)
            result["attempt"] = attempt
            attempts.append({"attempt": attempt,
                             "problems": [p["code"] for p in result["problems"]],
                             "occupancy": result["occupancy"]})
            if best is None or len(result["problems"]) < len(best[0]["problems"]):
                best = (result, copy.deepcopy(current))
            if not any(p["severity"] == "error" for p in result["problems"]):
                break
        result, final_spec = best
        specs[i - 1] = final_spec
        result["attempts"] = attempts
        result["rescued"] = final_spec.get("component") == RESCUE_COMPONENT and \
            spec.get("component") != RESCUE_COMPONENT
        if result["problems"]:
            log.warning("Scene %d still has %d problem(s): %s", i, len(result["problems"]),
                        ", ".join(p["code"] for p in result["problems"][:6]))
        else:
            log.info("Scene %d passed deterministic checks (occupancy %.0f%%)", i,
                     100 * result["occupancy"])
        results.append(result)
    problems = [Problem(**p) for r in results for p in r["problems"]]
    _dump(scenes_dir / "scenes.json",
          [{k: v for k, v in s.items() if k != "layout"} for s in specs])
    return results, problems


def _consistency_fix(storyboard: dict, puzzle: dict, cfg: dict) -> tuple[dict, list[dict]]:
    sb = copy.deepcopy(storyboard)
    answer = puzzle.get("answer")
    tag_scenes = {s.get("tag"): s for s in sb.get("scenes") or []}
    for tag in ("SOLUTION", "ANSWER"):
        scene = tag_scenes.get(tag)
        if scene is not None:
            scene.setdefault("props", {})["answer"] = str(answer)
    if "SOLUTION" in tag_scenes:
        scene = tag_scenes["SOLUTION"]
        narration = scene.get("narration") or ""
        # Words count: "one hundred twenty-seven" already states the answer even
        # when the digits never appear, so do not append a duplicate sentence.
        if not answer_in_text(answer, narration):
            from .script import fit_narration
            wps = float(cfg.get("video", {}).get("wps", 2.5))
            scene["narration"] = fit_narration(
                f"{narration} The answer is {answer}.".strip(),
                float(scene.get("duration") or 4.0), wps)
    if puzzle.get("type") == "number_series":
        terms = puzzle.get("terms") or []
        for tag in ("HOOK", "PATTERN"):
            scene = tag_scenes.get(tag)
            if scene is not None:
                scene.setdefault("props", {})["terms"] = list(terms)
    return sb, dedupe(check_storyboard(sb, puzzle, cfg))


def _storyboard_rounds(cfg: dict, run_dir: Path, storyboard: dict, puzzle: dict,
                       verification: dict, check_results: list[dict],
                       llm: LLMClient | None, audio_projection: dict) -> dict:
    result = judge_rounds(storyboard, verification, check_results, audio_projection, cfg,
                          puzzle, llm=llm)
    _dump(run_dir / "improvement_log.json", {
        "run_id": run_dir.name,
        "rounds": [{k: v for k, v in r.items() if k != "evidence"} for r in result["rounds"]],
        "best_round": result["best_round"],
        "best_overall": result["best_overall"],
        "max_rounds": result["max_rounds"],
        "min_improvement": result["min_improvement"],
        "llm_advisory": result.get("llm_advisory"),
        "weaknesses": result.get("weaknesses"),
    })
    return result


def create_video(cfg: dict, prompt: str, ratio: str = "9:16", duration: float = 35.0,
                 quality: str = "preview", voiceover: Path | None = None,
                 music: Path | None = None, offline: bool = False,
                 no_tts: bool = False, use_llm: bool = True,
                 resume_dir: Path | None = None, series_info: dict | None = None,
                 max_rounds: int | None = None) -> dict:
    quality = (quality or cfg.get("quality", {}).get("default", "preview")).lower()
    preview = quality != "final"
    if offline:
        no_tts = True
    # Six beats with a 2s floor need 12s; shorter requests are rounded up so the
    # storyboard duration always matches the rendered timeline.
    duration = max(12.0, min(float(duration), 180.0))
    if max_rounds is not None:
        cfg = copy.deepcopy(cfg)
        cfg.setdefault("quality", {}).setdefault("gate", {})["max_rounds"] = max(1, int(max_rounds))

    if resume_dir is not None:
        run_dir = Path(resume_dir)
        state = _load(run_dir / "checkpoint.json", {}) or {}
        prompt = state.get("prompt") or prompt
        ratio = state.get("ratio") or ratio
        duration = float(state.get("duration") or duration)
        quality = state.get("quality") or quality
        run_id = state.get("run_id") or run_dir.name
        log.info("Resuming run %s from stage %s", run_id, state.get("stage"))
    else:
        run_id = time.strftime("%Y%m%d_%H%M%S") + "_" + _slug(prompt)
        run_dir = PROJECT_ROOT / "runs" / run_id
        state = {"run_id": run_id, "prompt": prompt, "ratio": ratio,
                 "duration": duration, "quality": quality}
    scenes_dir = run_dir / "scenes"
    scenes_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "frames").mkdir(parents=True, exist_ok=True)

    fh = logging.FileHandler(run_dir / "run.log", encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s"))
    logging.getLogger("motionforge").addHandler(fh)

    budget = BudgetManager(cfg, PROJECT_ROOT, run_id)
    llm_cfg = dict(cfg)
    if offline or not use_llm or not cfg.get("api_key"):
        llm_cfg["api_key"] = ""
    llm = LLMClient(llm_cfg, log_dir=run_dir / "llm_logs", budget=budget)
    width, height = resolution_for(cfg, ratio)
    dsf = 0.5 if preview else 1.0
    output_resolution = [round(width * dsf), round(height * dsf)]
    log.info("Run %s | %s | %.0fs | %s | %dx%d (output %dx%d) | llm=%s",
             run_id, ratio, duration, quality, width, height,
             output_resolution[0], output_resolution[1], not llm.offline)

    memory = Memory(PROJECT_ROOT / "memory", cfg)
    warnings: list[str] = []
    _checkpoint(run_dir, "start", run_id=run_id, prompt=prompt, ratio=ratio,
                duration=duration, quality=quality)

    # ---- 1. Concept ----
    concept = None
    concept_path = run_dir / "concept.json"
    if concept_path.exists():
        concept = _load(concept_path)
    if not concept:
        concept = choose_concept(prompt, PROJECT_ROOT)
        _dump(concept_path, concept)
    _checkpoint(run_dir, "concept", concept_id=concept["id"])

    # ---- 2. Verified puzzle ----
    puzzle_path, verification_path = run_dir / "puzzle.json", run_dir / "verification.json"
    puzzle, verification = _load(puzzle_path), _load(verification_path)
    if not puzzle or not verification:
        allow_llm = None if llm.offline or budget.remaining_today() < 4 else llm
        puzzle, verification = generate_puzzle(cfg, allow_llm, prompt, concept, PROJECT_ROOT,
                                               max_attempts=2)
        save_puzzle(run_dir, puzzle, verification)
    if not verification.get("verified_by_code"):
        warnings.append("puzzle answer is not code-verified")
    _checkpoint(run_dir, "puzzle", puzzle_type=puzzle.get("type"),
                answer=puzzle.get("answer"), verified=verification.get("verified_by_code"))

    # ---- 3. Hooks ----
    hooks_path = run_dir / "hooks.json"
    hooks = _load(hooks_path)
    if not hooks:
        hooks = generate_hooks(concept, puzzle, None if llm.offline else llm)
        _dump(hooks_path, hooks)
    _checkpoint(run_dir, "hooks", hook=(hooks.get("best") or {}).get("text"))

    # ---- 4. Storyboard ----
    storyboard_path = run_dir / "storyboard.json"
    storyboard = _load(storyboard_path)
    if not storyboard:
        storyboard = build_storyboard(puzzle, concept, hooks, duration, cfg)
        storyboard["ratio"] = ratio
        storyboard["prompt"] = prompt
        storyboard, issues = _consistency_fix(storyboard, puzzle, cfg)
        _dump(storyboard_path, _strip_layout(storyboard))
        if issues:
            warnings.extend(i["code"] for i in issues)
    _checkpoint(run_dir, "storyboard",
                scenes=len(storyboard.get("scenes") or []), attempts=1)

    # ---- 5. Scenes ----
    with Renderer(cfg, ratio, preview) as renderer:
        renderer.run_dir = run_dir
        renderer.motion_js = (PROJECT_ROOT / "templates" / "motion.js").read_text(encoding="utf-8")
        from .scene_builder import PALETTE
        renderer.palette = PALETTE
        specs = build_scene_specs(storyboard, cfg, width, height)
        write_scene_files(specs, scenes_dir)
        _checkpoint(run_dir, "scenes", scene_count=len(specs))

        # ---- 6. Deterministic render checks (+ repair/rescue) ----
        check_results, check_problems = _render_and_repair(renderer, specs, puzzle, cfg, scenes_dir)
        storyboard["scenes"] = specs
        _dump(run_dir / "storyboard.json", _strip_layout(storyboard))
        _dump(run_dir / "scene_checks.json", check_results)
        _checkpoint(run_dir, "checks",
                    passed=sum(1 for r in check_results if not r["problems"]),
                    failed=sum(1 for r in check_results if r["problems"]))

        rendered_issues = check_rendered(
            [scenes_dir / f"scene_{i:02d}.html" for i in range(1, len(specs) + 1)],
            puzzle, storyboard)
        if rendered_issues:
            warnings.extend(i["code"] for i in rendered_issues)

        # ---- 7. Judge rounds on rendered evidence (audio projected) ----
        audio_projection = {"voiceover": not no_tts, "music": "planned",
                            "target_lufs": cfg.get("audio", {}).get("target_lufs", -14)}
        rounds = _storyboard_rounds(cfg, run_dir, storyboard, puzzle, verification,
                                    check_results, None if llm.offline else llm, audio_projection)
        best_sb = rounds["storyboard"]
        best_sb["ratio"] = ratio
        best_sb["prompt"] = prompt
        if best_sb.get("scenes") != storyboard.get("scenes"):
            log.info("Applying judge improvements from round %d", rounds["best_round"])
            storyboard = best_sb
            storyboard, issues = _consistency_fix(storyboard, puzzle, cfg)
            if issues:
                warnings.extend(i["code"] for i in issues)
            _dump(storyboard_path, _strip_layout(storyboard))
            specs = build_scene_specs(storyboard, cfg, width, height)
            write_scene_files(specs, scenes_dir)
            check_results, check_problems = _render_and_repair(renderer, specs, puzzle, cfg, scenes_dir)
            storyboard["scenes"] = specs
            _dump(run_dir / "storyboard.json", _strip_layout(storyboard))
            _dump(run_dir / "scene_checks.json", check_results)
        else:
            storyboard = best_sb

        # ---- 8. Audio ----
        audio_report = build_audio(run_dir, storyboard, cfg,
                                   external_voiceover=voiceover, external_music=music,
                                   tts_enabled=False if no_tts else None)
        if not audio_report.get("voiceover"):
            warnings.append("voiceover unavailable; video uses music + SFX")
        _checkpoint(run_dir, "audio", voiceover=audio_report.get("voiceover"),
                    loudnorm=audio_report.get("loudnorm"))

        # ---- 9. Final judge panel with real audio evidence ----
        final_panel = deterministic_panel(storyboard, verification, check_results, audio_report, cfg)
        _dump(run_dir / "judge.json", final_panel)
        improvement = _load(run_dir / "improvement_log.json", {}) or {}
        improvement.update({
            "run_id": run_id,
            "final_scores": final_panel["scores"],
            "final_overall": final_panel["overall"],
            "final_gate_passed": final_panel["passed"],
            "final_gates": final_panel["gates"],
            "weaknesses": final_panel.get("evidence"),
            "honest_notes": (
                "Scores evaluate measured layout, verified correctness, timed narration and the "
                "actual audio master. They are not a substitute for human or channel analytics."
            ),
        })
        _dump(run_dir / "improvement_log.json", improvement)
        _checkpoint(run_dir, "judged", overall=final_panel["overall"], passed=final_panel["passed"])

        # ---- 10. Packaging ----
        package = package_run(run_dir, storyboard, puzzle, verification, final_panel,
                              audio_report, cfg, run_dir / "final.mp4", concept, series_info)
        _checkpoint(run_dir, "packaged", title=package["title"])

        # ---- 11. Final render + encode ----
        final_scenes = [(scenes_dir / f"scene_{i:02d}.html", float(s.get("duration") or 4.0))
                        for i, s in enumerate(specs, start=1)]
        frames_dir = run_dir / "frames" / "final"
        log.info("Rendering final video: %d scenes, %d frames", len(final_scenes),
                 round(sum(d for _, d in final_scenes) * renderer.fps))
        n_frames = renderer.render_frames(final_scenes, frames_dir)
        out_path = run_dir / "final.mp4"
        renderer.encode(frames_dir, out_path, audio_path=Path(audio_report["path"]))
        _checkpoint(run_dir, "rendered", frames=n_frames)

        # Re-write the package now that the video definitely exists.
        if not Path(package.get("video") or "").exists():
            package = package_run(run_dir, storyboard, puzzle, verification, final_panel,
                                  audio_report, cfg, out_path, concept, series_info)

    # ---- 12. Memory + analytics + report ----
    if check_problems:
        codes = sorted({p.code for p in check_problems})
        for code in codes[:3]:
            memory.add_lesson(f"Rendered scene problem: {code}",
                              "deterministic component layout",
                              "Keep scene copy short and keep every block inside the mobile safe area.",
                              "layout")
    memory.save()
    report = {
        "run_id": run_id,
        "prompt": prompt,
        "ratio": ratio,
        "duration": duration,
        "quality": quality,
        "preview": preview,
        "fps": renderer.fps,
        "resolution": output_resolution,
        "frames_rendered": n_frames,
        "concept": concept.get("id"),
        "concept_name": concept.get("name"),
        "puzzle_type": puzzle.get("type"),
        "answer": puzzle.get("answer"),
        "verification": verification,
        "scores": final_panel["scores"],
        "overall_score": final_panel["overall"],
        "gate_passed": final_panel["passed"],
        "gates": final_panel["gates"],
        "scene_checks": check_results,
        "checks_passed": not check_problems,
        "audio": audio_report,
        "budget": budget.snapshot(),
        "degraded": bool(llm.degraded or warnings),
        "degraded_reasons": list(dict.fromkeys(llm.degraded_reasons + warnings)),
        "series": series_info,
        "scenes": [{"id": i, "tag": s.get("tag"), "duration": s.get("duration"),
                    "component": s.get("component")} for i, s in enumerate(specs, start=1)],
        "totals": {
            "scenes": len(specs),
            "problems_found": len(check_problems),
            "unresolved": sum(len(r["problems"]) for r in check_results),
            "judge_rounds": len(improvement.get("rounds") or []),
        },
        "output": str(out_path),
        "package": str(run_dir / "package.json"),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    _dump(run_dir / "report.json", report)
    analytics.record_run(PROJECT_ROOT, report, {"concept": concept.get("id"),
                                                "overall": final_panel["overall"],
                                                "passed": final_panel["passed"]}, package)
    _checkpoint(run_dir, "done", output=str(out_path))

    logging.getLogger("motionforge").removeHandler(fh)
    fh.close()
    llm.close()
    log.info("Done: %s | overall %.2f | gate=%s | unresolved=%d",
             out_path.name, final_panel["overall"], final_panel["passed"],
             report["totals"]["unresolved"])
    return report
