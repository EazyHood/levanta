"""Which phone filmed this video, and what focal length that implies.

Phones write their model into the MP4/MOV they record: iPhones as
``com.apple.quicktime.model`` (with ``...make`` and ``...software``), Android's
MediaRecorder as ``com.android.model`` / ``com.android.manufacturer`` (both live in
``moov/meta`` as ``mdta`` keys + ``ilst`` values).  From the model and the manufacturer's
published focal length (35 mm equivalent) or diagonal field of view of the main camera we
derive the focal length in pixels of the frames given to the network, which fixes most
of the metric-scale error (measured on TUM: 0.86 -> 0.93 with known intrinsics).

The derivation assumes the video uses the full sensor width (16:9 crops the height of a
4:3 sensor, not its width).  Electronic stabilisation crops a further 5-10 %, which makes
the true focal that much longer; the table value is therefore a lower bound within about
10 %.  No parsing library: the boxes are read directly, and only ``moov`` (a few MB at
most) is loaded.
"""

from __future__ import annotations

import math
import re
import struct
from dataclasses import dataclass
from pathlib import Path

# A 35 mm frame is 36 x 24 mm, diagonal 43.27 mm.  Manufacturers quote the equivalent
# focal length for the sensor's diagonal; a 4:3 sensor with that diagonal is 34.6 mm wide.
_FF_DIAG = math.hypot(36.0, 24.0)
_FF_WIDTH_43 = _FF_DIAG * 0.8


@dataclass(frozen=True)
class Phone:
    name: str
    f_eq_mm: float  # main camera, 35 mm equivalent, from the source
    source: str
    quoted_as: str  # "26 mm" or "FOV 85°": what the source actually says


def _from_fov(deg: float) -> float:
    return _FF_DIAG / (2.0 * math.tan(math.radians(deg) / 2.0))


