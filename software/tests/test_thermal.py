from breathe.thermal import Thermal, dew_point


def test_dew_point_25c_60pct():
    assert abs(dew_point(25.0, 60.0) - 16.7) < 0.1


def test_lag_and_slope():
    th = Thermal(tau_filter=1.0, tau_module=300.0)
    for i in range(60):
        th.update(20.0 + 0.05 * i, 50.0, t=float(i))     # +3 C/min ramp
    assert 2.0 < th.slope_c_per_min() < 3.5
    assert th.Ts < th.Ta                                   # surface lags the air
