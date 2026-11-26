"""MotionForge CLI — a verified YouTube Shorts production studio.

Usage:
  python main.py create "number series puzzle, 35 seconds" [--ratio 9:16] [--quality preview]
  python main.py series "Daily Logic" --topic "number series" --count 3
  python main.py batch prompts.txt
  python main.py resume <run_id>
  python main.py analytics [--import metrics.json]
  python main.py budget
  python main.py feedback <run_id> "text"
  python main.py approve <run_id>
  python main.py lessons
  python main.py list
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from pathlib import Path

from core.analytics import import_metrics, summary as analytics_summary
from core.budget import BudgetManager
from core.config import PROJECT_ROOT, load_config
from core.llm import LLMClient, LLMError
from core.memory import Memory
from core.pipeline import create_video
from core.series import batch_create, create_series, load_prompts, resume_run

log = logging.getLogger("motionforge")


def _setup_logging(verbose: bool = False):
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(levelname)-7s %(name)s: %(message)s",
        stream=sys.stdout,
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def _infer(prompt: str, ratio: str | None, duration: float | None) -> tuple[str, float]:
    if ratio is None:
        m = re.search(r"\b(16:9|9:16|1:1)\b", prompt)
        ratio = m.group(1) if m else "9:16"
    if duration is None:
        m = re.search(r"(\d+(?:\.\d+)?)\s*(?:seconds?|secs?)\b", prompt, re.I)
        duration = float(m.group(1)) if m else 35.0
    return ratio, duration


def _print_report(report: dict):
    print("\n=== MotionForge run complete ===")
    print(f"Output:    {report['output']}")
    print(f"Package:   {report.get('package')}")
    print(f"Scenes:    {report['totals']['scenes']} | judge rounds: {report['totals']['judge_rounds']} | "
          f"unresolved problems: {report['totals']['unresolved']}")
    scores = report.get("scores") or {}
    print("Scores:    " + " | ".join(f"{k}={v:.1f}" for k, v in scores.items()))
    print(f"Overall:   {report.get('overall_score', 0):.2f}/10 | gate passed: {report.get('gate_passed')}")
    print(f"Answer:    {report.get('answer')} ({'verified' if (report.get('verification') or {}).get('verified_by_code') else 'UNVERIFIED'})")
    b = report.get("budget") or {}
    print(f"Budget:    {b.get('run_requests', 0)} requests this run, "
          f"{b.get('daily_used', 0)}/{b.get('daily_limit', 0)} today, "
          f"${b.get('run_cost_usd', 0):.4f}")
    if report.get("degraded_reasons"):
        print("Degraded:  " + "; ".join(str(x) for x in report["degraded_reasons"][:4]))
    run_dir = PROJECT_ROOT / "runs" / report["run_id"]
    for name in ("final.mp4", "package.json", "improvement_log.json", "verification.json"):
        p = run_dir / name
        print(f"  {'OK ' if p.exists() else 'MISSING'} {name}")


def cmd_create(args, cfg):
    ratio, duration = _infer(args.prompt, args.ratio, args.duration)
    if ratio not in ("16:9", "9:16", "1:1"):
        sys.exit(f"Unsupported ratio {ratio!r}")
    duration = max(12.0, min(float(duration), 180.0))
    for audio in (args.music, args.voiceover):
        if audio and not Path(audio).exists():
            sys.exit(f"Audio file not found: {audio}")
    quality = "preview" if args.preview else (args.quality or cfg.get("quality", {}).get("default", "preview"))
    report = create_video(
        cfg, args.prompt, ratio=ratio, duration=duration, quality=quality,
        voiceover=Path(args.voiceover) if args.voiceover else None,
        music=Path(args.music) if args.music else None,
        offline=args.offline, no_tts=args.no_tts or args.offline,
        use_llm=not (args.no_llm or args.offline),
        max_rounds=args.max_rounds,
    )
    _print_report(report)


def cmd_feedback(args, cfg):
    run_dir = PROJECT_ROOT / "runs" / args.run_id
    if not run_dir.exists():
        sys.exit(f"Unknown run: {args.run_id}")
    memory = Memory(PROJECT_ROOT / "memory", cfg)
    llm = LLMClient(cfg, log_dir=run_dir / "llm_logs")
    context = ""
    for name in ("storyboard.json", "plan.json"):
        path = run_dir / name
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                context = f"Video prompt: {data.get('prompt', '')}\nStoryboard: {str(data)[:3000]}"
                break
            except json.JSONDecodeError:
                pass
    lesson = None
    try:
        lesson = llm.chat_json(
            [{"role": "system", "content":
              "Convert user feedback about a generated Shorts video into ONE reusable lesson. "
              'Return ONLY JSON: {"problem": "...", "cause": "...", '
              '"rule": "one short imperative sentence", '
              '"category": "layout|contrast|typography|animation|content|style|technical"}'},
             {"role": "user", "content": f"{context}\nUser feedback: {args.text}"}],
            label="feedback_lesson", max_tokens=500, temperature=0.3,
        )
    except (LLMError, ValueError) as exc:
        log.warning("LLM feedback conversion failed (%s); storing feedback verbatim", exc)
    if not isinstance(lesson, dict) or not lesson.get("rule"):
        lesson = {"problem": args.text, "cause": "user feedback",
                  "rule": args.text[:200], "category": "style"}
    lid, merged = memory.add_lesson(lesson.get("problem", args.text), lesson.get("cause", ""),
                                    lesson["rule"], lesson.get("category", "style"))
    print(f"{'Merged into' if merged else 'Saved'} lesson {lid}: {lesson['rule']}")
    llm.close()


def cmd_approve(args, cfg):
    run_dir = PROJECT_ROOT / "runs" / args.run_id
    if not run_dir.exists():
        sys.exit(f"Unknown run: {args.run_id}")
    memory = Memory(PROJECT_ROOT / "memory", cfg)
    n = memory.approve_run(run_dir)
    print(f"Approved {n} scenes from {args.run_id} -> memory/approved/{args.run_id}/")


def cmd_lessons(args, cfg):
    memory = Memory(PROJECT_ROOT / "memory", cfg)
    if not memory.lessons:
        print("No lessons learned yet.")
        return
    print(f"{len(memory.lessons)} learned lessons:\n")
    for lesson in sorted(memory.lessons,
                         key=lambda x: (-x.get("times_helped", 0), -x.get("times_seen", 0))):
        print(f"  {lesson['id']}  [{lesson['category']:<10}] seen={lesson.get('times_seen', 0)} "
              f"helped={lesson.get('times_helped', 0)}")
        print(f"      {lesson['rule']}")


def cmd_list(args, cfg):
    runs_dir = PROJECT_ROOT / "runs"
    if not runs_dir.exists():
        print("No runs yet.")
        return
    rows = []
    for d in sorted(runs_dir.iterdir(), reverse=True):
        if not d.is_dir():
            continue
        info = {"id": d.name, "prompt": "", "status": "incomplete", "output": "", "extra": ""}
        report = d / "report.json"
        story = d / "storyboard.json"
        if report.exists():
            try:
                r = json.loads(report.read_text(encoding="utf-8"))
                info.update(prompt=r.get("prompt", ""), status="done",
                            output=r.get("output", ""),
                            extra=f"{r.get('ratio')} {r.get('duration')}s "
                                  f"{r.get('quality', '')} score={r.get('overall_score')}")
            except json.JSONDecodeError:
                pass
        elif story.exists():
            try:
                info["prompt"] = json.loads(story.read_text(encoding="utf-8")).get("prompt", "")
            except json.JSONDecodeError:
                pass
        rows.append(info)
    for r in rows:
        print(f"  {r['id']}  [{r['status']}] {r['extra']}")
        print(f"      {r['prompt'][:80]}")
        if r["output"]:
            print(f"      -> {r['output']}")


def cmd_series(args, cfg):
    reports = create_series(cfg, args.name, args.topic, count=args.count,
                            ratio=args.ratio, duration=args.duration,
                            quality="preview" if args.preview else args.quality,
                            offline=args.offline, use_llm=not (args.no_llm or args.offline),
                            no_tts=args.no_tts or args.offline)
    for report in reports:
        _print_report(report)


def cmd_batch(args, cfg):
    prompts = load_prompts(Path(args.file))
    if not prompts:
        sys.exit("No prompts found in batch file")
    reports = batch_create(cfg, prompts, ratio=args.ratio, duration=args.duration,
                           quality="preview" if args.preview else args.quality,
                           offline=args.offline, use_llm=not (args.no_llm or args.offline),
                           no_tts=args.no_tts or args.offline)
    for report in reports:
        _print_report(report)


def cmd_resume(args, cfg):
    report = resume_run(cfg, args.run_id, offline=args.offline,
                        use_llm=not (args.no_llm or args.offline),
                        no_tts=args.no_tts or args.offline)
    _print_report(report)


def cmd_analytics(args, cfg):
    if args.import_path:
        data = import_metrics(PROJECT_ROOT, Path(args.import_path))
        print(f"Imported {len(data.get('imported', {}))} run metric record(s).")
    summary = analytics_summary(PROJECT_ROOT)
    print(f"Analytics: {summary['runs']} run(s), updated {summary['updated'] or 'never'}")
    print(summary["note"])
    if not summary["concepts"]:
        print("  No concept data yet.")
        return
    print(f"\n{'concept':<18} {'runs':>4} {'avg':>6} {'pass':>5} {'retention':>9}")
    for c in summary["concepts"]:
        print(f"{c['concept']:<18} {c.get('runs', 0):>4} "
              f"{c.get('avg_overall', 0):>6.2f} {c.get('gate_passes', 0):>5} "
              f"{c.get('retention', c.get('retention_proxy', 0)):>9.2f}")


def cmd_budget(args, cfg):
    budget = BudgetManager(cfg, PROJECT_ROOT)
    snap = budget.snapshot()
    print(f"Budget: {budget.bar()}")
    print(f"  run limit: {snap['run_requests']}/{snap['run_limit']} requests")
    print(f"  cost:      ${snap['run_cost_usd']:.4f} / ${snap['max_cost_usd']:.2f}")
    print(f"  cache hits:{snap['cache_hits']}")
    print(f"  exhausted: {snap['exhausted']}")


def main():
    parser = argparse.ArgumentParser(prog="motionforge", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p, duration=True, quality=True):
        p.add_argument("--ratio", choices=["16:9", "9:16", "1:1"], default=None)
        if duration:
            p.add_argument("--duration", type=float, default=None)
        if quality:
            p.add_argument("--quality", choices=["preview", "final"], default=None)
            p.add_argument("--preview", action="store_true", help="Legacy alias for --quality preview")
        p.add_argument("--offline", action="store_true", help="No LLM/TTS network calls")
        p.add_argument("--no-llm", action="store_true", help="Deterministic generation only")
        p.add_argument("--no-tts", action="store_true", help="Music + SFX only")

    p = sub.add_parser("create", help="Create a Short from a prompt")
    p.add_argument("prompt")
    common(p)
    p.add_argument("--music", help="Background music file")
    p.add_argument("--voiceover", help="Voiceover file")
    p.add_argument("--max-rounds", type=int, default=None)
    p.set_defaults(fn=cmd_create)

    p = sub.add_parser("series", help="Create a numbered series")
    p.add_argument("name")
    p.add_argument("--topic", required=True)
    p.add_argument("--count", type=int, default=3)
    common(p)
    p.set_defaults(fn=cmd_series)

    p = sub.add_parser("batch", help="Create many Shorts from a prompt file")
    p.add_argument("file")
    common(p)
    p.set_defaults(fn=cmd_batch)

    p = sub.add_parser("resume", help="Resume an interrupted run from its checkpoint")
    p.add_argument("run_id")
    p.add_argument("--offline", action="store_true")
    p.add_argument("--no-llm", action="store_true")
    p.set_defaults(fn=cmd_resume)

    p = sub.add_parser("analytics", help="Show or import run analytics")
    p.add_argument("--import", dest="import_path", default=None,
                   help="JSON file: {run_id: {retention: 0..1, completion: 0..1}}")
    p.set_defaults(fn=cmd_analytics)

    p = sub.add_parser("budget", help="Show today's request/cost budget")
    p.set_defaults(fn=cmd_budget)

    p = sub.add_parser("feedback", help="Teach the agent from your feedback")
    p.add_argument("run_id")
    p.add_argument("text")
    p.set_defaults(fn=cmd_feedback)

    p = sub.add_parser("approve", help="Mark a run's scenes as good examples")
    p.add_argument("run_id")
    p.set_defaults(fn=cmd_approve)

    p = sub.add_parser("lessons", help="Print learned rules")
    p.set_defaults(fn=cmd_lessons)

    p = sub.add_parser("list", help="List past runs")
    p.set_defaults(fn=cmd_list)

    args = parser.parse_args()
    _setup_logging(args.verbose)
    cfg = load_config()
    args.fn(args, cfg)


if __name__ == "__main__":
    main()
