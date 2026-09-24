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

**What happened on 2026-09-12 to 09-23, and why `supervise` exists.**  1, 2 and 4 fps ran and
verified; the watcher died during 8 fps and, because only it wrote the record, the run read as
"never launched".  The task at logon ran the same half hour of GPU at every boot, nine times in
eleven days, while the check for games ran only between runs.  On the 23rd the child finished
at 11:11 with both scenes ok, after its watcher was gone.  Now the record is written before
launch, a run whose watcher died is judged by the child's own results (if they are newer than
the launch), the child lives in a job object that kills it with its watcher, and the games are
checked every 30 s during the run.  The result of the sweep, which contradicted the prediction
above, is in bench/results/fps_sweep_2026-09-24.md.

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


POLL_S = 30.0  # how often a running child is checked against the games


class _KillOnCloseJob:
    """A Windows job object whose processes die when its last handle closes.

    On 2026-09-23 the watcher was ended from outside (task result 0xC000013A, no farewell line)
    while its child kept the card for another half hour with nobody supervising it.  A child
    placed in this job dies with the process holding the handle, however that process dies,
    and so do the children it starts (`levanta video` under the bench), because processes
    created inside a job stay in it.  Elsewhere this is a no-op.
    """

    def __init__(self) -> None:
        self.handle = None
        if sys.platform != "win32":
            return
        import ctypes
        from ctypes import wintypes

        class _Basic(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD),
            ]

        class _Io(ctypes.Structure):
            _fields_ = [(n, ctypes.c_ulonglong) for n in ("ReadOps", "WriteOps", "OtherOps", "ReadBytes", "WriteBytes", "OtherBytes")]

        class _Extended(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", _Basic), ("IoInfo", _Io), ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateJobObjectW.restype = wintypes.HANDLE
        k32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        k32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
        k32.CloseHandle.argtypes = [wintypes.HANDLE]
        job = k32.CreateJobObjectW(None, None)
        if not job:
            return
        info = _Extended()
        info.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not k32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)):  # 9 = extended limits
            k32.CloseHandle(job)
            return
        self._k32, self.handle = k32, job

    def adopt(self, proc: subprocess.Popen) -> bool:
        return bool(self.handle) and bool(self._k32.AssignProcessToJobObject(self.handle, int(proc._handle)))

    def kill(self) -> None:
        if self.handle:
            self._k32.TerminateJobObject(self.handle, 1)

    def close(self) -> None:
        if self.handle:
            self._k32.CloseHandle(self.handle)
            self.handle = None


def supervise(cmd: list[str], log: Path, should_stop=None, poll_s: float = POLL_S) -> dict:
    """Run ``cmd`` with its output in ``log``, stop its whole tree if ``should_stop()`` names a
    reason, and make sure the tree dies with this process whatever kills it.

    The first version checked for a game only *between* runs, and 8 fps is a 35-minute run: a
    game opened a minute after it started shared the card with it until the end.
    """
    t0 = time.time()
    stopped = None
    job = _KillOnCloseJob()
    with log.open("w", encoding="utf-8") as fh:
        try:
            proc = subprocess.Popen(cmd, stdout=fh, stderr=subprocess.STDOUT, creationflags=NO_WINDOW)
        except Exception as e:
            job.close()
            return {"rc": f"launch failed: {type(e).__name__}: {e}", "seconds": time.time() - t0, "stopped": None, "in_job": False}
        in_job = job.adopt(proc)
        try:
            while True:
                try:
                    rc: int | str = proc.wait(timeout=poll_s)
                    break
                except subprocess.TimeoutExpired:
                    reason = should_stop() if should_stop else None
                    if reason:
                        stopped = reason
                        job.kill() if in_job else proc.kill()
                        proc.wait()
                        rc = f"stopped: {reason}"
                        break
        finally:
            job.close()  # anything the child left running dies here too
    return {"rc": rc, "seconds": time.time() - t0, "stopped": stopped, "in_job": in_job}


