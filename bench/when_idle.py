"""Run something heavy on the card only when nobody is playing, and keep checking.

Jhona's order of 2026-09-06: no console over his game and no GPU while he plays.  This waits
until no game process is running, then runs the fps sweep one fps at a time, re-checking
before each so a game that starts mid-sweep pauses the sweep instead of fighting it.
Everything it writes goes under `out/`, never under %TEMP%, which Storage Sense empties.

Game processes seen live on this machine: RobloxPlayerBeta.exe, RiotClientServices.exe, and
League of Legends.exe when a match is on.  Matching is by substring so crash handlers and
launchers count too: a launcher open means a game is about to start.

**What the first version did on 2026-09-06.**  It wrote "done" the moment `run_one`
returned, whatever had happened, and "sweep complete" at the end.  The four children had
died in 21-25 ms without writing a byte, and the log said complete over an empty table for
four days.  Now a fps is only "done" when `fps_sweep.verify` finds nothing wrong with what
it left on disk; a failed fps is written as FAILED and the sweep never claims completion
over one.

Usage:
    python bench/when_idle.py C:/Users/jhona/arkitscenes_data/raw/Validation out/fps_sweep
    python bench/when_idle.py ... --eval-only     # rehearse the whole launch without the card
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

try:
    from quiet import NO_WINDOW
except ImportError:
    NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

HERE = Path(__file__).resolve().parent
GAMES = ("roblox", "league", "riotclient", "vgc", "vanguard")


def games_running() -> list[str]:
    """Names of the game processes alive right now; if we cannot look, assume he is playing."""
    try:
        out = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True, text=True, check=False, creationflags=NO_WINDOW).stdout
    except Exception:
        return ["(tasklist failed)"]
    names = [line.split('","')[0].strip('"') for line in out.splitlines() if line.startswith('"')]
    return sorted({n for n in names if any(g in n.lower() for g in GAMES)})


def wait_until_idle(log, poll_s: int = 60) -> None:
    while True:
        busy = games_running()
        if not busy:
            return
        log.write(f"{time.strftime('%H:%M:%S')} waiting: {', '.join(busy)}\n")
        log.flush()
        time.sleep(poll_s)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("scenes_dir", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--poll", type=int, default=60, help="seconds between checks while a game is open")
    ap.add_argument("--eval-only", action="store_true", help="rehearse: the bench loads truths and evaluates what is on disk, no card")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(HERE))
    from fps_sweep import FPS, collect, run_one, table, verify

    failed: list[float] = []
    with (args.out / "when_idle.log").open("a", encoding="utf-8") as log:
        log.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} start, interpreter {sys.executable}, eval_only={args.eval_only}\n")
        for fps in FPS:
            run_out = args.out / f"fps_{fps:g}"
            if verify(run_out) is None and not args.eval_only:
                log.write(f"fps {fps:g}: already done and verified, skipped\n")
                continue
            wait_until_idle(log, args.poll)
            log.write(f"{time.strftime('%H:%M:%S')} idle, running fps {fps:g}\n")
            log.flush()
            rec = run_one(args.scenes_dir, args.out, fps, eval_only=args.eval_only)
            problem = verify(run_out)
            if problem:
                failed.append(fps)
                log.write(f"{time.strftime('%H:%M:%S')} fps {fps:g} FAILED after {rec['seconds']:.1f} s: {problem}\n")
            else:
                log.write(f"{time.strftime('%H:%M:%S')} fps {fps:g} done in {rec['seconds']:.0f} s, rc 0, {rec['log_bytes']} bytes of log\n")
            log.flush()
        rows = collect(args.out)
        md = table(rows)
        (args.out / "fps_sweep.md").write_text(md + "\n", encoding="utf-8")
        if failed:
            log.write(f"sweep INCOMPLETE: failed fps {failed}\n")
        else:
            log.write("sweep complete: every fps verified\n")
    print(md)
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
