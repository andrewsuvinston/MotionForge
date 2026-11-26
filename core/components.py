"""Visual component library: deterministic HTML + setTime JS per component.

Every component is designed for a 1080x1920 (9:16) stage, uses the safe area,
fills the frame (occupancy >= 55%), and animates only from `t` via MF helpers.
"""
from __future__ import annotations

import html
from dataclasses import dataclass


@dataclass
class Rendered:
    html: str
    js: str


def _e(value) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def _pct(x: float) -> int:
    return max(0, min(100, round(x * 100)))


# --------------------------------------------------------------------------- hook

def _hook(p: dict) -> Rendered:
    badge = _e(p.get("badge") or "ONLY 1 IN 10 GETS THIS")
    question = _e(p.get("question") or "What comes next?")
    terms = p.get("terms") or []
    seq = "  ".join(_e(x) for x in terms) + "  ?" if terms else _e(p.get("number") or "?")
    hint = _e(p.get("hint") or "You have five seconds.")
    label = _e(p.get("label") or "NUMBER SERIES · CAN YOU CRACK IT?")
    micro = _e(p.get("micro") or "ONE RULE · ONE ANSWER")
    swipe_text = _e(p.get("swipe") or "Watch to the end")
    body = f"""
<div class="stack" id="hookWrap">
  <div class="chip occ pulse-soft" id="badge">{badge}</div>
  <div class="card hook-card occ" id="hookCard">
    <div class="micro" id="hookLab">{label}</div>
    <div class="hook-q" id="hookQ">{question}</div>
    <div class="hook-num mono occ" id="hookNum">{seq}</div>
    <div class="micro" id="hookMicro">{micro}</div>
    <div class="hook-hint" id="hookHint">{hint}</div>
  </div>
  <div class="swipe occ" id="swipe">{swipe_text} <span class="arrow">&#8594;</span></div>
</div>"""
    js = """
    var card = $('hookCard');
    var p0 = MF.seg(t, 0.0, 0.45, 'outCubic');
    if (card) {
      card.style.opacity = '1';
      card.style.transform = 'translateY(' + (46 * (1 - p0)) + 'px) scale(' + (0.92 + 0.08 * p0) + ') rotate(' + ((1 - p0) * -1.4) + 'deg)';
    }
    var badge = $('badge');
    if (badge) { badge.style.opacity = String(MF.seg(t, 0.0, 0.25, 'outCubic')); }
    var q = $('hookQ');
    if (q) {
      var pq = MF.seg(t, 0.0, 0.5, 'outCubic');
      q.style.opacity = String(0.35 + 0.65 * pq);
      q.style.transform = 'translateY(' + (24 * (1 - pq)) + 'px)';
    }
    var num = $('hookNum');
    if (num) {
      var pn = MF.seg(t, 0.05, 0.55, 'outBack');
      num.style.opacity = String(Math.min(1, pn * 1.6));
      var glow = 0.5 + 0.5 * Math.sin(t * 5.2);
      num.style.transform = 'scale(' + (0.88 + 0.12 * pn) + ')';
      num.style.filter = 'drop-shadow(0 0 ' + (18 + 22 * glow) + 'px rgba(250,204,21,0.45))';
    }
    var hint = $('hookHint');
    if (hint) { MF.reveal(hint, t, 0.75, 0.45, {dy: 18}); }
    var micro = $('hookMicro');
    if (micro) { MF.reveal(micro, t, 0.6, 0.4, {dy: 12}); }
    var swipe = $('swipe');
    if (swipe) {
      MF.reveal(swipe, t, 1.15, 0.5, {dy: 16});
      var ps = MF.seg(t, 1.3, 1.2, 'inOutSine');
      swipe.style.opacity = String((swipe.style.opacity || 1) * (0.65 + 0.35 * ps));
    }
    var lab = $('hookLab');
    if (lab) { MF.reveal(lab, t, 0.35, 0.4, {dy: 10}); }
"""
    return Rendered(body, js)


