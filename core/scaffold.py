"""Deterministic scene scaffold: safe-area CSS design system + component injection.

The LLM never writes HTML. It supplies structured scene JSON; this module turns
that JSON into a self-contained HTML document that is guaranteed to define
`window.setTime(t)` and `window.SCENE_DURATION`, use the mobile safe area, and
animate purely from `t`.
"""
from __future__ import annotations

import html
from pathlib import Path

from .captions import CAPTION_JS, caption_html, captions_for_scene
from .components import COMPONENTS, render_component
from .layout import FrameLayout, css_variables

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"

BASE_CSS = r"""
* { box-sizing: border-box; margin: 0; padding: 0; }
:root {
  --bg: #070B18; --surface: #111A2E; --surface2: #16213A;
  --primary: #22D3EE; --accent: #FACC15; --danger: #EF4444;
  --text: #F8FAFC; --muted: #94A3B8;
  --w: 1080px; --h: 1920px;
  --safe-top: 154px; --safe-bottom: 288px;
  --headline: 92px; --body: 56px; --caption: 50px; --min-font: 46px;
  --gutter: 65px; --gap: 22px;
}
html, body { width: 100%; height: 100%; overflow: hidden; background: #070B18; }
body {
  font-family: "Segoe UI", Arial, Helvetica, sans-serif;
  color: var(--text); -webkit-font-smoothing: antialiased;
  text-rendering: geometricPrecision;
}
.stage {
  position: absolute; inset: 0; width: var(--w); height: var(--h);
  overflow: hidden;
  background:
    radial-gradient(1200px 900px at 78% 4%, rgba(34,211,238,0.16), transparent 62%),
    radial-gradient(1000px 900px at 10% 96%, rgba(250,204,21,0.12), transparent 60%),
    linear-gradient(165deg, #0A1226 0%, #070B18 48%, #050813 100%);
}
.stage-inner { position: absolute; inset: 0; }
.bg-grid {
  position: absolute; inset: 0; opacity: 0.12;
  background-image:
    linear-gradient(rgba(148,163,184,0.35) 1px, transparent 1px),
    linear-gradient(90deg, rgba(148,163,184,0.35) 1px, transparent 1px);
  background-size: 64px 64px;
  mask-image: radial-gradient(circle at 50% 42%, #000 20%, transparent 78%);
}
.vignette {
  position: absolute; inset: 0;
  background: radial-gradient(circle at 50% 42%, transparent 38%, rgba(0,0,0,0.55) 100%);
}
.glow { position: absolute; border-radius: 50%; filter: blur(8px); pointer-events: none; }
.glow-a { width: 820px; height: 820px; top: -250px; right: -260px;
  background: radial-gradient(circle, rgba(34,211,238,0.22), transparent 66%); }
.glow-b { width: 760px; height: 760px; bottom: -240px; left: -220px;
  background: radial-gradient(circle, rgba(250,204,21,0.16), transparent 66%); }
.topbar {
  position: absolute; top: calc(var(--safe-top) + 2px); left: var(--gutter); right: var(--gutter);
  display: flex; align-items: center; justify-content: space-between;
  font-size: var(--min-font); font-weight: 800; letter-spacing: 0.12em;
  text-transform: uppercase; color: var(--muted);
}
.topbar .dot { width: 14px; height: 14px; border-radius: 50%; background: var(--primary);
  box-shadow: 0 0 18px var(--primary); }
.topbar .tag { color: #A5F3FC; }
.content {
  position: absolute; top: calc(var(--safe-top) + 82px); left: var(--gutter); right: var(--gutter);
  bottom: calc(var(--safe-bottom) + 180px); display: flex;
}
.stack { width: 100%; height: 100%; display: flex; flex-direction: column;
  justify-content: space-between; align-items: stretch; gap: var(--gap); }
.occ { position: relative; }
.card {
  background: linear-gradient(160deg, rgba(22,33,58,0.97), rgba(10,16,31,0.97));
  border: 2px solid rgba(148,163,184,0.22); border-radius: 36px;
  padding: 30px 34px;
  box-shadow: 0 24px 60px rgba(0,0,0,0.45), inset 0 1px 0 rgba(255,255,255,0.06);
}
.chip {
  align-self: flex-start; background: linear-gradient(90deg, rgba(34,211,238,0.20), rgba(34,211,238,0.05));
  border: 2px solid rgba(34,211,238,0.55); color: #A5F3FC;
  font-size: var(--min-font); font-weight: 800; letter-spacing: 0.12em;
  text-transform: uppercase; padding: 14px 24px; border-radius: 999px;
}
.headline { font-size: var(--headline); line-height: 1.06; font-weight: 900;
  letter-spacing: -0.02em; color: var(--text); }
.micro { font-size: var(--min-font); font-weight: 800; letter-spacing: 0.14em;
  text-transform: uppercase; color: var(--muted); }
.mono { font-family: Consolas, "Courier New", monospace; font-variant-numeric: tabular-nums; }
.banner {
  align-self: stretch; text-align: center; font-size: var(--min-font); font-weight: 900;
  color: #0B1220; background: linear-gradient(90deg, var(--accent), #FDE68A);
  border-radius: 999px; padding: 18px 22px;
  box-shadow: 0 12px 30px rgba(250,204,21,0.25);
}
.hint-panel { min-height: 220px; display: flex; flex-direction: column;
  justify-content: center; gap: 10px; }
.hint-text { font-size: var(--body); line-height: 1.18; color: #E2E8F0; }
.body-text { font-size: var(--body); line-height: 1.2; color: #E2E8F0; }
.bullets { display: flex; flex-direction: column; gap: 14px; margin-top: 18px; }
.bullet { display: flex; align-items: flex-start; gap: 14px; font-size: var(--body);
  line-height: 1.18; color: var(--text); }
.bullet .dot { width: 18px; height: 18px; border-radius: 50%; background: var(--primary);
  flex: 0 0 auto; margin-top: 14px; box-shadow: 0 0 14px rgba(34,211,238,0.6); }

/* ---------- hook ---------- */
.hook-card { min-height: 930px; display: flex; flex-direction: column;
  justify-content: center; gap: 26px; }
.hook-q { font-size: var(--headline); line-height: 1.05; font-weight: 900; }
.hook-num { font-size: 108px; line-height: 1.12; font-weight: 900; color: var(--accent);
  letter-spacing: -0.02em; }
.hook-hint { font-size: var(--body); line-height: 1.18; color: var(--muted); font-weight: 600; }
.swipe { font-size: var(--min-font); font-weight: 800; color: #A5F3FC;
  text-align: center; letter-spacing: 0.06em; }
.swipe .arrow { color: var(--accent); }

/* ---------- sequence ---------- */
.seq-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; width: 100%; }
.seq-row { display: flex; align-items: center; justify-content: space-between; gap: 10px; width: 100%; }
.num-card { min-height: 198px; display: flex; flex-direction: column; align-items: center;
  justify-content: center; gap: 6px; background: linear-gradient(160deg, #17213A, #0B1224);
  border: 2px solid rgba(148,163,184,0.28); border-radius: 28px; padding: 16px 12px; }
.num-idx { font-size: var(--min-font); color: var(--muted); font-weight: 700; }
.num-val { font-size: 74px; font-weight: 900; color: var(--text); line-height: 1.05; }
.num-card.missing { border-color: var(--accent); background: rgba(250,204,21,0.10);
  box-shadow: 0 0 26px rgba(250,204,21,0.22); }
.num-card.missing .num-val { color: var(--accent); }
.seq-arrow { font-size: 58px; color: var(--primary); font-weight: 900; }

/* ---------- countdown ---------- */
.ring-wrap { position: relative; width: 640px; height: 640px; margin: 0 auto; flex: 0 0 auto; }
.ring-svg { width: 100%; height: 100%; }
.ring-center { position: absolute; inset: 0; display: flex; flex-direction: column;
  align-items: center; justify-content: center; gap: 6px; }
.ring-num { font-size: 172px; font-weight: 900; color: var(--text); line-height: 1; }
.prompt { font-size: var(--body); color: #E2E8F0; text-align: center; }

/* ---------- solution ---------- */
.steps { display: flex; flex-direction: column; gap: 10px; width: 100%; }
.step-card { min-height: 160px; display: flex; align-items: center; gap: 20px;
  padding: 14px 24px; border-radius: 28px; background: linear-gradient(160deg, #141F36, #0A1122);
  border: 2px solid rgba(148,163,184,0.22); flex-shrink: 0; }
.step-num { width: 64px; height: 64px; border-radius: 50%; background: var(--primary);
  color: #06121A; font-size: var(--min-font); font-weight: 900; display: flex;
  align-items: center; justify-content: center; flex: 0 0 auto; }
.step-body { display: flex; flex-direction: column; gap: 4px; }
.step-math { font-size: 58px; font-weight: 800; color: var(--accent); line-height: 1.06; }
.step-text { font-size: var(--min-font); color: var(--muted); line-height: 1.12; }
.answer-band { min-height: 250px; display: flex; flex-direction: column;
  align-items: center; justify-content: center; gap: 8px; text-align: center;
  background: radial-gradient(circle at 50% 40%, rgba(250,204,21,0.14), rgba(10,16,31,0.96) 70%);
  border: 3px solid rgba(250,204,21,0.45); border-radius: 36px; padding: 16px; flex-shrink: 0; }
.answer-num { font-size: 126px; line-height: 1; font-weight: 900; color: var(--accent); }
.answer-recap { font-size: var(--body); color: var(--text); }

/* ---------- payoff ---------- */
.answer-hero { min-height: 640px; display: flex; flex-direction: column;
  align-items: center; justify-content: center; gap: 18px; text-align: center;
  background: radial-gradient(circle at 50% 42%, rgba(250,204,21,0.18), rgba(10,16,31,0.97) 72%);
  border: 3px solid rgba(250,204,21,0.5); border-radius: 44px; padding: 30px; }
.answer-huge { font-size: 226px; line-height: 0.98; font-weight: 900; color: var(--accent);
  letter-spacing: -0.03em; }
.answer-label { font-size: var(--body); color: #E2E8F0; }
.answer-kicker { font-size: var(--min-font); font-weight: 800; letter-spacing: 0.18em;
  text-transform: uppercase; color: #A5F3FC; }
.recap-card { min-height: 160px; display: flex; align-items: center;
  justify-content: center; text-align: center; font-size: var(--body); color: var(--text); }
.loop-card { min-height: 150px; display: flex; align-items: center; gap: 16px;
  font-size: var(--body); line-height: 1.16; color: #E2E8F0;
  background: rgba(34,211,238,0.08); border: 2px solid rgba(34,211,238,0.35);
  border-radius: 28px; padding: 22px 26px; }
.loop-icon { font-size: 62px; color: var(--primary); line-height: 1; }
.particles { position: absolute; inset: 0; pointer-events: none; }
.particle { position: absolute; left: 50%; top: 42%; width: 10px; height: 10px;
  border-radius: 50%; background: var(--accent); opacity: 0; }

/* ---------- clues ---------- */
.clue-list { display: flex; flex-direction: column; gap: 16px; width: 100%; }
.clue-card { min-height: 244px; display: flex; align-items: center; gap: 22px; }
.clue-icon { width: 78px; height: 78px; border-radius: 22px; flex: 0 0 auto;
  display: flex; align-items: center; justify-content: center;
  background: rgba(34,211,238,0.14); border: 2px solid rgba(34,211,238,0.45);
  color: var(--primary); font-size: 44px; font-weight: 900; }
.clue-text { font-size: var(--body); line-height: 1.18; color: var(--text); }

/* ---------- truth / lie ---------- */
.tl-list { display: flex; flex-direction: column; gap: 16px; width: 100%; }
.tl-card { min-height: 292px; display: flex; flex-direction: column; gap: 8px;
  justify-content: center; position: relative; }
.tl-name { font-size: var(--min-font); color: var(--primary); font-weight: 900;
  letter-spacing: 0.08em; text-transform: uppercase; }
.tl-line { font-size: var(--body); line-height: 1.18; color: var(--text); }
.stamp { position: absolute; right: 24px; top: 20px; font-size: 46px; font-weight: 900;
  padding: 6px 14px; border: 3px solid var(--danger); color: var(--danger);
  border-radius: 12px; transform: rotate(-8deg); }
.stamp.true { border-color: var(--primary); color: var(--primary); }

/* ---------- suspects ---------- */
.sus-list { display: flex; flex-direction: column; gap: 16px; width: 100%; }
.suspect-card { min-height: 330px; display: flex; align-items: center; gap: 20px; }
.suspect-card svg { width: 160px; height: auto; flex: 0 0 auto; }
.sus-info { display: flex; flex-direction: column; gap: 8px; }
.sus-name { font-size: var(--min-font); color: var(--primary); font-weight: 900;
  letter-spacing: 0.08em; text-transform: uppercase; }
.sus-line { font-size: var(--min-font); line-height: 1.16; color: var(--text); }

/* ---------- bars ---------- */
.bar-chart { display: flex; align-items: flex-end; justify-content: space-around;
  gap: 18px; height: 880px; padding: 16px 8px; width: 100%; }
.bar-col { flex: 1; display: flex; flex-direction: column; align-items: center;
  justify-content: flex-end; gap: 10px; height: 100%; }
.bar { width: 100%; max-width: 130px; transform-origin: bottom;
  background: linear-gradient(180deg, var(--primary), #0E7490);
  border-radius: 16px 16px 6px 6px; box-shadow: 0 0 26px rgba(34,211,238,0.25); }
.bar-val { font-size: 54px; font-weight: 900; color: var(--accent); }
.bar-lab { font-size: var(--min-font); color: var(--muted); font-weight: 700; }

/* ---------- equation ---------- */
.eq-card { min-height: 760px; display: flex; flex-direction: column;
  align-items: center; justify-content: center; gap: 40px; }
.eq-line { font-size: 108px; font-weight: 900; color: var(--text);
  display: flex; align-items: center; gap: 22px; }
.eq-op { color: var(--primary); }
.eq-answer { font-size: 146px; font-weight: 900; color: var(--accent); }

/* ---------- compare ---------- */
.cmp-row { display: flex; align-items: stretch; justify-content: center; gap: 18px;
  width: 100%; min-height: 640px; }
.cmp-card { flex: 1; min-height: 620px; display: flex; flex-direction: column;
  align-items: center; justify-content: center; gap: 22px; text-align: center; }
.cmp-val { font-size: 118px; font-weight: 900; color: var(--accent); }
.vs { align-self: center; font-size: 58px; font-weight: 900; color: var(--primary);
  background: #0B1224; border: 3px solid rgba(34,211,238,0.5); border-radius: 50%;
  width: 104px; height: 104px; display: flex; align-items: center; justify-content: center; }

/* ---------- progress ---------- */
.prog-list { display: flex; flex-direction: column; gap: 18px; width: 100%; }
.prog-item { min-height: 210px; display: flex; align-items: center; gap: 22px;
  padding: 22px 26px; border-radius: 28px; background: rgba(17,26,46,0.9);
  border: 2px solid rgba(148,163,184,0.2); }
.prog-item.done { opacity: 0.85; border-color: rgba(34,211,238,0.5); }
.prog-item.current { border-color: var(--accent); box-shadow: 0 0 28px rgba(250,204,21,0.18); }
.prog-dot { width: 70px; height: 70px; border-radius: 50%; background: var(--surface2);
  color: var(--text); font-size: 50px; font-weight: 900; display: flex;
  align-items: center; justify-content: center; flex: 0 0 auto; }
.prog-item.done .prog-dot { background: var(--primary); color: #06121A; }
.prog-item.current .prog-dot { background: var(--accent); color: #0B1220; }
.prog-text { font-size: var(--body); line-height: 1.16; color: var(--text); }

/* ---------- counter ---------- */
.counter-card { min-height: 780px; display: flex; flex-direction: column;
  align-items: center; justify-content: center; gap: 24px; }
.counter-num { font-size: 236px; font-weight: 900; color: var(--accent); line-height: 1; }
.counter-bar { width: 100%; height: 22px; border-radius: 999px;
  background: rgba(148,163,184,0.18); overflow: hidden; }
.counter-fill { height: 100%; width: 0%; background: linear-gradient(90deg, var(--primary), var(--accent)); }

/* ---------- text ---------- */
.text-card { min-height: 880px; display: flex; flex-direction: column;
  justify-content: center; gap: 20px; }

/* ---------- character ---------- */
.char-name { font-size: var(--min-font); font-weight: 900; letter-spacing: 0.14em;
  text-transform: uppercase; color: #A5F3FC; text-align: center; }
.char-stage { min-height: 700px; display: flex; align-items: center; justify-content: center; }
.char-stage svg { width: 430px; height: auto; }
.bubble { min-height: 180px; display: flex; align-items: center; justify-content: center;
  text-align: center; font-size: var(--body); line-height: 1.18; }

/* ---------- captions ---------- */
.caption-wrap {
  position: absolute; left: var(--gutter); right: var(--gutter);
  bottom: calc(var(--safe-bottom) + 18px); min-height: 108px;
  display: flex; flex-wrap: wrap; align-items: flex-end; justify-content: center;
  gap: 8px 14px; font-size: var(--caption); line-height: 1.08; font-weight: 900;
  text-align: center; text-shadow: 0 3px 0 rgba(0,0,0,0.65);
}
.word { color: #CBD5E1; padding: 0 2px; }
.word.active { color: var(--accent); text-shadow: 0 0 22px rgba(250,204,21,0.55); }
.word.past { color: var(--text); }

.progress-rail { position: absolute; left: var(--gutter); right: var(--gutter);
  bottom: calc(var(--safe-bottom) - 54px); height: 8px; border-radius: 999px;
  background: rgba(148,163,184,0.18); overflow: hidden; }
.progress-fill { height: 100%; width: 0%; border-radius: 999px;
  background: linear-gradient(90deg, var(--primary), var(--accent)); }

/* ---------- typography safety + density (overrides) ---------- */
/* Line boxes must be tall enough that glyphs never overflow their container. */
.topbar { white-space: nowrap; letter-spacing: 0.06em; }
.topbar span { white-space: nowrap; }
.chip, .banner, .micro, .swipe { line-height: 1.3; }
.headline, .hook-q { line-height: 1.28; }
.hook-num { line-height: 1.2; }
.hook-hint { line-height: 1.32; }
.num-val { line-height: 1.22; }
.seq-arrow, .ring-num { line-height: 1.3; }
.hint-text, .body-text { line-height: 1.3; }
.prompt { line-height: 1.3; }
.step-math { line-height: 1.22; }
.step-text { line-height: 1.28; }
.answer-num { line-height: 1.2; }
.answer-recap { line-height: 1.3; }
.answer-huge { line-height: 1.2; }
.answer-label, .answer-kicker { line-height: 1.3; }
.recap-card, .loop-card { line-height: 1.3; }
.loop-icon, .clue-icon { line-height: 1.3; }
.clue-text { line-height: 1.3; }
.tl-name, .tl-line { line-height: 1.3; }
.stamp { line-height: 1.2; }
.sus-name, .sus-line { line-height: 1.28; }
.bar-val { line-height: 1.2; }
.bar-lab { line-height: 1.3; }
.eq-line { line-height: 1.18; }
.eq-answer { line-height: 1.1; }
.cmp-val { line-height: 1.18; }
.prog-dot { line-height: 1.1; }
.prog-text { line-height: 1.3; }
.counter-num { line-height: 1.1; }
.bubble { line-height: 1.3; }
.char-name { line-height: 1.3; }
.banner { background-color: #FACC15; }
.clue-icon, .stamp { font-size: 50px; }

/* Dense mobile layout: real blocks cover >= 55% of frame height. */
.hook-card { min-height: 980px; }
.num-card { min-height: 256px; }
.hint-panel { min-height: 240px; }
.ring-wrap { width: 720px; height: 720px; }
.step-card { min-height: 175px; }
.answer-band { min-height: 270px; }
.answer-hero { min-height: 700px; }
.clue-card { min-height: 250px; }
.tl-card { min-height: 320px; }
.bar-chart { height: 980px; }
.cmp-row { min-height: 1000px; }
.cmp-card { min-height: 1000px; }
.prog-item { min-height: 310px; }
.counter-card { min-height: 1000px; }
.text-card { min-height: 1000px; }
.char-stage { min-height: 840px; }

/* Captions are rendered as short karaoke chunks, never full paragraphs. */
.caption-wrap { line-height: 1.3; min-height: 108px; }
.word { display: inline-block; line-height: 1.3; }
"""