def run_one(scenes_dir: Path, out: Path, fps: float, eval_only: bool = False, should_stop=None, poll_s: float = POLL_S) -> dict:
    """One fps, both scenes, its own directory, no console, and a record that can be checked.

    The record is written twice: once **before** launch, with the command and the start time,
    and again when the child returns.  On 2026-09-12 the watcher died during 8 fps, the only
    record was the one written after, and a finished run read as "never launched" for eleven
    days, which made the task at logon run the same half hour of GPU at every boot.
    """
    run_out = out / f"fps_{fps:g}"
    run_out.mkdir(parents=True, exist_ok=True)
    cmd = [interpreter(), str(HERE / "arkitscenes.py"), str(scenes_dir), str(run_out), "--only", *SCENES, "--runs", "noK", "--fps", f"{fps:g}"]
    if eval_only:
        cmd.append("--eval-only")
    log = run_out / "sweep.log"
    timing = run_out / "timing.json"
    record = {"fps": fps, "started": time.time(), "executable": cmd[0], "cmd": cmd, "eval_only": eval_only}
    timing.write_text(json.dumps(record, indent=1), encoding="utf-8")
    result = supervise(cmd, log, should_stop=should_stop, poll_s=poll_s)
    record.update(result)
    record["log_bytes"] = log.stat().st_size if log.exists() else 0
    timing.write_text(json.dumps(record, indent=1), encoding="utf-8")
    return record


def note(run_out: Path) -> str | None:
    """What a trustworthy run needs said about it, beyond "it ran"."""
    timing = run_out / "timing.json"
    rec = json.loads(timing.read_text(encoding="utf-8")) if timing.exists() else {}
    if "rc" not in rec:
        return "watcher died before recording it; counted from the child's own results"
    return None


def verify(run_out: Path) -> str | None:
    """Why this run cannot be trusted, or None if it can.

    Estrenado against the case that motivated it: a `timing.json` with only fps and 25 ms in
    it, a 0-byte log and no results.json must come back as a failure, not as a run.

    A missing return code is no longer a failure by itself.  It means the watcher died, and
    the child may well have finished: on 2026-09-23 8 fps wrote both scenes ok at 11:11 while
    its watcher was already gone.  Such a run is judged by what the child left, and only if
    its results are newer than the record written at launch, so an old results.json cannot
    stand in for a run that was cut short.
    """
    timing = run_out / "timing.json"
    results = run_out / "results.json"
    if not timing.exists() and not results.exists():
        return "no timing.json: never launched"
    rec = json.loads(timing.read_text(encoding="utf-8")) if timing.exists() else {}
    log = run_out / "sweep.log"
    if not log.exists() or log.stat().st_size == 0:
        return "log is empty: the child wrote nothing"
    if "rc" in rec:
        if rec["rc"] != 0:
            return f"return code {rec['rc']!r}"
        if rec.get("seconds", 0.0) < MIN_SECONDS:
            return f"took {rec.get('seconds', 0.0):.3f} s, less than Python needs to start"
    elif rec.get("eval_only"):
        return "rehearsal without a recorded return code"
    if not results.exists():
        return "no results.json: the bench never got to its evaluation"
    if "rc" not in rec and "started" in rec and results.stat().st_mtime < rec["started"]:
        return "results.json is older than this launch: the run was cut short and the file is a previous one"
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
        timing = run_out / "timing.json"
        secs = json.loads(timing.read_text(encoding="utf-8")).get("seconds") if timing.exists() else None
        why = note(run_out)
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
                "scale_factor": k.get("scale_factor"),
                "rooms": k.get("levanta_rooms"),
                "floor_iou": k.get("floor_iou"),
                "seconds_for_both_scenes": secs,
                "note": why,
            })
    return rows


def _fmt(v, spec: str = "{:.2f}") -> str:
    return "\u2014" if v is None else spec.format(v)


def _area(r: dict) -> str:
    # this table printed "area error" alone, and at 4 fps its -15 % was a plan 2.2 times too
    # big with a shape 83 % short; see bench/area_report.py
    from area_report import area_with_scale

    return area_with_scale(r["area_error_pct"], r.get("scale_factor"))


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
            f"| {_area(r)} | {_fmt(r['rooms'], '{:d}')} | {_fmt(r['floor_iou'])} | {r.get('note') or _fmt(r['seconds_for_both_scenes'], '{:.0f} s')} |"
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