# ----------------------------------------------------------------------- sequence

def _sequence(p: dict) -> Rendered:
    terms = [str(x) for x in (p.get("terms") or [])]
    title = _e(p.get("title") or "What comes next?")
    hint = _e(p.get("hint") or "Look at what changes between terms.")
    chip = _e(p.get("chip") or "FIND THE PATTERN")
    micro = _e(p.get("micro") or "5 TERMS · 1 RULE")
    show_missing = bool(p.get("show_missing", True))
    cards = []
    many = len(terms) > 5
    for i, term in enumerate(terms):
        cards.append(f'<div class="num-card occ" id="nc{i}"><div class="num-idx">{i + 1}</div>'
                     f'<div class="num-val mono">{_e(term)}</div></div>')
        if not many and i < len(terms) - 1:
            cards.append(f'<div class="seq-arrow" id="ar{i}">&#8250;</div>')
    if show_missing:
        cards.append('<div class="num-card missing occ" id="ncMissing">'
                     '<div class="num-idx">?</div><div class="num-val mono">?</div></div>')
    grid_cls = "seq-grid" if many else "seq-row"
    body = f"""
<div class="stack">
  <div class="chip occ" id="seqChip">{chip}</div>
  <h2 class="headline occ" id="seqTitle">{title}</h2>
  <div class="micro occ" id="seqMicro">{micro}</div>
  <div class="{grid_cls} occ" id="seqRow">{''.join(cards)}</div>
  <div class="hint-panel card occ" id="hintPanel">
    <div class="micro">PATTERN HINT</div>
    <div class="hint-text" id="hintText">{hint}</div>
  </div>
  <div class="banner occ" id="banner">Comment your answer before the timer ends</div>
</div>"""
    js = """
    var chip = $('seqChip');
    if (chip) { MF.reveal(chip, t, 0.0, 0.3, {dy: -14}); }
    var title = $('seqTitle');
    if (title) { MF.reveal(title, t, 0.08, 0.45, {dy: 30}); }
    var micro = $('seqMicro');
    if (micro) { MF.reveal(micro, t, 0.18, 0.4, {dy: 14}); }
    var cards = document.querySelectorAll('.num-card');
    for (var i = 0; i < cards.length; i++) {
      var start = 0.25 + i * 0.13;
      MF.reveal(cards[i], t, start, 0.42, {dy: 26, scale: 0.7, ease: 'outBack'});
    }
    var missing = $('ncMissing');
    if (missing) {
      var pm = MF.seg(t, 0.9, 1.1, 'inOutSine');
      missing.style.boxShadow = '0 0 ' + (16 + 26 * pm) + 'px rgba(250,204,21,0.55)';
      missing.style.borderColor = '#FACC15';
    }
    var arrows = document.querySelectorAll('.seq-arrow');
    for (var j = 0; j < arrows.length; j++) {
      MF.reveal(arrows[j], t, 0.4 + j * 0.13, 0.3, {dy: 0, dx: -10});
    }
    var hintPanel = $('hintPanel');
    if (hintPanel) { MF.reveal(hintPanel, t, dur * 0.52, 0.5, {dy: 22}); }
    var banner = $('banner');
    if (banner) {
      MF.reveal(banner, t, dur * 0.68, 0.45, {dy: 18});
      var pb = MF.seg(t, dur * 0.68, 0.45, 'outCubic');
      banner.style.opacity = String(pb * (0.85 + 0.15 * Math.sin(t * 4)));
    }
"""
    return Rendered(body, js)


# ---------------------------------------------------------------------- countdown

