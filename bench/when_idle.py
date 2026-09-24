"""Run something heavy on the card only when nobody is playing, and keep checking.

Jhona's order of 2026-09-06: no console over his game and no GPU while he plays.  This waits
until the card is free, then runs the fps sweep one fps at a time, re-checking before each so
a game that starts mid-sweep pauses the sweep instead of fighting it.  Everything it writes
goes under `out/`, never under %TEMP%, which Storage Sense empties.

**Two ways the first versions failed, both the watcher's and not the bench's.**

*The guard asked about the class, not the resource.*  It matched any process with "riot"
or "roblox" in its name, and `RiotClientServices.exe` with its crash handler are background
services that stay alive with no game open.  On 2026-09-12 at 16:08 both were running, the
card sat at 5 % used by the Start menu and Edge, and the guard said "waiting".  With Riot
installed there was never an idle moment, so the sweep never ran.  The question that matters
is whether the card is busy: GPU utilisation from `nvidia-smi`, and a short list of the
executables that actually render a game.  Launchers, services and crash handlers do not
count.

*The game was only checked between runs.*  8 fps is a 35-minute run, so a game opened a
minute into it shared the card until the end.  Now `game_open` is polled every 30 s during a
run and stops the child's whole tree, and the fps is retried when the card is free again.

*A process launched by hand does not survive the night.*  The log of 2026-09-11 stops at
23:07 with no farewell line: the PC slept or shut down and nothing relaunched the watcher.
It now runs as a scheduled task at logon with StartWhenAvailable (the pattern Bocado proved
after a shutdown), and it writes a farewell line on every exit so a log that simply stops is
recognisable as a death rather than a finish.

Usage:
    python bench/when_idle.py C:/Users/jhona/arkitscenes_data/raw/Validation out/fps_sweep
    python bench/when_idle.py ... --eval-only     # rehearse the whole launch without the card
    python bench/when_idle.py --probe             # say idle/busy right now and exit
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

# Executables that render a game.  Not RiotClientServices, not the crash handlers, not the
# launchers: those are alive whenever the game is installed, which is always.
GAME_EXES = (
    "league of legends.exe",
    "leagueclientux.exe",
    "valorant-win64-shipping.exe",
    "robloxplayerbeta.exe",
    "hd-player.exe",  # BlueStacks
)
GPU_BUSY_PERCENT = 25.0  # the desktop idles at 3-5 %; a game renders well above this
# The Claude app's own GPU process holds the card at 38 % whenever the app is open (measured
# 2026-09-24: claude.exe 3D 12.5-13.4 % plus copy 27.7 %, its webview 3D 8.2 %), so the global
# figure could never say "free" again.  The second gate reads the 3D engine per process instead,
# and these are known not to be games.  Our own pass runs on CUDA, not the 3D engine, so it does
# not count itself either.
NOT_GAMES_3D = ("claude.exe", "msedgewebview2.exe", "msedge.exe", "chrome.exe", "firefox.exe", "spotify.exe", "ms-teams.exe", "dwm.exe")
ENGINE_BUSY_PERCENT = 25.0  # any other process drawing this much 3D is taken for an unknown game


def process_names() -> list[str] | None:
    """Lower-cased image names alive right now, or None if we could not look."""
    try:
        out = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True, text=True, check=False, creationflags=NO_WINDOW).stdout
    except Exception:
        return None
    return [line.split('","')[0].strip('"').lower() for line in out.splitlines() if line.startswith('"')]


def gpu_utilisation() -> float | None:
    """Per cent of the card in use right now, or None if nvidia-smi is not there."""
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=utilization.gpu", "--format=csv,noheader,nounits"], capture_output=True, text=True, check=False, creationflags=NO_WINDOW, timeout=15).stdout
        return float(out.strip().splitlines()[0])
    except Exception:
        return None


LIVE = object()  # "read it now"; None means "could not be read", which is a different thing


def process_table() -> dict[int, str] | None:
    """Process id -> lower-cased image name, or None if we could not look."""
    try:
        out = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True, text=True, check=False, creationflags=NO_WINDOW).stdout
    except Exception:
        return None
    table = {}
    for line in out.splitlines():
        cells = line.strip().strip('"').split('","')
        if len(cells) >= 2 and cells[1].isdigit():
            table[int(cells[1])] = cells[0].lower()
    return table or None


def engine_3d_by_process() -> dict[int, float] | None:
    """Per cent of the 3D engine each process id is using now, from the Windows GPU Engine
    counters (one instance per process and engine, summed), or None if they cannot be read."""
    ps = r"(Get-Counter '\GPU Engine(*engtype_3D)\Utilization Percentage' -ErrorAction Stop).CounterSamples | ForEach-Object { $_.InstanceName + '=' + $_.CookedValue }"
    try:
        res = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True, check=False, creationflags=NO_WINDOW, timeout=30)
    except Exception:
        return None
    if res.returncode != 0:
        return None
    out: dict[int, float] = {}
    for line in res.stdout.splitlines():
        name, _, value = line.strip().rpartition("=")
        if not name.startswith("pid_"):
            continue
        try:
            pid, pct = int(name.split("_")[1]), float(value.replace(",", "."))
        except ValueError:
            continue
        out[pid] = out.get(pid, 0.0) + pct
    return out


def renderers(table=LIVE, engines=LIVE) -> dict[str, float] | None:
    """Image name -> per cent of the 3D engine, for every process drawing anything, or None
    if the counters cannot be read."""
    engines = engine_3d_by_process() if engines is LIVE else engines
    if engines is None:
        return None
    table = process_table() if table is LIVE else table
    out: dict[str, float] = {}
    for pid, pct in engines.items():
        if pct <= 0:
            continue
        name = (table or {}).get(pid, f"pid {pid}")
        out[name] = out.get(name, 0.0) + pct
    return out


def busy(procs=LIVE, gpu=LIVE, renders=LIVE) -> list[str]:
    """Why the card is not ours right now; empty when it is.

    Two gates.  The first is the list of executables that render a game.  The second is the 3D
    engine per process: anything outside :data:`NOT_GAMES_3D` drawing
    :data:`ENGINE_BUSY_PERCENT` or more is taken for a game nobody listed.  Only when the
    per-process counters cannot be read does it fall back to the card's global utilisation,
    which the Claude app alone keeps at 38 %.  Every input can be injected, so both directions
    are testable without opening a game; if nothing can be read at all, assume he is playing.
    """
    procs = process_names() if procs is LIVE else procs
    renders = renderers() if renders is LIVE else renders
    if renders is None:
        gpu = gpu_utilisation() if gpu is LIVE else gpu
    else:
        gpu = None
    reasons: list[str] = []
    if procs is None and renders is None and gpu is None:
        return ["cannot read processes or the card: assuming a game is open"]
    if procs is not None:
        reasons += sorted({p for p in procs if p in GAME_EXES})
    if renders is not None:
        reasons += [f"{name} 3D {pct:.0f} %" for name, pct in sorted(renders.items()) if name not in NOT_GAMES_3D and pct >= ENGINE_BUSY_PERCENT]
    elif gpu is not None and gpu >= GPU_BUSY_PERCENT:
        reasons.append(f"gpu {gpu:.0f} %")
    return reasons


def game_open(procs=LIVE) -> str | None:
    """The games rendering right now, for use *during* a run, or None.

    Only the process list: while the sweep runs, the card is busy with the sweep itself, so
    its utilisation says nothing about whether he is playing.
    """
    procs = process_names() if procs is LIVE else procs
    if procs is None:
        return None  # cannot look; the check before the run already said the card was free
    found = sorted({p for p in procs if p in GAME_EXES})
    return ", ".join(found) or None


def wait_until_idle(log, poll_s: int = 60) -> None:
    while True:
        why = busy()
        if not why:
            return
        log.write(f"{time.strftime('%H:%M:%S')} waiting: {', '.join(why)}\n")
        log.flush()
        time.sleep(poll_s)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("scenes_dir", type=Path, nargs="?")
    ap.add_argument("out", type=Path, nargs="?")
    ap.add_argument("--poll", type=int, default=60, help="seconds between checks while the card is busy")
    ap.add_argument("--eval-only", action="store_true", help="rehearse: the bench loads truths and evaluates what is on disk, no card")
    ap.add_argument("--probe", action="store_true", help="print why the card is busy right now, or 'idle', and exit")
    args = ap.parse_args()
    if args.probe:
        t0 = time.time()
        why = busy()
        drawing = renderers()
        shown = ", ".join(f"{n} {p:.0f} %" for n, p in sorted((drawing or {}).items(), key=lambda kv: -kv[1]) if p >= 0.5)
        print(f"gpu {gpu_utilisation()} %, 3D by process: {shown or 'none'} -> " + (", ".join(why) if why else "idle") + f" ({time.time() - t0:.1f} s)")
        return
    if args.scenes_dir is None or args.out is None:
        ap.error("scenes_dir and out are required unless --probe")
    args.out.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(HERE))
    from fps_sweep import FPS, collect, run_one, table, verify

    failed: list[float] = []
    outcome = "died"
    with (args.out / "when_idle.log").open("a", encoding="utf-8") as log:
        log.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} start, interpreter {sys.executable}, eval_only={args.eval_only}\n")
        log.flush()
        try:
            for fps in FPS:
                run_out = args.out / f"fps_{fps:g}"
                if verify(run_out) is None and not args.eval_only:
                    log.write(f"fps {fps:g}: already done and verified, skipped\n")
                    continue
                while True:
                    wait_until_idle(log, args.poll)
                    log.write(f"{time.strftime('%H:%M:%S')} idle, running fps {fps:g}\n")
                    log.flush()
                    # the games are watched during the run too: 8 fps is a 35-minute run, and a
                    # game opened a minute in used to share the card with it until the end
                    rec = run_one(args.scenes_dir, args.out, fps, eval_only=args.eval_only, should_stop=game_open)
                    if not rec.get("stopped"):
                        break
                    log.write(f"{time.strftime('%H:%M:%S')} fps {fps:g} stopped after {rec['seconds']:.0f} s: {rec['stopped']} opened; waiting to retry\n")
                    log.flush()
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
            outcome = f"sweep INCOMPLETE: failed fps {failed}" if failed else "sweep complete: every fps verified"
        except BaseException as e:
            outcome = f"died: {type(e).__name__}: {e}"
            raise
        finally:
            log.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} exit: {outcome}\n")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
