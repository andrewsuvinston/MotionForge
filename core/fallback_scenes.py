"""Deterministic fallback scenes.

Used when the LLM is unavailable (--offline or total API failure) so the pipeline
always produces a video. Built from the same MF helpers and design rules.
"""
from __future__ import annotations

import html as html_mod
import json


def _esc(s: str) -> str:
    return html_mod.escape(str(s), quote=True)


def build_scene_html(scene: dict, plan: dict, motion_js: str) -> str:
    pal = plan["palette"]
    fonts = plan["fonts"]
    dur = float(scene["duration"])
    headline = _esc(scene.get("headline") or plan.get("title", ""))
    sub = _esc(scene.get("sub") or "")
    kind = scene.get("visual", "title")
    data = scene.get("data") or {}

    body, script = "", ""
    if kind in ("title", "outro"):
        body = f"""
  <h1 id="headline">{headline}</h1>
  <div id="bar"></div>
  <div id="sub">{sub}</div>"""
        script = """
    MF.reveal(document.getElementById('headline'), t, 0.2, 0.7, {dy: 60});
    MF.reveal(document.getElementById('bar'), t, 0.55, 0.6, {dy: 0, scale: 0.2, ease: 'outExpo'});
    MF.reveal(document.getElementById('sub'), t, 0.9, 0.6, {dy: 30});"""
    elif kind == "bits":
        bits = data.get("bits") or [1, 0, 1, 1, 0, 1, 0, 1]
        value = sum(b * (2 ** (len(bits) - 1 - i)) for i, b in enumerate(bits))
        cards = "".join(f'<div class="bit {"zero" if not b else ""}">{b}</div>' for b in bits)
        body = f"""
  <h1 id="headline">{headline}</h1>
  <div class="bits">{cards}</div>
  <div id="sub">= <b id="num">0</b> {sub}</div>"""
        script = f"""
    MF.reveal(document.getElementById('headline'), t, 0.15, 0.6, {{dy: 50}});
    MF.stagger(document.querySelectorAll('.bit'), t, 0.8, 0.12, 0.45, {{dy: 0, scale: 0.6, ease: 'outBack'}});
    MF.reveal(document.getElementById('sub'), t, 2.0, 0.5, {{dy: 30}});
    MF.counter(document.getElementById('num'), t, 2.1, 1.2, 0, {value});"""
    elif kind == "bars":
        labels = data.get("labels") or ["A", "B", "C", "D"]
        values = data.get("values") or [3, 5, 8, 13]
        n = min(len(labels), len(values), 6)
        labels, values = labels[:n], values[:n]
        vmax = max(values) or 1
        cols = "".join(
            f'<div class="col"><div class="val" id="v{i}">{v}</div>'
            f'<div class="bar" style="height:{max(8, round(46 * v / vmax))}vmin"></div>'
            f'<div class="lbl">{_esc(l)}</div></div>'
            for i, (l, v) in enumerate(zip(labels, values)))
        body = f"""
  <h1 id="headline">{headline}</h1>
  <div class="chart">{cols}</div>
  <div id="sub">{sub}</div>"""
        script = """
    MF.reveal(document.getElementById('headline'), t, 0.15, 0.6, {dy: 50});
    MF.bars(document.querySelectorAll('.bar'), t, 0.7, 0.15, 0.7);
    MF.stagger(document.querySelectorAll('.val'), t, 1.0, 0.15, 0.4, {dy: 16});
    MF.stagger(document.querySelectorAll('.lbl'), t, 0.8, 0.15, 0.4, {dy: 16});
    MF.reveal(document.getElementById('sub'), t, 1.8, 0.5, {dy: 24});"""
    elif kind == "counter":
        target = data.get("value", 100)
        suffix = _esc(data.get("suffix", ""))
        body = f"""
  <h1 id="headline">{headline}</h1>
  <div id="big"><span id="num">0</span>{suffix}</div>
  <div id="sub">{sub}</div>"""
        script = f"""
    MF.reveal(document.getElementById('headline'), t, 0.15, 0.6, {{dy: 50}});
    MF.reveal(document.getElementById('big'), t, 0.5, 0.6, {{dy: 0, scale: 0.7, ease: 'outBack'}});
    MF.counter(document.getElementById('num'), t, 0.7, {max(0.8, dur - 1.5):.2f}, 0, {target});
    MF.reveal(document.getElementById('sub'), t, 1.4, 0.5, {{dy: 24}});"""
    elif kind == "line":
        values = data.get("values") or [1, 2, 4, 8, 16]
        n = min(len(values), 8)
        values = values[:n]
        vmax = max(values) or 1
        pts = " ".join(f"{10 + i * (80 / max(1, n - 1)):.1f},{88 - 72 * v / vmax:.1f}"
                       for i, v in enumerate(values))
        body = f"""
  <h1 id="headline">{headline}</h1>
  <svg id="chart" viewBox="0 0 100 100" preserveAspectRatio="xMidYMid meet">
    <polyline id="curve" points="{pts}" fill="none" stroke="{pal['primary']}"
      stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/>
  </svg>
  <div id="sub">{sub}</div>"""
        script = """
    MF.reveal(document.getElementById('headline'), t, 0.15, 0.6, {dy: 50});
    MF.reveal(document.getElementById('chart'), t, 0.4, 0.4, {dy: 0});
    MF.drawPath(document.getElementById('curve'), t, 0.7, Math.max(0.8, SCENE_DURATION - 1.6));
    MF.reveal(document.getElementById('sub'), t, 1.4, 0.5, {dy: 24});"""
    else:  # steps / icons / arrows
        labels = data.get("labels") or ["Input", "Process", "Output"]
        n = min(len(labels), 4)
        cards = "".join(
            f'<div class="step"><div class="circle">{i + 1}</div>'
            f'<div class="steplbl">{_esc(labels[i])}</div></div>'
            + ('<div class="arrow">&#8594;</div>' if i < n - 1 else "")
            for i in range(n))
        body = f"""
  <h1 id="headline">{headline}</h1>
  <div class="steps">{cards}</div>
  <div id="sub">{sub}</div>"""
        script = """
    MF.reveal(document.getElementById('headline'), t, 0.15, 0.6, {dy: 50});
    MF.stagger(document.querySelectorAll('.step'), t, 0.7, 0.35, 0.55, {dy: 40, ease: 'outCubic'});
    MF.stagger(document.querySelectorAll('.arrow'), t, 1.0, 0.35, 0.4, {dy: 0, dx: -20});
    MF.reveal(document.getElementById('sub'), t, 1.9, 0.5, {dy: 24});"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<script>
{motion_js}
</script>
<script>window.SCENE_DURATION = {json.dumps(dur)};</script>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  html, body {{ width: 100%; height: 100%; overflow: hidden; }}
  body {{ background: {pal['bg']}; color: {pal['text']};
         font-family: "{fonts['display']}", Arial, sans-serif; }}
  #stage {{ width: 100%; height: 100%; display: flex; flex-direction: column;
           align-items: center; justify-content: center; gap: 5vmin; padding: 8vmin; }}
  h1 {{ font-size: 7vmin; font-weight: 700; text-align: center; letter-spacing: -0.02em; }}
  #bar {{ width: 18vmin; height: 1.2vmin; border-radius: 1vmin; background: {pal['accent']}; }}
  #sub {{ font-size: 3.6vmin; color: {pal['muted']}; text-align: center; }}
  #big {{ font-size: 16vmin; font-weight: 800; color: {pal['primary']};
         font-family: "{fonts['mono']}", Consolas, monospace; }}
  .bits {{ display: flex; gap: 2vmin; flex-wrap: wrap; justify-content: center; }}
  .bit {{ width: 9vmin; height: 12vmin; display: flex; align-items: center; justify-content: center;
         font-family: "{fonts['mono']}", Consolas, monospace; font-size: 6.5vmin; font-weight: 700;
         border-radius: 1.6vmin; background: {pal['surface']};
         border: 0.35vmin solid {pal['primary']}; color: {pal['primary']}; }}
  .bit.zero {{ border-color: {pal['muted']}; color: {pal['muted']}; }}
  #sub b {{ color: {pal['accent']}; font-family: "{fonts['mono']}", Consolas, monospace; }}
  .chart {{ display: flex; align-items: flex-end; gap: 5vmin; height: 60vmin; }}
  .col {{ display: flex; flex-direction: column; align-items: center; justify-content: flex-end;
         gap: 1.6vmin; height: 100%; }}
  .bar {{ width: 10vmin; border-radius: 1.4vmin 1.4vmin 0.4vmin 0.4vmin;
         background: {pal['primary']}; transform-origin: bottom; }}
  .val {{ font-size: 3.6vmin; font-weight: 700; color: {pal['accent']};
         font-family: "{fonts['mono']}", Consolas, monospace; }}
  .lbl {{ font-size: 3.2vmin; color: {pal['muted']}; }}
  #chart {{ width: 70vmin; height: 55vmin; }}
  .steps {{ display: flex; align-items: center; gap: 3vmin; flex-wrap: wrap; justify-content: center; }}
  .step {{ display: flex; flex-direction: column; align-items: center; gap: 2.4vmin;
          background: {pal['surface']}; border-radius: 2.4vmin; padding: 4vmin 5vmin; }}
  .circle {{ width: 10vmin; height: 10vmin; border-radius: 50%; background: {pal['primary']};
            color: {pal['bg']}; display: flex; align-items: center; justify-content: center;
            font-size: 5.5vmin; font-weight: 800; }}
  .steplbl {{ font-size: 3.6vmin; font-weight: 600; }}
  .arrow {{ font-size: 6vmin; color: {pal['accent']}; }}
</style>
</head>
<body>
<div id="stage">{body}
</div>
<script>
  window.setTime = function (t) {{
    document.getElementById('stage').style.opacity = String(MF.envelope(t, SCENE_DURATION));
    {script}
  }};
  setTime(0);
</script>
</body>
</html>"""
