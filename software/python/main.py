"""BREATHE Vision - App Lab Python app (runs on the UNO Q's Linux side).

Flow: knob / dashboard -> event queue -> this loop -> camera scan -> rules + AI ->
LED matrix + buzzer (via Bridge) -> dashboard -> SQLite outbox -> Aiven PostgreSQL.
"""
import os
import queue
import sys
import threading
import time
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # so "breathe" is always found

try:                                              # on the UNO Q (App Lab)
    from arduino.app_utils import App, Bridge
    from arduino.app_bricks.web_ui import WebUI
    ON_BOARD = True
except ImportError:                               # on a laptop: stand-ins
    from breathe.devshim import App, Bridge, WebUI
    ON_BOARD = False

from breathe import config, decide, model, store, thermal, vision
from breathe import wizard as wizard_mod

cfg = config.load()
MODEL_PATH = f"{cfg['_data_dir']}/models/if_v1.joblib"
events: "queue.Queue[tuple]" = queue.Queue()
th = thermal.Thermal(tau_filter=cfg["thermal"]["tau_filter_s"], tau_module=cfg["thermal"]["tau_module_s"],
                     location=cfg["thermal"].get("sensor_location", ""))
db = store.Store(cfg)
models = model.load_or_none(MODEL_PATH)
memory: dict = {}                                 # reseat-confirmation memory for the rules
state = {"last": None, "slot_sel": 1, "busy": None, "message": "Starting...", "calib_mode": False,
         "history": [], "baseline_thermal": [], "ai": None, "knob_events": 0}

station = None
station_error = None


def connect_station():
    global station, station_error
    try:
        station = vision.make_station(cfg)
        station_error = None
        print(f"[main] vision ready: {station.mode}")
        state["message"] = f"Vision ready ({station.mode}). " + (
            "Calibrated." if station.status().get("baseline_ok") else "Not calibrated yet - see Calibration panel.")
    except Exception as e:  # noqa: BLE001
        station, station_error = None, str(e)
        state["message"] = f"VISION OFFLINE: {e}"
        print("[main] VISION OFFLINE:", e)


# ------------------------------------------------------------ MCU helpers
def mcu(name, *args):
    try:
        Bridge.notify(name, *args)
    except Exception as e:  # noqa: BLE001
        print(f"[main] Bridge.notify({name}) failed: {e}")


def show(bars, flags):
    b = [int(x) for x in (list(bars) + [0, 0, 0, 0])[:4]]
    mcu("show_cells", b[0], b[1], b[2], b[3], int(flags))


# ----------------------------------------------- callbacks from the MCU
# These run in the Bridge thread: NEVER call Bridge.call() here. Only queue work.
def on_thermo(t, rh):
    th.update(float(t), float(rh))


def on_knob(kind, val):
    events.put((str(kind), int(val)))


Bridge.provide("thermo", on_thermo)
Bridge.provide("knob", on_knob)


# ------------------------------------------------------------- the work
def ai_scores(meas, der, thsnap):
    if not models or not meas.get("ok"):
        return None
    feats, idx = [], []
    for i, (c, r) in enumerate(zip(meas["cells"], der["r"])):
        if r is not None:
            feats.append([r, (c["delta_mm"] or 0) - (der["c"] or 0), c["slope_deg"] or 0.0, c["lr_diff_mm"] or 0.0,
                          c["edge_conf"] or 0.0, c["mad_mm"] or 0.0])
            idx.append(i)
    s_cell, s_scan, ms = model.score(models, feats, decide.scan_features(meas, der, thsnap))
    cell = [None] * 4
    for i, s in zip(idx, s_cell):
        cell[i] = s
    thr_cell, thr_scan = model.thresholds(models)
    return {"cell": cell, "scan": s_scan, "ms": ms, "thr_cell": thr_cell, "thr_scan": thr_scan}


def do_scan():
    if station is None:
        connect_station()
        if station is None:
            res = decide.classify({"ok": False, "error": station_error}, th.snapshot(), cfg, memory)
            publish(res)
            return res
    show([0, 0, 0, 0], decide.FLAG_SCANNING)
    state["busy"] = "scanning"
    try:
        meas = station.scan()
    except Exception as e:  # noqa: BLE001  (camera unplugged / vision service unreachable)
        meas = {"ok": False, "error": f"vision link lost: {e}"}
    finally:
        state["busy"] = None
    thsnap = th.snapshot()
    ai = None
    if meas.get("ok"):
        ai = ai_scores(meas, decide.derived(meas), thsnap)
    res = decide.classify(meas, thsnap, cfg, memory, ai)
    publish(res)
    if res["verdict"] not in ("OK",) and meas.get("ok"):
        try:
            station.save_evidence(f"{time.strftime('%Y%m%d-%H%M%S')}_{res['verdict']}")
        except Exception:  # noqa: BLE001
            pass
    if res["verdict"] not in ("NOT_CALIBRATED", "VISION_OFFLINE"):
        db.enqueue_scan(cfg["pack_id"], res)
    return res


