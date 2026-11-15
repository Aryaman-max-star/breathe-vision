import json

from breathe import config, store


def test_outbox_local_only(tmp_path, monkeypatch):
    monkeypatch.delenv("AIVEN_PG_URI", raising=False)
    cfg = config.load(data_dir=tmp_path)
    s = store.Store(cfg, start_sync=False)
    res = {"ts": 1.0e9, "scan_id": "00000000-0000-0000-0000-000000000001", "verdict": "OK", "cells": [], "thermal": {}}
    s.enqueue_scan("P1", res)
    s.enqueue_scan("P1", res)                      # same id twice -> stored once
    assert s.pending() == 1
    assert json.loads(open(next((tmp_path / "scans").glob("*.jsonl"))).readline())["verdict"] == "OK"
