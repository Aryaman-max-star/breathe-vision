"""End-to-end on synthetic images: geometry fit, baseline, the 0.6 mm cell in every slot."""
import numpy as np
import pytest

from breathe import config, decide, vision
from breathe.thermal import Thermal


@pytest.fixture(scope="module")
def station(tmp_path_factory):
    cfg = config.load(data_dir=tmp_path_factory.mktemp("data"))
    cfg["camera"]["source"] = "synthetic"
    cfg["vision"]["frames"] = 6
    cfg["vision"]["calib_frames"] = 6
    st = vision.make_station(cfg)
    g = st.calibrate_geometry()
    assert g["fit_median_px"] < 1.0
    assert min(g["n_cols"]) >= 30
    for _ in range(8):
        st.sim("reseat")
        assert st.add_baseline()["ok"]
    fb = st.finish_baseline()
    assert fb["ok"] and fb["t_alarm_mm"] >= 0.25
    return st


@pytest.mark.parametrize("slot", [1, 2, 3, 4])
def test_fault_cell_each_slot(station, slot):
    station.sim("fault", slot)
    m = station.scan()
    d = [c["delta_mm"] for c in m["cells"]]
    assert 0.45 < d[slot - 1] < 0.75, d
    others = [x for i, x in enumerate(d) if i != slot - 1]
    assert max(abs(x) for x in others) < 0.12, d          # no perspective cross-talk


def test_rules_reseat_then_swell(station):
    cfg = station.cfg
    th = Thermal()
    for _ in range(25):
        th.update(22.0, 45.0)
    mem = {}
    station.sim("fault", 2)
    r1 = decide.classify(station.scan(), th.snapshot(), cfg, mem)
    assert r1["verdict"] == "RESEAT" and r1["verdict_slots"] == [2]
    station.sim("reseat")
    r2 = decide.classify(station.scan(), th.snapshot(), cfg, mem)
    assert r2["verdict"] == "SWELL" and r2["verdict_slots"] == [2]
    assert r2["bars"][1] >= 6 and r2["beep"] == 3
    station.sim("normal")
    r3 = decide.classify(station.scan(), th.snapshot(), cfg, mem)
    assert r3["verdict"] == "OK", r3["reason"]


def test_station_faults(station):
    cfg = station.cfg
    th = Thermal()
    station.sim("normal")
    station.sim("missing", 3)
    assert decide.classify(station.scan(), th.snapshot(), cfg, {})["verdict"] == "MISSING"
    station.sim("normal")
    station.sim("hand")
    assert decide.classify(station.scan(), th.snapshot(), cfg, {})["verdict"] == "OBSTRUCTED"
    station.sim("normal")
    station.sim("bump")
    assert decide.classify(station.scan(), th.snapshot(), cfg, {})["verdict"] == "CAMERA_MOVED"
    station.sim("normal")


def test_thermal_event(station):
    cfg = station.cfg
    th = Thermal(tau_filter=1.0)
    for i in range(25):
        th.update(22.0, 45.0, t=float(i))
    for i in range(25, 60):
        th.update(34.0, 30.0, t=float(i))
    station.sim("normal")
    r = decide.classify(station.scan(), th.snapshot(), cfg, {})
    assert r["verdict"] == "THERMAL"
    assert "geometry unchanged" in r["reason"]
