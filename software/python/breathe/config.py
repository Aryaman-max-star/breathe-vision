"""Loads python/config/station.yaml and python/config/.env, creates data folders."""
from __future__ import annotations

import os
from pathlib import Path

import yaml

PY_DIR = Path(__file__).resolve().parent.parent          # .../breathe-vision/python
APP_DIR = PY_DIR.parent                                  # .../breathe-vision


def _load_env(path: Path) -> None:
    """Very small .env reader: KEY=VALUE per line, # comments allowed."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


def load(path: str | os.PathLike | None = None, data_dir: str | os.PathLike | None = None) -> dict:
    cfg_path = Path(path) if path else PY_DIR / "config" / "station.yaml"
    cfg = yaml.safe_load(cfg_path.read_text())
    _load_env(cfg_path.parent / ".env")
    data = Path(data_dir) if data_dir else PY_DIR / "data"
    for sub in ("scans", "frames", "models"):
        (data / sub).mkdir(parents=True, exist_ok=True)
    if os.environ.get("BREATHE_CAMERA_SOURCE"):          # quick override for testing
        cfg["camera"]["source"] = os.environ["BREATHE_CAMERA_SOURCE"]
    cfg["_py_dir"] = str(PY_DIR)
    cfg["_config_dir"] = str(cfg_path.parent)
    cfg["_data_dir"] = str(data)
    cfg["_assets_dir"] = str(APP_DIR / "assets")
    return cfg
