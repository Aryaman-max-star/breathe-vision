# AGENTS.md - instructions for coding agents (Codex) working on BREATHE Vision

## What this is
A side-silhouette check station: an Arduino USB Camera (UVC, IMX376, 80 deg dFOV) on the UNO Q
(through a powered USB-C hub) looks across the tops of four mock battery
cells against the orange printed screen of the BREATHE foundation (measured in the red channel; the
screen's left/right/top edges are the camera-moved reference). Lens may be above OR below the cell tops. The UNO Q's Linux side measures each cell's height to ~0.05 mm,
classifies the scan (rules + Isolation Forest), drives the LED matrix/buzzer on the STM32 via
the Bridge, shows a dashboard (WebUI brick, port 7000) and syncs to Aiven PostgreSQL.

## Layout
- `python/main.py` - App Lab entry point (event loop, Bridge callbacks, REST API for the dashboard)
- `python/breathe/geometry.py` - pinhole model, silhouette per column, usable column masks
- `python/breathe/vision.py` - Station: geometry fit, baseline, scale, scan; RemoteStation (HTTP)
- `python/breathe/edges.py` - sub-pixel edge per column; `fit.py` robust statistics
- `python/breathe/decide.py` - rule table (pure, ordered); `recommend.py` - action texts
- `python/breathe/thermal.py`, `model.py`, `store.py`, `synth.py` (renderer for tests), `devshim.py`
- `python/vision_service.py` - plan a' (native camera service on :8765)
- `sketch/sketch.ino` - STM32 (Zephyr) sketch: Modulinos on Wire1, LED matrix, Bridge
- `assets/` - dashboard; `tests/` - pytest

## Constants (mm)
Lens (90, -52, 49.5): camera on its own base 52 mm in front of the foundation, so the cells' back edge is at
the camera's 20 cm minimum focus distance. Calibration fits lens height/distance/sideways offset, yaw, roll and
focal length (weak priors = station.yaml). Cells 18 x 30 x 42 (fault 42.6), bottom z 3.6, front y 119.4.
Slot LEFT edges x = 52.4, 71.6, 90.8, 110.0. Terminals r 2.2, h 2.5 at 7 and 23 mm from the front.
3840x2160 (15 frames/scan), hFOV 72.4 deg -> f ~ 2620 px. 0.6 mm at the back edge (201 mm) ~ 7.8 px.
Red channel: orange screen bright, dark cells dark.

## Rules
- Keep `breathe/` functions pure where possible; type hints; no Bridge calls inside Bridge callbacks
  (queue work for `loop()`); the sketch never calls Bridge/Monitor inside provide handlers.
- Every change ships with a pytest. Use `breathe.synth` to render test images.
- Run: `python -m pytest -q tests` from the repo root. All tests must pass.
- Log every Codex prompt in `docs/CODEX_LOG.md` and commit each change separately with the prompt in the body.
