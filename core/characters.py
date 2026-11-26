"""Original 2D blocky characters drawn as inline SVG (no external assets, no brands).

Characters: detective, suspect, assistant.
Expressions: neutral, shocked, thinking, happy.
The scene JS applies idle motion (bob / blink) deterministically from t.
"""
from __future__ import annotations

PALETTES = {
    "detective": {"body": "#1E3A5F", "accent": "#22D3EE", "skin": "#F2C9A0", "hat": "#0F172A"},
    "suspect": {"body": "#7F1D1D", "accent": "#EF4444", "skin": "#D9A066", "hat": "#3F1D1D"},
    "assistant": {"body": "#14532D", "accent": "#FACC15", "skin": "#E8B98A", "hat": "#0B2E1A"},
}

EXPRESSIONS = {"neutral", "shocked", "thinking", "happy"}


def _eyes(expression: str) -> str:
    if expression == "shocked":
        return ('<circle cx="38" cy="46" r="6.5" fill="#0B1220"/>'
                '<circle cx="62" cy="46" r="6.5" fill="#0B1220"/>'
                '<circle cx="40" cy="44" r="2" fill="#fff"/>'
                '<circle cx="64" cy="44" r="2" fill="#fff"/>')
    if expression == "thinking":
        return ('<circle cx="38" cy="47" r="4.5" fill="#0B1220"/>'
                '<circle cx="62" cy="47" r="4.5" fill="#0B1220"/>'
                '<rect x="31" y="37" width="15" height="3" rx="1.5" fill="#0B1220"/>'
                '<rect x="55" y="39" width="15" height="3" rx="1.5" fill="#0B1220"/>')
    if expression == "happy":
        return ('<path d="M32 47 Q38 41 44 47" stroke="#0B1220" stroke-width="3.5" fill="none" stroke-linecap="round"/>'
                '<path d="M56 47 Q62 41 68 47" stroke="#0B1220" stroke-width="3.5" fill="none" stroke-linecap="round"/>')
    return ('<circle cx="38" cy="46" r="5" fill="#0B1220"/>'
            '<circle cx="62" cy="46" r="5" fill="#0B1220"/>')


def _mouth(expression: str) -> str:
    if expression == "shocked":
        return '<ellipse cx="50" cy="66" rx="7" ry="9" fill="#0B1220"/>'
    if expression == "thinking":
        return '<rect x="42" y="64" width="16" height="4" rx="2" fill="#0B1220"/>'
    if expression == "happy":
        return '<path d="M38 62 Q50 74 62 62" stroke="#0B1220" stroke-width="4" fill="none" stroke-linecap="round"/>'
    return '<rect x="43" y="64" width="14" height="4" rx="2" fill="#0B1220"/>'


def character_svg(kind: str = "detective", expression: str = "neutral",
                  width: int = 320, animate_id: str = "") -> str:
    """Return an inline SVG character. `animate_id` lets scene JS animate the group."""
    pal = PALETTES.get(kind, PALETTES["detective"])
    expression = expression if expression in EXPRESSIONS else "neutral"
    aid = f' id="{animate_id}"' if animate_id else ""
    hat = ""
    if kind == "detective":
        hat = ('<path d="M22 30 L50 6 L78 30 Z" fill="' + pal["hat"] + '"/>'
               '<rect x="14" y="28" width="72" height="10" rx="5" fill="' + pal["hat"] + '"/>'
               '<rect x="44" y="8" width="12" height="6" rx="3" fill="' + pal["accent"] + '"/>')
    elif kind == "assistant":
        hat = ('<rect x="30" y="14" width="40" height="10" rx="5" fill="' + pal["hat"] + '"/>'
               '<circle cx="50" cy="10" r="5" fill="' + pal["accent"] + '"/>')
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" viewBox="0 0 100 140" fill="none">
  <g{aid}>
    <ellipse cx="50" cy="134" rx="30" ry="6" fill="#000" opacity="0.35"/>
    <rect x="30" y="92" width="40" height="38" rx="12" fill="{pal['body']}"/>
    <rect x="20" y="98" width="10" height="26" rx="5" fill="{pal['body']}"/>
    <rect x="70" y="98" width="10" height="26" rx="5" fill="{pal['body']}"/>
    <rect x="33" y="128" width="13" height="8" rx="4" fill="#0B1220"/>
    <rect x="54" y="128" width="13" height="8" rx="4" fill="#0B1220"/>
    <rect x="38" y="88" width="24" height="10" rx="5" fill="{pal['accent']}" opacity="0.9"/>
    <rect x="26" y="30" width="48" height="60" rx="22" fill="{pal['skin']}"/>
    {hat}
    {_eyes(expression)}
    {_mouth(expression)}
    <circle cx="24" cy="60" r="6" fill="{pal['skin']}"/>
    <circle cx="76" cy="60" r="6" fill="{pal['skin']}"/>
  </g>
</svg>'''