def publish(res):
    show(res["bars"], res["flags"])
    mcu("beep", int(res["beep"]))
    state["last"] = res
    state["history"] = ([{"ts": res["ts"], "verdict": res["verdict"], "reason": res["reason"]}] + state["history"])[:20]
    state["message"] = f"{res['verdict']}: {res['reason']}"
    print(f"[scan] {res['verdict']} - {res['reason']}")


def run_calib(step, arg=None):
    global models
    if station is None:
        connect_station()
        if station is None:
            state["message"] = "VISION OFFLINE - cannot calibrate"
            return
    show([0, 0, 0, 0], decide.FLAG_SCANNING)
    state["busy"] = step
    try:
        if step == "focus":
            r = station.focus_sweep()
            msg = f"Focus sweep: best = {r.get('best')}. {r.get('note', '')}"
        elif step == "geometry":
            r = station.calibrate_geometry()
            state["baseline_thermal"] = []
            msg = (f"Geometry fitted: median error {r['fit_median_px']} px (RMS {r['fit_rms_px']}), lens z = {r['cam']['Zc']:.1f} mm "
                   f"({r['lens_vs_tops']} the cell tops), usable columns per slot {r['n_cols']}. "
                   + (" WARNINGS: " + "; ".join(r["warnings"]) if r.get("warnings") else "Looks good."))
        elif step == "baseline_add":
            r = station.add_baseline()
            if r.get("ok"):
                state["baseline_thermal"].append(th.snapshot())
                msg = f"Baseline scan {r['n']} saved (edge confidence {r['edge_conf']}). Reseat cells every 4 scans."
            else:
                msg = r.get("error")
        elif step == "baseline_finish":
            r = station.finish_baseline()
            if r.get("ok"):
                th.set_base()
                msg = (f"Baseline from {r['n']} scans. Reseat sigma per slot {r['sigma_reseat_mm']} mm, "
                       f"relative sigma {r['sigma_rel_mm']} mm -> alarm at {r['t_alarm_mm']} mm, watch at {r['t_watch_mm']} mm. ")
                msg += train_ai(r["measurements"])
            else:
                msg = r.get("error")
        elif step == "baseline_reset":
            station.reset_baseline()
            state["baseline_thermal"] = []
            msg = "Baseline scans cleared."
        elif step == "fov":
            r = station.measure_fov()
            msg = ((f"Field of view measured: {r['hfov_deg']}° wide (the datasheet value was {r['old_hfov_deg']}°). "
                    "Saved. The placement guide now uses it."
                    + (" You calibrated with the old value: run the calibration wizard again." if r.get("recalibrate") else ""))
                   if r.get("ok") else r.get("error"))
        elif step == "reanchor":
            r = station.reanchor()
            msg = (f"Re-anchored to the new camera position (fit error {r['fit_median_px']} px, lens z = {r['lens_z']} mm, "
                   f"columns {r['n_cols']}). Thresholds, scale and AI kept. Scan again." if r.get("ok") else r.get("error"))
            memory.pop("pending_reseat", None)
        elif step == "scale":
            r = station.calibrate_scale(int(arg))
            msg = (f"Slot {arg}: fault cell measured +{r['raw_rel_mm']} mm -> scale {r['k_scale']} "
                   f"(placements: {r['placements']}). Neighbours {r['others_mm']} mm." if r.get("ok") else r.get("error"))
        else:
            msg = f"unknown step {step}"
        state["message"] = msg
        print("[calib]", msg)
        mcu("beep", 1 if "error" not in msg.lower() else 2)
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        state["message"] = f"Calibration step '{step}' failed: {e}"
        mcu("beep", 2)
    finally:
        state["busy"] = None
        show([0, 0, 0, 0], 0)