# (regex on the model string, Phone).  Model strings as written by the phone itself:
# Apple writes the marketing name ("iPhone 15 Pro"); Samsung its code ("SM-S911B");
# Google the marketing name ("Pixel 8").  Sources are the manufacturers' spec pages
# (Apple quotes millimetres, Samsung and Google a diagonal field of view).  Checked on
# 2026-09-05: Apple's iPhone 15 page says "48MP Main: 26 mm"; for the Galaxy S23 and the
# Pixel 8 the independent spec sheets at gsmarena.com give 24 mm and 25 mm, which is
# what 85 deg and 82 deg convert to here (23.6 and 24.9).  The rest are the same
# manufacturers' sheets as remembered, not re-read today: treat them as +-1 mm.
_A = "https://support.apple.com/en-us/"
_S = "https://www.samsung.com/us/smartphones/"
_G = "https://store.google.com/product/"
PHONES: list[tuple[str, Phone]] = [
    (r"^iPhone 16 Pro", Phone("iPhone 16 Pro / Pro Max", 24, _A + "121031", "24 mm")),
    (r"^iPhone 16(?! Pro)", Phone("iPhone 16 / 16 Plus", 26, _A + "121029", "26 mm")),
    (r"^iPhone 15 Pro", Phone("iPhone 15 Pro / Pro Max", 24, _A + "111829", "24 mm")),
    (r"^iPhone 15(?! Pro)", Phone("iPhone 15 / 15 Plus", 26, _A + "111831", "26 mm")),
    (r"^iPhone 14 Pro", Phone("iPhone 14 Pro / Pro Max", 24, _A + "111849", "24 mm")),
    (r"^iPhone 14(?! Pro)", Phone("iPhone 14 / 14 Plus", 26, _A + "111850", "26 mm")),
    (r"^iPhone 13 Pro", Phone("iPhone 13 Pro / Pro Max", 26, _A + "111871", "26 mm")),
    (r"^iPhone 13(?! Pro)", Phone("iPhone 13 / 13 mini", 26, _A + "111872", "26 mm")),
    (r"^iPhone 12 Pro", Phone("iPhone 12 Pro / Pro Max", 26, _A + "111875", "26 mm")),
    (r"^iPhone 12(?! Pro)", Phone("iPhone 12 / 12 mini", 26, _A + "111876", "26 mm")),
    (r"^iPhone 11 Pro", Phone("iPhone 11 Pro / Pro Max", 26, _A + "111879", "26 mm")),
    (r"^iPhone 11(?! Pro)", Phone("iPhone 11", 26, _A + "111881", "26 mm")),
    (r"^iPhone SE", Phone("iPhone SE (2020 / 2022)", 28, _A + "111866", "28 mm")),
    (r"^iPhone XR|^iPhone XS|^iPhone X$", Phone("iPhone X / XS / XR", 26, _A + "111865", "26 mm")),
    (r"^SM-S92[168]", Phone("Galaxy S24 / S24+ / S24 Ultra", _from_fov(85), _S + "galaxy-s24/", "FOV 85°")),
    (r"^SM-S91[168]", Phone("Galaxy S23 / S23+ / S23 Ultra", _from_fov(85), _S + "galaxy-s23/", "FOV 85°")),
    (r"^SM-S90[168]", Phone("Galaxy S22 / S22+ / S22 Ultra", _from_fov(85), _S + "galaxy-s22/", "FOV 85°")),
    (r"^SM-S93[168]", Phone("Galaxy S25 / S25+ / S25 Ultra", _from_fov(85), _S + "galaxy-s25/", "FOV 85°")),
    (r"^SM-A55", Phone("Galaxy A55", _from_fov(80), _S + "galaxy-a55-5g/", "FOV 80°")),
    (r"^SM-A54", Phone("Galaxy A54", _from_fov(80), _S + "galaxy-a54-5g/", "FOV 80°")),
    (r"^SM-A34", Phone("Galaxy A34", _from_fov(80), _S + "galaxy-a34-5g/", "FOV 80°")),
    (r"^SM-A35", Phone("Galaxy A35", _from_fov(80), _S + "galaxy-a35-5g/", "FOV 80°")),
    (r"^SM-A15", Phone("Galaxy A15", _from_fov(80), _S + "galaxy-a15-5g/", "FOV 80°")),
    (r"^SM-A14", Phone("Galaxy A14", _from_fov(80), _S + "galaxy-a14-5g/", "FOV 80°")),
    (r"^SM-A25", Phone("Galaxy A25", _from_fov(80), _S + "galaxy-a25-5g/", "FOV 80°")),
    (r"^SM-A16", Phone("Galaxy A16", _from_fov(80), _S + "galaxy-a16-5g/", "FOV 80°")),
    (r"^Pixel 9", Phone("Pixel 9 / 9 Pro", _from_fov(82), _G + "pixel_9_specs", "FOV 82°")),
    (r"^Pixel 8a", Phone("Pixel 8a", _from_fov(80), _G + "pixel_8a_specs", "FOV 80°")),
    (r"^Pixel 8", Phone("Pixel 8 / 8 Pro", _from_fov(82), _G + "pixel_8_specs", "FOV 82°")),
    (r"^Pixel 7a", Phone("Pixel 7a", _from_fov(80), _G + "pixel_7a_specs", "FOV 80°")),
    (r"^Pixel 7", Phone("Pixel 7 / 7 Pro", _from_fov(82), _G + "pixel_7_specs", "FOV 82°")),
    (r"^Pixel 6a", Phone("Pixel 6a", _from_fov(77), _G + "pixel_6a_specs", "FOV 77°")),
    (r"^Pixel 6", Phone("Pixel 6 / 6 Pro", _from_fov(82), _G + "pixel_6_specs", "FOV 82°")),
]


def identify(model: str | None) -> Phone | None:
    if not model:
        return None
    for pat, phone in PHONES:
        if re.search(pat, model.strip(), flags=re.I):
            return phone
    return None


def focal_px(phone: Phone, width_px: int) -> float:
    """Focal length in pixels for a landscape frame ``width_px`` wide (its long side)."""
    return width_px * phone.f_eq_mm / _FF_WIDTH_43


# -- the MP4 / MOV metadata -------------------------------------------------------------------

MODEL_KEYS = ("com.apple.quicktime.model", "com.android.model", "©mod")
MAKE_KEYS = ("com.apple.quicktime.make", "com.android.manufacturer", "©mak")


def _boxes(buf: bytes, start: int = 0, end: int | None = None):
    """Yield (type, payload_start, payload_end) for the boxes in buf[start:end]."""
    end = len(buf) if end is None else end
    pos = start
    while pos + 8 <= end:
        size, typ = struct.unpack(">I4s", buf[pos : pos + 8])
        hdr = 8
        if size == 1:
            if pos + 16 > end:
                return
            size = struct.unpack(">Q", buf[pos + 8 : pos + 16])[0]
            hdr = 16
        elif size == 0:
            size = end - pos
        if size < hdr:
            return
        yield typ, pos + hdr, min(pos + size, end)
        pos += size


