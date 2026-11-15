"""Rig variants: screen edges as the camera-moved reference, lens below/near the tops, optional fiducials."""
import copy

from breathe import config, vision
from breathe.synth import SyntheticCamera


def _station(tmp_path, mutate_true=None, mutate_cfg=None):
    cfg = config.load(data_dir=tmp_path)
    cfg["camera"]["source"] = "synthetic"
    cfg["vision"]["frames"] = 6
    cfg["vision"]["calib_frames"] = 6
    true_cfg = copy.deepcopy(cfg)
    if mutate_true:
        mutate_true(true_cfg)
    if mutate_cfg:
        mutate_cfg(cfg)
    return vision.Station(cfg, cam=SyntheticCamera(true_cfg)).open()


def test_screen_edges_detect_camera_bump(tmp_path):
    # the BREATHE foundation has no stuck-on squares: the orange screen's edges are the reference
    st = _station(tmp_path)
    g = st.calibrate_geometry()
    assert g["fiducials"] is None and g["screen_ref"] is not None
    for _ in range(3):
        st.add_baseline()
    st.finish_baseline()
    assert st.scan()["fiducial_shift_px"] < 0.5
    st.cam.set_fiducial_shift(3.0, 2.0)          # moves everything on the screen plane = camera bumped
    assert st.scan()["fiducial_shift_px"] > 1.0


def test_optional_fiducials_found_anywhere(tmp_path):
    # if you do add two dark squares, they are found even 20 mm away from where station.yaml says
    def move(c):
        c["geometry"]["fiducials_xz"] = [[45.0, 68.0], [135.0, 68.0]]

    def declare(c):
        c["geometry"]["fiducials_xz"] = [[30.0, 62.0], [150.0, 62.0]]
    st = _station(tmp_path, mutate_true=move, mutate_cfg=declare)
    g = st.calibrate_geometry()
    assert g["fiducials"] is not None
    for _ in range(3):
        st.add_baseline()
    st.finish_baseline()
    assert st.scan()["fiducial_shift_px"] < 0.5          # camera still -> no alarm
    st.cam.set_fiducial_shift(3.0, 2.0)                  # camera bumped
    assert st.scan()["fiducial_shift_px"] > 1.0


def test_no_shim_lens_at_46_6(tmp_path):
    # lens only 1.0 mm above the normal tops; terminals stick up above the lens
    def low(c):
        c["geometry"]["lens_xyz_mm"] = [90.0, 32.0, 46.6]
        c["synthetic"]["true_camera_offset"] = {"cx": 10.0, "cy": -5.0, "Yc": -5.0}
    st = _station(tmp_path, mutate_true=low, mutate_cfg=low)
    g = st.calibrate_geometry()
    assert g["fit_median_px"] < 1.0 and min(g["n_cols"]) >= 20
    for _ in range(6):
        st.cam.reseat()
        st.add_baseline()
    st.finish_baseline()
    for slot in (1, 3):
        hs = [42.0] * 4
        hs[slot - 1] = 42.6
        st.cam.set_heights(hs)
        d = [c["delta_mm"] for c in st.scan()["cells"]]
        assert 0.45 < d[slot - 1] < 0.75, d
        assert max(abs(x) for i, x in enumerate(d) if i != slot - 1) < 0.12, d


def test_lens_below_cell_tops(tmp_path):
    # the Arduino camera on the C920 stand may sit lower: lens at z = 38, below the 45.6 mm tops.
    # The silhouette is then the cells' FRONT top edge - still measured correctly.
    def low(c):
        c["geometry"]["lens_xyz_mm"] = [90.0, 32.0, 38.0]
        c["synthetic"]["true_camera_offset"] = {"cx": -15.0, "cy": 10.0, "Yc": -4.0, "roll": -0.003}

    def guess(c):
        c["geometry"]["lens_xyz_mm"] = [90.0, 32.0, 49.0]   # user's wrong guess; the fit must find "below"
    st = _station(tmp_path, mutate_true=low, mutate_cfg=guess)
    g = st.calibrate_geometry()
    assert g["lens_vs_tops"] == "below", g
    assert g["fit_median_px"] < 1.0 and min(g["n_cols"]) >= 20, g
    for _ in range(6):
        st.cam.reseat()
        st.add_baseline()
    st.finish_baseline()
    for slot in (2, 4):
        hs = [42.0] * 4
        hs[slot - 1] = 42.6
        st.cam.set_heights(hs)
        d = [c["delta_mm"] for c in st.scan()["cells"]]
        assert 0.45 < d[slot - 1] < 0.75, d
        assert max(abs(x) for i, x in enumerate(d) if i != slot - 1) < 0.12, d


def test_free_standing_camera_offset_and_turned(tmp_path):
    # camera on its own base: 15 mm to the right of the centre line, turned 5 deg back towards the cells
    import math

    def place(c):
        c["synthetic"]["true_camera_offset"] = {"Xc": 15.0, "yaw": math.radians(-5.0), "Yc": 8.0, "Zc": 0.8, "roll": -0.004}
    st = _station(tmp_path, mutate_true=place)
    g = st.calibrate_geometry()
    assert g["fit_median_px"] < 1.0 and min(g["n_cols"]) >= 15, g
    for _ in range(6):
        st.cam.reseat()
        st.add_baseline()
    st.finish_baseline()
    for slot in (1, 2, 3, 4):
        hs = [42.0] * 4
        hs[slot - 1] = 42.6
        st.cam.set_heights(hs)
        d = [c["delta_mm"] for c in st.scan()["cells"]]
        assert 0.45 < d[slot - 1] < 0.75, (slot, d)
        assert max(abs(x) for i, x in enumerate(d) if i != slot - 1) < 0.12, (slot, d)
