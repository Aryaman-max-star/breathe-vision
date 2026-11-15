"""Edge AI on the UNO Q: two Isolation Forests trained on NORMAL scans only."""
from __future__ import annotations

import time
from pathlib import Path

import joblib
import numpy as np
import sklearn
from sklearn.ensemble import IsolationForest
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import RobustScaler


EXPECTED_SCAN_FEATURES = 4      # must match decide.scan_features()


def _mk():
    return make_pipeline(RobustScaler(), IsolationForest(n_estimators=200, contamination="auto", random_state=0))


def _augment(X, noise, copies=6, seed=0):
    """Original samples + jittered copies (realistic harmless variation)."""
    X = np.asarray(X, dtype=float)
    if noise is None:
        return X
    rng = np.random.default_rng(seed)
    noise = np.asarray(noise, dtype=float)[: X.shape[1]]
    jit = [X + rng.normal(0, 1, X.shape) * noise for _ in range(copies)]
    return np.vstack([X] + jit)


def _oof_threshold(X, groups=None, k=5, margin=0.02, noise=None) -> float:
    """Anomaly threshold from out-of-fold scores: score each normal sample with a model that did
    NOT see it. A new scan is flagged only if it is stranger than every one of those."""
    X = np.asarray(X, dtype=float)
    n = len(X)
    if n < 2 * k:
        return -0.15
    ids = np.arange(n) if groups is None else np.asarray(groups)
    uniq = np.unique(ids)
    rng = np.random.default_rng(0)
    rng.shuffle(uniq)
    folds = np.array_split(uniq, k)
    oof = np.empty(n)
    for f in folds:
        test = np.isin(ids, f)
        m = _mk().fit(_augment(X[~test], noise))
        oof[test] = m.decision_function(X[test])
    return float(np.min(oof) - margin)


def train(X_cell, X_scan, path, cell_groups=None, cell_noise=None, scan_noise=None) -> dict:
    X_cell = np.asarray(X_cell, dtype=float)
    X_scan = np.asarray(X_scan, dtype=float)
    t0 = time.perf_counter()
    m = {"cell": _mk().fit(_augment(X_cell, cell_noise)), "scan": _mk().fit(_augment(X_scan, scan_noise)),
         "trained": time.time(), "n_cell": int(len(X_cell)), "n_scan": int(len(X_scan)),
         "n_cell_features": int(X_cell.shape[1]), "n_scan_features": int(X_scan.shape[1]),
         "sklearn": sklearn.__version__}
    m["train_ms"] = round((time.perf_counter() - t0) * 1e3, 1)
    m["thr_cell"] = _oof_threshold(X_cell, cell_groups, noise=cell_noise)
    m["thr_scan"] = _oof_threshold(X_scan, noise=scan_noise)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(m, path)   # only ever load files this board wrote itself
    return m


def load_or_none(path):
    p = Path(path)
    if not p.exists():
        return None
    try:
        m = joblib.load(p)
    except Exception as e:  # noqa: BLE001
        print(f"[model] could not load {p}: {e}")
        return None
    if m.get("sklearn") != sklearn.__version__:
        print("[model] scikit-learn version changed - retrain (finish calibration again)")
        return None
    if m.get("n_scan_features") != EXPECTED_SCAN_FEATURES:
        print("[model] AI inputs changed in this software version - retrain (run the calibration again)")
        return None
    return m


def score(m, x_cells, x_scan):
    t0 = time.perf_counter()
    s_cell = m["cell"].decision_function(np.asarray(x_cells, dtype=float)).tolist() if len(x_cells) else []
    s_scan = float(m["scan"].decision_function(np.asarray([x_scan], dtype=float))[0])
    return [round(x, 4) for x in s_cell], round(s_scan, 4), round((time.perf_counter() - t0) * 1e3, 2)


def thresholds(m) -> tuple[float, float]:
    return m.get("thr_cell", -0.08), m.get("thr_scan", -0.08)
