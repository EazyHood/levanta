"""What should the default sampling be?  Measured, not chosen.

`levanta video` samples at 1 fps by default.  A phone films at 30 or 60, so the default
keeps one frame in thirty or sixty, and the one flat nobody chose came out at a fifth of its
floor with the user told nothing.  The warning that followed said "run it again with
--fps 2", which hands a stranger a decision the tool can take by itself.  This sweep is what
decides that default.

Subject: the two ARKitScenes rooms whose `.mov` is still on disk, 41069021 (19.1 m2) and
42897526 (5.6 m2), both filmed at 60 fps with a LiDAR mesh as truth.  The flat nobody chose
cannot be the subject: its rendered walk is 1 fps native, so there is nothing to sweep.

Each fps runs the whole pipeline through `bench/arkitscenes.py` into its own directory, so
nothing overwrites anything, and the table reports per fps and per scene: frames kept,
frames per m2 of true floor, area error, rooms, floor IoU, and wall time.

**Prediction, written before the first run.**  Area error improves clearly from 1 to 2 fps,
little from 2 to 4, and not at all from 4 to 8, because past a few frames per m2 the extra
views land on surfaces already covered; wall time grows about linearly with fps since the
network works in chunks of 24 views.  So the knee is expected near 2-4 fps on these rooms,
which is 10-40 frames per m2, an order of magnitude above the 1.5 that separated the thin
flat from the bench.  If the error keeps falling to 8 fps the knee is beyond what a 60 fps
clip can give and the default should be "every frame the budget allows".

The output is not a number of fps.  It is the rule the default should implement: sample
until the plan reaches the minimum density, under a time ceiling, without asking.

Usage (free to write, needs the card to run -- see bench/when_idle.py):
    python bench/fps_sweep.py C:/Users/jhona/arkitscenes_data/raw/Validation out/fps_sweep
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

try:
    from quiet import NO_WINDOW
except ImportError:  # run from outside bench/
    NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

HERE = Path(__file__).resolve().parent
SCENES = ["41069021", "42897526"]
FPS = [1.0, 2.0, 4.0, 8.0]


def run_one(scenes_dir: Path, out: Path, fps: float) -> tuple[Path, float]:
    """One fps, both scenes, its own directory, no console."""
    run_out = out / f"fps_{fps:g}"
    run_out.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, str(HERE / "arkitscenes.py"), str(scenes_dir), str(run_out), "--only", *SCENES, "--runs", "noK", "--fps", f"{fps:g}"]
    t0 = time.time()
    with (run_out / "sweep.log").open("w", encoding="utf-8") as fh:
        subprocess.run(cmd, stdout=fh, stderr=subprocess.STDOUT, check=False, creationflags=NO_WINDOW)
    return run_out, time.time() - t0


def collect(out: Path) -> list[dict]:
    rows = []
    for fps in FPS:
        run_out = out / f"fps_{fps:g}"
        res = run_out / "results.json"
        if not res.exists():
            continue
        timing = run_out / "timing.json"
        secs = json.loads(timing.read_text(encoding="utf-8")).get("seconds") if timing.exists() else None
        for r in json.loads(res.read_text(encoding="utf-8")):
            k = r.get("noK", {})
            idx = run_out / r["video_id"] / "noK" / "frames" / "index.json"
            n = len(json.loads(idx.read_text(encoding="utf-8"))) if idx.exists() else None
            rows.append({
                "fps": fps,
                "scene": r["video_id"],
                "truth_m2": r["truth_area_m2"],
                "frames": n,
                "frames_per_m2": (n / r["truth_area_m2"]) if n else None,
                "area_error_pct": k.get("area_error_pct"),
                "rooms": k.get("levanta_rooms"),
                "floor_iou": k.get("floor_iou"),
                "seconds_for_both_scenes": secs,
            })
    return rows


def _fmt(v, spec: str = "{:.2f}") -> str:
    return "\u2014" if v is None else spec.format(v)


def table(rows: list[dict]) -> str:
    lines = [
        "| fps | scene | truth | frames | frames/m\u00b2 | area error | rooms | floor IoU | wall time (both) |",
        "|" + "---|" * 9,
    ]
    for r in rows:
        lines.append(
            f"| {r['fps']:g} | {r['scene']} | {r['truth_m2']:.1f} m\u00b2 | {_fmt(r['frames'], '{:d}')} | {_fmt(r['frames_per_m2'], '{:.1f}')} "
            f"| {_fmt(r['area_error_pct'], '{:+.0f} %')} | {_fmt(r['rooms'], '{:d}')} | {_fmt(r['floor_iou'])} | {_fmt(r['seconds_for_both_scenes'], '{:.0f} s')} |"
        )
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("scenes_dir", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--collect-only", action="store_true", help="do not run levanta, tabulate what is on disk")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
    args.out.mkdir(parents=True, exist_ok=True)
    if not args.collect_only:
        for fps in FPS:
            run_out, secs = run_one(args.scenes_dir, args.out, fps)
            (run_out / "timing.json").write_text(json.dumps({"fps": fps, "seconds": secs}), encoding="utf-8")
            print(f"fps {fps:g}: {secs:.0f} s")
    rows = collect(args.out)
    md = table(rows)
    (args.out / "fps_sweep.md").write_text(md + "\n", encoding="utf-8")
    (args.out / "fps_sweep.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")
    print(md)


if __name__ == "__main__":
    main()
