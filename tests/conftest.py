"""A known defect is a decision; a drawer of known defects is a dump.

`xfail(strict=True)` is the right mark for a defect that is understood and not yet fixed:
it forces the mark off the day the fix lands.  What it also does is leave the suite green,
and a suite that says green with four known failures underneath is a failure that cannot be
told apart from health.

So the count is printed where it is read, and it is capped.  Raising `MAX_XFAIL` is a
deliberate act with a reason next to it, which is the point.
"""

from __future__ import annotations

MAX_XFAIL = 1
"""1: `tests/test_apartment_gate.py::test_no_room_is_bigger_than_the_whole_flat` — one pass
fuses two rooms into a 55.8 m² blob on a 51.8 m² flat (bench/results/round18)."""


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    xfailed = terminalreporter.stats.get("xfailed", [])
    if not xfailed:
        return
    n = len(xfailed)
    terminalreporter.write_sep("=", f"{n} known defect{'s' if n != 1 else ''} (xfail), cap {MAX_XFAIL}", yellow=True)
    for rep in xfailed:
        reason = getattr(rep, "wasxfail", "") or ""
        terminalreporter.write_line(f"  {rep.nodeid}{': ' + reason if reason else ''}")
    if n > MAX_XFAIL:
        terminalreporter.write_line(f"  OVER THE CAP OF {MAX_XFAIL}: fix one, or raise MAX_XFAIL in tests/conftest.py with the reason next to it", red=True)


def pytest_sessionfinish(session, exitstatus):
    """Fail the run when the drawer fills up.

    The summary hook prints; only this one changes the exit code, and the difference was
    measured rather than assumed: the first version printed the warning and the suite still
    exited 0.
    """
    reporter = session.config.pluginmanager.get_plugin("terminalreporter")
    if reporter is None:
        return
    if len(reporter.stats.get("xfailed", [])) > MAX_XFAIL:
        session.exitstatus = 1
