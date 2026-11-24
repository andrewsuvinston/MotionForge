# MotionForge templates

- `motion.js` — deterministic animation helpers (`window.MF`). Injected into every
  generated scene by `core/scene_generator.py`. All state derives from `t`; there
  are no timers or CSS animations anywhere.
- `example_binary_scene.html` — a hand-approved reference scene (also seeded into
  `memory/approved/`) showing the expected structure and quality bar.

## Scene contract

Every scene HTML file must:

1. Be fully self-contained: inline CSS + JS + SVG only, **zero network requests**.
2. Define `window.SCENE_DURATION = <seconds>` matching the plan.
3. Define `window.setTime(t)` that sets the exact visual state for time `t`
   (seconds, `0 <= t <= SCENE_DURATION`). It must be idempotent and callable in
   any order.
4. Call `setTime(0)` once at load.
5. Use `MF.envelope(t, SCENE_DURATION)` on the root stage for fade-in/out
   transitions.

## MF helper API (cheat sheet)

```js
MF.seg(t, start, dur, ease?)        // eased 0..1 progress of a time segment
MF.reveal(el, t, start, dur, {dx, dy, scale, ease}?)  // fade + slide/scale in
MF.fade(el, t, start, dur, from?, to?)
MF.pop(el, t, start, dur)           // overshoot scale-in (icons, badges)
MF.stagger(els, t, start, each, dur, opts?)
MF.counter(el, t, start, dur, from, to, {decimals, prefix, suffix}?)
MF.bars(els, t, start, each, dur)   // scaleY growth, origin bottom
MF.drawPath(svgPathEl, t, start, dur)
MF.exit(el, t, start, dur, {dy}?)
MF.envelope(t, duration, fadeIn?, fadeOut?)  // 0..1 scene transition multiplier
```

Easings: `outCubic` (default), `inOutCubic`, `outQuint`, `outExpo`, `outBack`,
`inOutSine`. Never use linear motion for visible elements.
