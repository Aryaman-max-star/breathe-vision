import numpy as np
from scipy.special import erf

from breathe.edges import column_edges


def test_subpixel_edge_on_erf():
    rng = np.random.default_rng(1)
    H, W = 200, 50
    true = 100.0 + np.linspace(-0.5, 0.5, W)
    rows = np.arange(H)[:, None]
    img = 220 - 180 * 0.5 * (1 + erf((rows - true[None, :]) / (1.5 * np.sqrt(2))))
    img = img + rng.normal(0, 0.5, img.shape)
    v, conf, contrast, _ = column_edges(img.astype(np.float32), np.arange(W), np.full(W, 104.0), 20)
    assert np.max(np.abs(v - true)) < 0.1
    assert np.median(conf) > 0.8