def train_ai(measurements):
    global models
    X_cell, X_scan, groups = [], [], []
    ths = state["baseline_thermal"] or [th.snapshot()] * len(measurements)
    for n, (m, ts) in enumerate(zip(measurements, ths + [th.snapshot()] * max(0, len(measurements) - len(ths)))):
        m = {**m, "ok": True}
        der = decide.derived(m)
        cf = decide.cell_features(m, der)
        X_cell += cf
        groups += [n] * len(cf)
        ts = {**ts, "dT_c": 0.0}
        X_scan.append(decide.scan_features(m, der, ts))
    if len(X_scan) < cfg["model"]["min_train"]:
        return f"AI not trained: need {cfg['model']['min_train']} baseline scans (have {len(X_scan)})."
    m = model.train(X_cell, X_scan, MODEL_PATH, cell_groups=groups,
                    cell_noise=decide.CELL_FEATURE_NOISE, scan_noise=decide.SCAN_FEATURE_NOISE)
    models = m
    return f"AI (Isolation Forest) trained on {m['n_scan']} scans / {m['n_cell']} cells in {m['train_ms']} ms."


class _WizardOps:
    """What the step-by-step calibration wizard is allowed to do."""

    def is_synthetic(self):
        return station is not None and station.mode == "synthetic"

    def sim(self, action, slot=0):
        station.sim(action, slot)

    def focus(self):
        return station.focus_sweep()

    def geometry(self):
        state["baseline_thermal"] = []
        return station.calibrate_geometry()

    def baseline_reset(self):
        state["baseline_thermal"] = []
        return station.reset_baseline()

    def baseline_add(self):
        r = station.add_baseline()
        if r.get("ok"):
            state["baseline_thermal"].append(th.snapshot())
        return r

    def baseline_finish(self):
        r = station.finish_baseline()
        if r.get("ok"):
            th.set_base()
            r["ai_text"] = train_ai(r["measurements"])
            memory.pop("pending_reseat", None)
        return r

    def scale(self, slot):
        return station.calibrate_scale(int(slot))

    def test_scan(self):
        return do_scan() or {}


wiz = wizard_mod.Wizard(_WizardOps())


def run_wizard(action):
    if station is None:
        connect_station()
        if station is None and action != "cancel":
            state["message"] = "VISION OFFLINE - the camera must work before calibrating"
            return
    state["busy"] = "calibration"
    show([0, 0, 0, 0], decide.FLAG_SCANNING)
    try:
        getattr(wiz, action)()
    finally:
        state["busy"] = None
    r = wiz.result
    if wiz.active and wiz.step == "scale":
        bars = [8 if i + 1 == wiz.slot else 0 for i in range(4)]     # LED matrix: which slot to use
        show(bars, 0)
    elif wiz.step != "done":
        show([0, 0, 0, 0], 0)
    if r is not None and action in ("act", "skip"):
        mcu("beep", 1 if r.get("ok") else 2)
        state["message"] = ("✓ " if r.get("ok") else "⚠ ") + r.get("text", "")


def handle(kind, val):
    if kind == "short":
        if wiz.active:
            run_wizard("act")          # knob = the wizard's big button
        else:
            do_scan()
    elif kind == "long":
        if not wiz.active:
            run_wizard("start")
            state["message"] = "Calibration started: follow the steps on the dashboard (short press = the big button)."
    elif kind == "wizard":
        run_wizard(val)
    elif kind == "rotate":
        state["slot_sel"] = (state["slot_sel"] - 1 + val) % 4 + 1
        state["knob_events"] += 1
    elif kind == "calib":
        run_calib(*val) if isinstance(val, tuple) else run_calib(val)
    elif kind == "reconnect":
        connect_station()


# ------------------------------------------------------- dashboard API
def api_state():
    st = None
    if station is not None:
        try:
            st = station.status()
        except Exception as e:  # noqa: BLE001
            st = {"error": str(e)}
    return {"last": state["last"], "message": state["message"], "busy": state["busy"],
            "calib_mode": state["calib_mode"], "slot_sel": state["slot_sel"], "history": state["history"],
            "station": st, "station_error": station_error, "thermal": th.snapshot(),
            "chart": list(th.chart)[-300:], "db": db.status(), "ai_trained": bool(models),
            "on_board": ON_BOARD, "pack_id": cfg["pack_id"], "queue": events.qsize(), "camera": state["camera"],
            "wizard": wiz.screen()}


_placement_last = {"status": None}


def api_placement():
    """Live camera-placement check for the dashboard panel. Beeps once when the camera becomes OK."""
    if station is None:
        return {"status": "lost", "headline": f"Vision offline: {station_error}", "steps": []}
    if state["busy"]:
        return {"busy": True}
    try:
        r = station.placement_check()
    except Exception as e:  # noqa: BLE001
        return {"status": "lost", "headline": f"Placement check failed: {e}", "steps": []}
    if r.get("status") == "ok" and _placement_last["status"] not in (None, "ok"):
        mcu("beep", 1)                                   # audible "you can let go now"
    if r.get("status"):
        _placement_last["status"] = r["status"]
    return r


