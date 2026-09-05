"""The phone that filmed a video is read from the file, and its focal length follows.

Three videos with injected metadata (written the way the phones write it: ``mdta`` keys
+ ``ilst`` values inside ``moov/meta``): an iPhone 15 Pro, a Galaxy S23 by its code
``SM-S911B``, and one with no model at all.

Thresholds written before the fix ran:
- iPhone 15 Pro, frames 1024 px wide: 24 mm equivalent -> 1024 * 24 / 34.6 = 710 +- 1 px;
- SM-S911B: FOV 85 deg -> 23.6 mm equivalent -> 699 +- 2 px;
- no model: no focal, and `levanta check` says so and points at --door-width;
- `levanta check` names the phone when it knows it; the table has >= 30 phones, every
  entry with a source URL and a 35 mm-equivalent between 20 and 30 mm.
"""

from __future__ import annotations

import struct

import numpy as np
import pytest
from typer.testing import CliRunner

from levanta.cli import app
from levanta.io.phone import PHONES, focal_for_video, identify, phone_of, read_mp4_metadata


def _box(typ: bytes, payload: bytes) -> bytes:
    return struct.pack(">I4s", 8 + len(payload), typ) + payload


def _meta_box(pairs: dict[str, str], full_box: bool = True) -> bytes:
    keys = b"".join(_box(b"mdta", k.encode("utf-8"))[0:0] + struct.pack(">I", 8 + len(k.encode())) + b"mdta" + k.encode() for k in pairs)
    keys_box = _box(b"keys", struct.pack(">II", 0, len(pairs)) + keys)
    items = b""
    for i, (_k, v) in enumerate(pairs.items(), start=1):
        data = _box(b"data", struct.pack(">II", 1, 0) + v.encode("utf-8"))
        items += _box(struct.pack(">I", i), data)
    hdlr = _box(b"hdlr", struct.pack(">I", 0) + b"\x00" * 4 + b"mdta" + b"\x00" * 12 + b"\x00")
    body = hdlr + keys_box + _box(b"ilst", items)
    return _box(b"meta", (struct.pack(">I", 0) if full_box else b"") + body)


def _write_mp4(path, pairs: dict[str, str] | None, width=320, height=180, seconds=3, fps=10.0):
    """A real (tiny) video from OpenCV with the phone's metadata added to its moov."""
    cv2 = pytest.importorskip("cv2")
    w = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height))
    rng = np.random.default_rng(0)
    for _ in range(int(fps * seconds)):
        w.write(rng.integers(0, 255, (height, width, 3), dtype=np.uint8))
    w.release()
    if not pairs:
        return path
    data = path.read_bytes()
    pos, out = 0, b""
    while pos + 8 <= len(data):  # rewrite the top-level moov with a meta box inside
        size, typ = struct.unpack(">I4s", data[pos : pos + 8])
        if size == 0:
            size = len(data) - pos
        if typ == b"moov":
            body = data[pos + 8 : pos + size] + _meta_box(pairs)
            out += struct.pack(">I4s", 8 + len(body), b"moov") + body
        else:
            out += data[pos : pos + size]
        pos += size
    path.write_bytes(out)
    return path


def test_table_is_complete_and_sourced():
    assert len(PHONES) >= 30
    for pat, phone in PHONES:
        assert phone.source.startswith("https://") and 20.0 <= phone.f_eq_mm <= 30.0, (pat, phone)


def test_iphone_metadata_gives_the_focal(tmp_path):
    p = _write_mp4(tmp_path / "iphone.mp4", {"com.apple.quicktime.make": "Apple", "com.apple.quicktime.model": "iPhone 15 Pro", "com.apple.quicktime.software": "17.4"})
    meta = read_mp4_metadata(p)
    assert phone_of(meta) == ("iPhone 15 Pro", "Apple")
    f, phone, model = focal_for_video(p, 1024)
    assert phone is not None and phone.name.startswith("iPhone 15 Pro") and model == "iPhone 15 Pro"
    assert abs(f - 1024 * 24 / 34.6) < 1.0


def test_samsung_code_is_recognised(tmp_path):
    p = _write_mp4(tmp_path / "s23.mp4", {"com.android.version": "14", "com.android.manufacturer": "samsung", "com.android.model": "SM-S911B"})
    f, phone, model = focal_for_video(p, 1024)
    assert model == "SM-S911B" and phone is not None and "S23" in phone.name
    assert abs(f - 1024 * 23.57 / 34.6) < 2.0
    assert identify("SM-A546E").name == "Galaxy A54" and identify("Pixel 8 Pro").name.startswith("Pixel 8")
    assert identify("Nokia 3310") is None and identify(None) is None


def test_unknown_phone_means_no_focal_and_check_says_so(tmp_path):
    p = _write_mp4(tmp_path / "unknown.mp4", None)
    assert phone_of(read_mp4_metadata(p)) == (None, None) and focal_for_video(p, 1024)[0] is None  # OpenCV writes its own ©too tag
    r = CliRunner().invoke(app, ["check", str(p)])
    assert r.exit_code == 0, r.output
    assert "phone" in r.output.lower() and "--door-width" in r.output
    p2 = _write_mp4(tmp_path / "known.mp4", {"com.apple.quicktime.model": "iPhone 14"})
    r2 = CliRunner().invoke(app, ["check", str(p2)])
    assert "iPhone 14" in r2.output and "focal" in r2.output.lower()
