"""Repeatability table for the Project Hub post, from the scan log.

    python tools/report.py                 -> prints a Markdown table and writes docs/results_table.md
It counts the verdicts and gives per-slot statistics of the relative height.
"""
import glob
import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
rows = []
for f in sorted(glob.glob(str(ROOT / "python" / "data" / "scans" / "*.jsonl"))):
    rows += [json.loads(l) for l in open(f) if l.strip()]
if not rows:
    sys.exit("no scans logged yet")
verdicts = Counter(r["verdict"] for r in rows)
lines = ["# BREATHE Vision - results", "", f"Scans logged: {len(rows)}", "", "| Verdict | Count |", "|---|---|"]
lines += [f"| {k} | {v} |" for k, v in verdicts.most_common()]
lines += ["", "| Slot | OK scans | mean rel (mm) | std rel (mm) | max rel when flagged (mm) | times flagged SWELL |", "|---|---|---|---|---|---|"]
for s in range(4):
    ok = [r["cells"][s]["rel_mm"] for r in rows if r["verdict"] == "OK" and r.get("cells") and r["cells"][s].get("rel_mm") is not None]
    sw = [r["cells"][s]["rel_mm"] for r in rows if r["verdict"] == "SWELL" and s + 1 in r.get("verdict_slots", [])]
    lines.append(f"| {s + 1} | {len(ok)} | {np.mean(ok) if ok else float('nan'):.3f} | {np.std(ok) if ok else float('nan'):.3f} | "
                 f"{max(sw) if sw else float('nan'):.3f} | {len(sw)} |")
t = [r["t_alarm_mm"] for r in rows if r.get("t_alarm_mm")]
lines += ["", f"Alarm threshold used: {t[-1] if t else 'n/a'} mm"]
text = "\n".join(lines)
print(text)
(ROOT / "docs" / "results_table.md").write_text(text + "\n")
