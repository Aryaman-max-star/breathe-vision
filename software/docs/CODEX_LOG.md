# Codex log

Write one row per Codex prompt, at the time you use it. Be honest about what was generated where:
the starting code base was written with Claude (Anthropic) from the BREATHE build specification.

| Time | Module | Prompt (short) | Result: accepted / edited / rejected | Tests |
|---|---|---|---|---|
| | | | | |

Ideas that are good Codex tasks during the hackathon:
1. "Add a per-slot left/right tilt plot to the dashboard using the `delta_l_mm`/`delta_r_mm` fields; keep `assets/app.js` dependency-free."
2. "Write `tools/plot_columns.py` that loads `python/data/calibration.json` and the last averaged PNG in `python/data/frames/` and plots each slot's per-column edge vs. baseline (matplotlib), for the Project Hub post."
3. "Add a pytest that renders a 1 mm tilted cell with `breathe.synth` (one side raised) and checks `decide.classify` returns RESEAT."
4. "Add Modulino Pixels support to `sketch/sketch.ino`: show the verdict colour; keep all Bridge rules in AGENTS.md."
