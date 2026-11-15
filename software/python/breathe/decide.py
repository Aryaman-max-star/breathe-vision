"""Rule engine: one verdict per scan, checked IN ORDER (first match wins), plus per-cell actions.

classify() is a pure function apart from `memory`, a small dict that remembers which
slot was asked to be reseated (reseat-before-swell confirmation).
"""
from __future__ import annotations

import time

import numpy as np

from .recommend import SEVERITY_ORDER, action

FLAG_THERMAL, FLAG_CAMERA, FLAG_OBSTRUCT, FLAG_SCANNING = 1, 2, 4, 8


def _med(xs):
    xs = [x for x in xs if x is not None]
    return float(np.median(xs)) if xs else None


def derived(meas: dict) -> dict:
    """Common mode c, per-cell relative rise r_i, spread."""
    d = [c["delta_mm"] if c["status"] in ("ok", "low_conf") else None for c in meas["cells"]]
    c = _med(d)
    r = []
    for i, di in enumerate(d):
        others = [x for j, x in enumerate(d) if j != i and x is not None]
        r.append(None if di is None or not others else di - float(np.median(others)))
    present = [x for x in d if x is not None]
    spread = (max(present) - min(present)) if len(present) >= 2 else 0.0
    return {"delta": d, "c": c, "r": r, "spread": spread}


def cell_features(meas: dict, der: dict) -> list[list[float]]:
    out = []
    for c, r in zip(meas["cells"], der["r"]):
        if r is None:
            continue
        out.append([r, (c["delta_mm"] or 0) - (der["c"] or 0), c["slope_deg"] or 0.0, c["lr_diff_mm"] or 0.0,
                    c["edge_conf"] or 0.0, c["mad_mm"] or 0.0])
    return out


# Typical harmless variation of each AI input. Training adds jittered copies with this much noise,
# so normal drift (lighting, a small camera nudge) is not mistaken for an anomaly.
CELL_FEATURE_NOISE = [0.035, 0.035, 0.3, 0.03, 0.05, 0.01]  # r, delta-c (mm), slope (deg), L-R (mm), conf, MAD (mm)
SCAN_FEATURE_NOISE = [0.04, 0.035, 0.04, 0.05]                # c, max r, spread (mm), min conf


def scan_features(meas: dict, der: dict, th: dict | None = None) -> list[float]:
    """Measurement features only. Left out on purpose: room conditions (temperature, humidity drift
    over a session; the THERMAL rules handle them) and camera shift (small shifts are corrected
    automatically; big ones are the CAMERA_MOVED rule)."""
    rs = [x for x in der["r"] if x is not None]
    confs = [c["edge_conf"] or 0 for c in meas["cells"]]
    return [der["c"] or 0.0, max(rs) if rs else 0.0, der["spread"], min(confs) if confs else 0.0]