def api_snapshot():
    if station is None:
        return {"jpg": None, "error": station_error}
    try:
        return station.snapshot_b64()
    except Exception as e:  # noqa: BLE001
        return {"jpg": None, "error": str(e)}


ui = WebUI()
ui.expose_api("GET", "/api/state", api_state)
ui.expose_api("GET", "/api/snapshot", api_snapshot)
ui.expose_api("GET", "/api/placement", api_placement)
for _act in ("start", "act", "skip", "cancel"):
    ui.expose_api("GET", f"/api/wizard/{_act}", (lambda a: lambda: (events.put(("wizard", a)), {"queued": a})[1])(_act))
ui.expose_api("GET", "/api/scan", lambda: (events.put(("short", 0)), {"queued": True})[1])
ui.expose_api("GET", "/api/reconnect", lambda: (events.put(("reconnect", 0)), {"queued": True})[1])
ui.expose_api("GET", "/api/aiven", lambda: db.query_health(cfg["pack_id"]))
ui.expose_api("GET", "/api/thermal_reset", lambda: (th.set_base(), {"ok": True})[1])
for step in ("focus", "geometry", "baseline_add", "baseline_finish", "baseline_reset", "reanchor", "fov"):
    ui.expose_api("GET", f"/api/calib/{step}", (lambda s: lambda: (events.put(("calib", s)), {"queued": s})[1])(step))
for n in (1, 2, 3, 4):
    ui.expose_api("GET", f"/api/calib/scale{n}",
                  (lambda k: lambda: (events.put(("calib", ("scale", k))), {"queued": f"scale{k}"})[1])(n))
    for act in ("fault", "missing"):
        ui.expose_api("GET", f"/api/sim/{act}{n}",
                      (lambda a, k: lambda: station.sim(a, k) if station else {"ok": False})(act, n))
for act in ("normal", "reseat", "hand", "bump", "nudge", "far_off", "home"):
    ui.expose_api("GET", f"/api/sim/{act}", (lambda a: lambda: station.sim(a, 0) if station else {"ok": False})(act))


def _sim_heat(on):
    if not ON_BOARD:                       # laptop only: pretend someone breathes on the Thermo
        Bridge.fake_temp = 31.0 if on else 22.0
        Bridge.fake_rh = 90.0 if on else 45.0
    return {"ok": not ON_BOARD}


ui.expose_api("GET", "/api/sim/heat_on", lambda: _sim_heat(True))
ui.expose_api("GET", "/api/sim/heat_off", lambda: _sim_heat(False))

threading.Thread(target=connect_station, daemon=True).start()
show([0, 0, 0, 0], 0)


_last_connect = [time.time()]
_watch = {"last": time.time(), "running": False}
state["camera"] = {"ok": True, "error": None, "reconnects": 0}


def _watchdog():
    """Every few seconds, while idle, read one frame. A camera that dropped off USB is
    reconnected here, in the background, so it is ready again before the next scan."""
    try:
        h = station.health()
        if not h.get("busy"):
            was_ok = state["camera"]["ok"]
            state["camera"] = {"ok": bool(h.get("ok")), "error": h.get("error"), "reconnects": h.get("reconnects", 0)}
            if not h.get("ok"):
                state["message"] = f"Camera reconnecting... ({h.get('error')})"
            elif not was_ok:
                state["message"] = "Camera is back. Ready to scan."
                mcu("beep", 1)
    except Exception as e:  # noqa: BLE001
        state["camera"] = {"ok": False, "error": str(e), "reconnects": state["camera"].get("reconnects", 0)}
    finally:
        _watch["running"] = False


def loop():
    # keep trying to reach the camera every 10 s while it is offline
    if station is None and time.time() - _last_connect[0] > 10 and not state["busy"]:
        _last_connect[0] = time.time()
        threading.Thread(target=connect_station, daemon=True).start()
    # camera watchdog (every 8 s, never during a scan or calibration step)
    if station is not None and not state["busy"] and not _watch["running"] and time.time() - _watch["last"] > 8:
        _watch["last"], _watch["running"] = time.time(), True
        threading.Thread(target=_watchdog, daemon=True).start()
    try:
        kind, val = events.get(timeout=0.2)
    except queue.Empty:
        return
    try:
        handle(kind, val)
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        state["message"] = f"Error: {e}"


App.run(user_loop=loop)
