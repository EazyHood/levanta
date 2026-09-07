"""Run something heavy on the card only when nobody is playing, and keep checking.

Jhona's order of 2026-09-06: no console over his game and no GPU while he plays.  This waits
until no game process is running, then runs the fps sweep one fps at a time, re-checking
before each so a game that starts mid-sweep pauses the sweep instead of fighting it.
Everything it writes goes under `out/`, never under %TEMP%, which Storage Sense empties.

Game processes seen live on this machine: RobloxPlayerBeta.exe, RiotClientServices.exe, and
League of Legends.exe when a match is on.  Matching is by substring so crash handlers and
launchers count too: a launcher open means a game is about to start.

Usage:
    python bench/when_idle.py C:/Users/jhona/arkitscenes_data/raw/Validation out/fps_sweep
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
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(HERE))
    from fps_sweep import FPS, collect, run_one, table

    with (args.out / "when_idle.log").open("a", encoding="utf-8") as log:
        for fps in FPS:
            if (args.out / f"fps_{fps:g}" / "timing.json").exists():
                log.write(f"fps {fps:g}: already done, skipped\n")
                continue
            wait_until_idle(log, args.poll)
            log.write(f"{time.strftime('%H:%M:%S')} idle, running fps {fps:g}\n")
            log.flush()
            run_out, secs = run_one(args.scenes_dir, args.out, fps)
            (run_out / "timing.json").write_text(json.dumps({"fps": fps, "seconds": secs}), encoding="utf-8")
            log.write(f"{time.strftime('%H:%M:%S')} fps {fps:g} done in {secs:.0f} s\n")
            log.flush()
        rows = collect(args.out)
        md = table(rows)
        (args.out / "fps_sweep.md").write_text(md + "\n", encoding="utf-8")
        log.write("sweep complete\n")
    print(md)


if __name__ == "__main__":
    main()
