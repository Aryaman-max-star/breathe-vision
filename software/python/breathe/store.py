"""Local SQLite outbox -> Aiven PostgreSQL (TLS). Data is never lost when Wi-Fi drops:
every result is written locally first and a background thread syncs it."""
from __future__ import annotations

import datetime as dt
import json
import os
import sqlite3
import threading
import time
import uuid
from pathlib import Path

try:
    import psycopg
    from psycopg.types.json import Jsonb
except Exception:  # noqa: BLE001
    psycopg = None

SCHEMA = (Path(__file__).resolve().parent / "schema.sql")


def _ts(t: float) -> dt.datetime:
    return dt.datetime.fromtimestamp(t, tz=dt.timezone.utc)


class Store:
    def __init__(self, cfg: dict, start_sync: bool = True):
        self.cfg = cfg
        self.data = Path(cfg["_data_dir"])
        self.db = sqlite3.connect(str(self.data / "outbox.db"), check_same_thread=False)
        self.db.execute("CREATE TABLE IF NOT EXISTS outbox (id TEXT PRIMARY KEY, tbl TEXT, payload TEXT, "
                        "tries INT DEFAULT 0, created REAL)")
        self.db.execute("CREATE TABLE IF NOT EXISTS sent (id TEXT PRIMARY KEY, tbl TEXT, payload TEXT, sent REAL)")
        self.db.commit()
        self.lock = threading.Lock()
        self.uri = os.environ.get("AIVEN_PG_URI", "").strip()
        self.enabled = bool(cfg.get("database", {}).get("enabled", True) and self.uri and psycopg)
        self.last_error = None if self.enabled else (
            "psycopg not installed" if not psycopg else "AIVEN_PG_URI not set in python/config/.env")
        self.last_sync = None
        self.schema_ok = False
        if self.enabled and start_sync:
            threading.Thread(target=self._sync_loop, daemon=True).start()

    # ----------------------------------------------------------------- local
    def enqueue_scan(self, pack_id: str, res: dict) -> str:
        sid = res.get("scan_id") or str(uuid.uuid4())
        th = res.get("thermal") or {}
        ai = res.get("ai") or {}
        scan = {"scan_id": sid, "pack_id": pack_id, "ts": res["ts"], "station_id": self.cfg["station_id"],
                "verdict": res["verdict"], "common_mode_mm": res.get("c_mm"), "t_air_c": th.get("t_air_c"),
                "rh_pct": th.get("rh_pct"), "t_surf_est_c": th.get("t_surf_est_c"), "t_dew_c": th.get("t_dew_c"),
                "dTdt_c_per_min": th.get("dTdt_c_per_min"), "if_scan_score": ai.get("scan"),
                "inference_ms": ai.get("ms"), "frames": res.get("frames"), "calib_id": res.get("calib_id"),
                "sw_version": "1.0.0", "raw": res}
        cells = [{"slot": c["slot"], "delta_mm": c.get("delta_mm"), "rel_mm": c.get("rel_mm"),
                  "slope_deg": c.get("slope_deg"), "lr_diff_mm": c.get("lr_diff_mm"), "edge_conf": c.get("edge_conf"),
                  "n_cols": c.get("n_cols"), "if_cell_score": c.get("if_cell_score"), "status": c.get("status"),
                  "action": c.get("action"), "severity": c.get("severity")} for c in res.get("cells", [])]
        self._put(sid, "scan_bundle", {"scan": scan, "cells": cells})
        day = time.strftime("%Y%m%d", time.localtime(res["ts"]))
        with open(self.data / "scans" / f"{day}.jsonl", "a") as f:
            f.write(json.dumps(res, default=str) + "\n")
        return sid

    def enqueue_event(self, pack_id: str, kind: str, detail: dict, scan_id: str | None = None):
        eid = str(uuid.uuid4())
        self._put(eid, "event", {"event_id": eid, "scan_id": scan_id, "pack_id": pack_id, "ts": time.time(),
                                 "kind": kind, "detail": detail})

    def _put(self, id_, tbl, payload):
        with self.lock:
            self.db.execute("INSERT OR IGNORE INTO outbox VALUES (?,?,?,0,?)",
                            (id_, tbl, json.dumps(payload, default=str), time.time()))
            self.db.commit()

    def pending(self) -> int:
        with self.lock:
            return self.db.execute("SELECT count(*) FROM outbox").fetchone()[0]

    def status(self) -> dict:
        return {"enabled": self.enabled, "pending": self.pending(), "last_error": self.last_error,
                "last_sync": self.last_sync}

    # ---------------------------------------------------------------- remote
    def connect(self):
        ca = Path(self.cfg["_config_dir"]) / "ca.pem"
        kw = dict(connect_timeout=5, application_name="breathe-vision")
        if ca.exists():
            kw.update(sslmode="verify-ca", sslrootcert=str(ca))
        else:
            kw.update(sslmode="require")
        return psycopg.connect(self.uri, **kw)

    def _ensure_schema(self, conn):
        if self.schema_ok:
            return
        conn.execute(SCHEMA.read_text())
        conn.execute("INSERT INTO packs (pack_id, chemistry) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                     (self.cfg["pack_id"], "mock-PLA"))
        conn.commit()
        self.schema_ok = True

    def sync_once(self) -> int:
        with self.lock:
            rows = self.db.execute("SELECT id, tbl, payload FROM outbox ORDER BY created LIMIT 50").fetchall()
        if not rows:
            return 0
        n = 0
        with self.connect() as conn:
            self._ensure_schema(conn)
            for id_, tbl, payload in rows:
                p = json.loads(payload)
                with conn.transaction():
                    if tbl == "scan_bundle":
                        s = p["scan"]
                        conn.execute("INSERT INTO packs (pack_id) VALUES (%s) ON CONFLICT DO NOTHING", (s["pack_id"],))
                        conn.execute(
                            "INSERT INTO scans (scan_id, pack_id, ts, station_id, verdict, common_mode_mm, t_air_c, rh_pct,"
                            " t_surf_est_c, t_dew_c, dTdt_c_per_min, if_scan_score, inference_ms, frames, calib_id,"
                            " sw_version, raw) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"
                            " ON CONFLICT DO NOTHING",
                            (s["scan_id"], s["pack_id"], _ts(s["ts"]), s["station_id"], s["verdict"], s["common_mode_mm"],
                             s["t_air_c"], s["rh_pct"], s["t_surf_est_c"], s["t_dew_c"], s["dTdt_c_per_min"],
                             s["if_scan_score"], s["inference_ms"], s["frames"], s["calib_id"], s["sw_version"],
                             Jsonb(s["raw"])))
                        for c in p["cells"]:
                            conn.execute(
                                "INSERT INTO cell_measurements (scan_id, slot, delta_mm, rel_mm, slope_deg, lr_diff_mm,"
                                " edge_conf, n_cols, if_cell_score, status, action, severity)"
                                " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                                (s["scan_id"], c["slot"], c["delta_mm"], c["rel_mm"], c["slope_deg"], c["lr_diff_mm"],
                                 c["edge_conf"], c["n_cols"], c["if_cell_score"], c["status"], c["action"], c["severity"]))
                    elif tbl == "event":
                        conn.execute("INSERT INTO events (event_id, scan_id, pack_id, ts, kind, detail)"
                                     " VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                                     (p["event_id"], p["scan_id"], p["pack_id"], _ts(p["ts"]), p["kind"], Jsonb(p["detail"])))
                with self.lock:
                    self.db.execute("DELETE FROM outbox WHERE id = ?", (id_,))
                    self.db.execute("INSERT OR REPLACE INTO sent VALUES (?,?,?,?)", (id_, tbl, payload, time.time()))
                    self.db.commit()
                n += 1
        return n

    def _sync_loop(self):
        backoff = self.cfg.get("database", {}).get("sync_every_s", 5)
        while True:
            try:
                self.sync_once()
                self.last_error = None
                self.last_sync = time.time()
                backoff = self.cfg.get("database", {}).get("sync_every_s", 5)
            except Exception as e:  # noqa: BLE001
                self.last_error = f"{type(e).__name__}: {e}"[:300]
                with self.lock:
                    self.db.execute("UPDATE outbox SET tries = tries + 1")
                    self.db.commit()
                backoff = min(60, backoff * 2)
            time.sleep(backoff)

    def query_health(self, pack_id: str) -> dict:
        """For the judges: pack_health view and the latest scans, straight from Aiven."""
        if not self.enabled:
            return {"ok": False, "error": self.last_error}
        try:
            with self.connect() as conn:
                self._ensure_schema(conn)
                ssl = conn.execute("SELECT ssl, version FROM pg_stat_ssl WHERE pid = pg_backend_pid()").fetchone()
                health = conn.execute("SELECT pack_id, last_scan, n_scans, n_flags FROM pack_health "
                                      "WHERE pack_id = %s", (pack_id,)).fetchall()
                scans = conn.execute("SELECT ts, verdict, common_mode_mm, t_air_c, if_scan_score FROM scans "
                                     "WHERE pack_id = %s ORDER BY ts DESC LIMIT 10", (pack_id,)).fetchall()
            return {"ok": True, "tls": {"ssl": ssl[0], "version": ssl[1]} if ssl else None,
                    "health": [[str(x) for x in r] for r in health],
                    "scans": [[str(x) for x in r] for r in scans]}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": f"{type(e).__name__}: {e}"[:300]}