def _countdown(p: dict) -> Rendered:
    seconds = max(3, int(p.get("seconds") or 5))
    title = _e(p.get("title") or "Your turn. Lock in an answer.")
    prompt = _e(p.get("prompt") or "Comment before the ring closes")
    ticks = "".join(
        f'<line x1="300" y1="26" x2="300" y2="44" stroke="#334155" stroke-width="4" '
        f'transform="rotate({i * 30} 300 300)"/>' for i in range(12))
    body = f"""
<div class="stack">
  <div class="chip occ" id="cdChip">VIEWER CHALLENGE</div>
  <h2 class="headline occ" id="cdTitle">{title}</h2>
  <div class="ring-wrap occ" id="ringWrap">
    <svg viewBox="0 0 600 600" class="ring-svg">
      {ticks}
      <circle cx="300" cy="300" r="250" fill="none" stroke="#1E293B" stroke-width="30"/>
      <circle id="ring" cx="300" cy="300" r="250" fill="none" stroke="#22D3EE" stroke-width="30"
              stroke-linecap="round" transform="rotate(-90 300 300)"/>
    </svg>
    <div class="ring-center">
      <div class="ring-num mono occ" id="cdNum">{seconds}</div>
      <div class="micro">SECONDS</div>
    </div>
  </div>
  <div class="prompt occ" id="cdPrompt">{prompt}</div>
  <div class="banner occ" id="cdBanner">No calculator. Trust the pattern.</div>
</div>"""
    js = f"""
    var C = 2 * Math.PI * 250;
    var ring = $('ring');
    var p = MF.clamp01(t / Math.max(dur, 0.001));
    if (ring) {{
      ring.style.strokeDasharray = String(C);
      ring.style.strokeDashoffset = String(C * (1 - p));
      ring.style.stroke = p > 0.72 ? '#EF4444' : '#22D3EE';
    }}
    var num = $('cdNum');
    if (num) {{
      var remaining = Math.max(0, Math.ceil({seconds} * (1 - p)));
      num.textContent = String(remaining);
      var frac = (t * 1.0) % 1;
      num.style.transform = 'scale(' + (1 + 0.07 * (1 - frac)) + ')';
      num.style.color = remaining <= 2 ? '#EF4444' : '#F8FAFC';
    }}
    var chip = $('cdChip');
    if (chip) {{ MF.reveal(chip, t, 0.0, 0.3, {{dy: -14}}); }}
    var title = $('cdTitle');
    if (title) {{ MF.reveal(title, t, 0.1, 0.45, {{dy: 28}}); }}
    var wrap = $('ringWrap');
    if (wrap) {{ MF.pop(wrap, t, 0.2, 0.6); }}
    var prompt = $('cdPrompt');
    if (prompt) {{ MF.reveal(prompt, t, 0.9, 0.5, {{dy: 20}}); }}
    var banner = $('cdBanner');
    if (banner) {{ MF.reveal(banner, t, 1.6, 0.5, {{dy: 16}}); }}
"""
    return Rendered(body, js)


# ----------------------------------------------------------------------- solution

