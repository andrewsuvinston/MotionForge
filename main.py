"""MotionForge CLI — self-improving code-based motion graphics agent.

Usage:
  python main.py create "prompt" [--ratio 9:16] [--duration 30] [--preview]
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

from core.config import PROJECT_ROOT, load_config
from core.llm import LLMClient, LLMError
from core.memory import Memory
from core.pipeline import create_video

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
        ratio = m.group(1) if m else "16:9"
    if duration is None:
        m = re.search(r"(\d+(?:\.\d+)?)\s*(?:seconds?|secs?)\b", prompt, re.I)
        duration = float(m.group(1)) if m else 30.0
    return ratio, duration


def cmd_create(args, cfg):
    ratio, duration = _infer(args.prompt, args.ratio, args.duration)
    if ratio not in cfg["render"]["resolutions"]:
        sys.exit(f"Unsupported ratio {ratio!r}; choose from {list(cfg['render']['resolutions'])}")
    duration = max(4.0, min(float(duration), 180.0))
    for audio in (args.music, args.voiceover):
        if audio and not Path(audio).exists():
            sys.exit(f"Audio file not found: {audio}")
    report = create_video(
        cfg, args.prompt, ratio=ratio, duration=duration, preview=args.preview,
        voiceover=Path(args.voiceover) if args.voiceover else None,
        music=Path(args.music) if args.music else None,
        no_review=args.no_review, offline=args.offline,
        max_iterations=args.max_iterations,
    )
    print("\n=== MotionForge run complete ===")
    print(f"Output:   {report['output']}")
    print(f"Scenes:   {len(report['scenes'])} | iterations: {report['totals']['iterations']} | "
          f"problems found: {report['totals']['problems_found']} | "
          f"unresolved: {report['totals']['unresolved']}")
    print(f"Lessons:  +{report['totals']['lessons_added']} added, "
          f"{report['totals']['lessons_pruned']} pruned")
    print(f"Report:   {PROJECT_ROOT / 'runs' / report['run_id'] / 'report.json'}")


def cmd_feedback(args, cfg):
    run_dir = PROJECT_ROOT / "runs" / args.run_id
    if not run_dir.exists():
        sys.exit(f"Unknown run: {args.run_id}")
    memory = Memory(PROJECT_ROOT / "memory", cfg)
    llm = LLMClient(cfg, log_dir=run_dir / "llm_logs")
    context = ""
    plan_path = run_dir / "plan.json"
    if plan_path.exists():
        try:
            context = f"Video prompt: {json.loads(plan_path.read_text(encoding='utf-8')).get('prompt', '')}"
        except json.JSONDecodeError:
            pass
    lesson = None
    try:
        lesson = llm.chat_json(
            [{"role": "system", "content":
              "Convert user feedback about a generated motion-graphics video into ONE reusable lesson. "
              'Return ONLY JSON: {"problem": "...", "cause": "...", '
              '"rule": "one short imperative sentence", '
              '"category": "layout|contrast|typography|animation|content|style|technical"}'},
             {"role": "user", "content": f"{context}\nUser feedback: {args.text}"}],
            cfg["models"]["generator_model"], label="feedback_lesson", max_tokens=500, temperature=0.3,
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
    for l in sorted(memory.lessons, key=lambda x: (-x.get("times_helped", 0), -x.get("times_seen", 0))):
        print(f"  {l['id']}  [{l['category']:<10}] seen={l.get('times_seen', 0)} "
              f"helped={l.get('times_helped', 0)}")
        print(f"      {l['rule']}")


def cmd_list(args, cfg):
    runs_dir = PROJECT_ROOT / "runs"
    if not runs_dir.exists():
        print("No runs yet.")
        return
    rows = []
    for d in sorted(runs_dir.iterdir(), reverse=True):
        if not d.is_dir():
            continue
        info = {"id": d.name, "prompt": "", "status": "incomplete", "output": ""}
        report = d / "report.json"
        plan = d / "plan.json"
        if report.exists():
            try:
                r = json.loads(report.read_text(encoding="utf-8"))
                info.update(prompt=r.get("prompt", ""), status="done",
                            output=r.get("output", ""),
                            extra=f"{r.get('ratio')} {r.get('duration')}s "
                                  f"{'preview' if r.get('preview') else 'final'}")
            except json.JSONDecodeError:
                pass
        elif plan.exists():
            try:
                info["prompt"] = json.loads(plan.read_text(encoding="utf-8")).get("prompt", "")
            except json.JSONDecodeError:
                pass
        rows.append(info)
    if not rows:
        print("No runs yet.")
        return
    for r in rows:
        print(f"  {r['id']}  [{r['status']}] {r.get('extra', '')}")
        print(f"      {r['prompt'][:80]}")
        if r["output"]:
            print(f"      -> {r['output']}")


def main():
    parser = argparse.ArgumentParser(prog="motionforge", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("create", help="Create a motion-graphics video from a prompt")
    p.add_argument("prompt")
    p.add_argument("--ratio", choices=["16:9", "9:16", "1:1"], default=None)
    p.add_argument("--duration", type=float, default=None, help="Total seconds (default: inferred or 30)")
    p.add_argument("--preview", action="store_true", help="Half resolution, 15 fps")
    p.add_argument("--music", help="Background music file (mp3/wav)")
    p.add_argument("--voiceover", help="Voiceover file (mp3/wav)")
    p.add_argument("--no-review", action="store_true", help="Skip the vision reviewer")
    p.add_argument("--offline", action="store_true", help="No LLM calls; built-in templates only")
    p.add_argument("--max-iterations", type=int, default=None)
    p.set_defaults(fn=cmd_create)

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
