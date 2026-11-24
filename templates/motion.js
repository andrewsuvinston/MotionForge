/* MotionForge deterministic animation helpers.
 * Every function derives state purely from t (seconds). No timers, no CSS animations.
 * Exposed as window.MF. Scenes must define window.SCENE_DURATION and window.setTime(t).
 */
(function () {
  "use strict";
  const clamp01 = (x) => (x < 0 ? 0 : x > 1 ? 1 : x);

  const ease = {
    outCubic: (x) => 1 - Math.pow(1 - x, 3),
    inOutCubic: (x) => (x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2),
    outQuint: (x) => 1 - Math.pow(1 - x, 5),
    outExpo: (x) => (x >= 1 ? 1 : 1 - Math.pow(2, -10 * x)),
    outBack: (x) => {
      const c1 = 1.70158, c3 = c1 + 1;
      return 1 + c3 * Math.pow(x - 1, 3) + c1 * Math.pow(x - 1, 2);
    },
    inOutSine: (x) => -(Math.cos(Math.PI * x) - 1) / 2,
  };

  /* Eased progress (0..1) of the segment [start, start+dur] at time t. */
  function seg(t, start, dur, e) {
    const fn = typeof e === "function" ? e : ease[e] || ease.outCubic;
    return fn(clamp01((t - start) / Math.max(dur, 1e-6)));
  }

  /* Fade + move + optional scale-in. el ends fully visible at start+dur. */
  function reveal(el, t, start, dur, o) {
    o = o || {};
    const p = seg(t, start, dur, o.ease || "outCubic");
    const dx = (o.dx || 0) * (1 - p);
    const dy = (o.dy === undefined ? 40 : o.dy) * (1 - p);
    const sc = o.scale ? o.scale + (1 - o.scale) * p : 1;
    el.style.opacity = String(p);
    el.style.transform = "translate(" + dx + "px," + dy + "px) scale(" + sc + ")";
  }

  /* Pure opacity fade between two values. */
  function fade(el, t, start, dur, from, to) {
    const p = seg(t, start, dur, "inOutSine");
    el.style.opacity = String((from === undefined ? 0 : from) + ((to === undefined ? 1 : to) - (from === undefined ? 0 : from)) * p);
  }

  /* Scale-pop with overshoot (great for icons / badges). */
  function pop(el, t, start, dur) {
    const p = seg(t, start, dur, "outBack");
    const o = seg(t, start, Math.min(dur, 0.2), "outCubic");
    el.style.opacity = String(o);
    el.style.transform = "scale(" + (0.5 + 0.5 * p) + ")";
  }

  /* Staggered reveal of a list of elements. */
  function stagger(els, t, start, each, dur, o) {
    Array.prototype.forEach.call(els, (el, i) => reveal(el, t, start + i * each, dur, o));
  }

  /* Animated number counter. */
  function counter(el, t, start, dur, from, to, o) {
    o = o || {};
    const p = seg(t, start, dur, o.ease || "outExpo");
    const v = from + (to - from) * p;
    const dec = o.decimals || 0;
    el.textContent = (o.prefix || "") + v.toFixed(dec) + (o.suffix || "");
  }

  /* Grow bars from the bottom (elements should have transform-origin: bottom). */
  function bars(els, t, start, each, dur) {
    Array.prototype.forEach.call(els, (el, i) => {
      const p = seg(t, start + i * each, dur, "outCubic");
      el.style.transform = "scaleY(" + p + ")";
      el.style.opacity = String(Math.min(1, p * 3));
    });
  }

  /* Draw an SVG path / line / polyline progressively. */
  function drawPath(pathEl, t, start, dur) {
    if (!pathEl.__mfLen) {
      try { pathEl.__mfLen = pathEl.getTotalLength(); } catch (e) { pathEl.__mfLen = 1000; }
      pathEl.style.strokeDasharray = String(pathEl.__mfLen);
    }
    const p = seg(t, start, dur, "inOutCubic");
    pathEl.style.strokeDashoffset = String(pathEl.__mfLen * (1 - p));
    pathEl.style.opacity = p > 0 ? "1" : "0";
  }

  /* Fade/slide an element OUT near the end of a scene. */
  function exit(el, t, start, dur, o) {
    o = o || {};
    const p = seg(t, start, dur, "inOutCubic");
    el.style.opacity = String(1 - p);
    el.style.transform = "translateY(" + (o.dy === undefined ? -30 : o.dy) * p + "px)";
  }

  /* Scene envelope: 0->1 fade-in over fi seconds, 1->0 fade-out over fo seconds.
   * Apply to the root stage element for clean transitions between scenes. */
  function envelope(t, duration, fi, fo) {
    fi = fi === undefined ? 0.35 : fi;
    fo = fo === undefined ? 0.3 : fo;
    const a = seg(t, 0, fi, "inOutSine");
    const b = seg(duration - t, 0, fo, "inOutSine");
    return Math.min(a, b);
  }

  window.MF = { clamp01, ease, seg, reveal, fade, pop, stagger, counter, bars, drawPath, exit, envelope };
})();
