"""The guard asks whether the card is busy, not whether Riot is installed.

The first guard matched any process with "riot" or "roblox" in its name.  RiotClientServices
and its crash handler are background services that never exit, so with Riot installed the
watcher never found an idle moment and the sweep never ran.  Both directions are fixed here
with injected inputs, because the wrong one cannot be reproduced without opening a game.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bench"))
from when_idle import ENGINE_BUSY_PERCENT, GPU_BUSY_PERCENT, NOT_GAMES_3D, busy, renderers

RIOT_BACKGROUND = ["riotclientservices.exe", "riotclientcrashhandler.exe", "explorer.exe", "msedge.exe"]


def test_riot_in_the_background_with_the_card_idle_is_idle():
    """The state of 2026-09-12 16:08: two Riot services, the card at 5 %, no game.  The old
    guard said waiting; the sweep never ran."""
    assert busy(procs=RIOT_BACKGROUND, gpu=5.0, renders=None) == []


def test_league_rendering_is_busy():
    assert busy(procs=[*RIOT_BACKGROUND, "league of legends.exe"], gpu=5.0, renders=None) == ["league of legends.exe"]


def test_roblox_rendering_is_busy():
    assert "robloxplayerbeta.exe" in busy(procs=[*RIOT_BACKGROUND, "robloxplayerbeta.exe"], gpu=60.0, renders=None)


def test_a_busy_card_is_busy_even_with_no_known_game():
    """A game not on the list, or anything else that renders, still owns the card."""
    why = busy(procs=RIOT_BACKGROUND, gpu=GPU_BUSY_PERCENT + 1, renders=None)
    assert why and why[0].startswith("gpu")


def test_the_desktop_idle_is_under_the_threshold():
    """Measured on this machine: the desktop with Edge and the Start menu sits at 3-5 %."""
    assert 5.0 < GPU_BUSY_PERCENT


def test_when_nothing_can_be_read_assume_he_is_playing():
    assert busy(procs=None, gpu=None, renders=None)


def test_the_process_check_alone_still_works_when_nvidia_smi_is_missing():
    assert busy(procs=RIOT_BACKGROUND, gpu=None, renders=None) == []
    assert busy(procs=["league of legends.exe"], gpu=None, renders=None) == ["league of legends.exe"]


# The second gate, per process.  The state of 2026-09-24 14:22: the Claude app's GPU process at
# 3D 14 % (plus copy 28 %) and its webview at 8 %, the card at 38 % in total, no game.  The
# global gate said "waiting" and the Replica laps would never have started.
CLAUDE_OPEN = {"claude.exe": 14.0, "msedgewebview2.exe": 8.4}
DESKTOP = ["claude.exe", "msedgewebview2.exe", "explorer.exe", *RIOT_BACKGROUND]


def test_the_claude_app_open_with_no_game_is_idle():
    assert busy(procs=DESKTOP, gpu=38.0, renders=CLAUDE_OPEN) == []


def test_a_known_non_game_drawing_hard_is_still_idle():
    assert busy(procs=DESKTOP, gpu=90.0, renders={"claude.exe": 80.0, "chrome.exe": 40.0}) == []
    assert "dwm.exe" in NOT_GAMES_3D


def test_an_unknown_process_drawing_like_a_game_is_busy():
    why = busy(procs=DESKTOP, gpu=38.0, renders={**CLAUDE_OPEN, "somegame.exe": ENGINE_BUSY_PERCENT + 5})
    assert why == ["somegame.exe 3D 30 %"]


def test_a_listed_game_is_busy_whatever_it_draws():
    assert busy(procs=[*DESKTOP, "league of legends.exe"], gpu=38.0, renders=CLAUDE_OPEN) == ["league of legends.exe"]


def test_counters_that_cannot_be_read_fall_back_to_the_card():
    assert busy(procs=DESKTOP, gpu=38.0, renders=None) == ["gpu 38 %"]


def test_renderers_sums_engines_by_image_name():
    table = {10: "claude.exe", 11: "somegame.exe", 12: "claude.exe"}
    got = renderers(table=table, engines={10: 5.0, 12: 9.0, 11: 0.0, 13: 2.0})
    assert got == {"claude.exe": 14.0, "pid 13": 2.0}
    assert renderers(table=table, engines=None) is None
