"""The measuring station: calibration + scans.

Station        - runs the camera in this process (App Lab app, or vision_service.py)
RemoteStation  - same methods, but forwards them over HTTP to vision_service.py (plan a')
make_station() - picks one according to camera.source in station.yaml
"""
from __future__ import annotations

import base64
import collections
import json
import math
import threading
import time
import urllib.request
import uuid
from pathlib import Path

import cv2
import numpy as np
from scipy.optimize import least_squares

from . import camera as camera_mod
from .edges import abs_edge_1d, column_edges, edge_polarity, silhouette_from_below
from .fit import robust_mean
from .geometry import CamParams, Scene, silhouette, usable_columns


def _f(x):
    """numpy -> plain python for JSON."""
    if x is None:
        return None
    if isinstance(x, (np.floating, float)):
        return None if not math.isfinite(float(x)) else round(float(x), 5)
    if isinstance(x, (np.integer,)):
        return int(x)
    return x


class Station:
    def __init__(self, cfg: dict, cam=None):
        self.cfg = cfg
        self.W, self.H = cfg["camera"]["width"], cfg["camera"]["height"]
        self.scene = Scene(cfg["geometry"])
        self.vcfg = cfg["vision"]
        self.data = Path(cfg["_data_dir"])
        self.calib_path = self.data / "calibration.json"
        self.base_path = self.data / "baseline_raw.json"
        self.fov_path = self.data / "camera_fov.json"
        self.fov_measured = None
        if self.fov_path.exists():                   # this camera's real field of view, measured on the rig
            try:
                self.fov_measured = float(json.loads(self.fov_path.read_text())["hfov_deg"])
                cfg["camera"]["hfov_deg"] = self.fov_measured
            except Exception:  # noqa: BLE001
                self.fov_measured = None
        self.lock = threading.RLock()
        self.cam = cam
        self.error = None
        self.calib = self._load_calib()
        self.baseline_raws: list[dict] = self._load_baseline_raws()
        self.last_img = None
        self.last_raw = None
        self.last_meas = None
        self._snap_cache = None

    # ------------------------------------------------------------------ setup
    def open(self):
        if self.cam is None:
            src = self.cfg["camera"].get("source", "auto")
            if src == "synthetic":
                from .synth import SyntheticCamera
                self.cam = SyntheticCamera(self.cfg)
            else:
                self.cam = camera_mod.V4L2Camera(self.cfg)
        self.cam.open()
        self.W, self.H = self.cfg["camera"]["width"], self.cfg["camera"]["height"]
        if self.calib and self.calib.get("focus") is not None:
            self.cam.apply_controls(focus=self.calib["focus"])
        return self

    @property
    def mode(self):
        return "synthetic" if getattr(self.cam, "is_synthetic", False) else "camera"

    def _load_calib(self):
        if not self.calib_path.exists():
            return None
        c = json.loads(self.calib_path.read_text())
        for s in c["slots"]:
            for k in ("cols", "depth", "x_edge", "v_model", "v_base", "left", "kind"):
                if s.get(k) is not None:
                    s[k] = np.asarray(s[k])
            s["cols"] = s["cols"].astype(int)
            s["left"] = s["left"].astype(bool)
        c["cam"] = CamParams.from_dict(c["cam"])
        # a calibration made at another resolution (e.g. the earlier 4K setting) is useless now: ignore it
        res = c.get("resolution")
        if (res and list(res) != [self.W, self.H]) or (not res and abs(c["cam"].cx - self.W / 2) > 0.25 * self.W):
            print("[vision] saved calibration is for a different camera resolution - ignored; run the calibration again")
            return None
        return c

    def _save_calib(self):
        c = dict(self.calib)
        c["cam"] = self.calib["cam"].to_dict()
        c["slots"] = []
        for s in self.calib["slots"]:
            d = {}
            for k, v in s.items():
                d[k] = v.tolist() if isinstance(v, np.ndarray) else v
            c["slots"].append(d)
        self.calib_path.write_text(json.dumps(c))

    def _load_baseline_raws(self):
        if not self.base_path.exists():
            return []
        out = []
        for r in json.loads(self.base_path.read_text()):
            out.append(self._raw_from_json(r))
        return out

    def _save_baseline_raws(self):
        self.base_path.write_text(json.dumps([self._raw_to_json(r) for r in self.baseline_raws]))

    @staticmethod
    def _raw_to_json(r):
        return {k: (v.tolist() if isinstance(v, np.ndarray) else
                    [{kk: (vv.tolist() if isinstance(vv, np.ndarray) else vv) for kk, vv in s.items()} for s in v]
                    if k == "slots" else v) for k, v in r.items()}

    @staticmethod
    def _raw_from_json(r):
        r = dict(r)
        r["slots"] = [{k: (np.asarray(v, dtype=float) if isinstance(v, list) else v) for k, v in s.items()}
                      for s in r["slots"]]
        return r

    # ------------------------------------------------------------- utilities
    def _avg(self, n=None):
        n = n or self.vcfg["frames"]
        return camera_mod.grab_average(self.cam, n)

    def status(self) -> dict:
        c = self.calib
        return {
            "mode": self.mode,
            "device": getattr(self.cam, "device", None),
            "error": self.error,
            "geometry_ok": bool(c),
            "baseline_n_pending": len(self.baseline_raws),
            "baseline_ok": bool(c and c.get("baseline_n")),
            "calib_id": c.get("id") if c else None,
            "fit_rms_px": c.get("fit_rms_px") if c else None,
            "fit_median_px": c.get("fit_median_px") if c else None,
            "t_alarm_mm": c.get("t_alarm") if c else None,
            "t_watch_mm": c.get("t_watch") if c else None,
            "sigma_rel_mm": c.get("sigma_rel_mm") if c else None,
            "k_scale": [s.get("k_scale", 1.0) for s in c["slots"]] if c else None,
            "k_measured": [s.get("k_measured", False) for s in c["slots"]] if c else None,
            "n_cols": [int(len(s["cols"])) for s in c["slots"]] if c else None,
            "focus": c.get("focus") if c else None,
            "fiducials": bool(c and (c.get("fiducials") or c.get("screen_ref"))),
            "lens_vs_tops": (("above" if c["cam"].Zc > self.scene.z0 + self.scene.normal_h else "below") if c else None),
            "sky_ref": round(c["sky_ref"], 1) if c and c.get("sky_ref") else None,
            "resolution": [self.W, self.H],
            "controls": getattr(self.cam, "applied", None),
            "camera_reconnects": getattr(self.cam, "reconnects", 0),
            "hfov_deg": self.cfg["camera"].get("hfov_deg"),
            "fov_measured": self.fov_measured,
            "camera_error": getattr(self.cam, "last_error", None),
        }

    # ---------------------------------------------------------- geometry fit
    def _model_v(self, cam: CamParams, us):
        boxes = self.scene.boxes([self.scene.normal_h] * self.scene.n)
        v, idx, _, _ = silhouette(cam, boxes, us)
        kinds = np.array([b.kind for b in boxes] + ["none"])
        k = kinds[np.where(idx >= 0, idx, len(boxes))]
        return np.where(np.isin(k, ["cell", "terminal"]), v, np.nan)

    def _fit_camera(self, img):
        cam0 = CamParams.default(self.cfg)
        top = self.scene.z0 + self.scene.normal_h
        us_all = np.arange(self.W, dtype=float)
        # start each column inside the dark holder/cells (z = 18 mm at the cells' front) and walk up
        d_front = self.scene.y0 - cam0.Yc
        r_start = cam0.cy + cam0.f * (cam0.Zc - 18.0) / d_front + np.zeros(self.W)
        r_stop = cam0.cy - cam0.f * (self.scene.screen["z1"] - 4.0 - cam0.Zc) / (self.scene.screen["y"] - cam0.Yc)
        meas = silhouette_from_below(img, np.minimum(r_start, self.H - 2), int(r_stop))
        step = max(2, self.W // 1000)                       # ~1000 columns, also at 4K
        us = np.arange(0, self.W, step, dtype=float)
        meas_s = meas[us.astype(int)]
        prior = CamParams(**cam0.to_dict())                 # where station.yaml says the camera is
        # 1) coarse search on a grid (cx, then f and lens distance Yc); vertical offset by median
        def score(cam):
            mv = self._model_v(cam, us)
            m = np.isfinite(mv)
            if m.sum() < 50:
                return None
            diff = meas_s[m] - mv[m]
            ok = np.isfinite(diff)
            if ok.sum() < 50:
                return None
            dcy = float(np.median(diff[ok]))
            err = np.where(ok, np.minimum(np.abs(diff - dcy), 10.0), 10.0)
            return float(np.mean(err)), dcy

        z_cands = sorted({round(cam0.Zc, 2)} | {round(top + d, 2) for d in (-12, -9, -6, -4, -2.5, 2.5, 4, 6, 9)})
        # the camera stands on its own: it can be a bit to the side and turned. Start by assuming it
        # points at the middle of the holder, then search the turn angle (yaw) for every lens height.
        hold_y = 0.5 * (self.scene.y0 + self.scene.y1)
        yaw0 = math.atan2(90.0 - cam0.Xc, hold_y - cam0.Yc)
        yaws = yaw0 + np.radians(np.arange(-15.0, 15.01, 0.2))
        us3 = us[::2]
        meas3 = meas_s[::2]

        def score3(cam):
            mv = self._model_v(cam, us3)
            m = np.isfinite(mv)
            if m.sum() < 30:
                return None
            diff = meas3[m] - mv[m]
            ok = np.isfinite(diff)
            if ok.sum() < 30:
                return None
            dcy = float(np.median(diff[ok]))
            return float(np.mean(np.where(ok, np.minimum(np.abs(diff - dcy), 10.0), 10.0))), dcy

        # stage 1: lens height x lens distance x turn, on every 2nd column (cheap)
        cands = []
        for zc in z_cands:
            for dy in (-24.0, -16.0, -8.0, 0.0, 8.0, 16.0, 24.0):
                yc = cam0.Yc + dy
                y0 = math.atan2(90.0 - cam0.Xc, hold_y - yc)
                best_c = None
                for yw in y0 + np.radians(np.arange(-15.0, 15.01, 0.25)):
                    cam = CamParams(**{**cam0.to_dict(), "Zc": zc, "Yc": yc, "yaw": float(yw)})
                    sc = score3(cam)
                    if sc:
                        s_pen = sc[0] + 0.02 * ((zc - prior.Zc) / 3.0) ** 2   # gentle pull to the configured height
                        if best_c is None or s_pen < best_c[0]:
                            best_c = (s_pen, cam, sc[1])
                if best_c:
                    cands.append(best_c)
        if not cands:
            raise RuntimeError("Could not see the cells. Check lighting, camera aim and that the cells are in place.")
        cands.sort(key=lambda c: c[0])
        # stage 2: sideways offset + small turn around the 3 best, then least squares from each
        results = []
        for sc0, camc, dcy in cands[:3]:
            camz = CamParams(**{**camc.to_dict(), "cy": camc.cy + dcy})
            best = (sc0, camz)
            for dy in (-4.0, 0.0, 4.0):
                for dx in (-16.0, -8.0, 0.0, 8.0, 16.0):
                    for dyaw in np.radians([-0.25, 0.0, 0.25]):
                        cand = CamParams(**{**camz.to_dict(), "Yc": camz.Yc + dy, "Xc": camz.Xc + dx})
                        cand.yaw = camz.yaw + dyaw + (math.atan2(90.0 - cand.Xc, hold_y - cand.Yc) -
                                                      math.atan2(90.0 - camz.Xc, hold_y - camz.Yc))
                        sc = score(cand)
                        if sc and sc[0] < best[0]:
                            cand.cy = cand.cy + sc[1]
                            best = (sc[0], cand)
            results.append(self._refine(best[1], us, meas_s, top, prior))
        cam, rms, med = min(results, key=lambda r: r[2])
        return cam, rms, med, meas

    def _refine(self, cam1: CamParams, us, meas_s, top, prior: CamParams | None = None):
        """Least-squares polish of cy, lens height/distance/sideways position, yaw, roll and focal length.
        cx stays fixed (degenerate with yaw).
        From 20 cm away, 'higher + further sideways + turned more' looks almost the same as the true
        pose, so weak priors (where station.yaml says the camera is) pick the physically right one.
        They barely matter for the measurement itself, but they make the reported lens height reliable."""
        prior = prior or cam1
        hold_y = 0.5 * (self.scene.y0 + self.scene.y1)
        yaw_aim = math.atan2(90.0 - prior.Xc, hold_y - prior.Yc)
        sig = np.array([10.0, 5.0, 15.0, math.radians(6.0)])          # Xc, Zc, Yc (mm), yaw (rad)
        w_prior = 2.0                                                  # 1 sigma off = 2 px of residual
        use = np.isfinite(self._model_v(cam1, us)) & np.isfinite(meas_s)
        uu, mm = us[use], meas_s[use]
        above = cam1.Zc > top              # lens above or below the cell tops: stay on that side

        f_nom = prior.f

        def mk(p):
            return CamParams(cam1.cx, p[0], p[6], p[3], p[2], p[1], p[5], p[4])

        def res_img(p):
            r = mm - self._model_v(mk(p), uu)
            return np.where(np.isfinite(r), r, 20.0)

        def res(p):
            pri = (np.array([p[3], p[1], p[2], p[4]]) - np.array([prior.Xc, prior.Zc, prior.Yc, yaw_aim])) / sig
            pri_f = (p[6] / f_nom - 1.0) / 0.05                          # focal length: datasheet +/- 5 %
            return np.concatenate([res_img(p), w_prior * pri, [w_prior * pri_f]])

        p0 = np.array([cam1.cy, cam1.Zc, cam1.Yc, cam1.Xc, cam1.yaw, 0.0, cam1.f])
        lb = np.array([p0[0] - 40, top + 0.25 if above else top - 25.0, p0[2] - 15, p0[3] - 12, p0[4] - 0.08, -0.05, f_nom * 0.88])
        ub = np.array([p0[0] + 40, top + 15.0 if above else top - 0.25, p0[2] + 15, p0[3] + 12, p0[4] + 0.08, 0.05, f_nom * 1.12])
        p0 = np.clip(p0, lb + 1e-6, ub - 1e-6)
        sol = least_squares(res, p0, bounds=(lb, ub), loss="soft_l1", f_scale=0.5,
                            x_scale=[5, 0.3, 2, 1, 0.002, 0.002, 10], diff_step=1e-3, max_nfev=600)
        cam = mk(sol.x)
        r = res_img(sol.x)
        rms = float(np.sqrt(np.mean(np.minimum(np.abs(r), 20.0) ** 2)))
        med = float(np.median(np.abs(r)))
        return cam, rms, med

    def _screen_ref(self, img, cam: CamParams, base: dict | None = None, seed: dict | None = None):
        """Left, right and top edge of the printed screen = camera-moved reference (no stickers).
        At calibration (no base): start from `seed` (the cell-anchored screen edges) and remember which
        way each edge goes (dark->bright or bright->dark). Later: search only close to the remembered
        edge and with the same direction, so a laptop/projection edge next to the screen is ignored."""
        scr = self.scene.screen
        ya = scr["y"]
        if base is None and seed and seed.get("band"):
            r0, r1 = seed["band"]
        else:
            zt = self.scene.z0 + self.scene.normal_h + self.scene.th + 5.0
            zb = scr["z1"] - 6.0
            r0 = int(np.clip(cam.project(90.0, ya, zb)[1], 0, self.H - 1))
            r1 = int(np.clip(cam.project(90.0, ya, zt)[1], 0, self.H - 1))
        if base is not None and base.get("band"):
            r0, r1 = base["band"]
        half = int(1.3 * self._motion_max_px() + 8) if base else 90
        out = {"band_v": 0.5 * (r0 + r1), "band": [int(r0), int(r1)]}
        if r1 - r0 >= 8:
            prof = img[r0:r1].mean(axis=0)
            for key, x in (("left", scr["x0"]), ("right", scr["x1"])):
                if base and base.get(key) is not None:
                    pred, pol = base[key], base.get("pol_" + key)
                elif seed and seed.get("u" + key[0].upper()) is not None:
                    pred, pol = seed["u" + key[0].upper()], None
                else:
                    pred, pol = cam.project(x, ya, scr["z1"] - 15.0)[0], None
                u = abs_edge_1d(prof, pred, half=half if base else 25 if seed else 90, polarity=pol)
                out[key] = u
                if u is not None:
                    out["pol_" + key] = pol if pol is not None else edge_polarity(prof, u)
            # the same side edges in the upper and the lower half of the band: their lean = camera roll
            rm = (r0 + r1) // 2
            out["v_hi"], out["v_lo"] = 0.5 * (r0 + rm), 0.5 * (rm + r1)
            for key in ("left", "right"):
                if out.get(key) is None:
                    continue
                pol = out.get("pol_" + key)
                out[key + "_hi"] = abs_edge_1d(img[r0:rm].mean(axis=0), out[key], half=12, polarity=pol)
                out[key + "_lo"] = abs_edge_1d(img[rm:r1].mean(axis=0), out[key], half=12, polarity=pol)
        # screen top at three places (left, middle, right of the screen); a bright projection or a person
        # behind one of them can spoil it, so the motion estimate uses the ones that agree
        L = out.get("left") if out.get("left") is not None else (base or {}).get("left")
        Rr = out.get("right") if out.get("right") is not None else (base or {}).get("right")
        for key, frac in (("top_l", 0.25), ("top_c", 0.5), ("top_r", 0.75)):
            if base and base.get(key + "_u") is not None:
                u = base[key + "_u"]
            elif L is not None and Rr is not None:
                u = L + frac * (Rr - L)
            else:
                u = cam.project(scr["x0"] + frac * (scr["x1"] - scr["x0"]), ya, scr["z1"])[0]
            c0, c1 = int(np.clip(u - 40, 0, self.W - 1)), int(np.clip(u + 40, 0, self.W - 1))
            col = img[:, c0:c1].mean(axis=1) if c1 - c0 > 10 else None
            if col is None:
                out[key] = None
            elif base and base.get(key) is not None:
                out[key] = abs_edge_1d(col, base[key], half=half, polarity=base.get("pol_" + key))
            else:
                # from inside the screen (the band) walk up until the screen ends, then refine there
                level = float(np.median(col[r0:r1])) if r1 > r0 else float(col[r0])
                lowv = float(np.percentile(col[:max(r0, 2)], 10))
                vt = None
                if level - lowv > 20:
                    thr_t = 0.5 * (level + lowv)
                    k = r0
                    while k > 1 and col[k] >= thr_t:
                        k -= 1
                    if k > 1:
                        vt = abs_edge_1d(col, k, half=8, min_contrast=15)
                out[key] = vt
            if out.get(key) is not None and not (base and base.get("pol_" + key) is not None):
                out["pol_" + key] = edge_polarity(col, out[key])
            elif base and base.get("pol_" + key) is not None:
                out["pol_" + key] = base["pol_" + key]
            out[key + "_u"] = u
        return out if any(out.get(k) is not None for k in ("left", "right", "top_l", "top_c", "top_r")) else None

    def _find_fiducials(self, img, cam: CamParams):
        """OPTIONAL: two dark squares on the screen (only if fiducials_xz is set in station.yaml).
        Found by searching the bright area above the cells for two compact dark blobs."""
        if not self.scene.fiducials:
            return None
        # always the blob search: a plain dark-pixel centroid near the expected place could grab the
        # dark room beyond the screen edge
        return self._find_fiducial_blobs(img, cam)

    def _find_fiducial_blobs(self, img, cam: CamParams):
        mv = self._model_v(cam, np.arange(self.W, dtype=float))
        if not np.isfinite(mv).any():
            return None
        r1 = int(np.nanmin(mv) - 40)              # stay well above the cells and terminals
        if r1 < 40:
            return None
        band = img[:r1].astype(np.float32)
        sky = float(np.percentile(band, 90))
        mask = (band < 0.5 * sky).astype(np.uint8)
        n, lab, stats, cents = cv2.connectedComponentsWithStats(mask, 8)
        cands = []
        for i in range(1, n):
            x, y, w, h, a = stats[i]
            if a < 80 or a > 40000 or x == 0 or y == 0 or x + w >= self.W or y + h >= r1:
                continue
            if not 0.5 < w / max(h, 1) < 2.0 or a < 0.6 * w * h:      # roughly a filled square
                continue
            cands.append((a, cents[i][0], cents[i][1]))
        left = [c for c in cands if c[1] < cam.cx]
        right = [c for c in cands if c[1] >= cam.cx]
        if not left or not right:
            return None
        l, r = max(left), max(right)
        out = []
        for _, u, v in (l, r):
            c = self._centroid(img, u, v, 40)
            if c is None:
                return None
            out.append(c)
        return out

    @staticmethod
    def _centroid(img, u, v, r):
        h, w = img.shape
        x0, x1 = int(max(0, u - r)), int(min(w, u + r))
        y0, y1 = int(max(0, v - r)), int(min(h, v + r))
        if x1 - x0 < 10 or y1 - y0 < 10:
            return None
        p = img[y0:y1, x0:x1].astype(np.float32)
        sky, mn = np.percentile(p, 90), p.min()
        if sky - mn < 60:
            return None
        wgt = np.clip(0.5 * (sky + mn) - p, 0, None)
        if wgt.sum() <= 0:
            return None
        ys, xs = np.mgrid[y0:y1, x0:x1]
        return [float((wgt * xs).sum() / wgt.sum()), float((wgt * ys).sum() / wgt.sum())]

    def calibrate_geometry(self) -> dict:
        """Step 1 of calibration: four NORMAL cells in place, clean view."""
        with self.lock:
            img = self._avg(self.vcfg.get("calib_frames", 60))
            cam, rms, med, meas = self._fit_camera(img)
            slots = usable_columns(cam, self.scene, self.W, self.vcfg)
            for s in slots:
                s["k_scale"] = 1.0
                s["k_measured"] = False
            fids = self._find_fiducials(img, cam)
            old_focus = self.calib.get("focus") if self.calib else None
            self.calib = {
                "id": "cal-" + time.strftime("%Y%m%d-%H%M%S"),
                "created": time.time(),
                "cam": cam,
                "fit_rms_px": round(rms, 3),
                "fit_median_px": round(med, 3),
                "slots": slots,
                "fiducials": fids,
                "focus": old_focus,
                "baseline_n": 0,
                "resolution": [self.W, self.H],
            }
            self.calib["sky_ref"] = self._sky_stats(img)[0]
            self.calib["placement_ref"] = self._placement_features(img, cam)
            self.calib["screen_ref"] = self._screen_ref(img, cam, seed=self.calib["placement_ref"])
            self.baseline_raws = []
            self._save_baseline_raws()
            self._save_calib()
            self.last_img = img
            self._save_overlay(img, meas)
            warn = []
            if med > self.vcfg.get("max_fit_median_px", 1.0):
                warn.append(f"fit error {med:.2f} px is high: check data/frames/calib_overlay.png")
            top = self.scene.z0 + self.scene.normal_h
            if top - 1.5 < cam.Zc < top + self.scene.fault_h - self.scene.normal_h + 1.5:
                warn.append(f"lens centre found at z = {cam.Zc:.1f} mm, too close to the cell tops ({top:.1f} mm): "
                            "raise the camera to z >= 48 or lower it to z <= 44 (GUIDE Part 10.2)")
            if fids is None and not self.calib.get("screen_ref"):
                warn.append("screen edges not found: camera-moved check disabled (is the whole screen width in view?)")
            for s in slots:
                if len(s["cols"]) < 20:
                    warn.append(f"slot {s['slot']}: only {len(s['cols'])} usable columns")
            return {"ok": True, "fit_rms_px": round(rms, 3), "fit_median_px": round(med, 3), "cam": cam.to_dict(),
                    "lens_vs_tops": "above" if cam.Zc > self.scene.z0 + self.scene.normal_h else "below",
                    "n_cols": [int(len(s["cols"])) for s in slots], "fiducials": fids,
                    "screen_ref": self.calib["screen_ref"],
                    "sky_ref": round(self.calib["sky_ref"], 1), "warnings": warn}

    def _save_overlay(self, img, meas=None):
        cam = self.calib["cam"]
        vis = cv2.cvtColor(np.clip(img, 0, 255).astype(np.uint8), cv2.COLOR_GRAY2BGR)
        us = np.arange(self.W, dtype=float)
        mv = self._model_v(cam, us)
        for u in range(0, self.W, 2):
            if np.isfinite(mv[u]):
                cv2.circle(vis, (u, int(round(mv[u]))), 1, (0, 0, 255), -1)       # red = model
            if meas is not None and np.isfinite(meas[u]):
                cv2.circle(vis, (u, int(round(meas[u]))), 1, (255, 128, 0), -1)  # blue = seen
        for s in self.calib["slots"]:
            for u, v in zip(s["cols"], s["v_model"]):
                cv2.circle(vis, (int(u), int(round(v)) + 6), 1, (0, 200, 0), -1)  # green = used
            cv2.putText(vis, f"S{s['slot']}", (int(s["u_center"]) - 15, int(cam.cy) + 140),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 2)
        if self.calib.get("fiducials"):
            for fu, fv in self.calib["fiducials"]:
                cv2.drawMarker(vis, (int(fu), int(fv)), (0, 0, 255), cv2.MARKER_CROSS, 40, 2)
        sr = self.calib.get("screen_ref") or {}
        for k in ("left", "right"):
            if sr.get(k) is not None:
                cv2.line(vis, (int(sr[k]), 0), (int(sr[k]), self.H - 1), (255, 0, 255), 1)       # magenta = screen sides
        for k in ("top_l", "top_r"):
            if sr.get(k) is not None:
                u = int(sr[k + "_u"])
                cv2.line(vis, (u - 60, int(sr[k])), (u + 60, int(sr[k])), (255, 0, 255), 2)   # magenta = screen top
        cv2.imwrite(str(self.data / "frames" / "calib_overlay.png"), vis)

    # ------------------------------------------------------ camera placement
    def _target_cam(self) -> CamParams:
        """The optimal camera pose from station.yaml (pointing at the middle of the holder)."""
        cam = CamParams.default(self.cfg)
        cam.yaw = math.atan2(90.0 - cam.Xc, 0.5 * (self.scene.y0 + self.scene.y1) - cam.Yc)
        return cam

    def _placement_features(self, img, cam: CamParams):
        """Where the screen and the cell tops appear, anchored on the CELLS: the camera points at
        them, and the screen is by definition the bright area right above them. So bright things
        elsewhere (a laptop beside the screen, a projection, people behind it) can't be mistaken
        for the screen. Returns a dict, or {'error': text}."""
        H, W = img.shape
        # 1. the cell block: the lowest long dark stretch in the middle columns; its top = cell tops
        mid = np.median(img[:, int(0.42 * W):int(0.58 * W)], axis=1)
        lo_v, hi_v = np.percentile(mid, 5), np.percentile(mid, 95)
        if hi_v - lo_v < 25:
            return {"error": "I can't see the cells against the orange screen. Point the camera at the cells."}
        thr_v = 0.5 * (lo_v + hi_v)
        dark = mid < thr_v
        runs, a0 = [], None
        for i, d in enumerate(np.append(dark, False)):
            if d and a0 is None:
                a0 = i
            elif not d and a0 is not None:
                runs.append((a0, i - 1))
                a0 = None
        cells = [r for r in runs if r[1] - r[0] >= 0.08 * H and r[0] > 0.05 * H]
        if not cells:
            return {"error": "I can't find the cells in the middle of the picture. Point the camera at the cells."}
        c_top = cells[-1][0]                                   # lowest dark block = cells + holder
        above = [i for i in range(c_top - 1, -1, -1) if not dark[i]]
        if not above:
            return {"error": "There is no bright screen above the cells. Tilt the camera so the screen is in view."}
        # bright run directly above the cells = the screen
        s_bot = above[0]
        s_top = s_bot
        while s_top - 1 >= 0 and not dark[s_top - 1]:
            s_top -= 1
        if s_bot - s_top < 0.03 * H:
            return {"error": "I can only see a thin strip of screen above the cells. Tilt the camera down a little."}
        # band: inside the screen, just above the cells (clear of the terminals and of the screen top)
        span = s_bot - s_top
        r0 = int(s_bot - 0.75 * span)
        r1 = int(s_bot - 0.25 * span)
        if r1 - r0 < 4:
            r0, r1 = s_top + 1, s_bot
        prof = img[r0:r1].mean(axis=0)
        cx = W // 2
        level = float(np.median(prof[int(cx - 0.03 * W):int(cx + 0.03 * W)]))
        lo = float(np.percentile(prof, 10))
        if level - lo < 25:
            return {"error": "The screen doesn't stand out from its surroundings. Light the screen more evenly."}
        thr = 0.5 * (level + lo)
        sustain = max(3, int(0.006 * W))                       # a real edge: dark for at least this long
        rm0 = (r0 + r1) // 2

        def top_at(u0, u1):
            """Row where the screen ends going up, in columns u0..u1 (None if it doesn't end)."""
            u0, u1 = int(max(0, u0)), int(min(W, u1))
            if u1 - u0 < 2:
                return None
            col = img[:, u0:u1].mean(axis=1)
            k = rm0
            while k > 0 and col[k] >= thr:
                k -= 1
            return float(k) if k > 0 else None
        top_c = top_at(cx - 0.02 * W, cx + 0.02 * W)

        def same_screen(j, direction, gap_len):
            """After a short dark gap: is the bright part beyond it still the screen (a cable crossing
            it), or something else (a laptop, a projection)? Same brightness AND same top edge = screen."""
            if gap_len > 0.03 * W or top_c is None:
                return False
            a = j + direction * gap_len
            b = a + direction * int(0.03 * W)
            lo_u, hi_u = (a, b) if direction > 0 else (b, a)
            lo_u, hi_u = int(max(0, lo_u)), int(min(W, hi_u))
            if hi_u - lo_u < 3:
                return False
            seg = prof[lo_u:hi_u]
            if abs(float(np.median(seg)) - level) > 0.2 * level:
                return False
            t = top_at(lo_u, hi_u)
            return t is not None and abs(t - top_c) < 0.02 * H

        def walk(direction):
            i = cx
            while 0 < i < W - 1:
                j = i + direction
                if prof[j] < thr:
                    k = j
                    while 0 <= k < W and prof[k] < thr:      # length of this dark stretch
                        k += direction
                    gap_len = abs(k - j)
                    if gap_len >= sustain and not (0 <= k < W and same_screen(j, direction, gap_len)):
                        p0, p1 = prof[i], prof[j]
                        return i + direction * ((p0 - thr) / (p0 - p1) if p0 != p1 else 0.5), False
                    if not (0 <= k < W):
                        break
                    i = k                                  # bridge the gap (cable) and carry on
                    continue
                i = j
            return float(max(0, min(W - 1, i))), True       # ran off the picture

        uR, touch_r = walk(+1)
        uL, touch_l = walk(-1)
        w = uR - uL
        if w < 0.08 * W:
            return {"error": "I can't find the screen's edges. Point the camera at the orange screen behind the cells."}
        out = {"uL": float(uL), "uR": float(uR), "w": float(w), "uS": float(0.5 * (uL + uR)),
               "touch_left": bool(touch_l), "touch_right": bool(touch_r), "band": [int(r0), int(r1)]}
        # roll: lean of the two vertical screen edges between the upper and lower half of the band
        rm = (r0 + r1) // 2
        leans = []
        for u0, ok, pol in ((uL, not touch_l, 1), (uR, not touch_r, -1)):
            if not ok:
                continue
            hi_e = abs_edge_1d(img[r0:rm].mean(axis=0), u0, half=15, min_contrast=10, polarity=pol)
            lo_e = abs_edge_1d(img[rm:r1].mean(axis=0), u0, half=15, min_contrast=10, polarity=pol)
            if hi_e is not None and lo_e is not None:
                leans.append(math.atan2(lo_e - hi_e, 0.5 * (r1 - r0)))
        out["lean"] = float(np.mean(leans)) if leans else None
        # screen top at the left and right quarter (from inside the screen, going up)
        for key, frac in (("vT_l", 0.25), ("vT_r", 0.75)):
            uc = uL + frac * w
            c0, c1 = int(max(0, uc - 0.04 * W)), int(min(W, uc + 0.04 * W))
            col = img[:, c0:c1].mean(axis=1)
            k = rm
            while k > 0 and col[k] >= thr:
                k -= 1
            out[key] = float(k + (thr - col[k]) / (col[k + 1] - col[k])) if (k > 0 and col[k + 1] != col[k]) else None
            out[key.replace("vT", "uT")] = float(uc)
        # cell-top line (median over the middle of the screen) and the cell group's centre
        c0, c1 = int(uL + 0.05 * w), int(uR - 0.05 * w)
        sub = img[r1:min(H, r1 + int(0.3 * H)), c0:c1]
        below = sub < thr
        has = below.any(axis=0)
        first = np.where(has, np.argmax(below, axis=0), sub.shape[0]).astype(float) + r1
        midc = slice(int(0.35 * (c1 - c0)), int(0.65 * (c1 - c0)))
        vals = first[midc][has[midc]]
        if len(vals) < 10:
            return {**out, "error": "I can't see the cell tops against the screen. Tilt the camera so the cells sit in front of the screen."}
        vC = float(np.median(vals))
        tol = cam.f * 4.0 / (0.5 * (self.scene.y0 + self.scene.y1) - cam.Yc)
        group = np.nonzero(has & (first <= vC + tol))[0]
        out["vC"] = vC
        if len(group):
            out["uG"] = float(c0 + 0.5 * (group[0] + group[-1]))
        out["touch_top"] = out.get("vT_l") is None or out.get("vT_r") is None
        return out

    def _placement_picture(self, img, f) -> str | None:
        """Small picture of what the placement guide sees: yellow = rows it reads the screen in,
        pink = screen edges it found, green = cell-top line. Base64 JPEG for the dashboard."""
        try:
            vis = cv2.cvtColor(np.clip(img, 0, 255).astype(np.uint8), cv2.COLOR_GRAY2BGR)
            H, W = img.shape
            t = max(2, W // 640)
            if f.get("band"):
                for r in f["band"]:
                    cv2.line(vis, (0, int(r)), (W - 1, int(r)), (0, 220, 255), t)
            for k in ("uL", "uR"):
                if f.get(k) is not None:
                    cv2.line(vis, (int(f[k]), 0), (int(f[k]), H - 1), (255, 0, 255), 2 * t)
            for k, u in (("vT_l", "uT_l"), ("vT_r", "uT_r")):
                if f.get(k) is not None and f.get(u) is not None:
                    cv2.line(vis, (int(f[u]) - 40 * t, int(f[k])), (int(f[u]) + 40 * t, int(f[k])), (255, 0, 255), 2 * t)
            if f.get("vC") is not None:
                cv2.line(vis, (0, int(f["vC"])), (W - 1, int(f["vC"])), (0, 200, 0), t)
            small = cv2.resize(vis, (640, int(640 * H / W)), interpolation=cv2.INTER_AREA)
            ok, buf = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 70])
            return base64.b64encode(buf.tobytes()).decode() if ok else None
        except Exception:  # noqa: BLE001
            return None

    def measure_fov(self) -> dict:
        """Measure the camera's real horizontal field of view from the rig itself.
        Assumes the camera stands where station.yaml says (lens_xyz_mm, default 5 cm in front of the
        foundation, on the centre line): then the orange screen's width in the picture fixes the
        field of view. Needs the whole screen in view."""
        with self.lock:
            img = camera_mod.grab_average(self.cam, 10, discard=3)
        old = float(self.cfg["camera"].get("hfov_deg", 72.4))
        scr = self.scene.screen
        width_mm = scr["x1"] - scr["x0"]
        hfov = old
        for _ in range(3):                           # refine: a better guess also finds the screen better
            self.cfg["camera"]["hfov_deg"] = hfov
            cam = self._target_cam()
            f = self._placement_features(img, cam)
            if "uL" not in f or f.get("touch_left") or f.get("touch_right"):
                self.cfg["camera"]["hfov_deg"] = old
                return {"ok": False, "error": "I need to see the WHOLE orange screen (both side edges) to measure. "
                                              "Turn or move the camera back a little, then try again."}
            d_s = scr["y"] - cam.Yc
            f_px = f["w"] * d_s / width_mm * math.cos(cam.yaw)
            hfov = math.degrees(2 * math.atan((self.W / 2) / f_px))
        if not 40.0 <= hfov <= 140.0:
            self.cfg["camera"]["hfov_deg"] = old
            return {"ok": False, "error": f"That gives an impossible field of view ({hfov:.0f}°). Check the camera "
                                          "position matches station.yaml and the whole screen is visible."}
        self.cfg["camera"]["hfov_deg"] = round(hfov, 2)
        self.fov_measured = round(hfov, 2)
        self.fov_path.write_text(json.dumps({"hfov_deg": self.fov_measured, "measured": time.time(),
                                             "resolution": [self.W, self.H]}))
        self._tgt_cache, self._p_key = None, None
        return {"ok": True, "hfov_deg": self.fov_measured, "old_hfov_deg": round(old, 1),
                "recalibrate": bool(self.calib), "screen_px": round(f["w"], 1)}

    def _target_features(self):
        if getattr(self, "_tgt_cache", None) is None:
            from .synth import render_clean                     # draw what the optimal pose would see
            cam = self._target_cam()
            img = render_clean({**self.cfg, "synthetic": {**self.cfg.get("synthetic", {}), "blur_px": 1.5}},
                               [self.scene.normal_h] * self.scene.n, cam=cam)
            self._tgt_cache = self._placement_features(img, cam)
        return self._tgt_cache

    def placement_check(self) -> dict:
        """Which way to move the camera. Before calibration: towards the optimal position.
        After calibration: back into the range that is corrected automatically."""
        if not self.lock.acquire(blocking=False):
            return {"busy": True}
        try:
            img = camera_mod.grab_average(self.cam, 4, discard=3)   # discard = flush stale buffered frames
        finally:
            self.lock.release()
        pc = self.cfg.get("placement", {})
        calibrated = bool(self.calib and self.calib.get("placement_ref") and self.calib.get("baseline_n"))
        if calibrated:
            cam, tgt, mode = self.calib["cam"], self.calib["placement_ref"], "calibration"
        else:
            cam, tgt, mode = self._target_cam(), self._target_features(), "optimal"
        f = self._placement_features(img, cam)
        res = {"mode": mode, "steps": [], "numbers": {}, "picture": self._placement_picture(img, f)}
        if "error" in f and "uS" not in f:
            res.update(status="lost", headline=f["error"])
            return res
        if f.get("touch_left") or f.get("touch_right"):
            side = "UNO Q" if f.get("touch_left") else "Modulinos"
            res["steps"].append({"axis": "aim", "ok": False,
                                 "text": f"The screen runs off the picture: turn the camera towards the {side}, or move it further back."})
        if "error" in f:
            res.update(status="adjust", headline=f["error"])
            return res
        F = cam.f
        d_s = self.scene.screen["y"] - (self._target_cam().Yc if not calibrated else cam.Yc)
        d_c = 0.5 * (self.scene.y0 + self.scene.y1) - (self._target_cam().Yc if not calibrated else cam.Yc)
        scale = f["w"] / tgt["w"]
        dist_err = d_s / scale - d_s                          # + = too far away
        # plausibility: the camera is 12-40 cm from the screen, so the screen can't look less than
        # ~0.6x or more than ~1.7x as wide as expected. Outside that, the screen was misread.
        unsure = not (0.6 <= scale <= 1.7) or not (120.0 <= d_s / scale <= 400.0)
        turn = math.degrees(math.atan2(f["uS"] - tgt["uS"], F))   # + = screen right of target -> turn towards Modulinos
        dv = f["vC"] - tgt["vC"]
        tilt = math.degrees(math.atan2(dv, F))                # + = cells too low in the picture -> tilt down
        roll = 0.0                                            # + = picture turned anticlockwise
        if f.get("lean") is not None and tgt.get("lean") is not None:
            roll = math.degrees(f["lean"] - tgt["lean"])
        if calibrated:   # within what the scans correct automatically
            t = self.cfg["thresholds"]
            lim_px, lim_roll, lim_s = self._motion_max_px(), t.get("motion_max_roll_deg", 0.7), t.get("motion_max_scale", 0.015)
            tol = {"dist": lim_s * d_s, "turn": math.degrees(lim_px / F), "tilt": math.degrees(lim_px / F), "roll": lim_roll}
        else:
            # before calibration the position only has to be ROUGHLY right: calibration measures the real one
            # before calibration only the FRAMING matters (screen fully in view, cells in front of it):
            # calibration measures the exact position, so only wildly-off placements get a step
            tol = {"dist": max(pc.get("tol_distance_mm", 60.0), 60.0), "turn": max(pc.get("tol_turn_deg", 15.0), 15.0),
                   "tilt": max(pc.get("tol_tilt_deg", 12.0), 12.0), "roll": max(pc.get("tol_roll_deg", 8.0), 8.0)}
        lower_mm = dv * d_c / F

        # ---- steadiness: judge the MEDIAN of the last few checks, not one noisy picture ----------
        raw = {"distance": float(dist_err), "turn": float(turn), "tilt": float(tilt), "roll": float(roll),
               "lower": float(lower_mm), "lens": float(d_s / scale)}
        key = (mode, getattr(self.cam, "reconnects", 0))
        if getattr(self, "_p_key", None) != key:          # new mode or camera reconnected: start fresh
            self._p_hist, self._p_ok, self._p_okrun, self._p_key = collections.deque(maxlen=5), {}, 0, key
            self._p_shown = {}
        self._p_hist.append(raw)
        hist = list(self._p_hist)
        med = {k: float(np.median([h[k] for h in hist])) for k in raw}
        tol_ax = {"distance": tol["dist"], "turn": tol["turn"], "tilt": tol["tilt"], "roll": tol["roll"]}
        spread = {k: max(h[k] for h in hist) - min(h[k] for h in hist) for k in tol_ax}
        floor = {"distance": 8.0, "turn": 1.0, "tilt": 1.0, "roll": 0.6}       # a glitchy camera wobbles a bit
        steady = len(hist) >= 3 and all(spread[k] <= max(0.75 * tol_ax[k], floor[k]) for k in tol_ax)

        def is_ok(axis):
            # hysteresis: become OK only well inside the tolerance, stop being OK only clearly outside
            prev = self._p_ok.get(axis, False)
            ok = abs(med[axis]) <= tol_ax[axis] * (1.15 if prev else 1.0)
            if steady:
                self._p_ok[axis] = ok
            return ok

        if not hasattr(self, "_p_shown") or len(hist) == 1:
            self._p_shown = {}

        def sticky(name, x, stepsz, minimum):
            """Round to steps, but keep the number already shown unless the new value is clearly
            different (no 3.5 -> 4.0 -> 3.5 flicker when the true value sits on a boundary)."""
            x = abs(x)
            prev = self._p_shown.get(name)
            if prev is not None and abs(x - prev) < 1.0 * stepsz:
                return prev
            val = max(minimum, round(x / stepsz) * stepsz)
            self._p_shown[name] = val
            return val

        mm5 = lambda x, n="mm": int(sticky(n, x, 5.0, 5))              # noqa: E731  (5 mm steps)
        deg = lambda x, n="deg": sticky(n, x, 0.5, 0.5)                # noqa: E731  (0.5 deg steps)

        def step(axis, ok, text):
            res["steps"].append({"axis": axis, "ok": bool(ok), "text": text})

        d, t_, ti, ro = med["distance"], med["turn"], med["tilt"], med["roll"]
        ok_d, ok_t, ok_ti, ok_r = is_ok("distance"), is_ok("turn"), is_ok("tilt"), is_ok("roll")
        if unsure:
            step("distance", False, f"I can't judge the distance: the orange screen looks {scale:.0%} as wide as "
                                    "expected, so I'm probably not seeing all of it. Check the picture below: the two "
                                    "pink lines should sit on the screen's left and right edges. Make sure the WHOLE "
                                    "screen is in view and evenly lit, with nothing in front of it.")
        else:
            step("distance", ok_d, "Distance OK" if ok_d else
                 (f"Move the camera about {mm5(d, 'd')} mm CLOSER to the cells" if d > 0 else
                  f"Move the camera about {mm5(d, 'd')} mm FURTHER from the cells"))
            step("turn", ok_t, "Aim left/right OK" if ok_t else
                 f"Turn the camera about {deg(t_, 't'):.1f}° towards the {'Modulinos' if t_ > 0 else 'UNO Q'} "
                 f"(or slide it {'towards the Modulinos' if t_ > 0 else 'towards the UNO Q'})")
        step("tilt", ok_ti, "Up/down OK" if ok_ti else
             (f"Tilt the camera DOWN about {deg(ti, 'ti'):.1f}° (or lower the lens about {mm5(med['lower'], 'lo')} mm)" if ti > 0 else
              f"Tilt the camera UP about {deg(ti, 'ti'):.1f}° (or raise the lens about {mm5(med['lower'], 'lo')} mm)"))
        step("roll", ok_r, "Level OK" if ok_r else
             f"Rotate the camera about {deg(ro, 'ro'):.1f}° {'anticlockwise' if ro > 0 else 'clockwise'} (as seen from behind it)")
        all_ok = all(s["ok"] for s in res["steps"])
        self._p_okrun = (self._p_okrun + 1) if (all_ok and steady) else 0
        res["numbers"] = {"distance_error_mm": round(d, 1), "turn_deg": round(t_, 2), "tilt_deg": round(ti, 2),
                          "roll_deg": round(ro, 2), "lens_to_screen_mm": round(med["lens"], 0),
                          "steady": steady, "samples": len(hist)}
        if unsure:
            res["status"] = "adjust"
            res["headline"] = "I can't read the screen properly. Check the picture below."
            if mode == "optimal" and not (f.get("touch_left") or f.get("touch_right")):
                res["offer_fov"] = True
                res["headline"] = (f"The orange screen looks {scale:.0%} as wide as I expect. If the pink lines in the "
                                   "picture DO sit on the screen's edges and the camera IS about 5 cm in front of the "
                                   "foundation, this camera simply sees a wider area than its datasheet says: press "
                                   "\"Measure this camera's field of view\" below.")
        elif not steady:
            res["status"] = "settling"
            res["headline"] = ("Hold the camera still for a moment… the picture is still changing "
                               "(camera adjusting, or it's being moved). Directions firm up in a few seconds.")
        elif all_ok and self._p_okrun >= 1:           # OK while steady
            res["status"] = "ok"
            res["headline"] = ("Camera is within the automatic-correction range: OK to scan." if mode == "calibration"
                               else "Camera is in the optimal position. Now calibrate.")
        elif all_ok:
            res["status"] = "settling"
            res["headline"] = "Looks good, confirming… hold still."
        else:
            res["status"] = "adjust"
            res["headline"] = ("Camera moved too far to correct automatically. Easiest: put the 4 normal cells in and "
                               "press \"Re-anchor here\" (about 2 minutes). Or bring it back with the steps below."
                               if mode == "calibration" else
                               "Adjust the camera (top step first), then let go and wait for the next update.")
        if mode != "calibration":
            res["hint"] = ("Keep the lens in line with the foundation's centre spine, about 5 cm in front of the front "
                           "edge. Before calibrating, it doesn't need to be perfect: if all 4 cells and the whole "
                           "orange screen are in the picture, you can calibrate from here.")
        res["steps"].sort(key=lambda s: s["ok"])
        return res

    def reanchor(self, n: int = 5) -> dict:
        """The camera was moved too far: re-learn where things are, keeping the noise level, alarm
        thresholds, fault-cell scale and the AI. Needs the 4 NORMAL cells in place (~2 min)."""
        if not self.calib or not self.calib.get("baseline_n"):
            return {"ok": False, "error": "Not calibrated yet: do the full calibration instead"}
        with self.lock:
            keep = {k: self.calib.get(k) for k in ("baseline_n", "sigma_reseat_mm", "sigma_rel_mm", "t_alarm", "t_watch", "focus")}
            k_old = [(s.get("k_scale", 1.0), s.get("k_measured", False), s.get("k_samples", [])) for s in self.calib["slots"]]
            img = self._avg(self.vcfg.get("calib_frames", 60))
            cam, rms, med, meas = self._fit_camera(img)
            slots = usable_columns(cam, self.scene, self.W, self.vcfg)
            for s, (k, km, ks) in zip(slots, k_old):
                s["k_scale"], s["k_measured"], s["k_samples"] = k, km, ks
            self.calib.update(cam=cam, slots=slots, fit_rms_px=round(rms, 3), fit_median_px=round(med, 3),
                              placement_ref=self._placement_features(img, cam),
                              id="cal-" + time.strftime("%Y%m%d-%H%M%S") + "-ra")
            self.calib["screen_ref"] = self._screen_ref(img, cam, seed=self.calib["placement_ref"])
            self.calib["sky_ref"] = self._sky_stats(img)[0]
            raws = [self._measure_raw(self._avg()) for _ in range(n)]
            for i, s in enumerate(self.calib["slots"]):
                V = np.array([np.where(r["slots"][i]["conf"] >= 0.3, r["slots"][i]["v"], np.nan) for r in raws])
                import warnings
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    s["v_base"] = np.nanmedian(V, axis=0)
            self.calib.update(keep)
            self._save_calib()
            self.last_img = img
            return {"ok": True, "fit_median_px": round(med, 3), "n_cols": [int(len(s["cols"])) for s in slots],
                    "lens_z": round(cam.Zc, 1)}

    # ------------------------------------------------------------ measuring
    def _centers(self, s):
        if s.get("v_base") is None:
            return s["v_model"]
        return np.where(np.isfinite(s["v_base"]), s["v_base"], s["v_model"])

    def _motion(self, snow: dict | None):
        """How the image moved since calibration, from the screen edges: shift (du, dv) px,
        rotation theta (rad) and scale s, about the calibration principal point.
        Needs both side edges and at least one of the three top points; else None."""
        sref = self.calib.get("screen_ref") if self.calib else None
        if not sref or not snow or any(sref.get(k) is None or snow.get(k) is None for k in ("left", "right")):
            return None
        cam = self.calib["cam"]
        s = (snow["right"] - snow["left"]) / (sref["right"] - sref["left"])

        def tilt(d):                      # mean lean of the two vertical screen edges (rad)
            vals = [math.atan2(d[k + "_lo"] - d[k + "_hi"], d["v_lo"] - d["v_hi"]) for k in ("left", "right")
                    if d.get(k + "_lo") is not None and d.get(k + "_hi") is not None]
            return float(np.mean(vals)) if vals else None
        t_now, t_ref = tilt(snow), tilt(sref)
        th = -(t_now - t_ref) if (t_now is not None and t_ref is not None) else 0.0
        um0, vb0 = 0.5 * (sref["left"] + sref["right"]), sref["band_v"]
        du = 0.5 * (snow["left"] + snow["right"]) - (cam.cx + s * ((um0 - cam.cx) - (vb0 - cam.cy) * th))
        dvs = []
        for k in ("top_l", "top_c", "top_r"):
            if sref.get(k) is None or snow.get(k) is None or sref.get(k + "_u") is None:
                continue
            ut, vt = sref[k + "_u"], sref[k]
            dvs.append(snow[k] - (cam.cy + s * ((vt - cam.cy) + (ut - cam.cx) * th)))
        if not dvs:
            return None
        dv = float(np.median(dvs))                     # a spoiled point (projection behind) is outvoted
        t = self.cfg["thresholds"]
        lim = self._motion_max_px()
        within = (abs(du) <= lim and abs(dv) <= lim and
                  abs(math.degrees(th)) <= t.get("motion_max_roll_deg", 0.7) and
                  abs(s - 1) <= t.get("motion_max_scale", 0.015))
        return {"du": float(du), "dv": float(dv), "theta": float(th), "s": float(s), "within": bool(within)}

    def _motion_max_px(self) -> float:
        """Largest picture shift that is corrected automatically, from an angle so it is the same
        physical camera move at any resolution (0.85 deg ~ 3 mm of camera slide at 20 cm)."""
        t = self.cfg["thresholds"]
        if t.get("motion_max_px"):
            return float(t["motion_max_px"])
        f = self.calib["cam"].f if self.calib else CamParams.default(self.cfg).f
        return f * math.tan(math.radians(t.get("motion_max_deg", 0.85)))

    def _map(self, motion, u, v):
        """Calibration-image point(s) -> where they are now."""
        cam = self.calib["cam"]
        if not motion:
            return u, v
        s, th = motion["s"], motion["theta"]
        c, sn = math.cos(th), math.sin(th)
        x, y = u - cam.cx, v - cam.cy
        return (cam.cx + s * (x * c - y * sn) + motion["du"], cam.cy + s * (x * sn + y * c) + motion["dv"])

    def _measure_raw(self, img) -> dict:
        band = int(self.vcfg["band_px"])
        scr = self._screen_ref(img, self.calib["cam"], self.calib.get("screen_ref")) if self.calib.get("screen_ref") else None
        motion = self._motion(scr)
        use = motion if (motion and motion["within"]) else None     # small moves are corrected automatically
        slots = []
        for s in self.calib["slots"]:
            cols = s["cols"].astype(float)
            vc = self._centers(s)
            if use is None:
                v, conf, contrast, bmean = column_edges(img, s["cols"], vc, band)
            else:
                up, vp = self._map(use, cols, vc)
                slope = np.gradient(vc, cols) if len(cols) > 1 else np.zeros_like(vc)
                uc = np.clip(np.round(up), 0, self.W - 1).astype(int)
                vpred = vp + (slope + use["theta"]) * (uc - up)
                vl, conf, contrast, bmean = column_edges(img, uc, vpred, band)
                v = vc + (vl - vpred) / use["s"]                    # back into calibration-image rows
            slots.append({"v": v, "conf": conf, "contrast": contrast, "band_mean": bmean})
        fid = None
        if self.calib.get("fiducials"):
            fid = []
            for fu, fv in self.calib["fiducials"]:
                c = self._centroid(img, fu, fv, 40)
                fid.append(c)
        sky_mean, dark_frac = self._sky_stats(img, use)
        return {"ts": time.time(), "slots": slots, "fiducials": fid, "screen": scr, "motion": motion,
                "sky_mean": sky_mean, "dark_frac": dark_frac}

    def _sky_stats(self, img, motion=None):
        cam = self.calib["cam"]
        vals = []
        for s in self.calib["slots"]:
            c = self._centers(s)
            uu, cc = self._map(motion, s["cols"][::3].astype(float), c[::3])
            for u, vc, d in zip(np.round(uu).astype(int), cc, s["depth"][::3]):
                r0 = int(vc - 8.0 * cam.f / d)
                r1 = int(vc - 3.0 * cam.f / d)
                if 0 <= r0 < r1 <= self.H and 0 <= u < self.W:
                    vals.append(img[r0:r1, int(u)])
        if not vals:
            return float("nan"), 0.0
        allv = np.concatenate(vals)
        ref = self.calib.get("sky_ref") or float(np.median(allv))
        return float(np.mean(allv)), float(np.mean(allv < 0.5 * ref))

    def _measure(self, raw: dict, k_override=None) -> dict:
        cam = self.calib["cam"]
        sky_ref = self.calib.get("sky_ref") or 200.0
        min_conf = self.vcfg["min_conf"]
        cells = []
        for i, (s, r) in enumerate(zip(self.calib["slots"], raw["slots"])):
            conf = np.asarray(r["conf"])
            v = np.asarray(r["v"])
            medconf = float(np.median(conf)) if len(conf) else 0.0
            band_bright = float(np.median(r["band_mean"])) if len(conf) else 0.0
            cell = {"slot": s["slot"], "n_cols": 0, "edge_conf": round(medconf, 3), "delta_mm": None,
                    "delta_l_mm": None, "delta_r_mm": None, "lr_diff_mm": None, "slope_deg": None,
                    "mad_mm": None, "status": "ok"}
            if len(conf) and medconf < 0.25 and band_bright > 0.75 * sky_ref:
                cell["status"] = "missing"
                cells.append(cell)
                continue
            if s.get("v_base") is None:
                cell["status"] = "no_baseline"
                cells.append(cell)
                continue
            k = s.get("k_scale", 1.0) if k_override is None else k_override
            good = (conf >= 0.3) & np.isfinite(v) & np.isfinite(s["v_base"])
            dz = -(v - s["v_base"]) * s["depth"] / cam.f * k
            dmean, mad, n = robust_mean(dz[good])
            if dmean is None:
                cell["status"] = "no_edge"
                cells.append(cell)
                continue
            dl, _, nl = robust_mean(dz[good & s["left"]], min_n=3)
            dr, _, nr = robust_mean(dz[good & ~s["left"]], min_n=3)
            cell.update(delta_mm=dmean, mad_mm=mad, n_cols=n, delta_l_mm=dl, delta_r_mm=dr)
            if dl is not None and dr is not None:
                xl = float(np.mean(s["x_edge"][s["left"]]))
                xr = float(np.mean(s["x_edge"][~s["left"]]))
                cell["lr_diff_mm"] = dl - dr
                cell["slope_deg"] = math.degrees(math.atan2(dr - dl, max(abs(xr - xl), 1.0)))
            if medconf < min_conf:
                cell["status"] = "low_conf"
            cells.append(cell)
        # camera motion from fiducials
        shift, droll = 0.0, 0.0
        base = self.calib.get("fiducials")
        fid = raw.get("fiducials")
        sref, snow = self.calib.get("screen_ref"), raw.get("screen")
        fid_ok = bool(base) or bool(sref)
        camera_moved = None
        motion = raw.get("motion")
        if not base and sref:
            if motion is None:              # screen edges not all found: cannot vouch for the camera
                shift, camera_moved = 99.0, True
            else:
                shift = max(abs(motion["du"]), abs(motion["dv"]))
                droll = math.degrees(motion["theta"])
                camera_moved = not motion["within"]    # small moves are corrected, big ones are not
        if base and fid:
            if any(c is None for c in fid):
                shift = 99.0
            else:
                shift = max(math.hypot(a[0] - b[0], a[1] - b[1]) for a, b in zip(fid, base))
                a0 = math.atan2(base[1][1] - base[0][1], base[1][0] - base[0][0])
                a1 = math.atan2(fid[1][1] - fid[0][1], fid[1][0] - fid[0][0])
                droll = math.degrees(a1 - a0)
        return {
            "ts": raw["ts"],
            "calib_id": self.calib.get("id"),
            "cells": [{k: _f(v) for k, v in c.items()} for c in cells],
            "fiducial_shift_px": _f(shift),
            "roll_change_deg": _f(droll),
            "camera_moved": camera_moved,
            "motion": ({k: (_f(x) if not isinstance(x, bool) else x) for k, x in motion.items()} if motion else None),
            "fiducials_enabled": fid_ok,
            "sky_mean": _f(raw["sky_mean"]),
            "sky_ref": _f(sky_ref),
            "dark_frac": _f(raw["dark_frac"]),
            "t_alarm_mm": self.calib.get("t_alarm"),
            "t_watch_mm": self.calib.get("t_watch"),
            "sigma_rel_mm": self.calib.get("sigma_rel_mm"),
            "sigma_reseat_mm": self.calib.get("sigma_reseat_mm"),
        }

    def health(self) -> dict:
        """Watchdog: read one frame if the camera is idle. A dead connection is reconnected here,
        between scans, instead of during the next scan."""
        if not self.lock.acquire(blocking=False):
            return {"ok": True, "busy": True}
        try:
            g = self.cam.read_gray()
            ok = camera_mod.frame_ok(g)
            return {"ok": ok, "reconnects": getattr(self.cam, "reconnects", 0),
                    "error": None if ok else "damaged picture"}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "reconnects": getattr(self.cam, "reconnects", 0), "error": str(e)}
        finally:
            self.lock.release()

    def scan(self) -> dict:
        """One measurement. If the camera drops out during it, wait and measure again (3 tries),
        so a drop-out costs a few seconds but never gives a verdict from damaged pictures."""
        last = None
        for attempt in range(3):
            try:
                return self._scan_once()
            except RuntimeError as e:
                last = e
                time.sleep(2.0 * (attempt + 1))
        return {"ok": False, "error": f"camera unavailable: {last}"}

    def _scan_once(self) -> dict:
        if not self.calib:
            return {"ok": False, "error": "NOT_CALIBRATED"}
        with self.lock:
            t0 = time.perf_counter()
            img = self._avg()
            raw = self._measure_raw(img)
            m = self._measure(raw)
            m["ok"] = True
            m["scan_ms"] = round((time.perf_counter() - t0) * 1e3, 1)
            m["frames"] = self.vcfg["frames"]
            m["scan_id"] = str(uuid.uuid4())
            self.last_img, self.last_raw, self.last_meas = img, raw, m
            return m

    # --------------------------------------------------------- baseline etc.
    def add_baseline(self) -> dict:
        """Calibration step 2: one scan of the 4 NORMAL cells. Reseat cells every few scans."""
        if not self.calib:
            return {"ok": False, "error": "Run 'Fit geometry' first"}
        with self.lock:
            img = self._avg()
            raw = self._measure_raw(img)
            self.baseline_raws.append(raw)
            self._save_baseline_raws()
            self.last_img, self.last_raw = img, raw
            confs = [round(float(np.median(s["conf"])), 2) if len(s["conf"]) else 0 for s in raw["slots"]]
            return {"ok": True, "n": len(self.baseline_raws), "edge_conf": confs}

    def finish_baseline(self) -> dict:
        """Calibration step 3: compute per-column baseline, noise and thresholds."""
        if not self.calib:
            return {"ok": False, "error": "Run 'Fit geometry' first"}
        n = len(self.baseline_raws)
        if n < 3:
            return {"ok": False, "error": f"Need at least 3 baseline scans (have {n}); 20 recommended"}
        with self.lock:
            for i, s in enumerate(self.calib["slots"]):
                V = np.array([np.where(r["slots"][i]["conf"] >= 0.3, r["slots"][i]["v"], np.nan)
                              for r in self.baseline_raws])
                with np.errstate(all="ignore"):
                    import warnings
                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore")
                        s["v_base"] = np.nanmedian(V, axis=0)
            meas = [self._measure(r) for r in self.baseline_raws]
            D = np.array([[c["delta_mm"] if c["delta_mm"] is not None else np.nan for c in m["cells"]] for m in meas])
            sig_reseat = np.nanstd(D, axis=0, ddof=1)
            R = np.full_like(D, np.nan)
            for j in range(D.shape[1]):
                others = np.delete(D, j, axis=1)
                R[:, j] = D[:, j] - np.nanmedian(others, axis=1)
            sig_rel = float(np.nanmax(np.nanstd(R, axis=0, ddof=1)))
            th = self.cfg["thresholds"]
            self.calib["baseline_n"] = n
            self.calib["sigma_reseat_mm"] = [round(float(x), 4) for x in sig_reseat]
            self.calib["sigma_rel_mm"] = round(sig_rel, 4)
            # alarm level = 4x the cell-vs-neighbours variation, but never above alarm_mm_max (0.45 mm),
            # so the 0.6 mm fault cell is always caught even on a rig whose cells sit less repeatably
            self.calib["t_alarm"] = round(min(max(th["k_alarm_sigma"] * sig_rel, th["alarm_mm_min"]),
                                              th.get("alarm_mm_max", 0.35)), 3)
            self.calib["t_watch"] = round(min(max(th["k_watch_sigma"] * sig_rel, th["watch_mm_min"]),
                                              th.get("watch_mm_max", 0.35), self.calib["t_alarm"]), 3)
            self.calib["sky_ref"] = float(np.nanmedian([r["sky_mean"] for r in self.baseline_raws]))
            fids = [r["fiducials"] for r in self.baseline_raws if r.get("fiducials") and all(r["fiducials"])]
            if fids:
                self.calib["fiducials"] = np.median(np.array(fids), axis=0).tolist()
            if self.calib.get("screen_ref"):
                ref = dict(self.calib["screen_ref"])
                for k in ("left", "right", "top_l", "top_c", "top_r", "left_hi", "left_lo", "right_hi", "right_lo"):
                    vals = [r["screen"][k] for r in self.baseline_raws if r.get("screen") and r["screen"].get(k) is not None]
                    ref[k] = float(np.median(vals)) if vals else None
                self.calib["screen_ref"] = ref
            self._save_calib()
            meas = [self._measure(r) for r in self.baseline_raws]   # again with final sky/fiducial refs
            return {"ok": True, "n": n, "sigma_reseat_mm": self.calib["sigma_reseat_mm"],
                    "sigma_rel_mm": self.calib["sigma_rel_mm"], "t_alarm_mm": self.calib["t_alarm"],
                    "t_watch_mm": self.calib["t_watch"], "measurements": meas}

    def reset_baseline(self) -> dict:
        with self.lock:
            self.baseline_raws = []
            self._save_baseline_raws()
            return {"ok": True, "n": 0}

    def calibrate_scale(self, slot: int) -> dict:
        """Calibration step 4: the 0.6 mm-taller FAULT cell is in `slot`, the others normal."""
        if not self.calib or not self.calib.get("baseline_n"):
            return {"ok": False, "error": "Finish the baseline first"}
        with self.lock:
            img = self._avg(max(self.vcfg["frames"], 30))
            raw = self._measure_raw(img)
            m = self._measure(raw, k_override=1.0)
            d = [c["delta_mm"] for c in m["cells"]]
            if d[slot - 1] is None or any(x is None for x in d):
                return {"ok": False, "error": "A cell edge was not found; check the view and retry"}
            others = [x for j, x in enumerate(d) if j != slot - 1]
            rel = d[slot - 1] - float(np.median(others))
            expected = self.scene.fault_h - self.scene.normal_h
            if rel <= 0.2 * expected:
                return {"ok": False, "error": f"Slot {slot} only {rel:.3f} mm higher. Is the fault cell in slot {slot}?"}
            k1 = expected / rel
            if not 0.6 <= k1 <= 1.6:
                return {"ok": False, "error": f"Scale {k1:.2f} out of range; check cell heights / geometry"}
            s = self.calib["slots"][slot - 1]
            s.setdefault("k_samples", [])
            s["k_samples"] = list(s["k_samples"]) + [round(rel, 5)]
            k = expected / float(np.mean(s["k_samples"]))     # average over every placement so far
            s["k_scale"], s["k_measured"] = round(k, 4), True
            measured = [x["k_scale"] for x in self.calib["slots"] if x.get("k_measured")]
            for x in self.calib["slots"]:
                if not x.get("k_measured"):
                    x["k_scale"] = round(float(np.median(measured)), 4)
            self._save_calib()
            return {"ok": True, "slot": slot, "raw_rel_mm": round(rel, 4), "k_scale": round(k, 4),
                    "placements": len(s["k_samples"]), "others_mm": [round(x, 4) for x in others]}

    def focus_sweep(self) -> dict:
        """Find the sharpest manual focus on the cells' top edge."""
        if getattr(self.cam, "is_synthetic", False):
            return {"ok": True, "best": None, "note": "synthetic camera: nothing to focus"}
        with self.lock:
            if self.calib:
                vs = np.concatenate([s["v_model"] for s in self.calib["slots"]])
                r0, r1 = int(vs.min() - 60), int(vs.max() + 60)
            else:
                r0, r1 = int(self.H * 0.35), int(self.H * 0.7)
            curve = []
            for val in self.cam.focus_values():
                self.cam.set_focus(val)
                for _ in range(8):
                    self.cam.read_gray()
                img = camera_mod.grab_average(self.cam, 3, discard=0)
                band = img[r0:r1]
                sharp = float(cv2.Laplacian(band, cv2.CV_32F).var())
                curve.append([val, round(sharp, 2)])
            best = max(curve, key=lambda x: x[1])[0]
            self.cam.set_focus(best)
            self.cfg["camera"]["focus_absolute"] = best
            if self.calib:
                self.calib["focus"] = best
                self._save_calib()
            for _ in range(8):
                self.cam.read_gray()
            vals = [c[1] for c in curve]
            flat = (max(vals) - min(vals)) < 0.05 * max(max(vals), 1e-6)
            note = ("Sharpness did not change: this camera ignores manual focus (autofocus stays on)." if flat else
                    "If the best value is at the end of the range, the cells are closer than the lens can focus "
                    "(about 20 cm): that is OK, or move the camera back (GUIDE Part 10.2).")
            return {"ok": True, "best": best, "curve": curve, "note": note}

    # ------------------------------------------------------------- pictures
    def snapshot_b64(self) -> dict:
        """Small JPEG of the live view with the measurement overlay drawn on it."""
        if not self.lock.acquire(blocking=False):
            return {"jpg": self._snap_cache, "busy": True}
        try:
            bgr = self.cam.read_bgr().copy()
        except Exception as e:  # noqa: BLE001
            return {"jpg": self._snap_cache, "error": str(e)}
        finally:
            self.lock.release()
        if self.calib:
            for i, s in enumerate(self.calib["slots"]):
                c = self._centers(s)
                pts = np.stack([s["cols"], np.round(c)], axis=1).astype(np.int32)
                for p in pts[::4]:
                    cv2.circle(bgr, tuple(int(x) for x in p), 2, (255, 160, 0), -1)
                if self.last_raw is not None and self.last_meas is not None:
                    v = self.last_raw["slots"][i]["v"]
                    for u, vv in list(zip(s["cols"], v))[::4]:
                        if np.isfinite(vv):
                            cv2.circle(bgr, (int(u), int(round(vv))), 2, (0, 220, 0), -1)
                cv2.putText(bgr, f"S{s['slot']}", (int(s["u_center"]) - 25, int(np.max(c)) + 90),
                            cv2.FONT_HERSHEY_SIMPLEX, 1.6, (0, 0, 255), 3)
            for f in self.calib.get("fiducials") or []:
                cv2.drawMarker(bgr, (int(f[0]), int(f[1])), (0, 0, 255), cv2.MARKER_CROSS, 50, 3)
        small = cv2.resize(bgr, (640, int(640 * self.H / self.W)), interpolation=cv2.INTER_AREA)
        ok, buf = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 75])
        self._snap_cache = base64.b64encode(buf.tobytes()).decode() if ok else self._snap_cache
        return {"jpg": self._snap_cache}

    def save_evidence(self, name: str) -> dict:
        """Save the averaged band around the cells as a PNG (proof for non-OK verdicts)."""
        if self.last_img is None or not self.calib:
            return {"ok": False}
        vs = np.concatenate([s["v_model"] for s in self.calib["slots"]])
        r0, r1 = max(0, int(vs.min() - 150)), min(self.H, int(vs.max() + 80))
        path = self.data / "frames" / f"{name}.png"
        cv2.imwrite(str(path), np.clip(self.last_img[r0:r1], 0, 255).astype(np.uint8))
        return {"ok": True, "path": str(path)}

    # ----------------------------------------------------------- simulation
    def sim(self, action: str, slot: int = 0) -> dict:
        """Only for camera.source = synthetic: change the fake rig."""
        cam = self.cam
        if not getattr(cam, "is_synthetic", False):
            return {"ok": False, "error": "not in synthetic mode"}
        n, f = self.scene.normal_h, self.scene.fault_h
        if action == "normal":
            cam.set_heights([n] * 4); cam.set_hand(False); cam.set_fiducial_shift(0, 0); cam.move_camera()
        elif action == "fault":
            hs = [n] * 4; hs[slot - 1] = f; cam.set_heights(hs)
        elif action == "missing":
            hs = list(cam.heights); hs[slot - 1] = None; cam.set_heights(hs)
        elif action == "reseat":
            cam.reseat()
        elif action == "hand":
            cam.set_hand(not cam.hand)
        elif action == "nudge":            # small knock: corrected automatically
            cam.move_camera(Xc=1.0, yaw=0.004, roll=0.003)
        elif action == "bump":             # big knock: CAMERA_MOVED
            cam.move_camera(Xc=6.0, yaw=0.03)
        elif action == "far_off":          # badly placed camera, for the placement guide
            cam.move_camera(Xc=-12.0, Yc=25.0, yaw=-0.06, cy=-80.0, roll=0.02)
        elif action == "home":
            cam.move_camera()
        else:
            return {"ok": False, "error": "unknown action"}
        return {"ok": True, "heights": cam.heights}


