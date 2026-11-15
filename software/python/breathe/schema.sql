CREATE TABLE IF NOT EXISTS packs (pack_id TEXT PRIMARY KEY, chemistry TEXT, n_cells INT DEFAULT 4,
  created_at TIMESTAMPTZ DEFAULT now());
CREATE TABLE IF NOT EXISTS scans (scan_id UUID PRIMARY KEY, pack_id TEXT REFERENCES packs(pack_id),
  ts TIMESTAMPTZ NOT NULL, station_id TEXT NOT NULL, verdict TEXT NOT NULL,
  common_mode_mm REAL, t_air_c REAL, rh_pct REAL, t_surf_est_c REAL, t_dew_c REAL, dTdt_c_per_min REAL,
  if_scan_score REAL, inference_ms REAL, frames INT, calib_id TEXT, sw_version TEXT, raw JSONB);
CREATE TABLE IF NOT EXISTS cell_measurements (scan_id UUID REFERENCES scans(scan_id) ON DELETE CASCADE,
  slot SMALLINT CHECK (slot BETWEEN 1 AND 4), delta_mm REAL, rel_mm REAL, slope_deg REAL, lr_diff_mm REAL,
  edge_conf REAL, n_cols INT, if_cell_score REAL, status TEXT, action TEXT, severity TEXT,
  PRIMARY KEY (scan_id, slot));
CREATE TABLE IF NOT EXISTS events (event_id UUID PRIMARY KEY, scan_id UUID NULL, pack_id TEXT,
  ts TIMESTAMPTZ, kind TEXT, detail JSONB);
CREATE INDEX IF NOT EXISTS scans_pack_ts ON scans(pack_id, ts DESC);
CREATE OR REPLACE VIEW pack_health AS SELECT pack_id, max(ts) last_scan, count(*) n_scans,
  count(*) FILTER (WHERE verdict IN ('SWELL','WATCH')) n_flags FROM scans GROUP BY pack_id;
