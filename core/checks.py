"""Automatic quality checks.

The DOM measurement script (MEASURE_JS) runs inside Playwright; all check logic
is pure Python so it can be unit-tested with synthetic measurements.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field, asdict

# Collects every element that has its own visible text, with geometry, styles,
# effective opacity/background, overflow and a DOM path for ancestry tests.
MEASURE_JS = r"""
() => {
  const vw = window.innerWidth, vh = window.innerHeight;
  const all = Array.from(document.body.querySelectorAll('*'));
  const textEls = all.filter(el =>
    Array.from(el.childNodes).some(n => n.nodeType === 3 && n.textContent.trim()));
  const idx = new Map(textEls.map((el, i) => [el, i]));
  function effOpacity(el) {
    let o = 1, n = el;
    while (n && n.nodeType === 1) {
      const s = getComputedStyle(n);
      if (s.visibility === 'hidden' || s.display === 'none') return 0;
      o *= parseFloat(s.opacity);
      n = n.parentElement;
    }
    return o;
  }
  function effBg(el) {
    let n = el;
    while (n && n.nodeType === 1) {
      const c = getComputedStyle(n).backgroundColor;
      const m = c && c.match(/[\d.]+/g);
      if (m && (m.length < 4 || parseFloat(m[3]) > 0.05)) return c;
      n = n.parentElement;
    }
    return getComputedStyle(document.documentElement).backgroundColor;
  }
  function pathOf(el) {
    const p = [];
    let n = el;
    while (n && n.parentElement) {
      p.unshift(Array.prototype.indexOf.call(n.parentElement.children, n));
      n = n.parentElement;
    }
    return p;
  }
  const elements = textEls.map((el, i) => {
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    const own = Array.from(el.childNodes).filter(n => n.nodeType === 3)
      .map(n => n.textContent).join('').trim();
    let parentTextIdx = -1, n = el.parentElement;
    while (n) { if (idx.has(n)) { parentTextIdx = idx.get(n); break; } n = n.parentElement; }
    return {
      idx: i, parentTextIdx, path: pathOf(el),
      tag: el.tagName, id: el.id || '', cls: String(el.className || '').slice(0, 60),
      text: own.slice(0, 80),
      x: r.x, y: r.y, w: r.width, h: r.height,
      opacity: effOpacity(el), fontSize: parseFloat(s.fontSize) || 0,
      fontWeight: s.fontWeight, color: s.color, bg: effBg(el),
      overflowX: el.scrollWidth - el.clientWidth,
      overflowY: el.scrollHeight - el.clientHeight,
    };
  });
  return {
    vw, vh, elements,
    duration: (typeof window.SCENE_DURATION === 'number') ? window.SCENE_DURATION : null,
    hasSetTime: typeof window.setTime === 'function',
  };
}
"""


@dataclass
class Problem:
    code: str
    message: str
    severity: str = "error"          # error | warning
    scene: int | None = None
    element: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------- color helpers ----------------

def parse_color(css: str) -> tuple[float, float, float, float]:
    """Parse #rgb/#rrggbb/rgb()/rgba() into (r,g,b,a) with 0..255 / 0..1."""
    if not css:
        return (0.0, 0.0, 0.0, 0.0)
    css = css.strip().lower()
    if css in ("transparent", "none"):
        return (0.0, 0.0, 0.0, 0.0)
    if css.startswith("#"):
        h = css[1:]
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        if len(h) >= 6:
            return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), 1.0)
        return (0.0, 0.0, 0.0, 0.0)
    m = re.match(r"rgba?\(([^)]+)\)", css)
    if m:
        parts = [p.strip() for p in m.group(1).replace("/", ",").split(",") if p.strip()]
        try:
            vals = [float(p) for p in parts[:4]]
        except ValueError:
            return (0.0, 0.0, 0.0, 0.0)
        while len(vals) < 4:
            vals.append(1.0)
        return (vals[0], vals[1], vals[2], vals[3])
    return (0.0, 0.0, 0.0, 0.0)


def _luminance(rgb: tuple[float, float, float]) -> float:
    def chan(c: float) -> float:
        c /= 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (chan(c) for c in rgb[:3])
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(fg: str, bg: str) -> float:
    """WCAG contrast ratio between two CSS colors (alpha ignored)."""
    f, b = parse_color(fg), parse_color(bg)
    l1, l2 = _luminance(f), _luminance(b)
    lighter, darker = max(l1, l2), min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)


def _is_ancestor(a: dict, b: dict) -> bool:
    pa, pb = a.get("path") or [], b.get("path") or []
    short, long_ = (pa, pb) if len(pa) <= len(pb) else (pb, pa)
    return bool(short) and long_[:len(short)] == short


def _label(el: dict) -> str:
    ident = el.get("id") or el.get("cls") or el.get("tag", "?")
    return f"{el.get('tag', '?')}#{ident} '{el.get('text', '')[:30]}'"