def _solution(p: dict) -> Rendered:
    title = _e(p.get("title") or "Here is the trick")
    steps = p.get("steps") or []
    answer = _e(p.get("answer") or "")
    recap = _e(p.get("recap") or "")
    cards = []
    # Show the last three transitions: with four cards plus the answer band the
    # band content overflowed its border on a 1080x1920 frame. The final three
    # steps still end on the answer, so the logic reads cleanly.
    visible = steps[-3:]
    for i, step in enumerate(visible):
        math = _e(step.get("math") or "")
        text = _e(step.get("text") or "")
        cards.append(
            f'<div class="step-card occ" id="step{i}">'
            f'<div class="step-num">{i + 1}</div>'
            f'<div class="step-body"><div class="step-math mono">{math}</div>'
            f'<div class="step-text">{text}</div></div></div>')
    body = f"""
<div class="stack">
  <h2 class="headline occ" id="solTitle">{title}</h2>
  <div class="steps occ" id="steps">{''.join(cards)}</div>
  <div class="answer-band occ" id="answerBand">
    <div class="micro">ANSWER</div>
    <div class="answer-num mono occ" id="answerNum">{answer}</div>
    <div class="answer-recap" id="answerRecap">{recap}</div>
  </div>
</div>"""
    js = """
    var title = $('solTitle');
    if (title) { MF.reveal(title, t, 0.05, 0.4, {dy: 26}); }
    var steps = document.querySelectorAll('.step-card');
    var n = steps.length;
    for (var i = 0; i < n; i++) {
      var start = 0.15 + i * 0.55;
      MF.reveal(steps[i], t, start, 0.45, {dy: 26, dx: 18});
      var badge = steps[i].querySelector('.step-num');
      if (badge) { MF.pop(badge, t, start + 0.08, 0.36); }
    }
    // Reveal the answer shortly after the last step, never later than 55% of
    // the scene: waiting for 66% left the lower frame empty on 3-step puzzles.
    var bandAt = Math.min(dur * 0.55, 0.15 + Math.max(0, n - 1) * 0.55 + 1.0);
    var band = $('answerBand');
    if (band) { MF.reveal(band, t, bandAt, 0.45, {dy: 20, scale: 0.96}); }
    var num = $('answerNum');
    if (num) {
      var pn = MF.seg(t, bandAt + 0.1, 0.45, 'outBack');
      num.style.opacity = String(pn);
      num.style.transform = 'scale(' + (0.7 + 0.3 * pn) + ')';
      num.style.filter = 'drop-shadow(0 0 ' + (10 + 18 * Math.max(0, Math.sin((t - bandAt) * 6))) + 'px rgba(250,204,21,0.4))';
    }
    var recap = $('answerRecap');
    if (recap) { MF.reveal(recap, t, bandAt + 0.35, 0.4, {dy: 14}); }
"""
    return Rendered(body, js)


# ------------------------------------------------------------------------- payoff

def _payoff(p: dict) -> Rendered:
    answer = _e(p.get("answer") or "")
    recap = _e(p.get("recap") or "Did you get it before the timer?")
    teaser = _e(p.get("teaser") or "Next: a puzzle almost nobody solves.")
    kicker = _e(p.get("kicker") or "THE ANSWER IS")
    particles = "".join(
        f'<span class="particle" data-a="{i * 30}" data-d="{80 + (i % 4) * 26}"></span>'
        for i in range(12))
    body = f"""
<div class="stack">
  <div class="chip occ" id="payChip">ANSWER</div>
  <div class="answer-hero occ" id="payHero">
    <div class="answer-kicker">{kicker}</div>
    <div class="answer-huge mono occ" id="payNum">{answer}</div>
    <div class="answer-label">That is the next number.</div>
  </div>
  <div class="card recap-card occ" id="payRecap">{recap}</div>
  <div class="loop-card occ" id="payLoop">
    <span class="loop-icon">&#8635;</span>
    <span id="payTeaser">{teaser}</span>
  </div>
  <div class="particles" id="particles">{particles}</div>
</div>"""
    js = """
    var chip = $('payChip');
    if (chip) { MF.reveal(chip, t, 0.0, 0.25, {dy: -12}); }
    var hero = $('payHero');
    if (hero) { MF.pop(hero, t, 0.05, 0.55); }
    var num = $('payNum');
    if (num) {
      var pn = MF.seg(t, 0.08, 0.5, 'outBack');
      num.style.transform = 'scale(' + (0.6 + 0.4 * pn) + ')';
      num.style.filter = 'drop-shadow(0 0 ' + (24 + 20 * Math.sin(t * 6)) + 'px rgba(250,204,21,0.5))';
    }
    var recap = $('payRecap');
    if (recap) { MF.reveal(recap, t, 0.7, 0.45, {dy: 20}); }
    var loop = $('payLoop');
    if (loop) {
      MF.reveal(loop, t, 1.15, 0.45, {dy: 16});
      loop.style.opacity = String(parseFloat(loop.style.opacity || '1') * (0.8 + 0.2 * Math.sin(t * 3)));
    }
    var parts = document.querySelectorAll('.particle');
    for (var i = 0; i < parts.length; i++) {
      var a = parseFloat(parts[i].dataset.a) * Math.PI / 180;
      var d = parseFloat(parts[i].dataset.d);
      var pp = MF.seg(t, 0.12, 0.9, 'outExpo');
      var x = Math.cos(a) * d * pp, y = Math.sin(a) * d * pp;
      parts[i].style.transform = 'translate(' + x + 'px,' + y + 'px) scale(' + (1 - 0.5 * pp) + ')';
      parts[i].style.opacity = String(Math.max(0, 1 - pp));
    }
"""
    return Rendered(body, js)


