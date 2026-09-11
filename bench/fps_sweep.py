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

**What happened on 2026-09-06, and why `verify` exists.**  The first version launched each
fps with `check=False`, recorded only the elapsed time, and the watcher wrote "done" on
return whatever had happened.  All four "runs" took 21-25 ms, less than Python takes to
start, wrote zero bytes to their logs, and the watcher wrote "sweep complete" over an empty
table that sat unread for four days.  A run is now only a run if its return code was 0, its
log is not empty, it took at least a second, and it left `results.json`; anything else is
named as a failure by `verify`, and the interpreter is pinned to the venv by absolute path
rather than inherited.

Usage (free to write, needs the card to run -- see bench/when_idle.py):
    python bench/fps_sweep.py C:/Users/jhona/arkitscenes_data/raw/Validation out/fps_sweep
    python bench/fps_sweep.py ... --eval-only      # rehearse the launch without the card
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
MIN_SECONDS = 1.0  # Python alone takes longer than 25 ms; a run under a second never ran


def interpreter() -> str:
    """The venv's own python.exe by absolute path; never whatever the parent happened to be."""
    venv = HERE.parent / ".venv" / "Scripts" / "python.exe"
    if venv.exists():
        return str(venv)
    posix = HERE.parent / ".venv" / "bin" / "python"
    return str(posix) if posix.exists() else sys.executable


def run_one(scenes_dir: Path, out: Path, fps: float, eval_only: bool = False) -> dict:
    """One fps, both scenes, its own directory, no console, and a record that can be checked."""
    run_out = out / f"fps_{fps:g}"
    run_out.mkdir(parents=True, exist_ok=True)
    cmd = [interpreter(), str(HERE / "arkitscenes.py"), str(scenes_dir), str(run_out), "--only", *SCENES, "--runs", "noK", "--fps", f"{fps:g}"]
    if eval_only:
        cmd.append("--eval-only")
    log = run_out / "sweep.log"
    t0 = time.time()
    with log.open("w", encoding="utf-8") as fh:
        try:
            rc: int | str = subprocess.run(cmd, stdout=fh, stderr=subprocess.STDOUT, check=False, creationflags=NO_WINDOW).returncode
        except Exception as e:
            rc = f"launch failed: {type(e).__name__}: {e}"
    record = {
        "fps": fps,
        "seconds": time.time() - t0,
        "rc": rc,
        "executable": cmd[0],
        "cmd": cmd,
        "log_bytes": log.stat().st_size if log.exists() else 0,
        "eval_only": eval_only,
    }
    (run_out / "timing.json").write_text(json.dumps(record, indent=1), encoding="utf-8")
    return record


def verify(run_out: Path) -> str | None:
    """Why this run cannot be trusted, or None if it can.

    Estrenado against the case that motivated it: a `timing.json` with only fps and 25 ms in
    it, a 0-byte log and no results.json must come back as a failure, not as a run.
    """
    timing = run_out / "timing.json"
    if not timing.exists():
        return "no timing.json: never launched"
    rec = json.loads(timing.read_text(encoding="utf-8"))
    if "rc" not in rec:
        return "no return code recorded: the old launcher that could not tell a run from nothing"
    if rec["rc"] != 0:
        return f"return code {rec['rc']!r}"
    log = run_out / "sweep.log"
    if not log.exists() or log.stat().st_size == 0:
        return "log is empty: the child wrote nothing"
    if rec.get("seconds", 0.0) < MIN_SECONDS:
        return f"took {rec.get('seconds', 0.0):.3f} s, less than Python needs to start"
    results = run_out / "results.json"
    if not results.exists():
        return "no results.json: the bench never got to its evaluation"
    if not rec.get("eval_only"):
        # a real run where levanta itself fell over still leaves a results.json, with the
        # scene marked not ok; that is the next way this file could say "done" over nothing
        rows = json.loads(results.read_text(encoding="utf-8"))
        bad = [r.get("video_id") for r in rows if not r.get("noK", {}).get("ok")]
        if not rows or bad:
            return f"levanta did not finish on {bad or 'any scene'}"
    return None


def collect(out: Path) -> list[dict]:
    rows = []
    for fps in FPS:
        run_out = out / f"fps_{fps:g}"
        problem = verify(run_out)
        if problem:
            rows.append({"fps": fps, "scene": "(all)", "failed": problem})
            continue
        secs = json.loads((run_out / "timing.json").read_text(encoding="utf-8")).get("seconds")
        for r in json.loads((run_out / "results.json").read_text(encoding="utf-8")):
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
        if "failed" in r:
            lines.append(f"| {r['fps']:g} | **FAILED** | {r['failed']} | | | | | | |")
            continue
        lines.append(
            f"| {r['fps']:g} | {r['scene']} | {r['truth_m2']:.1f} m\u00b2 | {_fmt(r['frames'], '{:d}')} | {_fmt(r['frames_per_m2'], '{:.1f}')} "
            f"| {_fmt(r['area_error_pct'], '{:+.0f} %')} | {_fmt(r['rooms'], '{:d}')} | {_fmt(r['floor_iou'])} | {_fmt(r['seconds_for_both_scenes'], '{:.0f} s')} |"
        )
    if not rows:
        lines.append("| | **no runs on disk** | | | | | | | |")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("scenes_dir", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--collect-only", action="store_true", help="do not run levanta, tabulate what is on disk")
    ap.add_argument("--eval-only", action="store_true", help="pass --eval-only to the bench: rehearses the launch, loads truths, touches no card")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
    args.out.mkdir(parents=True, exist_ok=True)
    failed = []
    if not args.collect_only:
        for fps in FPS:
            rec = run_one(args.scenes_dir, args.out, fps, eval_only=args.eval_only)
            problem = verify(args.out / f"fps_{fps:g}")
            print(f"fps {fps:g}: rc={rec['rc']!r} {rec['seconds']:.1f} s {rec['log_bytes']} bytes -> {problem or 'ok'}")
            if problem:
                failed.append(fps)
    rows = collect(args.out)
    md = table(rows)
    (args.out / "fps_sweep.md").write_text(md + "\n", encoding="utf-8")
    (args.out / "fps_sweep.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")
    print(md)
    if failed:
        print(f"FAILED fps: {failed}")
        sys.exit(1)


if __name__ == "__main__":
    main()
