"""The sweep's child must stop when a game opens, and must die when its watcher dies.

Both failed in September.  The game was checked only between runs, and 8 fps is a 35-minute
run.  And on 2026-09-23 the watcher was ended from outside (task result 0xC000013A, no
farewell line) while its child kept the card for another half hour with nobody supervising
it.  These tests use harmless sleeping children instead of the GPU, and the last one does to
a watcher exactly what happened that day: a hard kill.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import pytest

BENCH = Path(__file__).resolve().parent.parent / "bench"
sys.path.insert(0, str(BENCH))
from fps_sweep import supervise  # noqa: E402
from when_idle import game_open  # noqa: E402

windows_only = pytest.mark.skipif(sys.platform != "win32", reason="job objects are a Windows mechanism")


def _alive(pid: int) -> bool:
    """Whether a process with this pid is still running, without psutil."""
    if sys.platform != "win32":
        import os

        try:
            os.kill(pid, 0)
        except OSError:
            return False
        return True
    import ctypes

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    h = k32.OpenProcess(0x00100000 | 0x1000, False, pid)  # SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return False
    try:
        return k32.WaitForSingleObject(h, 0) == 0x102  # WAIT_TIMEOUT: still running
    finally:
        k32.CloseHandle(h)


def _gone_within(pid: int, seconds: float) -> bool:
    end = time.time() + seconds
    while time.time() < end:
        if not _alive(pid):
            return True
        time.sleep(0.1)
    return not _alive(pid)


def _wait_for(path: Path, seconds: float = 20.0) -> str:
    end = time.time() + seconds
    while time.time() < end:
        if path.exists() and path.read_text(encoding="utf-8").strip():
            return path.read_text(encoding="utf-8").strip()
        time.sleep(0.1)
    raise AssertionError(f"{path} never appeared")


def test_a_child_that_finishes_is_left_alone(tmp_path):
    rec = supervise([sys.executable, "-c", "print('ran')"], tmp_path / "log.txt", should_stop=lambda: None, poll_s=0.2)
    assert rec["rc"] == 0 and rec["stopped"] is None
    assert "ran" in (tmp_path / "log.txt").read_text(encoding="utf-8")


def test_a_game_opening_mid_run_stops_the_child(tmp_path):
    """A 60-second child stopped on the first poll: gone in well under its own length."""
    t0 = time.time()
    rec = supervise([sys.executable, "-c", "import time; time.sleep(60)"], tmp_path / "log.txt", should_stop=lambda: "league of legends.exe", poll_s=0.5)
    assert rec["stopped"] == "league of legends.exe"
    assert str(rec["rc"]).startswith("stopped:")
    assert time.time() - t0 < 15


@windows_only
def test_stopping_takes_the_grandchildren_too(tmp_path):
    """Under the sweep the bench starts `levanta video` as its own process; stopping only the
    direct child would leave that one on the card."""
    pidfile = tmp_path / "grandchild.pid"
    code = (
        "import subprocess, sys, time;"
        f"g = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']);"
        f"open(r'{pidfile}', 'w').write(str(g.pid));"
        "time.sleep(60)"
    )
    def stop_once_the_grandchild_exists():
        return "roblox" if pidfile.exists() else None

    rec = supervise([sys.executable, "-c", code], tmp_path / "log.txt", should_stop=stop_once_the_grandchild_exists, poll_s=0.5)
    assert rec["stopped"] == "roblox" and rec["in_job"]
    grandchild = int(pidfile.read_text(encoding="utf-8"))
    assert _gone_within(grandchild, 5), "the grandchild survived the stop"


@windows_only
def test_a_watcher_killed_hard_takes_its_child_with_it(tmp_path):
    """What happened on 2026-09-23, done on purpose: the watcher is terminated from outside
    with no chance to clean up, and the child it was supervising must not keep running."""
    # scripts in files and paths through argv: nesting a Windows path inside one string inside
    # another turned "C:\Users" into a \U escape and the watcher never started
    pidfile = tmp_path / "child.pid"
    child_py = tmp_path / "child.py"
    child_py.write_text("import os, sys, time\nopen(sys.argv[1], 'w').write(str(os.getpid()))\ntime.sleep(120)\n", encoding="utf-8")
    watcher_py = tmp_path / "watcher.py"
    watcher_py.write_text(
        "import sys\nfrom pathlib import Path\nsys.path.insert(0, sys.argv[1])\nfrom fps_sweep import supervise\n"
        "supervise([sys.executable, sys.argv[2], sys.argv[3]], Path(sys.argv[4]), poll_s=0.5)\n",
        encoding="utf-8",
    )
    err = (tmp_path / "watcher.err").open("w", encoding="utf-8")
    w = subprocess.Popen(
        [sys.executable, str(watcher_py), str(BENCH), str(child_py), str(pidfile), str(tmp_path / "log.txt")],
        stderr=err, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    try:
        try:
            child = int(_wait_for(pidfile))
        except AssertionError:
            err.close()
            raise AssertionError("watcher never started its child: " + (tmp_path / "watcher.err").read_text(encoding="utf-8")) from None
        assert _alive(child), "the child should be running before the watcher is killed"
        w.kill()  # TerminateProcess: no finally, no atexit, like the task being ended
        w.wait(timeout=10)
        assert _gone_within(child, 5), "the child outlived its watcher, as the 8 fps run did"
    finally:
        if w.poll() is None:
            w.kill()
        err.close()


def test_game_open_names_the_game_and_ignores_the_launcher():
    assert game_open(["riotclientservices.exe", "riotclientcrashhandler.exe", "explorer.exe"]) is None
    assert game_open(["riotclientservices.exe", "league of legends.exe"]) == "league of legends.exe"
    assert game_open(None) is None  # cannot look mid-run: the check before the run already passed