# -------------------------------------------------------------------- clue cards

def _clue_cards(p: dict) -> Rendered:
    title = _e(p.get("title") or "Three clues. One answer.")
    clues = p.get("clues") or []
    cards = []
    for i, clue in enumerate(clues[:4]):
        icon = _e(clue.get("icon") or str(i + 1))
        text = _e(clue.get("text") or "")
        cards.append(f'<div class="clue-card card occ" id="clue{i}">'
                     f'<div class="clue-icon">{icon}</div><div class="clue-text">{text}</div></div>')
    body = f"""
<div class="stack">
  <h2 class="headline occ" id="clueTitle">{title}</h2>
  <div class="clue-list occ" id="clueList">{''.join(cards)}</div>
</div>"""
    js = """
    var title = $('clueTitle');
    if (title) { MF.reveal(title, t, 0.05, 0.4, {dy: 24}); }
    var cards = document.querySelectorAll('.clue-card');
    for (var i = 0; i < cards.length; i++) {
      MF.reveal(cards[i], t, 0.25 + i * 0.6, 0.5, {dy: 30, dx: 14});
    }
"""
    return Rendered(body, js)


# ---------------------------------------------------------------------- truth/lie

def _truth_lie(p: dict) -> Rendered:
    title = _e(p.get("title") or "One of them is lying")
    cards = p.get("cards") or []
    html_cards = []
    for i, c in enumerate(cards[:3]):
        name = _e(c.get("name") or f"Person {i + 1}")
        line = _e(c.get("line") or "")
        stamp = _e(c.get("stamp") or "?")
        cls = "stamp true" if stamp.upper() == "TRUE" else ("stamp lie" if stamp.upper() == "LIE" else "stamp")
        html_cards.append(f'<div class="tl-card card occ" id="tl{i}"><div class="tl-name">{name}</div>'
                          f'<div class="tl-line">"{line}"</div>'
                          f'<div class="{cls}" id="stamp{i}">{stamp}</div></div>')
    body = f"""
<div class="stack">
  <h2 class="headline occ" id="tlTitle">{title}</h2>
  <div class="tl-list occ">{''.join(html_cards)}</div>
</div>"""
    js = """
    var title = $('tlTitle');
    if (title) { MF.reveal(title, t, 0.05, 0.4, {dy: 24}); }
    var cards = document.querySelectorAll('.tl-card');
    for (var i = 0; i < cards.length; i++) { MF.reveal(cards[i], t, 0.2 + i * 0.5, 0.45, {dy: 24}); }
    var stamps = document.querySelectorAll('.stamp');
    for (var j = 0; j < stamps.length; j++) {
      var s = 0.9 + j * 0.5;
      var ps = MF.seg(t, s, 0.35, 'outBack');
      stamps[j].style.opacity = String(Math.min(1, ps * 1.3));
      stamps[j].style.transform = 'rotate(-8deg) scale(' + (1.6 - 0.6 * ps) + ')';
    }
"""
    return Rendered(body, js)


# ------------------------------------------------------------------------ suspects

