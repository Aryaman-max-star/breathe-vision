"""3-D model of the rig and pinhole projection.

Coordinates (mm): x across the cells (slot 1 on the left), y away from the camera,
z up. The camera looks along +y.

    u = cx + f (X - Xc) / (Y - Yc)
    v = cy + f (Zc - Z) / (Y - Yc)  + tan(roll) (u - cx)

For every image column u we work out which surface forms the top silhouette
(the highest point = smallest v). For a box-shaped top face that is the point
with the largest depth y that still projects into column u: either the BACK top
edge or, for off-axis cells, a SIDE top edge (a slanted line in the image).
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass

import numpy as np

KIND_NONE, KIND_BACK, KIND_SIDE = 0, 1, 2


@dataclass
class CamParams:
    cx: float
    cy: float
    f: float
    Xc: float = 90.0
    Yc: float = 32.0
    Zc: float = 49.0
    roll: float = 0.0  # radians, rotation about the viewing axis
    yaw: float = 0.0   # radians, camera turned left/right (positive = towards +x)

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "CamParams":
        return CamParams(**{k: float(d.get(k, 0.0)) for k in ("cx", "cy", "f", "Xc", "Yc", "Zc", "roll", "yaw")})

    @staticmethod
    def default(cfg: dict) -> "CamParams":
        w, h = cfg["camera"]["width"], cfg["camera"]["height"]
        hfov = cfg["camera"].get("hfov_deg", 72.4)        # Arduino USB Camera: 80 deg diagonal -> ~72.4 deg horizontal (16:9)
        f = (w / 2) / math.tan(math.radians(hfov / 2))
        x, y, z = cfg["geometry"]["lens_xyz_mm"]
        return CamParams(cx=w / 2, cy=h / 2, f=f, Xc=x, Yc=y, Zc=z)

    def project(self, X: float, Y: float, Z: float) -> tuple[float, float]:
        dx, dy = X - self.Xc, Y - self.Yc
        s, c = math.sin(self.yaw), math.cos(self.yaw)
        d = dx * s + dy * c                       # depth along the viewing direction
        u = self.cx + self.f * (dx * c - dy * s) / d
        v = self.cy + self.f * (self.Zc - Z) / d + math.tan(self.roll) * (u - self.cx)
        return u, v


@dataclass
class Box:
    x0: float
    x1: float
    y0: float
    y1: float
    z: float           # height of the top face
    owner: int         # slot index 0..3, or -1 for the holder
    kind: str          # "cell" | "terminal" | "holder"


class Scene:
    """The holder, the four cells and their terminals."""

    def __init__(self, g: dict):
        c = g["cell"]
        self.w, self.dy = c["width_x"], c["depth_y"]
        self.normal_h, self.fault_h, self.z0 = c["normal_h"], c["fault_h"], c["bottom_z"]
        self.y0 = c["front_y"]
        self.y1 = self.y0 + self.dy
        self.left = list(g["slot_left_x"])
        self.xc = [l + self.w / 2 for l in self.left]
        t = g["terminal"]
        self.tr, self.th = t["radius"], t["height"]
        self.ty = [self.y0 + v for v in t["y_from_front"]]
        self.holder = g["holder"]
        self.screen_y = g["screen_y"]
        self.screen = g.get("screen", {"x0": 25.0, "x1": 155.0, "y": g["screen_y"], "z0": 2.4, "z1": 76.0})
        self.fiducials = [tuple(p) for p in (g.get("fiducials_xz") or [])]
        self.fid_size = g.get("fiducial_size_mm", 5.0)
        self.n = len(self.left)

    def cell_box(self, i: int, h: float) -> Box:
        return Box(self.left[i], self.left[i] + self.w, self.y0, self.y1, self.z0 + h, i, "cell")

    def terminal_boxes(self, i: int, h: float, margin: float = 0.0) -> list[Box]:
        r = self.tr + margin
        top = self.z0 + h + self.th
        return [Box(self.xc[i] - r, self.xc[i] + r, ty - r, ty + r, top, i, "terminal") for ty in self.ty]

    def holder_box(self) -> Box:
        hd = self.holder
        return Box(hd["x0"], hd["x1"], hd["front_y"], hd["back_y"], hd["top_z"], -1, "holder")

    def boxes(self, heights) -> list[Box]:
        out = [self.holder_box()]
        for i, h in enumerate(heights):
            if h is None:
                continue
            out.append(self.cell_box(i, h))
            out.extend(self.terminal_boxes(i, h))
        return out


def box_columns(cam: CamParams, b: Box, us: np.ndarray):
    """For every column u: (v, depth d, kind, valid, x_at_edge, y_at_edge) of box b's top face."""
    us = np.asarray(us, dtype=np.float64)
    # world slope dX/dY of the vertical plane that projects into column u (yaw rotates it)
    t = np.tan(np.arctan((us - cam.cx) / cam.f) + cam.yaw)
    with np.errstate(divide="ignore", invalid="ignore"):
        ya = cam.Yc + (b.x0 - cam.Xc) / t
        yb = cam.Yc + (b.x1 - cam.Xc) / t
    lo = np.where(t > 0, ya, yb)
    hi = np.where(t > 0, yb, ya)
    zero = np.abs(t) < 1e-12
    inside0 = b.x0 <= cam.Xc <= b.x1
    lo = np.where(zero, -np.inf if inside0 else np.inf, lo)
    hi = np.where(zero, np.inf if inside0 else -np.inf, hi)
    ymax = np.minimum(b.y1, hi)
    ymin = np.maximum(b.y0, lo)
    valid = ymax >= ymin
    below = b.z < cam.Zc
    y_use = ymax if below else ymin           # top face below the lens: farthest point is highest
    dw = y_use - cam.Yc                       # distance along y in the world
    d = dw * (t * math.sin(cam.yaw) + math.cos(cam.yaw))   # depth along the viewing direction
    with np.errstate(divide="ignore", invalid="ignore"):
        v = cam.cy + cam.f * (cam.Zc - b.z) / d + math.tan(cam.roll) * (us - cam.cx)
    edge_y = b.y1 if below else b.y0
    kind = np.where(np.isclose(y_use, edge_y), KIND_BACK, KIND_SIDE)
    v = np.where(valid, v, np.inf)
    with np.errstate(invalid="ignore"):
        x_edge = cam.Xc + t * dw
    return v, d, kind, valid, x_edge, y_use


