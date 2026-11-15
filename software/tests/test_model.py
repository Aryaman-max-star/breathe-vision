import numpy as np

from breathe import model


def test_if_roundtrip(tmp_path):
    rng = np.random.default_rng(0)
    Xc = rng.normal(0, 0.03, (120, 6))
    Xs = rng.normal(0, 0.03, (30, 9))
    p = tmp_path / "if.joblib"
    model.train(Xc, Xs, p)
    m = model.load_or_none(p)
    sc, ss, ms = model.score(m, [[0.6, 0.6, 0, 0, 1, 0]], [0.0] * 9)
    assert sc[0] < 0             # a 0.6 mm cell is an outlier for the normal-only model
    assert ms < 1000