def _suspects(p: dict) -> Rendered:
    from .characters import character_svg
    title = _e(p.get("title") or "Who is telling the truth?")
    suspects = p.get("suspects") or []
    cards = []
    for i, s in enumerate(suspects[:3]):
        svg = character_svg(s.get("character", "suspect"), s.get("expression", "neutral"),
                            width=160, animate_id=f"char{i}")
        name = _e(s.get("name") or f"Suspect {i + 1}")
        line = _e(s.get("line") or "")
        cards.append(f'<div class="suspect-card card occ" id="sus{i}">{svg}'
                     f'<div class="sus-info"><div class="sus-name">{name}</div>'
                     f'<div class="sus-line">"{line}"</div></div></div>')
    body = f"""
<div class="stack">
  <h2 class="headline occ" id="susTitle">{title}</h2>
  <div class="sus-list occ">{''.join(cards)}</div>
</div>"""
    js = """
    var title = $('susTitle');
    if (title) { MF.reveal(title, t, 0.05, 0.4, {dy: 24}); }
    var cards = document.querySelectorAll('.suspect-card');
    for (var i = 0; i < cards.length; i++) { MF.reveal(cards[i], t, 0.2 + i * 0.5, 0.45, {dy: 26}); }
    var chars = document.querySelectorAll('svg g[id^=char]');
    for (var j = 0; j < chars.length; j++) {
      chars[j].style.transform = 'translateY(' + (Math.sin(t * 2.2 + j) * 4) + 'px)';
    }
"""
    return Rendered(body, js)


# --------------------------------------------------------------------------- bars

def _bars(p: dict) -> Rendered:
    title = _e(p.get("title") or "The numbers tell the story")
    labels = p.get("labels") or ["A", "B", "C", "D"]
    values = p.get("values") or [3, 5, 8, 13]
    n = min(len(labels), len(values), 6)
    labels, values = labels[:n], values[:n]
    vmax = max([float(v) for v in values] + [1])
    cols = []
    for i, (lab, val) in enumerate(zip(labels, values)):
        h = max(12, round(46 * float(val) / vmax))
        cols.append(f'<div class="bar-col occ"><div class="bar-val mono" id="bv{i}">{_e(val)}</div>'
                    f'<div class="bar" id="bar{i}" style="height:{h}vmin"></div>'
                    f'<div class="bar-lab">{_e(lab)}</div></div>')
    body = f"""
<div class="stack">
  <h2 class="headline occ" id="barTitle">{title}</h2>
  <div class="bar-chart occ" id="barChart">{''.join(cols)}</div>
</div>"""
    js = """
    var title = $('barTitle');
    if (title) { MF.reveal(title, t, 0.05, 0.4, {dy: 24}); }
    MF.bars(document.querySelectorAll('.bar'), t, 0.25, 0.14, 0.7);
    var vals = document.querySelectorAll('.bar-val');
    for (var i = 0; i < vals.length; i++) { MF.reveal(vals[i], t, 0.4 + i * 0.14, 0.35, {dy: 14}); }
"""
    return Rendered(body, js)


# ----------------------------------------------------------------------- equation

def _equation(p: dict) -> Rendered:
    title = _e(p.get("title") or "Build the equation")
    left = _e(p.get("left") or "2x + 3")
    right = _e(p.get("right") or "11")
    answer = _e(p.get("answer") or "x = 4")
    hint = _e(p.get("hint") or "Undo the operations in reverse order.")
    body = f"""
<div class="stack">
  <h2 class="headline occ" id="eqTitle">{title}</h2>
  <div class="card eq-card occ" id="eqCard">
    <div class="eq-line mono occ"><span id="eqLeft">{left}</span>
      <span class="eq-op" id="eqOp">=</span><span id="eqRight">{right}</span></div>
    <div class="eq-answer mono occ" id="eqAnswer">{answer}</div>
  </div>
  <div class="hint-panel card occ" id="eqHint">
    <div class="micro">HOW TO SOLVE</div>
    <div class="hint-text">{hint}</div>
  </div>
</div>"""
    js = """
    var title = $('eqTitle');
    if (title) { MF.reveal(title, t, 0.05, 0.4, {dy: 24}); }
    var card = $('eqCard');
    if (card) { MF.reveal(card, t, 0.2, 0.5, {dy: 20, scale: 0.94}); }
    var left = $('eqLeft');
    if (left) { MF.reveal(left, t, 0.45, 0.4, {dy: 12}); }
    var op = $('eqOp');
    if (op) { MF.pop(op, t, 0.8, 0.35); }
    var right = $('eqRight');
    if (right) { MF.reveal(right, t, 1.0, 0.4, {dy: 12}); }
    var ans = $('eqAnswer');
    if (ans) { MF.pop(ans, t, dur * 0.6, 0.5); }
    var hint = $('eqHint');
    if (hint) { MF.reveal(hint, t, dur * 0.35, 0.5, {dy: 20}); }
"""
    return Rendered(body, js)