def classify(meas: dict, th: dict, cfg: dict, memory: dict, ai: dict | None = None) -> dict:
    """meas: Station.scan() output, th: Thermal.snapshot(), ai: {"cell": [...], "scan": float} scores."""
    T = cfg["thresholds"]
    tc = cfg["thermal"]
    res = {"ts": meas.get("ts", time.time()), "scan_id": meas.get("scan_id"), "verdict": "OK", "slots": [],
           "reason": "", "flags": 0, "thermal": th, "ai": ai, "meas": meas}
    if not meas.get("ok", False):
        v = "NOT_CALIBRATED" if meas.get("error") == "NOT_CALIBRATED" else "VISION_OFFLINE"
        return _finish(res, v, meas.get("error", ""), [], cfg, None, None, 0.25)

    t_alarm = meas.get("t_alarm_mm") or T["alarm_mm_min"]
    t_watch = meas.get("t_watch_mm") or T["watch_mm_min"]
    sigma = meas.get("sigma_rel_mm") or 0.05
    cells = meas["cells"]
    der = derived(meas)
    res.update(c_mm=der["c"], r_mm=der["r"], spread_mm=der["spread"], t_alarm_mm=t_alarm, t_watch_mm=t_watch)
    thermal_event = th.get("valid") and ((th.get("dT_c") or 0) > tc["dT_event_c"] or
                                          (th.get("dTdt_c_per_min") or 0) > tc["dTdt_event_c_per_min"])
    if thermal_event:
        res["flags"] |= FLAG_THERMAL

    # 1. obstruction / lighting
    low = [c["slot"] for c in cells if c["status"] in ("low_conf", "no_edge")]
    sky_ratio = (meas["sky_mean"] / meas["sky_ref"]) if meas.get("sky_mean") and meas.get("sky_ref") else 1.0
    if (meas.get("dark_frac") or 0) > T["sky_dark_frac"] or len(low) >= 2:
        res["flags"] |= FLAG_OBSTRUCT
        return _finish(res, "OBSTRUCTED", f"dark sky {100 * (meas.get('dark_frac') or 0):.1f} %, low-confidence slots {low}",
                       [], cfg, der, None, t_alarm)
    if abs(sky_ratio - 1) > T["sky_change_frac"]:
        res["flags"] |= FLAG_OBSTRUCT
        return _finish(res, "LIGHTING", f"screen brightness changed {100 * (sky_ratio - 1):+.0f} %", [], cfg, der, None, t_alarm)
    # 2. camera moved
    moved = meas.get("camera_moved")
    if moved is None:                       # optional stuck-on fiducials: plain thresholds
        moved = (meas.get("fiducial_shift_px") or 0) > T["fiducial_px"] or abs(meas.get("roll_change_deg") or 0) > T["roll_deg"]
    if moved:
        res["flags"] |= FLAG_CAMERA
        return _finish(res, "CAMERA_MOVED", f"camera moved {meas['fiducial_shift_px']:.1f} px, more than can be corrected automatically", [], cfg, der, None, t_alarm)
    # 3. missing
    missing = [c["slot"] for c in cells if c["status"] == "missing"]
    if missing:
        memory.pop("pending_reseat", None)
        return _finish(res, "MISSING", f"no cell in slot(s) {missing}", missing, cfg, der, None, t_alarm)
    # 4. tilted / not seated
    lr_lim = max(4 * sigma, T["lr_mm_min"])
    tilted = [c["slot"] for c in cells if (c["slope_deg"] is not None and abs(c["slope_deg"]) > T["slope_deg"])
              or (c["lr_diff_mm"] is not None and abs(c["lr_diff_mm"]) > lr_lim)]
    if tilted:
        return _finish(res, "RESEAT", f"cell(s) {tilted} tilted (left/right differ)", tilted, cfg, der, None, t_alarm)
    # 5. single-cell swelling, with reseat-and-confirm, and WHY: internal fault vs heat
    #    hot = the air at the module (Thermo in its pocket) is warming fast or clearly above normal
    t_air = th.get("t_air_c")
    hot = bool(thermal_event or (t_air is not None and t_air > tc.get("ok_band_c", [15.0, 35.0])[1]))
    res["hot"] = hot
    heat_txt = (f"air at the module {th.get('dT_c', 0):+.1f} °C vs normal" if th.get("valid") else "module hot")
    raised = [i + 1 for i, r in enumerate(der["r"]) if r is not None and r >= t_alarm]
    hot_mem = set(memory.get("swell_hot", []))
    pend = memory.get("pending_reseat", {})
    if isinstance(pend, list):                       # older format
        pend = {s: None for s in pend}
    pend = {int(k): v for k, v in pend.items()}
    # confirm with the AVERAGE of the scan before and after reseating: one unlucky seating can't hide a
    # swollen cell, and one unlucky seating of a normal cell can't fake one
    confirmed = []
    for s, r1 in pend.items():
        r2 = der["r"][s - 1]
        if r2 is None:
            continue
        mean = r2 if r1 is None else 0.5 * (r1 + r2)
        if mean >= t_alarm:
            confirmed.append(s)
    confirmed += [s for s in raised if s in hot_mem and s not in confirmed]   # confirmed earlier (while hot)
    n_present = len([x for x in der["delta"] if x is not None])
    if confirmed and len(confirmed) < n_present:
        confirmed = sorted(confirmed)
        memory.pop("pending_reseat", None)
        sizes = ", ".join(f"slot {s} +{der['r'][s - 1]:.2f} mm" for s in confirmed)
        if hot:
            memory["swell_hot"] = sorted(hot_mem | set(confirmed))
            res["cause"] = "heat"
            why = (f"{sizes}, swollen while the module is HOT ({heat_txt}): likely heat-driven, from an external "
                   "hotspot or a cooling problem. Let it cool and scan again to see if it recovers.")
        elif set(confirmed) & hot_mem:
            memory["swell_hot"] = sorted(hot_mem - set(confirmed))
            res["cause"] = "permanent"
            why = f"{sizes}, STILL swollen after cooling down: permanent damage from the heat."
        else:
            res["cause"] = "internal"
            why = f"{sizes}, swollen at normal temperature: internal fault (gas build-up / ageing inside the cell)."
        return _finish(res, "SWELL", why, confirmed, cfg, der, res["cause"], t_alarm)
    if raised and len(raised) < n_present:
        memory["pending_reseat"] = {s: der["r"][s - 1] for s in raised}
        note = " The module is hot right now." if hot else ""
        return _finish(res, "RESEAT", "raised cell(s) " + ", ".join(f"{s} (+{der['r'][s - 1]:.2f} mm)" for s in raised) +
                       " - reseat and scan again to confirm." + note, raised, cfg, der, None, t_alarm)
    memory.pop("pending_reseat", None)
    # 5a. a cell that swelled while hot is back to normal now that it's cool: heat-related, reversible
    if hot_mem and not hot:
        rec = [s for s in sorted(hot_mem) if der["r"][s - 1] is not None and der["r"][s - 1] < t_watch]
        if rec:
            memory["swell_hot"] = sorted(hot_mem - set(rec))
            res["cause"] = "heat"
            return _finish(res, "RECOVERED", "slot(s) " + ", ".join(map(str, rec)) + " back to normal after cooling: "
                           "the swelling was heat-related and reversible.", rec, cfg, der, None, t_alarm)
    # 6. uniform rise
    c = der["c"] or 0.0
    if c >= t_alarm and der["spread"] < T["uniform_spread_mm"]:
        dh_th = tc["alpha_pla_per_k"] * tc["cell_length_mm"] * max(0.0, (th.get("t_surf_est_c") or 0) - (th.get("t_base_c") or 0))
        if thermal_event:
            v = "THERMAL_OK" if c <= dh_th + 2 * sigma else "UNIFORM_RISE"
            return _finish(res, v, f"all cells +{c:.2f} mm, expected thermal {dh_th:.3f} mm", [], cfg, der, None, t_alarm)
        return _finish(res, "HOLDER_LIFTED", f"all cells +{c:.2f} mm with no temperature change", [], cfg, der, None, t_alarm)
    # 5b. watch
    watch = [i + 1 for i, r in enumerate(der["r"]) if r is not None and t_watch <= r < t_alarm]
    # 7. thermal event with normal geometry
    if thermal_event:
        dTs = (th.get("t_surf_est_c") or 0) - (th.get("t_base_c") or 0)
        dh_th = tc["alpha_pla_per_k"] * tc["cell_length_mm"] * max(0.0, dTs)
        detail = (f"air {th.get('dT_c', 0):+.1f} C, est. surface {dTs:+.1f} C, geometry unchanged "
                  f"(expected expansion {dh_th:.3f} mm)")
        return _finish(res, "THERMAL", detail, watch, cfg, der, detail, t_alarm)
    if watch:
        return _finish(res, "WATCH", ", ".join(f"slot {s} +{der['r'][s - 1]:.2f} mm" for s in watch), watch, cfg, der, None, t_alarm)
    # 9. AI anomaly
    margin = cfg.get("model", {}).get("if_margin", -0.08)
    if ai and ai.get("scan") is not None:
        thr_c = min(ai.get("thr_cell", margin), margin)   # learned on this rig, never laxer than if_margin
        thr_s = min(ai.get("thr_scan", margin), margin)
        bad_cells = [i + 1 for i, s in enumerate(ai.get("cell") or []) if s is not None and s < thr_c]
        if ai["scan"] < thr_s or bad_cells:
            return _finish(res, "ANOMALY", f"AI score scan {ai['scan']:.3f}, cells {bad_cells}", bad_cells, cfg, der, None, t_alarm)
    return _finish(res, "OK", "all cells within limits", [], cfg, der, None, t_alarm)