SCENE_JS = r"""
(function () {
  "use strict";
  var dur = window.SCENE_DURATION;
  function $(id) { return document.getElementById(id); }
  window.setTime = function (time) {
    var t = Math.max(0, Math.min(dur, Number(time) || 0));
    var inner = $('stageInner');
    if (inner) {
      var env = MF.envelope(t, dur, 0.22, 0.22);
      inner.style.opacity = String(env);
    }
    var fill = $('progressFill');
    if (fill) { fill.style.width = (100 * t / Math.max(dur, 0.001)) + '%'; }
    __COMPONENT_JS__
    __CAPTION_JS__
  };
  window.setTime(0);
})();
"""


def _palette_css(palette: dict) -> str:
    pal = palette or {}
    return (
        f"--bg:{pal.get('bg', '#070B18')}; --surface:{pal.get('surface', '#111A2E')};"
        f"--surface2:{pal.get('surface2', '#16213A')}; --primary:{pal.get('primary', '#22D3EE')};"
        f"--accent:{pal.get('accent', '#FACC15')}; --danger:{pal.get('danger', '#EF4444')};"
        f"--text:{pal.get('text', '#F8FAFC')}; --muted:{pal.get('muted', '#94A3B8')};"
    )


def load_motion_js() -> str:
    path = TEMPLATE_DIR / "motion.js"
    return path.read_text(encoding="utf-8")


