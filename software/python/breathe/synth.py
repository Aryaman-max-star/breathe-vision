"""Synthetic renderer: draws the 4-cell silhouette against the white screen.

Used for tests and for camera.source = synthetic, so the whole pipeline can be
tried before the rig exists. The 'true' camera is deliberately a little
different from the configured one so the geometry fit has something to find.
"""
from __future__ import annotations

import math

import numpy as np
from scipy.ndimage import gaussian_filter

from .geometry import CamParams, Scene, silhouette

SKY, DARK, FID = 225.0, 35.0, 30.0


def true_camera(cfg: dict) -> CamParams:
    cam = CamParams.default(cfg)
    o = cfg.get("synthetic", {}).get("true_camera_offset", {}) or {}
    cam.cx += o.get("cx", 0.0)
    cam.cy += o.get("cy", 0.0)
    cam.f *= o.get("f_scale", 1.0)
    cam.Zc += o.get("Zc", 0.0)
    cam.Yc += o.get("Yc", 0.0)
    cam.roll += o.get("roll", 0.0)
    cam.Xc += o.get("Xc", 0.0)
    cam.yaw += o.get("yaw", 0.0)
    return cam


def render_clean(cfg: dict, heights, cam: CamParams | None = None, fiducial_shift=(0.0, 0.0),
                 hand: bool = False) -> np.ndarray:
    """Noise-free grey image (float32) for the given cell heights (None = missing cell)."""
    w, h = cfg["camera"]["width"], cfg["camera"]["height"]
    cam = cam or true_camera(cfg)
    if abs(cam.roll) > 1e-9:
        # a real camera roll ROTATES the whole picture (vertical lines lean); the measuring model
        # approximates it, so the simulator must do it properly: render level, then rotate
        level = CamParams(**{**cam.to_dict(), "roll": 0.0})
        img = render_clean(cfg, heights, cam=level, fiducial_shift=fiducial_shift, hand=hand)
        import cv2
        M = cv2.getRotationMatrix2D((cam.cx, cam.cy), -math.degrees(cam.roll), 1.0)
        return cv2.warpAffine(img, M, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    scene = Scene(cfg["geometry"])
    us = np.arange(w, dtype=float)
    sil_v, _, _, _ = silhouette(cam, scene.boxes(heights), us)
    rows = np.arange(h, dtype=np.float32)[:, None]
    sil = np.where(np.isfinite(sil_v), sil_v, h + 10).astype(np.float32)[None, :]
    cover = np.clip(rows - sil + 0.5, 0, 1)                   # 1 below silhouette (pixel-area antialias)
    # the orange screen (bright in the red channel) in front of the room background
    bg = cfg.get("synthetic", {}).get("background", 70.0)
    scr = scene.screen
    # per column: which point of the screen plane is seen, and the screen's top/bottom rows there
    # (exact for camera turn/roll, so camera motion can be simulated)
    t = np.tan(np.arctan((us - cam.cx) / cam.f) + cam.yaw)
    dw = scr["y"] - cam.Yc
    X = cam.Xc + t * dw
    d = dw * (t * math.sin(cam.yaw) + math.cos(cam.yaw))
    tilt = math.tan(cam.roll) * (us - cam.cx)
    v_top = cam.cy + cam.f * (cam.Zc - scr["z1"]) / d + tilt + fiducial_shift[1]
    v_bot = cam.cy + cam.f * (cam.Zc - scr["z0"]) / d + tilt + fiducial_shift[1]
    su0 = cam.project(scr["x0"], scr["y"], 0.5 * (scr["z0"] + scr["z1"]))[0] + fiducial_shift[0]
    su1 = cam.project(scr["x1"], scr["y"], 0.5 * (scr["z0"] + scr["z1"]))[0] + fiducial_shift[0]
    cu = np.clip(np.minimum(np.arange(w) + 1, su1) - np.maximum(np.arange(w), su0), 0, 1)
    rows_f = np.arange(h, dtype=np.float32)[:, None]
    cv = np.clip(rows_f - v_top[None, :].astype(np.float32) + 0.5, 0, 1) * \
        np.clip(v_bot[None, :].astype(np.float32) - rows_f + 0.5, 0, 1)
    screen = cv * cu[None, :].astype(np.float32)
    img = bg + (SKY - bg) * screen
    img = img - (img - DARK) * cover
    # fiducials (dark squares on the screen)
    s = scene.fid_size / 2
    for (fx, fz) in scene.fiducials:
        u0, v0 = cam.project(fx - s, scene.screen_y, fz + s)
        u1, v1 = cam.project(fx + s, scene.screen_y, fz - s)
        u0 += fiducial_shift[0]; u1 += fiducial_shift[0]
        v0 += fiducial_shift[1]; v1 += fiducial_shift[1]
        cu = np.clip(np.minimum(np.arange(w) + 1, u1) - np.maximum(np.arange(w), u0), 0, 1)
        cv = np.clip(np.minimum(np.arange(h) + 1, v1) - np.maximum(np.arange(h), v0), 0, 1)
        a = cv[:, None] * cu[None, :]
        img = img * (1 - a) + FID * a
    if hand:
        img[int(h * 0.2):int(h * 0.55), int(w * 0.45):int(w * 0.6)] = 60.0
    blur = cfg.get("synthetic", {}).get("blur_px", 1.2)
    return gaussian_filter(img, blur).astype(np.float32)


class SyntheticCamera:
    """Behaves like V4L2Camera but returns rendered frames."""

    is_synthetic = True

    def __init__(self, cfg: dict, seed: int = 0):
        self.cfg = cfg
        sc = cfg.get("synthetic", {})
        self.heights = list(sc.get("heights", [42.0] * 4))
        self.noise = float(sc.get("noise", 3.0))
        self.reseat_sigma = float(sc.get("reseat_sigma_mm", 0.03))
        self.rng = np.random.default_rng(seed)
        self.jitter = [0.0] * 4
        self.fiducial_shift = (0.0, 0.0)
        self.cam_move = {}                    # simulated camera displacement (mm / rad / px)
        self.hand = False
        self._clean = None
        self.device = "synthetic"
        self.reconnects = 0
        self.last_error = None

    # --- simulation controls -------------------------------------------------
    def set_heights(self, heights, reseat: bool = True):
        self.heights = list(heights)
        if reseat:
            self.reseat()
        self._clean = None

    def reseat(self):
        self.jitter = [float(self.rng.normal(0, self.reseat_sigma)) for _ in range(4)]
        self._clean = None

    def set_fiducial_shift(self, du, dv):
        self.fiducial_shift = (du, dv)
        self._clean = None

    def move_camera(self, **delta):
        """Displace the simulated camera, e.g. move_camera(Xc=0.8, yaw=0.003). Empty = back home."""
        self.cam_move = dict(delta)
        self._clean = None

    def _true_cam(self):
        cam = true_camera(self.cfg)
        for k, v in self.cam_move.items():
            setattr(cam, k, getattr(cam, k) + v)
        return cam

    def set_hand(self, on: bool):
        self.hand = on
        self._clean = None

    # --- camera interface -----------------------------------------------------
    def open(self):
        return self

    def apply_controls(self, focus=None):
        pass

    def set_focus(self, value):
        pass

    def _base(self):
        if self._clean is None:
            hs = [None if h is None else h + j for h, j in zip(self.heights, self.jitter)]
            self._clean = render_clean(self.cfg, hs, cam=self._true_cam(), fiducial_shift=self.fiducial_shift,
                                       hand=self.hand)
        return self._clean

    def read_gray(self) -> np.ndarray:
        base = self._base()
        return np.clip(base + self.rng.normal(0, self.noise, base.shape).astype(np.float32), 0, 255)

    def read_bgr(self) -> np.ndarray:
        g = self.read_gray().astype(np.uint8)
        return np.repeat(g[:, :, None], 3, axis=2)

    def close(self):
        pass