# ---------------- main check entry ----------------

def run_checks(measurement: dict, plan_duration: float, console_errors: list[str],
               frame_stats: list[dict], cfg: dict, default_bg: str = "#000000") -> list[Problem]:
    """Run all automatic checks on one scene's measurements. Pure function."""
    cc = cfg.get("checks", {})
    problems: list[Problem] = []
    vw = measurement.get("vw", 0)
    vh = measurement.get("vh", 0)
    elements = measurement.get("elements", [])

    # --- structural / runtime ---
    if not measurement.get("hasSetTime"):
        problems.append(Problem("missing_settime", "window.setTime(t) is not defined; scene is not deterministic"))
    measured_dur = measurement.get("duration")
    if measured_dur is None:
        problems.append(Problem("duration_mismatch", "window.SCENE_DURATION is not defined"))
    elif abs(float(measured_dur) - float(plan_duration)) > 0.1:
        problems.append(Problem("duration_mismatch",
                                f"SCENE_DURATION={measured_dur}s but plan says {plan_duration}s"))
    for err in list(dict.fromkeys(console_errors))[:5]:
        problems.append(Problem("console_error", f"JavaScript error: {err[:200]}"))

    # --- blank frames (only after animations should have settled) ---
    for fs in frame_stats:
        if fs.get("fraction", 0) >= 0.4 and \
           fs.get("stddev", 99) < float(cc.get("blank_stddev", 2.0)) and \
           fs.get("colors", 999) <= int(cc.get("blank_max_colors", 8)):
            problems.append(Problem("blank_frame",
                                    f"Frame at {fs['fraction']:.0%} of scene is blank (solid background)"))

    visible = [e for e in elements
               if e.get("opacity", 0) > 0.5 and e.get("w", 0) > 1 and e.get("h", 0) > 1
               and (e.get("text") or "").strip()]
    tol = float(cc.get("edge_tolerance_px", 4))
    min_font = min(vw, vh) * float(cc.get("min_font_ratio", 0.022))

    for el in visible:
        # off-screen / screen-edge overflow
        if el["x"] < -tol or el["y"] < -tol or el["x"] + el["w"] > vw + tol or el["y"] + el["h"] > vh + tol:
            problems.append(Problem("offscreen", f"{_label(el)} extends outside the screen", element=_label(el)))
        # container overflow
        if el.get("overflowX", 0) > 2 or el.get("overflowY", 0) > 2:
            problems.append(Problem("text_overflow",
                                    f"{_label(el)} overflows its container "
                                    f"(+{el.get('overflowX', 0)}px x, +{el.get('overflowY', 0)}px y)",
                                    element=_label(el)))
        # font too small
        if 0 < el.get("fontSize", 0) < min_font:
            problems.append(Problem("small_font",
                                    f"{_label(el)} font {el['fontSize']:.0f}px < minimum {min_font:.0f}px "
                                    f"for this resolution", element=_label(el)))
        # contrast
        bg = el.get("bg") or default_bg
        if parse_color(bg)[3] < 0.05:
            bg = default_bg
        ratio = contrast_ratio(el.get("color", "#fff"), bg)
        large = el.get("fontSize", 0) >= 32 or (
            el.get("fontSize", 0) >= 24 and str(el.get("fontWeight", "400")) in ("700", "800", "900", "bold"))
        need = float(cc.get("min_contrast_large", 3.0)) if large else float(cc.get("min_contrast_small", 4.5))
        if ratio < need:
            problems.append(Problem("low_contrast",
                                    f"{_label(el)} contrast {ratio:.2f}:1 < {need}:1 "
                                    f"({el.get('color')} on {bg})", element=_label(el)))

    # --- overlapping text blocks ---
    threshold = float(cc.get("overlap_threshold", 0.2))
    for i in range(len(visible)):
        for j in range(i + 1, len(visible)):
            a, b = visible[i], visible[j]
            if _is_ancestor(a, b) or a.get("parentTextIdx") == b.get("idx") or b.get("parentTextIdx") == a.get("idx"):
                continue
            if a.get("text") == b.get("text"):
                continue  # duplicated label/shadow text
            ix = max(0.0, min(a["x"] + a["w"], b["x"] + b["w"]) - max(a["x"], b["x"]))
            iy = max(0.0, min(a["y"] + a["h"], b["y"] + b["h"]) - max(a["y"], b["y"]))
            inter = ix * iy
            smaller = min(a["w"] * a["h"], b["w"] * b["h"])
            if smaller > 0 and inter / smaller > threshold:
                problems.append(Problem("overlap",
                                        f"{_label(a)} overlaps {_label(b)} "
                                        f"({inter / smaller:.0%} of smaller block)"))

    # dedupe identical messages
    seen, unique = set(), []
    for p in problems:
        key = (p.code, p.message)
        if key not in seen:
            seen.add(key)
            unique.append(p)
    return unique
