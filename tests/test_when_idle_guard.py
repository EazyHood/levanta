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
from when_idle import GPU_BUSY_PERCENT, busy

RIOT_BACKGROUND = ["riotclientservices.exe", "riotclientcrashhandler.exe", "explorer.exe", "msedge.exe"]


def test_riot_in_the_background_with_the_card_idle_is_idle():
    """The state of 2026-09-12 16:08: two Riot services, the card at 5 %, no game.  The old
    guard said waiting; the sweep never ran."""
    assert busy(procs=RIOT_BACKGROUND, gpu=5.0) == []


def test_league_rendering_is_busy():
    assert busy(procs=[*RIOT_BACKGROUND, "league of legends.exe"], gpu=5.0) == ["league of legends.exe"]


def test_roblox_rendering_is_busy():
    assert "robloxplayerbeta.exe" in busy(procs=[*RIOT_BACKGROUND, "robloxplayerbeta.exe"], gpu=60.0)


def test_a_busy_card_is_busy_even_with_no_known_game():
    """A game not on the list, or anything else that renders, still owns the card."""
    why = busy(procs=RIOT_BACKGROUND, gpu=GPU_BUSY_PERCENT + 1)
    assert why and why[0].startswith("gpu")


def test_the_desktop_idle_is_under_the_threshold():
    """Measured on this machine: the desktop with Edge and the Start menu sits at 3-5 %."""
    assert 5.0 < GPU_BUSY_PERCENT


def test_when_nothing_can_be_read_assume_he_is_playing():
    assert busy(procs=None, gpu=None)


def test_the_process_check_alone_still_works_when_nvidia_smi_is_missing():
    assert busy(procs=RIOT_BACKGROUND, gpu=None) == []
    assert busy(procs=["league of legends.exe"], gpu=None) == ["league of legends.exe"]
