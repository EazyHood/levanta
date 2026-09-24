"""Before/after table for two bench runs (results.json files) of bench/arkitscenes.py.

Usage: python bench/compare.py before.json after.json [--run noK]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _fmt(v, f="{:.2f}"):
    return "—" if v is None else f.format(v)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("before", type=Path)
    ap.add_argument("after", type=Path)
    ap.add_argument("--run", default="noK")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    before = {r["video_id"]: r for r in json.loads(args.before.read_text(encoding="utf-8"))}
    after = {r["video_id"]: r for r in json.loads(args.after.read_text(encoding="utf-8"))}
    k = args.run
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from area_report import area_with_scale

    lines = [
        "| scene | truth floor / rooms | area error before → after | floor IoU before → after | camera RMS before → after | rooms | doors | flagged |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for vid in after:
        a, b = before.get(vid, {}).get(k, {}), after[vid].get(k, {})
        tr = after[vid]
        lines.append(
            f"| {vid} | {tr['truth_area_m2']:.1f} m² / {tr['truth_rooms']} "
            f"| {area_with_scale(a.get('area_error_pct'), a.get('scale_factor'))} → **{area_with_scale(b.get('area_error_pct'), b.get('scale_factor'))}** "
            f"| {_fmt(a.get('floor_iou'))} → **{_fmt(b.get('floor_iou'))}** "
            f"| {_fmt(a.get('traj_rms_m'))} → **{_fmt(b.get('traj_rms_m'))}** m "
            f"| {b.get('levanta_rooms', '—')} ({tr['truth_rooms']}) | {b.get('levanta_doors', '—')} | {'yes' if b.get('unreliable') or b.get('scale_chain_broken') else 'no'} |"
        )
    print("\n".join(lines))


if __name__ == "__main__":
    main()
