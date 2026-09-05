"""A dependency-free vector PDF writer for :class:`~levanta.io.draw.Drawing`.

Uses the standard Helvetica fonts (no embedding needed) with WinAnsi encoding, which
covers Spanish accents, ², ° and ×.  One drawing per page, placed at a given offset.
"""

from __future__ import annotations

import zlib
from pathlib import Path

import numpy as np

from levanta.io.draw import Drawing

PAPER_MM = {
    "A4": (210.0, 297.0),
    "A3": (297.0, 420.0),
    "A2": (420.0, 594.0),
    "A1": (594.0, 841.0),
    "Letter": (215.9, 279.4),
    "Legal": (215.9, 355.6),
    "Tabloid": (279.4, 431.8),
}
PT_PER_MM = 72.0 / 25.4

# Helvetica / Helvetica-Bold advance widths for chars 32..126 (AFM, units of 1/1000 em)
_W_REG = [278, 278, 355, 556, 556, 889, 667, 191, 333, 333, 389, 584, 278, 333, 278, 278, 556, 556, 556, 556, 556, 556, 556, 556, 556, 556, 278, 278, 584, 584, 584, 556, 1015, 667, 667, 722, 722, 667, 611, 778, 722, 278, 500, 667, 556, 833, 722, 778, 667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 278, 278, 278, 469, 556, 333, 556, 556, 500, 556, 556, 278, 556, 556, 222, 222, 500, 222, 833, 556, 556, 556, 556, 333, 500, 278, 556, 500, 722, 500, 500, 500, 334, 260, 334, 584]
_W_BOLD = [278, 333, 474, 556, 556, 889, 722, 238, 333, 333, 389, 584, 278, 333, 278, 278, 556, 556, 556, 556, 556, 556, 556, 556, 556, 556, 333, 333, 584, 584, 584, 611, 975, 722, 722, 722, 722, 667, 611, 778, 722, 278, 556, 722, 611, 833, 722, 778, 667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 333, 278, 333, 584, 556, 333, 556, 611, 556, 611, 556, 333, 611, 611, 278, 278, 556, 278, 889, 611, 611, 611, 611, 389, 556, 333, 611, 556, 778, 556, 556, 500, 389, 280, 389, 584]


def text_width(s: str, size: float, bold: bool = False) -> float:
    table = _W_BOLD if bold else _W_REG
    total = 0
    for ch in s:
        o = ord(ch)
        total += table[o - 32] if 32 <= o <= 126 else 556
    return total * size / 1000.0


def _esc(s: str) -> bytes:
    b = s.encode("cp1252", errors="replace")
    return b.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


def _rgb(color: str | None) -> tuple[float, float, float]:
    c = (color or "#000000").lstrip("#")
    if len(c) == 3:
        c = "".join(ch * 2 for ch in c)
    return int(c[0:2], 16) / 255.0, int(c[2:4], 16) / 255.0, int(c[4:6], 16) / 255.0


