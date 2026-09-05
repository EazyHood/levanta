"""A tiny 2-D drawing model with two renderers: SVG (vector) and PNG (Pillow).

Plans, site plans and the 3-D preview are all described once as a list of
primitives in *page pixels* (y down), so the vector and the raster outputs are
guaranteed to show the same thing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import pairwise
from pathlib import Path

import numpy as np

Point = tuple[float, float]


@dataclass
class Prim:
    kind: str  # "polygon" | "polyline" | "text" | "circle"
    pts: list[Point] = field(default_factory=list)
    holes: list[list[Point]] = field(default_factory=list)
    fill: str | None = None
    stroke: str | None = None
    width: float = 1.0
    dash: tuple[float, float] | None = None
    text: str = ""
    x: float = 0.0
    y: float = 0.0
    size: float = 12.0
    anchor: str = "middle"  # start | middle | end
    weight: str = "normal"  # normal | bold
    color: str = "#222"
    rotate: float = 0.0  # degrees, counter-clockwise, about (x, y)
    r: float = 0.0
    cls: str = ""  # SVG class name (for styling / selecting in the HTML viewer)


@dataclass
class Drawing:
    width: float
    height: float
    prims: list[Prim] = field(default_factory=list)
    background: str = "#ffffff"
    font_family: str = "Inter, 'Segoe UI', Helvetica, Arial, sans-serif"
    meta: dict = field(default_factory=dict)  # e.g. the plan->pixel transform of a floor plan

    # -- builders ------------------------------------------------------------------------

    def polygon(self, pts, fill=None, stroke=None, width=1.0, dash=None, holes=None, cls="") -> Prim:
        p = Prim("polygon", pts=[(float(x), float(y)) for x, y in pts], holes=[[(float(x), float(y)) for x, y in h] for h in (holes or [])], fill=fill, stroke=stroke, width=width, dash=dash, cls=cls)
        self.prims.append(p)
        return p

    def polyline(self, pts, stroke="#222", width=1.0, dash=None, cls="") -> Prim:
        p = Prim("polyline", pts=[(float(x), float(y)) for x, y in pts], stroke=stroke, width=width, dash=dash, cls=cls)
        self.prims.append(p)
        return p

    def line(self, a, b, stroke="#222", width=1.0, dash=None, cls="") -> Prim:
        return self.polyline([a, b], stroke=stroke, width=width, dash=dash, cls=cls)

    def text(self, x, y, text, size=12.0, anchor="middle", weight="normal", color="#222", rotate=0.0, cls="") -> Prim:
        p = Prim("text", x=float(x), y=float(y), text=str(text), size=size, anchor=anchor, weight=weight, color=color, rotate=rotate, cls=cls)
        self.prims.append(p)
        return p

    def circle(self, x, y, r, fill="#222", stroke=None, width=1.0, cls="") -> Prim:
        p = Prim("circle", x=float(x), y=float(y), r=float(r), fill=fill, stroke=stroke, width=width, cls=cls)
        self.prims.append(p)
        return p

    # -- output --------------------------------------------------------------------------

    def to_svg(self) -> str:
        return render_svg(self)

    def save_svg(self, path: str | Path) -> Path:
        path = Path(path)
        path.write_text(self.to_svg(), encoding="utf-8")
        return path

    def to_image(self, scale: float = 2.0):
        return render_png(self, scale=scale)

    def save_png(self, path: str | Path, scale: float = 2.0) -> Path:
        path = Path(path)
        self.to_image(scale=scale).save(path)
        return path


# ----------------------------------------------------------------------------------------
# SVG
# ----------------------------------------------------------------------------------------


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _f(v: float) -> str:
    return f"{v:.1f}"


def render_svg(d: Drawing, standalone: bool = True) -> str:
    out: list[str] = []
    W, H = d.width, d.height
    if standalone:
        out.append(f'<svg xmlns="http://www.w3.org/2000/svg" width="{W:.0f}" height="{H:.0f}" viewBox="0 0 {W:.0f} {H:.0f}" font-family="{_esc(d.font_family)}">')
    else:
        out.append(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W:.0f} {H:.0f}" style="width:100%;height:auto;max-width:{W:.0f}px" font-family="{_esc(d.font_family)}">')
    if d.background:
        out.append(f'<rect width="{W:.0f}" height="{H:.0f}" fill="{d.background}"/>')
    for p in d.prims:
        cls = f' class="{_esc(p.cls)}"' if p.cls else ""
        if p.kind in ("polygon", "polyline"):
            if len(p.pts) < 2:
                continue
            if p.kind == "polygon":
                path = "M " + " ".join(f"{_f(x)},{_f(y)}" for x, y in p.pts) + " Z"
                for h in p.holes:
                    path += " M " + " ".join(f"{_f(x)},{_f(y)}" for x, y in h) + " Z"
            else:
                path = "M " + " L ".join(f"{_f(x)},{_f(y)}" for x, y in p.pts)
            style = f'fill="{p.fill or "none"}"'
            if p.kind == "polygon" and p.holes:
                style += ' fill-rule="evenodd"'
            if p.stroke:
                style += f' stroke="{p.stroke}" stroke-width="{p.width:g}" stroke-linejoin="round" stroke-linecap="round"'
                if p.dash:
                    style += f' stroke-dasharray="{p.dash[0]:g} {p.dash[1]:g}"'
            out.append(f'<path{cls} d="{path}" {style}/>')
        elif p.kind == "text":
            anchor = {"start": "start", "middle": "middle", "end": "end"}[p.anchor]
            tr = f' transform="rotate({-p.rotate:g} {_f(p.x)} {_f(p.y)})"' if p.rotate else ""
            fw = ' font-weight="700"' if p.weight == "bold" else ""
            out.append(f'<text{cls} x="{_f(p.x)}" y="{_f(p.y)}" font-size="{p.size:g}" text-anchor="{anchor}" fill="{p.color}"{fw}{tr}>{_esc(p.text)}</text>')
        elif p.kind == "circle":
            st = f' stroke="{p.stroke}" stroke-width="{p.width:g}"' if p.stroke else ""
            out.append(f'<circle{cls} cx="{_f(p.x)}" cy="{_f(p.y)}" r="{p.r:g}" fill="{p.fill or "none"}"{st}/>')
    out.append("</svg>")
    return "\n".join(out)


# ----------------------------------------------------------------------------------------
# PNG (Pillow)
# ----------------------------------------------------------------------------------------

_FONT_CANDIDATES = {
    "normal": ["segoeui.ttf", "arial.ttf", "calibri.ttf", "DejaVuSans.ttf", "LiberationSans-Regular.ttf", "Helvetica.ttc", "Arial.ttf"],
    "bold": ["segoeuib.ttf", "arialbd.ttf", "calibrib.ttf", "DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf", "Helvetica.ttc", "Arial Bold.ttf"],
}
_FONT_DIRS = [
    Path("C:/Windows/Fonts"),
    Path("/usr/share/fonts/truetype/dejavu"),
    Path("/usr/share/fonts/truetype/liberation"),
    Path("/usr/share/fonts/truetype/liberation2"),
    Path("/usr/share/fonts/TTF"),
    Path("/System/Library/Fonts"),
    Path("/Library/Fonts"),
    Path.home() / ".fonts",
]
_font_cache: dict[tuple[str, int], object] = {}


def _font(size: float, weight: str = "normal"):
    from PIL import ImageFont

    key = (weight, round(size))
    if key in _font_cache:
        return _font_cache[key]
    font = None
    for name in _FONT_CANDIDATES[weight]:
        for d in _FONT_DIRS:
            p = d / name
            if p.exists():
                try:
                    font = ImageFont.truetype(str(p), round(size))
                    break
                except OSError:
                    continue
        if font is not None:
            break
    if font is None:
        try:
            font = ImageFont.load_default(size=round(size))
        except TypeError:  # older Pillow
            font = ImageFont.load_default()
    _font_cache[key] = font
    return font


def _hex(color: str | None):
    if color is None:
        return None
    c = color.lstrip("#")
    if len(c) == 3:
        c = "".join(ch * 2 for ch in c)
    return (int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16))


def _dashed(pts: list[Point], dash: tuple[float, float]) -> list[list[Point]]:
    """Split a polyline into dash segments."""
    on, off = dash
    segs: list[list[Point]] = []
    pos = 0.0
    drawing = True
    for (x0, y0), (x1, y1) in pairwise(pts):
        L = float(np.hypot(x1 - x0, y1 - y0))
        if L == 0:
            continue
        t = 0.0
        while t < L:
            step = (on if drawing else off) - pos
            t2 = min(L, t + step)
            if drawing:
                segs.append([(x0 + (x1 - x0) * t / L, y0 + (y1 - y0) * t / L), (x0 + (x1 - x0) * t2 / L, y0 + (y1 - y0) * t2 / L)])
            pos += t2 - t
            if pos >= (on if drawing else off) - 1e-9:
                pos = 0.0
                drawing = not drawing
            t = t2
    return segs


def render_png(d: Drawing, scale: float = 2.0):
    from PIL import Image, ImageDraw

    W, H = round(d.width * scale), round(d.height * scale)
    img = Image.new("RGB", (W, H), _hex(d.background) or (255, 255, 255))
    draw = ImageDraw.Draw(img)
    S = scale
    for p in d.prims:
        if p.kind == "polygon" and len(p.pts) >= 3:
            pts = [(x * S, y * S) for x, y in p.pts]
            if p.fill:
                draw.polygon(pts, fill=_hex(p.fill))
                for h in p.holes:
                    if len(h) >= 3:
                        draw.polygon([(x * S, y * S) for x, y in h], fill=_hex(d.background))
            if p.stroke:
                w = max(1, round(p.width * S))
                rings = [pts] + [[(x * S, y * S) for x, y in h] for h in p.holes]
                for ring in rings:
                    closed = [*ring, ring[0]]
                    if p.dash:
                        for seg in _dashed(closed, (p.dash[0] * S, p.dash[1] * S)):
                            draw.line(seg, fill=_hex(p.stroke), width=w)
                    else:
                        draw.line(closed, fill=_hex(p.stroke), width=w, joint="curve")
        elif p.kind == "polyline" and len(p.pts) >= 2 and p.stroke:
            pts = [(x * S, y * S) for x, y in p.pts]
            w = max(1, round(p.width * S))
            if p.dash:
                for seg in _dashed(pts, (p.dash[0] * S, p.dash[1] * S)):
                    draw.line(seg, fill=_hex(p.stroke), width=w)
            else:
                draw.line(pts, fill=_hex(p.stroke), width=w, joint="curve")
        elif p.kind == "text" and p.text:
            font = _font(p.size * S, p.weight)
            anchor = {"start": "ls", "middle": "ms", "end": "rs"}[p.anchor]
            if p.rotate:
                # render on a transparent tile, rotate, paste
                tw = int(font.getlength(p.text)) + 8
                th = int(p.size * S * 1.6) + 8
                tile = Image.new("RGBA", (tw, th), (0, 0, 0, 0))
                ImageDraw.Draw(tile).text((4, th - 4 - int(p.size * S * 0.3)), p.text, font=font, fill=_hex(p.color), anchor="ls")
                tile = tile.rotate(p.rotate, expand=True, resample=Image.BICUBIC)
                # anchor handling for rotated text: centre the tile on (x, y)
                cx, cy = p.x * S, p.y * S
                img.paste(tile, (int(cx - tile.width / 2), int(cy - tile.height / 2)), tile)
            else:
                draw.text((p.x * S, p.y * S), p.text, font=font, fill=_hex(p.color), anchor=anchor)
        elif p.kind == "circle":
            r = p.r * S
            box = [p.x * S - r, p.y * S - r, p.x * S + r, p.y * S + r]
            draw.ellipse(box, fill=_hex(p.fill), outline=_hex(p.stroke) if p.stroke else None, width=max(1, round(p.width * S)))
    return img