def silhouette(cam: CamParams, boxes: list[Box], us: np.ndarray):
    """Top silhouette: v (inf where nothing), index of the winning box, depth, kind."""
    us = np.asarray(us, dtype=np.float64)
    best_v = np.full(us.shape, np.inf)
    best_i = np.full(us.shape, -1, dtype=int)
    best_d = np.full(us.shape, np.nan)
    best_k = np.zeros(us.shape, dtype=int)
    for i, b in enumerate(boxes):
        v, d, kind, valid, _, _ = box_columns(cam, b, us)
        better = valid & (v < best_v)
        best_v = np.where(better, v, best_v)
        best_i = np.where(better, i, best_i)
        best_d = np.where(better, d, best_d)
        best_k = np.where(better, kind, best_k)
    return best_v, best_i, best_d, best_k


def _erode(mask: np.ndarray, g: int) -> np.ndarray:
    if g <= 0:
        return mask
    k = np.ones(2 * g + 1)
    return np.convolve(mask.astype(float), k, mode="same") >= (2 * g + 1) - 1e-9


def usable_columns(cam: CamParams, scene: Scene, width: int, vcfg: dict) -> list[dict]:
    """Columns where slot i's own top edge is the silhouette, whatever the neighbours' heights.

    A column is used for slot i only if
      * the silhouette there (all cells at normal height) is slot i's top face,
      * no OTHER cell's top face projects into that column at all (so a taller
        neighbour can never overlap it - this replaces the two-pass mask),
      * no terminal (any slot, + margin) projects into it,
      * the edge point is at least edge_margin_mm away from the rounded corners.
    The result is then eroded by column_guard_px on both sides.
    """
    us = np.arange(width, dtype=np.float64)
    heights = [scene.normal_h] * scene.n
    boxes = scene.boxes(heights)
    sil_v, sil_i, _, _ = silhouette(cam, boxes, us)
    owners = np.array([b.owner for b in boxes])
    is_cell = np.array([b.kind == "cell" for b in boxes])
    m = vcfg["edge_margin_mm"]
    tm = vcfg["terminal_margin_mm"]
    guard = int(vcfg["column_guard_px"])

    cell_valid = []
    for i in range(scene.n):
        _, _, _, valid, _, _ = box_columns(cam, scene.cell_box(i, scene.normal_h), us)
        cell_valid.append(valid)
    term_cover = np.zeros(width, dtype=bool)
    for i in range(scene.n):
        for tb in scene.terminal_boxes(i, scene.normal_h, margin=tm):
            term_cover |= box_columns(cam, tb, us)[3]

    out = []
    for i in range(scene.n):
        cb = scene.cell_box(i, scene.normal_h)
        v, d, kind, valid, xe, ye = box_columns(cam, cb, us)
        owner_ok = (sil_i >= 0) & (owners[sil_i] == i) & is_cell[sil_i]
        ok = valid & owner_ok & ~term_cover
        for j in range(scene.n):
            if j != i:
                ok &= ~cell_valid[j]
        back_ok = (kind == KIND_BACK) & (xe >= cb.x0 + m) & (xe <= cb.x1 - m)
        side_ok = (kind == KIND_SIDE) & (ye >= cb.y0 + m) & (ye <= cb.y1 - m)
        ok &= back_ok | side_ok
        ok = _erode(ok, guard)
        cols = np.nonzero(ok)[0]
        # centre column of the cell (where the terminal bump is) separates the left/right halves
        u_c, _ = cam.project(scene.xc[i], (scene.ty[0] + scene.ty[1]) / 2, 0.0)
        out.append({
            "slot": i + 1,
            "cols": cols.astype(int),
            "depth": d[cols],
            "kind": kind[cols],
            "x_edge": xe[cols],
            "v_model": v[cols],
            "left": cols < u_c,
            "u_center": float(u_c),
        })
    return out
