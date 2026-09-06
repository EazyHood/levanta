# Contributing

Thanks for looking at levanta. The project is MIT-licensed; by contributing you agree
that your contribution is licensed under the same terms and that the original author's
copyright notice stays in place.

## Set up

```bash
git clone https://github.com/EazyHood/levanta
cd levanta
python -m venv .venv && . .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
pytest -q
ruff check src tests
```

## Ground rules

- **Every algorithmic change comes with a control.** The synthetic apartments in
  `tests/synthetic.py` have exact ground truth; the thresholds in
  `tests/test_pipeline_synthetic.py` were fixed before the first run and should only
  move when a change genuinely improves the result. Add a scene if your change targets
  a situation the existing ones do not cover.
- **One planner change per round.** When you touch `src/levanta/plan/`, change *one*
  thing, then run `python bench/planner_bench.py` and keep it only if the table says so.
  Round 4 shipped two changes together, a new scoring in `snap_edges_to_walls` and a
  longer snap reach; the pair helped, so both were kept. Round 6 swept them separately
  and found the scoring was worse or equal on all seven scenes: a useless change had
  been sitting in the planner for two rounds, and it was what broke the published TUM
  example. A bench run over the sum of two changes cannot say which one earned the gain.
  If two are unavoidable, sweep each alone as well.
- **Judge a planner change room by room, not on the total.** The bench prints each room
  against its own truth because a total can be right for two wrong reasons: on the
  Replica flat the total area was +19 % while one room was −73 % and another +161 %.
- **No GPU in tests.** The MapAnything backend is exercised manually
  (`levanta video`, `levanta reconstruct`); everything else must run on CPU in CI.
- **Public data only** in examples and tests, with its license named.
- Keep functions small and importable on their own; the CLI is a thin wrapper.

## Releasing

1. Bump the version in `pyproject.toml`, `src/levanta/__init__.py` and `CITATION.cff`;
   add a section to `CHANGELOG.md`.
2. `python -m build && python -m twine check dist/*` must pass.
3. Tag and push: `git tag v0.2.0 && git push origin v0.2.0`. The `publish` workflow builds
   and uploads to PyPI through Trusted Publishing (one-time setup on pypi.org: add a
   pending publisher for `EazyHood/levanta`, workflow `publish.yml`, environment `pypi`).

## Reporting a bad plan

Run `levanta plan your_cloud.ply -o out --debug-png` and attach `out/plan_debug.png`
together with `out/plan.json`. The PNG shows what the planner saw (line of sight,
wall points, detected lines, rooms) and is usually enough to see what went wrong.
