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
- **No GPU in tests.** The MapAnything backend is exercised manually
  (`levanta video`, `levanta reconstruct`); everything else must run on CPU in CI.
- **Public data only** in examples and tests, with its license named.
- Keep functions small and importable on their own; the CLI is a thin wrapper.

## Reporting a bad plan

Run `levanta plan your_cloud.ply -o out --debug-png` and attach `out/plan_debug.png`
together with `out/plan.json`. The PNG shows what the planner saw (line of sight,
wall points, detected lines, rooms) and is usually enough to see what went wrong.