def _finish(res, verdict, reason, slots, cfg, der, detail, t_alarm):
    res["verdict"], res["reason"], res["verdict_slots"] = verdict, reason, list(slots)
    th = res.get("thermal") or {}
    cond = th.get("surf_minus_dew_c") is not None and th["surf_minus_dew_c"] < cfg["thermal"]["dew_margin_c"]
    res["condensation_risk"] = bool(cond)
    sev, text = action(verdict, slots[0] if slots else None,
                       (der["r"][slots[0] - 1] if der and slots and der["r"][slots[0] - 1] is not None else None),
                       t_alarm, detail or "")
    res["severity"], res["action"] = sev, text
    if cond:
        res["action"] += " | " + action("CONDENSATION")[1]
    # per-cell lines
    meas = res["meas"]
    station_fault = verdict in ("OBSTRUCTED", "LIGHTING", "CAMERA_MOVED", "NOT_CALIBRATED", "VISION_OFFLINE")
    bars, cells_out = [], []
    cells = meas.get("cells") or [{"slot": i + 1, "status": "no_edge"} for i in range(4)]
    for i, c in enumerate(cells):
        r = der["r"][i] if der else None
        if c.get("status") == "missing":
            cv, cs, ca = "MISSING", *action("MISSING", c["slot"])
        elif station_fault or c.get("status") != "ok" and r is None:
            cv, cs, ca = "NO_VERDICT", "INFO", "No cell verdict (station fault)."
        elif c["slot"] in slots and verdict in ("SWELL", "RESEAT", "WATCH", "ANOMALY", "RECOVERED"):
            cv = verdict
            cs, ca = action(verdict, c["slot"], r, t_alarm)
        else:
            cv, cs, ca = "OK", *action("OK")
        cells_out.append({**c, "rel_mm": r, "verdict": cv, "severity": cs, "action": ca,
                          "if_cell_score": (res["ai"] or {}).get("cell", [None] * 4)[i] if res.get("ai") and
                          i < len((res["ai"] or {}).get("cell") or []) else None})
        if c.get("status") == "missing":
            bars.append(-8)
        elif station_fault or r is None:
            bars.append(-1)
        else:
            bars.append(int(max(1, min(8, round(max(r, 0.0) / (t_alarm / 3))))))
    res["cells"] = cells_out
    res["bars"] = bars
    res["beep"] = 3 if verdict == "SWELL" else (1 if verdict == "OK" else 2)
    res["severity_rank"] = SEVERITY_ORDER.index(sev) if sev in SEVERITY_ORDER else 0
    res.pop("meas", None)
    res["scan_ms"] = meas.get("scan_ms")
    res["frames"] = meas.get("frames")
    res["calib_id"] = meas.get("calib_id")
    res["fiducial_shift_px"] = meas.get("fiducial_shift_px")
    res["sky_mean"] = meas.get("sky_mean")
    return res
