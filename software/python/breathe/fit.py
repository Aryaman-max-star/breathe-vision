"""Robust statistics helpers."""
from __future__ import annotations

import numpy as np


def robust_mean(x, min_n: int = 5, floor: float = 0.02):
    """Median/MAD-trimmed mean. Returns (mean, mad, n_kept) or (None, None, 0)."""
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    if len(x) < min_n:
        return None, None, 0
    med = np.median(x)
    mad = 1.4826 * np.median(np.abs(x - med))
    keep = np.abs(x - med) <= max(3 * mad, floor)
    return float(np.mean(x[keep])), float(mad), int(keep.sum())


def robust_line(u, v, w=None, min_n: int = 8):
    """Huber-like line fit v = a + b u with MAD rejection. Returns dict or None."""
    u = np.asarray(u, dtype=float)
    v = np.asarray(v, dtype=float)
    m = np.isfinite(v) & np.isfinite(u)
    if w is not None:
        m &= np.asarray(w) > 0.3
    u, v = u[m], v[m]
    if len(u) < min_n:
        return None
    b, a = np.polyfit(u, v, 1)
    for _ in range(3):
        r = v - (a + b * u)
        mad = 1.4826 * np.median(np.abs(r - np.median(r)))
        keep = np.abs(r) < max(3 * mad, 0.25)
        if keep.sum() < min_n:
            break
        b, a = np.polyfit(u[keep], v[keep], 1)
    return {"a": float(a), "b": float(b), "n": int(keep.sum()), "mad": float(mad)}
