"""Generated placeholder posters.

The demo never ships real movie artwork: posters are protected by copyright.
Each movie gets a typographic poster with colours derived from its slug.
"""

import hashlib
import textwrap
from xml.sax.saxutils import escape

WIDTH, HEIGHT = 600, 900


def _palette(seed: str) -> tuple[int, int]:
    digest = hashlib.sha256(seed.encode()).digest()
    hue = digest[0] * 360 // 256
    return hue, (hue + 20 + digest[1] % 40) % 360


def render(movie) -> str:
    hue_a, hue_b = _palette(movie.slug)
    lines = textwrap.wrap(movie.title.upper(), width=14)[:5]
    size = 76 if max((len(line) for line in lines), default=0) <= 10 else 56
    top = HEIGHT * 0.58 - (len(lines) - 1) * size * 0.55
    title = "".join(
        f'<text x="48" y="{top + i * size * 1.05:.0f}" font-size="{size}">{escape(line)}</text>' for i, line in enumerate(lines)
    )
    year = movie.release_date.year if movie.release_date else ""
    credit = ", ".join(movie.directors[:2])
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {WIDTH} {HEIGHT}" width="{WIDTH}" height="{HEIGHT}">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="hsl({hue_a} 70% 22%)"/>
      <stop offset="1" stop-color="hsl({hue_b} 80% 10%)"/>
    </linearGradient>
    <radialGradient id="glow" cx="0.75" cy="0.2" r="0.7">
      <stop offset="0" stop-color="hsl({hue_b} 90% 60%)" stop-opacity="0.55"/>
      <stop offset="1" stop-color="hsl({hue_b} 90% 60%)" stop-opacity="0"/>
    </radialGradient>
  </defs>
  <rect width="{WIDTH}" height="{HEIGHT}" fill="url(#bg)"/>
  <rect width="{WIDTH}" height="{HEIGHT}" fill="url(#glow)"/>
  <g font-family="Helvetica, Arial, sans-serif" fill="#fff" font-weight="800" letter-spacing="-2">{title}</g>
  <g font-family="Helvetica, Arial, sans-serif" fill="#fff" opacity="0.75" font-size="24">
    <text x="48" y="{HEIGHT - 96}">{escape(credit)}</text>
    <text x="48" y="{HEIGHT - 60}">{year}</text>
    <text x="{WIDTH - 48}" y="{HEIGHT - 60}" text-anchor="end" font-size="16" opacity="0.7">DEMO ARTWORK</text>
  </g>
</svg>"""