# ------------------------------------------------------------------------ compare

def _compare(p: dict) -> Rendered:
    title = _e(p.get("title") or "Which one wins?")
    left = p.get("left") or {"label": "Option A", "value": "?"}
    right = p.get("right") or {"label": "Option B", "value": "?"}
    if not isinstance(left, dict):
        left = {"label": "Option A", "value": left}
    if not isinstance(right, dict):
        right = {"label": "Option B", "value": right}
    body = f"""
<div class="stack">
  <h2 class="headline occ" id="cmpTitle">{title}</h2>
  <div class="cmp-row occ">
    <div class="cmp-card card occ" id="cmpL"><div class="micro">{_e(left.get('label'))}</div>
      <div class="cmp-val mono">{_e(left.get('value'))}</div></div>
    <div class="vs occ" id="vs">VS</div>
    <div class="cmp-card card occ" id="cmpR"><div class="micro">{_e(right.get('label'))}</div>
      <div class="cmp-val mono">{_e(right.get('value'))}</div></div>
  </div>
</div>"""
    js = """
    var title = $('cmpTitle');
    if (title) { MF.reveal(title, t, 0.05, 0.4, {dy: 24}); }
    var l = $('cmpL'), r = $('cmpR'), vs = $('vs');
    if (l) { MF.reveal(l, t, 0.2, 0.45, {dx: -30, dy: 0}); }
    if (r) { MF.reveal(r, t, 0.4, 0.45, {dx: 30, dy: 0}); }
    if (vs) { MF.pop(vs, t, 0.7, 0.4); }
"""
    return Rendered(body, js)


# ----------------------------------------------------------------------- progress

def _progress(p: dict) -> Rendered:
    title = _e(p.get("title") or "The plan")
    steps = p.get("steps") or ["Step 1", "Step 2", "Step 3"]
    steps = [s.get("text", "") if isinstance(s, dict) else str(s) for s in steps]
    current = int(p.get("current") or 0)
    items = "".join(
        f'<div class="prog-item {"done" if i < current else ("current" if i == current else "")} occ">'
        f'<div class="prog-dot">{i + 1}</div><div class="prog-text">{_e(s)}</div></div>'
        for i, s in enumerate(steps))
    body = f"""
<div class="stack">
  <h2 class="headline occ" id="progTitle">{title}</h2>
  <div class="prog-list occ" id="progList">{items}</div>
</div>"""
    js = """
    var title = $('progTitle');
    if (title) { MF.reveal(title, t, 0.05, 0.4, {dy: 24}); }
    var items = document.querySelectorAll('.prog-item');
    for (var i = 0; i < items.length; i++) { MF.reveal(items[i], t, 0.2 + i * 0.5, 0.4, {dy: 18}); }
"""
    return Rendered(body, js)


# ------------------------------------------------------------------------ counter