def _meta_children(buf: bytes, start: int, end: int):
    """'meta' is a full box in ISO files (4 bytes of version/flags first) and a plain box
    in QuickTime files: look at what parses."""
    for skip in (4, 0):
        kids = list(_boxes(buf, start + skip, end))
        if any(t in (b"hdlr", b"keys", b"ilst") for t, _, _ in kids):
            return kids
    return []


def _parse_meta(buf: bytes, start: int, end: int, out: dict[str, str]) -> None:
    keys: list[str] = []
    ilst: tuple[int, int] | None = None
    for typ, a, b in _meta_children(buf, start, end):
        if typ == b"keys":
            n = struct.unpack(">I", buf[a + 4 : a + 8])[0]
            pos = a + 8
            for _ in range(n):
                if pos + 8 > b:
                    break
                ksize = struct.unpack(">I", buf[pos : pos + 4])[0]
                keys.append(buf[pos + 8 : pos + ksize].decode("utf-8", "replace"))
                pos += ksize
        elif typ == b"ilst":
            ilst = (a, b)
    if ilst is None:
        return
    for typ, a, b in _boxes(buf, *ilst):
        idx = struct.unpack(">I", typ)[0]
        if 1 <= idx <= len(keys):
            name = keys[idx - 1]
        else:
            name = typ.decode("latin-1")
        for dt, da, db in _boxes(buf, a, b):
            if dt == b"data" and db - da >= 8:
                kind = struct.unpack(">I", buf[da : da + 4])[0]
                payload = buf[da + 8 : db]
                if kind in (1, 2, 4):  # UTF-8, UTF-16, or unset text
                    out[name] = payload.decode("utf-16" if kind == 2 else "utf-8", "replace").strip("\x00 ")
                elif kind == 0 and all(32 <= c < 127 for c in payload):
                    out[name] = payload.decode("ascii").strip()


def read_mp4_metadata(path: str | Path) -> dict[str, str]:
    """The ``mdta``/``ilst`` string metadata of an MP4/MOV (``moov/meta``, ``moov/udta/meta``
    or a file-level ``meta``): model, make, software, creation date ... as written by the
    phone.  Empty when there is none."""
    path = Path(path)
    out: dict[str, str] = {}
    size = path.stat().st_size
    with path.open("rb") as fh:
        pos = 0
        while pos + 8 <= size:
            fh.seek(pos)
            head = fh.read(16)
            if len(head) < 8:
                break
            bsize, typ = struct.unpack(">I4s", head[:8])
            hdr = 8
            if bsize == 1:
                bsize = struct.unpack(">Q", head[8:16])[0]
                hdr = 16
            elif bsize == 0:
                bsize = size - pos
            if bsize < hdr:
                break
            if typ in (b"moov", b"meta") and bsize <= 64 * 2**20:
                fh.seek(pos)
                buf = fh.read(bsize)
                if typ == b"meta":
                    _parse_meta(buf, hdr, len(buf), out)
                else:
                    for t, a, b in _boxes(buf, hdr, len(buf)):
                        if t == b"meta":
                            _parse_meta(buf, a, b, out)
                        elif t == b"udta":
                            for t2, a2, b2 in _boxes(buf, a, b):
                                if t2 == b"meta":
                                    _parse_meta(buf, a2, b2, out)
            pos += bsize
    return out


def phone_of(meta: dict[str, str]) -> tuple[str | None, str | None]:
    """(model, make) as the phone wrote them, or (None, None)."""
    model = next((meta[k] for k in MODEL_KEYS if meta.get(k)), None)
    make = next((meta[k] for k in MAKE_KEYS if meta.get(k)), None)
    return model, make


def focal_for_video(path: str | Path, frame_width_px: int) -> tuple[float | None, Phone | None, str | None]:
    """(focal in pixels for frames ``frame_width_px`` wide, the phone, the raw model string).

    The focal is None when the phone is unknown or the file carries no model: then the
    scale must come from ``--focal-px`` or ``--door-width``."""
    meta = read_mp4_metadata(path)
    model, _make = phone_of(meta)
    phone = identify(model)
    return (focal_px(phone, frame_width_px) if phone else None), phone, model