# ======================================================================
class RemoteStation:
    """Talks to python/vision_service.py over HTTP (plan a'). Same methods as Station."""

    METHODS = ("status", "scan", "calibrate_geometry", "add_baseline", "finish_baseline", "reset_baseline",
               "calibrate_scale", "focus_sweep", "snapshot_b64", "save_evidence", "sim", "placement_check", "reanchor",
               "health", "measure_fov")

    def __init__(self, urls: list[str]):
        self.urls = list(urls)
        self.url = None
        self.mode = "service"

    def find(self) -> "RemoteStation":
        for u in self.urls:
            try:
                with urllib.request.urlopen(u + "/health", timeout=2) as r:
                    if r.status == 200:
                        self.url = u
                        return self
            except Exception:  # noqa: BLE001
                continue
        raise RuntimeError("vision_service.py not reachable at " + ", ".join(self.urls))

    def _call(self, name, *args, timeout=120):
        if self.url is None:
            self.find()
        body = json.dumps({"args": list(args)}).encode()
        req = urllib.request.Request(f"{self.url}/call/{name}", data=body,
                                     headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())

    def __getattr__(self, name):
        if name in RemoteStation.METHODS:
            return lambda *a: self._call(name, *a, timeout=10 if name in ("snapshot_b64", "status") else 180)
        raise AttributeError(name)


def make_station(cfg: dict):
    """Pick the camera source according to station.yaml (camera.source)."""
    src = cfg["camera"].get("source", "auto")
    if src in ("synthetic", "v4l2"):
        return Station(cfg).open()
    if src == "service":
        return RemoteStation(cfg["camera"]["service_urls"]).find()
    # auto: local camera first, then the native service
    try:
        return Station(cfg).open()
    except Exception as e_local:  # noqa: BLE001
        print(f"[vision] local camera failed: {e_local}; trying vision_service.py ...")
        try:
            return RemoteStation(cfg["camera"]["service_urls"]).find()
        except Exception as e_remote:  # noqa: BLE001
            raise RuntimeError(f"No camera. Local: {e_local}. Service: {e_remote}") from e_remote
