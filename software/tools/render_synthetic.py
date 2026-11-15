"""Draw the synthetic rig to PNG files so you can see what the camera should see.

    python tools/render_synthetic.py            -> data/frames/synthetic_normal.png, synthetic_fault_slotN.png
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "python"))
import cv2  # noqa: E402
import numpy as np  # noqa: E402

from breathe import config  # noqa: E402
from breathe.synth import render_clean  # noqa: E402

cfg = config.load()
out = Path(cfg["_data_dir"]) / "frames"
n, f = cfg["geometry"]["cell"]["normal_h"], cfg["geometry"]["cell"]["fault_h"]
cv2.imwrite(str(out / "synthetic_normal.png"), np.clip(render_clean(cfg, [n] * 4), 0, 255).astype(np.uint8))
for s in range(4):
    hs = [n] * 4
    hs[s] = f
    cv2.imwrite(str(out / f"synthetic_fault_slot{s + 1}.png"), np.clip(render_clean(cfg, hs), 0, 255).astype(np.uint8))
print("written to", out)