def _counter(p: dict) -> Rendered:
    title = _e(p.get("title") or "Watch the number climb")
    frm = p.get("from", 0)
    to = p.get("to", 100)
    suffix = _e(p.get("suffix") or "")
    body = f"""
<div class="stack">
  <h2 class="headline occ" id="cntTitle">{title}</h2>
  <div class="counter-card card occ" id="cntCard">
    <div class="counter-num mono occ" id="cntNum">0</div>
    <div class="micro" id="cntLabel">{_e(p.get('label') or 'AND STILL COUNTING')}</div>
    <div class="counter-bar occ"><div class="counter-fill" id="cntFill"></div></div>
  </div>
</div>"""
    js = f"""
    var title = $('cntTitle');
    if (title) {{ MF.reveal(title, t, 0.05, 0.4, {{dy: 24}}); }}
    var card = $('cntCard');
    if (card) {{ MF.reveal(card, t, 0.2, 0.5, {{dy: 20}}); }}
    MF.counter($('cntNum'), t, 0.35, dur * 0.7, {frm}, {to});
    var fill = $('cntFill');
    if (fill) {{ fill.style.width = (MF.seg(t, 0.35, dur * 0.7, 'outCubic') * 100) + '%'; }}
"""
    return Rendered(body, js)


# --------------------------------------------------------------------------- text

def _text(p: dict) -> Rendered:
    title = _e(p.get("title") or "")
    body_text = _e(p.get("body") or "")
    bullets = p.get("bullets") or []
    items = "".join(f'<div class="bullet occ"><span class="dot"></span><span>{_e(b)}</span></div>'
                    for b in bullets[:4])
    body = f"""
<div class="stack">
  <h2 class="headline occ" id="txtTitle">{title}</h2>
  <div class="card text-card occ" id="txtCard">
    <div class="body-text">{body_text}</div>
    <div class="bullets occ">{items}</div>
  </div>
</div>"""
    js = """
    var title = $('txtTitle');
    if (title) { MF.reveal(title, t, 0.05, 0.4, {dy: 24}); }
    var card = $('txtCard');
    if (card) { MF.reveal(card, t, 0.2, 0.5, {dy: 20}); }
    var bullets = document.querySelectorAll('.bullet');
    for (var i = 0; i < bullets.length; i++) { MF.reveal(bullets[i], t, 0.5 + i * 0.4, 0.4, {dy: 16}); }
"""
    return Rendered(body, js)


# -------------------------------------------------------------------- character

def _character(p: dict) -> Rendered:
    from .characters import character_svg
    kind = p.get("character", "detective")
    expression = p.get("expression", "thinking")
    name = _e(p.get("name") or "Detective")
    line = _e(p.get("line") or "Something does not add up here.")
    svg = character_svg(kind, expression, width=430, animate_id="heroChar")
    body = f"""
<div class="stack">
  <div class="char-name occ" id="charName">{name}</div>
  <div class="char-stage occ" id="charStage">{svg}</div>
  <div class="card bubble occ" id="charBubble">{line}</div>
</div>"""
    js = """
    var name = $('charName');
    if (name) { MF.reveal(name, t, 0.05, 0.35, {dy: -10}); }
    var stage = $('charStage');
    if (stage) { MF.pop(stage, t, 0.1, 0.5); }
    var bubble = $('charBubble');
    if (bubble) { MF.reveal(bubble, t, 0.5, 0.45, {dy: 20}); }
    var hero = document.getElementById('heroChar');
    if (hero) {
      hero.style.transform = 'translateY(' + (Math.sin(t * 2.4) * 6) + 'px)';
    }
"""
    return Rendered(body, js)


COMPONENTS = {
    "hook_question": _hook,
    "sequence": _sequence,
    "countdown": _countdown,
    "solution_steps": _solution,
    "payoff": _payoff,
    "clue_cards": _clue_cards,
    "truth_lie": _truth_lie,
    "suspects": _suspects,
    "bars": _bars,
    "equation": _equation,
    "compare": _compare,
    "progress": _progress,
    "counter": _counter,
    "text": _text,
    "character": _character,
}


def render_component(name: str, props: dict) -> Rendered:
    fn = COMPONENTS.get(name, _text)
    return fn(props or {})