def drawing_to_content(d: Drawing, ox: float, oy: float, page_h: float, scale: float = 1.0) -> bytes:
    """PDF content stream drawing ``d`` with its top-left corner at (ox, oy) from the
    page's top-left, ``scale`` PDF points per drawing pixel."""
    out: list[str] = []

    def X(x: float) -> float:
        return ox + x * scale

    def Y(y: float) -> float:
        return page_h - (oy + y * scale)

    def f(v: float) -> str:
        return f"{v:.2f}"

    if d.background and d.background.lower() not in ("#fff", "#ffffff"):
        r, g, b = _rgb(d.background)
        out.append(f"{r:.3f} {g:.3f} {b:.3f} rg {f(X(0))} {f(Y(d.height))} {f(d.width * scale)} {f(d.height * scale)} re f")
    for p in d.prims:
        if p.kind in ("polygon", "polyline") and len(p.pts) >= 2:
            ops = []
            rings = [p.pts] + (p.holes if p.kind == "polygon" else [])
            for ring in rings:
                ops.append(f"{f(X(ring[0][0]))} {f(Y(ring[0][1]))} m")
                ops += [f"{f(X(x))} {f(Y(y))} l" for x, y in ring[1:]]
                if p.kind == "polygon":
                    ops.append("h")
            path = " ".join(ops)
            fill = p.fill if p.kind == "polygon" else None
            if fill and p.stroke:
                r, g, b = _rgb(fill)
                R, G, B = _rgb(p.stroke)
                out.append(f"q {r:.3f} {g:.3f} {b:.3f} rg {R:.3f} {G:.3f} {B:.3f} RG {f(max(0.2, p.width * scale))} w 1 J 1 j {path} {'B*' if p.holes else 'B'} Q")
            elif fill:
                r, g, b = _rgb(fill)
                out.append(f"q {r:.3f} {g:.3f} {b:.3f} rg {path} {'f*' if p.holes else 'f'} Q")
            elif p.stroke:
                R, G, B = _rgb(p.stroke)
                dash = f"[{p.dash[0] * scale:.2f} {p.dash[1] * scale:.2f}] 0 d " if p.dash else ""
                out.append(f"q {R:.3f} {G:.3f} {B:.3f} RG {f(max(0.2, p.width * scale))} w 1 J 1 j {dash}{path} S Q")
        elif p.kind == "text" and p.text:
            size = p.size * scale
            bold = p.weight == "bold"
            w = text_width(p.text, size, bold)
            dx = {"start": 0.0, "middle": -w / 2, "end": -w}[p.anchor]
            r, g, b = _rgb(p.color)
            ang = np.deg2rad(p.rotate)
            c, s_ = np.cos(ang), np.sin(ang)
            x0, y0 = X(p.x), Y(p.y)
            # shift along the (rotated) baseline by the anchor offset
            tx, ty = x0 + dx * c, y0 + dx * s_
            font = "/F2" if bold else "/F1"
            out.append(f"BT {r:.3f} {g:.3f} {b:.3f} rg {font} {size:.2f} Tf {c:.4f} {s_:.4f} {-s_:.4f} {c:.4f} {f(tx)} {f(ty)} Tm ({_esc(p.text).decode('latin-1')}) Tj ET")
        elif p.kind == "circle":
            k = 0.5523
            cx, cy, r_ = X(p.x), Y(p.y), p.r * scale
            path = (
                f"{f(cx + r_)} {f(cy)} m "
                f"{f(cx + r_)} {f(cy + k * r_)} {f(cx + k * r_)} {f(cy + r_)} {f(cx)} {f(cy + r_)} c "
                f"{f(cx - k * r_)} {f(cy + r_)} {f(cx - r_)} {f(cy + k * r_)} {f(cx - r_)} {f(cy)} c "
                f"{f(cx - r_)} {f(cy - k * r_)} {f(cx - k * r_)} {f(cy - r_)} {f(cx)} {f(cy - r_)} c "
                f"{f(cx + k * r_)} {f(cy - r_)} {f(cx + r_)} {f(cy - k * r_)} {f(cx + r_)} {f(cy)} c h"
            )
            fill = p.fill
            if fill and p.stroke:
                rr, gg, bb = _rgb(fill)
                R, G, B = _rgb(p.stroke)
                out.append(f"q {rr:.3f} {gg:.3f} {bb:.3f} rg {R:.3f} {G:.3f} {B:.3f} RG {f(max(0.2, p.width * scale))} w {path} B Q")
            elif fill:
                rr, gg, bb = _rgb(fill)
                out.append(f"q {rr:.3f} {gg:.3f} {bb:.3f} rg {path} f Q")
            elif p.stroke:
                R, G, B = _rgb(p.stroke)
                out.append(f"q {R:.3f} {G:.3f} {B:.3f} RG {f(max(0.2, p.width * scale))} w {path} S Q")
    return ("\n".join(out)).encode("latin-1", errors="replace")


def write_pdf(path: str | Path, pages: list[tuple[Drawing, float, float, float, float, float]], title: str = "levanta") -> Path:
    """``pages``: list of (drawing, page_w_pt, page_h_pt, offset_x_pt, offset_y_pt, scale)."""
    path = Path(path)
    objs: list[bytes] = []

    def add(obj: bytes) -> int:
        objs.append(obj)
        return len(objs)

    font1 = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    font2 = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>")
    page_ids: list[int] = []
    pages_id_placeholder = None
    contents = []
    for d, pw, ph, ox, oy, sc in pages:
        stream = zlib.compress(drawing_to_content(d, ox, oy, ph, sc))
        cid = add(b"<< /Length " + str(len(stream)).encode() + b" /Filter /FlateDecode >>\nstream\n" + stream + b"\nendstream")
        contents.append((cid, pw, ph))
    pages_id = len(objs) + len(contents) + 1
    for cid, pw, ph in contents:
        pid = add(f"<< /Type /Page /Parent {pages_id} 0 R /MediaBox [0 0 {pw:.2f} {ph:.2f}] /Contents {cid} 0 R /Resources << /Font << /F1 {font1} 0 R /F2 {font2} 0 R >> >> >>".encode())
        page_ids.append(pid)
    kids = " ".join(f"{p} 0 R" for p in page_ids)
    real_pages_id = add(f"<< /Type /Pages /Kids [{kids}] /Count {len(page_ids)} >>".encode())
    assert real_pages_id == pages_id, (real_pages_id, pages_id, pages_id_placeholder)
    catalog = add(f"<< /Type /Catalog /Pages {pages_id} 0 R >>".encode())
    info = add(b"<< /Title (" + _esc(title) + b") /Producer (levanta) >>")

    buf = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for i, obj in enumerate(objs, start=1):
        offsets.append(len(buf))
        buf += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref = len(buf)
    buf += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        buf += f"{off:010d} 00000 n \n".encode()
    buf += f"trailer\n<< /Size {len(objs) + 1} /Root {catalog} 0 R /Info {info} 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    path.write_bytes(bytes(buf))
    return path


def page_size_pt(paper: str = "A4", orientation: str = "landscape") -> tuple[float, float]:
    w_mm, h_mm = PAPER_MM.get(paper, PAPER_MM["A4"])
    if orientation == "landscape":
        w_mm, h_mm = h_mm, w_mm
    return w_mm * PT_PER_MM, h_mm * PT_PER_MM
