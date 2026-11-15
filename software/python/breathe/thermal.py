"""Air temperature / humidity from the Modulino Thermo, plus an honest surface ESTIMATE.

The sensor measures AIR. The 'surface' value is a first-order lag model
dTs/dt = (Ta - Ts) / tau and must be labelled as an estimate.
"""
from __future__ import annotations

import collections
import math
import time


def dew_point(t_c: float, rh_pct: float) -> float:
    """Magnus formula, beta = 17.62, lambda = 243.12 C (valid -45..60 C)."""
    b, l = 17.62, 243.12
    h = math.log(max(rh_pct, 0.1) / 100.0) + b * t_c / (l + t_c)
    return l * h / (b - h)


class Thermal:
    def __init__(self, tau_filter: float = 10.0, tau_module: float = 300.0, location: str = ""):
        self.tf, self.tm = tau_filter, tau_module
        self.location = location
        self.Ta = self.Ts = self.Tbase = self.rh = self.raw_t = None
        self.t_last = None
        self.hist = collections.deque(maxlen=60)          # (t, Ta) for the slope, ~1 min
        self.chart = collections.deque(maxlen=600)        # 10 min for the dashboard
        self.n = 0

    def update(self, T: float, RH: float, t: float | None = None):
        t = time.time() if t is None else t
        if T is None or not math.isfinite(T) or T < -40 or T > 125:
            return
        if self.raw_t is not None and abs(T - self.raw_t) > 15.0:
            self.rejected = getattr(self, "rejected", 0) + 1   # a jump this big is a glitch, not air
            if self.rejected < 5:
                return                                         # (5 in a row = real change: accept)
        self.rejected = 0
        dt = 1.0 if self.t_last is None else max(0.05, min(10.0, t - self.t_last))
        self.t_last = t
        self.raw_t = T
        if self.Ta is None:
            self.Ta = self.Ts = T
        self.Ta += dt / (self.tf + dt) * (T - self.Ta)       # low-pass filter
        self.Ts += (dt / self.tm) * (self.Ta - self.Ts)      # first-order lag (surface estimate)
        self.rh = RH
        self.n += 1
        if self.Tbase is None and self.n >= 20:             # baseline after ~20 s of readings
            self.Tbase = self.Ta
        self.hist.append((t, self.Ta))
        if self.n % 2 == 0:
            self.chart.append([round(t, 1), round(self.Ta, 2), round(self.Ts, 2),
                               round(self.dew_point(), 2) if self.rh is not None else None])

    def set_base(self):
        if self.Ta is not None:
            self.Tbase = self.Ta

    def slope_c_per_min(self) -> float:
        if len(self.hist) < 10:
            return 0.0
        ts, ys = zip(*self.hist)
        mt, my = sum(ts) / len(ts), sum(ys) / len(ys)
        den = sum((a - mt) ** 2 for a in ts)
        return 60 * sum((a - mt) * (b - my) for a, b in self.hist) / den if den else 0.0

    def dew_point(self):
        if self.Ta is None or self.rh is None:
            return None
        return dew_point(self.Ta, self.rh)

    def snapshot(self) -> dict:
        ok = self.Ta is not None
        td = self.dew_point()
        return {
            "valid": ok,
            "t_air_c": round(self.Ta, 2) if ok else None,
            "t_surf_est_c": round(self.Ts, 2) if ok else None,
            "t_dew_c": round(td, 2) if td is not None else None,
            "rh_pct": round(self.rh, 1) if self.rh is not None else None,
            "t_base_c": round(self.Tbase, 2) if self.Tbase is not None else None,
            "dT_c": round(self.Ta - self.Tbase, 2) if ok and self.Tbase is not None else 0.0,
            "dTdt_c_per_min": round(self.slope_c_per_min(), 3),
            "surf_minus_dew_c": round(self.Ts - td, 2) if ok and td is not None else None,
            "tau_module_s": self.tm,
            "sensor_location": self.location,
        }
