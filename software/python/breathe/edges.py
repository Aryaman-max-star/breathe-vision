"""Sub-pixel edge per image column (gradient peak + 3-point parabola)."""
from __future__ import annotations

import numpy as np
from scipy.ndimage import gaussian_filter1d


def column_edges(img: np.ndarray, us: np.ndarray, vc: np.ndarray, band: int):
    """Find the bright-above / dark-below edge in each column.

    img  : averaged grey image (float32, H x W)
    us   : column indices (int)
    vc   : expected edge row per column (float); search vc +/- band
    returns v (sub-pixel rows), conf (0..1), contrast, band_mean
    """
    us = np.asarray(us, dtype=int)
    n = len(us)
    if n == 0:
        z = np.zeros(0)
        return z, z, z, z
    offs = np.arange(-band - 3, band + 4)
    vc = np.nan_to_num(np.asarray(vc, dtype=float), nan=img.shape[0] / 2)
    base = np.round(vc).astype(int)
    rows = np.clip(base[None, :] + offs[:, None], 0, img.shape[0] - 1)
    p = img[rows, us[None, :]].astype(np.float32)
    p = gaussian_filter1d(p, 1.0, axis=0, mode="nearest")
    g = np.full_like(p, -np.inf)
    g[1:-1] = 0.5 * (p[:-2] - p[2:])          # positive for bright above, dark below
    g[:3] = -np.inf
    g[-3:] = -np.inf
    k = np.argmax(g, axis=0)
    i = np.arange(n)
    gm, g0, gp = g[k - 1, i], g[k, i], g[k + 1, i]
    gm = np.where(np.isfinite(gm), gm, g0)
    gp = np.where(np.isfinite(gp), gp, g0)
    den = gm - 2 * g0 + gp
    with np.errstate(divide="ignore", invalid="ignore"):
        delta = np.where(np.abs(den) > 1e-6, 0.5 * (gm - gp) / den, 0.0)
    delta = np.clip(delta, -0.5, 0.5)
    v = rows[0, :] + k + delta

    top = np.median(p[:5], axis=0)
    bot = np.median(p[-5:], axis=0)
    contrast = top - bot
    g2 = g.copy()
    for j in range(-10, 11):                    # a soft (out-of-focus) edge is wide: mask +/-10 px
        kk = np.clip(k + j, 0, g.shape[0] - 1)
        g2[kk, i] = -np.inf
    second = np.maximum(np.max(g2, axis=0), 0.0)
    g0c = np.maximum(g0, 1e-6)
    sharp = np.clip(g0c / np.maximum(0.05 * np.abs(contrast), 1.0), 0, 1)   # tolerates blur up to ~8 px
    uniq = np.clip(1 - second / g0c, 0, 1)
    cfac = np.clip(contrast / 25.0, 0, 1)
    conf = sharp * uniq * cfac
    return v, conf, contrast, p.mean(axis=0)


def coarse_silhouette(img: np.ndarray, r0: int, r1: int):
    """Model-free silhouette for every column: first 50 % crossing scanning down from row r0.

    Used only for the geometry fit. Returns v (nan where not found).
    """
    r0 = max(0, int(r0))
    r1 = min(img.shape[0] - 1, int(r1))
    band = img[r0:r1].astype(np.float32)
    sky = np.median(band[:6], axis=0)
    dark = np.percentile(band, 5)
    thr = 0.5 * (sky + dark)
    below = band < thr[None, :]
    found = below.any(axis=0) & (sky - dark > 25)
    first = np.argmax(below, axis=0)
    cols = np.arange(band.shape[1])
    a = band[np.maximum(first - 1, 0), cols]
    b = band[first, cols]
    with np.errstate(divide="ignore", invalid="ignore"):
        frac = np.where(a - b > 1e-6, (a - thr) / (a - b), 0.5)
    v = r0 + first - 1 + np.clip(frac, 0, 1)
    v = np.where(found & (first > 0), v, np.nan)
    return v


def silhouette_from_below(img: np.ndarray, r_start, r_stop: int):
    """Model-free silhouette for every column: start inside the dark cells/holder (row r_start,
    per column) and walk UP until the image turns bright (the screen). Works whether the lens is
    above or below the cell tops. Returns v (nan where not found)."""
    h, w = img.shape
    r_start = np.clip(np.asarray(r_start, dtype=int), 1, h - 1)
    r_stop = int(max(0, r_stop))
    top = int(min(r_stop, r_start.min()))
    band = img[top:int(r_start.max()) + 1].astype(np.float32)
    hi, lo = np.percentile(band, 95), np.percentile(band, 5)
    thr = 0.5 * (hi + lo)
    v = np.full(w, np.nan)
    if hi - lo < 25:
        return v
    rows = np.arange(top, top + band.shape[0])[:, None]
    valid_row = rows <= r_start[None, :]
    bright = (band > thr) & valid_row
    dark_start = band[np.clip(r_start - top, 0, band.shape[0] - 1), np.arange(w)] < thr
    # last bright row above the dark run that contains r_start
    idx = np.where(bright, rows, -1).max(axis=0)
    ok = dark_start & (idx >= top) & (idx < r_start)
    cols = np.arange(w)
    k = np.clip(idx - top, 0, band.shape[0] - 2)
    a = band[k, cols]
    b = band[k + 1, cols]
    with np.errstate(divide="ignore", invalid="ignore"):
        frac = np.where(a - b > 1e-6, (a - thr) / (a - b), 0.5)
    v = np.where(ok, idx + np.clip(frac, 0, 1), np.nan)
    return v


def abs_edge_1d(profile: np.ndarray, center: float, half: int = 60, min_contrast: float = 20.0,
                polarity: int | None = None):
    """Strongest edge in a 1-D profile near `center`, sub-pixel. None if weak.
    polarity +1 = rising (darker before, brighter after), -1 = falling, None = either.
    Fixing the polarity stops it from jumping to a neighbouring edge of the opposite kind
    (e.g. a bright laptop just outside the screen)."""
    p = gaussian_filter1d(np.asarray(profile, dtype=np.float32), 1.5)
    n = len(p)
    c = int(round(center))
    a, b = max(2, c - half), min(n - 3, c + half)
    if b - a < 10:
        return None
    gs = 0.5 * (p[a + 1:b + 1] - p[a - 1:b - 1])
    g = np.abs(gs) if polarity is None else np.clip(gs * polarity, 0, None)
    k = int(np.argmax(g))
    if g[k] <= 0:
        return None
    i = a + k
    left = float(np.mean(p[max(0, i - 15):max(1, i - 5)]))
    right = float(np.mean(p[min(n - 1, i + 5):min(n, i + 15)]))
    if abs(left - right) < min_contrast:
        return None
    gm, g0, gp = (g[k - 1] if k > 0 else g[k]), g[k], (g[k + 1] if k + 1 < len(g) else g[k])
    den = gm - 2 * g0 + gp
    d = 0.5 * (gm - gp) / den if abs(den) > 1e-6 else 0.0
    return float(i + np.clip(d, -0.5, 0.5))


def edge_polarity(profile: np.ndarray, at: float) -> int:
    """+1 if the profile rises across position `at`, -1 if it falls."""
    p = gaussian_filter1d(np.asarray(profile, dtype=np.float32), 1.5)
    i = int(round(at))
    n = len(p)
    left = float(np.mean(p[max(0, i - 15):max(1, i - 5)]))
    right = float(np.mean(p[min(n - 1, i + 5):min(n, i + 15)]))
    return 1 if right >= left else -1
