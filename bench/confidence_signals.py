"""Do the two signals a user already has predict which rooms are wrong?

Every sheet now prints, per room, how much of its outline rests on floor that was actually
seen, and warns when two rooms share floor.  Neither needs ground truth, so both are
available in someone's house.  The question is whether they carry information: if a room
with little seen floor, or a room overlapping its neighbour, is reliably the wrong one, the
sheet can say *do not trust this room* without anyone measuring anything.

It also tests a hypothesis from round 10: that the overlap between two rooms and the
spilling of a room outside the building are the same failure seen from two sides, because
sight lines that leave through a doorway both inflate one room and push it onto its
neighbour.  If they move together, the overlap is a cheap thermometer for the whole thing.

The sample is small on purpose: it is every room of every scene the bench scores, which is
what exists.  With this many rooms a correlation is a hint, not a result, and the report
says so.

Usage:
    python bench/planner_bench.py --json out/pb.json      # produces the per-room rows
    python bench/confidence_signals.py out/pb.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np


def spearman(a: np.ndarray, b: np.ndarray) -> float:
    """Rank correlation, which is what a handful of points can support."""
    if len(a) < 3:
        return float("nan")
    ra = np.argsort(np.argsort(a)).astype(float)
    rb = np.argsort(np.argsort(b)).astype(float)
    return float(np.corrcoef(ra, rb)[0, 1])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("bench_json", type=Path)
    args = ap.parse_args()
    data = json.loads(args.bench_json.read_text(encoding="utf-8"))
    rows = data["rows"] if isinstance(data, dict) else data

    pairs = []
    for r in rows:
        if r.get("unreliable"):
            continue
        for m in r.get("per_room", []):
            if m.get("error_pct") is None or m.get("floor_seen_pct") is None:
                continue
            pairs.append((r["scene"], m["truth_m2"], m["error_pct"], m["floor_seen_pct"], m["overlap_pct"], m["outside_pct"], m["covered_pct"]))

    if not pairs:
        raise SystemExit("no scored rooms with the signals; re-run planner_bench.py")

    print(f"{len(pairs)} rooms levanta stands behind, every one of them scored against its own truth")
    print()
    print("| scene | truth | error | on seen floor | shared with another room | off the floor |")
    print("|" + "---|" * 6)
    for scene, truth_m2, err, seen, ov, off, _cov in pairs:
        print(f"| {scene[:26]} | {truth_m2:.1f} m² | {err:+.0f} % | {seen:.0f} % | {ov:.0f} % | {off:.0f} % |")

    err = np.array([abs(p[2]) for p in pairs])
    seen = np.array([p[3] for p in pairs])
    ov = np.array([p[4] for p in pairs])
    off = np.array([p[5] for p in pairs])
    print()
    print(f"rank correlation of |error| with the seen-floor share : {spearman(seen, err):+.2f}  (a useful warning would be strongly negative)")
    print(f"rank correlation of |error| with the shared-floor share: {spearman(ov, err):+.2f}  (a useful warning would be strongly positive)")
    print(f"rank correlation of shared floor with off-the-floor    : {spearman(ov, off):+.2f}  (round 10's hypothesis: the same failure twice)")

    bad = err > 50
    if bad.any() and (~bad).any():
        print()
        print(f"rooms wrong by more than 50 %: seen floor {seen[bad].mean():.0f} % on average, shared {ov[bad].mean():.0f} %")
        print(f"the rest                     : seen floor {seen[~bad].mean():.0f} % on average, shared {ov[~bad].mean():.0f} %")


if __name__ == "__main__":
    main()