def build_scene_html(scene: dict, motion_js: str, layout: FrameLayout,
                     palette: dict, tag: str = "", index: int = 1,
                     total: int = 1) -> str:
    """Render one scene dict -> self-contained deterministic HTML string."""
    component = scene.get("component") or "text"
    props = scene.get("props") or {}
    rendered = render_component(component, props)
    duration = float(scene.get("duration") or 5.0)

    captions = scene.get("captions")
    if not captions:
        captions = captions_for_scene(scene.get("narration", ""), duration)
    cap_html = caption_html(captions)

    component_js = rendered.js.replace("</script", "<\\/script")
    scene_js = SCENE_JS.replace("__COMPONENT_JS__", component_js).replace(
        "__CAPTION_JS__", CAPTION_JS).replace("</script", "<\\/script")

    title = html.escape(str(scene.get("title") or scene.get("name") or ""))
    tag_text = html.escape(tag or scene.get("tag") or "PUZZLE")
    tick = f"{index:02d}/{total:02d}" if total else f"{index:02d}"

    css = "\n".join([
        BASE_CSS,
        ":root {", css_variables(layout), _palette_css(palette), "}",
    ])

    body = rendered.html.replace("</script", "<\\/script")
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
{css}
</style>
</head>
<body>
<div class="stage" id="stage">
  <div class="bg-grid"></div>
  <div class="glow glow-a"></div>
  <div class="glow glow-b"></div>
  <div class="vignette"></div>
  <div class="stage-inner" id="stageInner">
    <div class="topbar" id="topbar">
      <span>APTITUDE</span>
      <span class="dot"></span>
      <span class="tag">{tag_text} · {tick}</span>
    </div>
    <main class="content" id="content">
      {body}
    </main>
    <div class="caption-wrap occ" id="captionWrap">
      {cap_html}
    </div>
    <div class="progress-rail"><div class="progress-fill" id="progressFill"></div></div>
  </div>
</div>
<script>
{motion_js}
</script>
<script>
window.SCENE_DURATION = {duration:.3f};
{scene_js}
</script>
</body>
</html>
"""
