"""Hour-1 camera smoke test. Run it on the UNO Q (board terminal):

    cd ~/ArduinoApps/breathe-vision        (or wherever the app folder is)
    ~/breathe-venv/bin/python tools/smoke_test.py

It finds the Arduino USB Camera, opens it at 1920x1080 MJPG, saves one frame to /tmp/smoke.jpg
and prints the frame rate it achieved.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "python"))
import cv2  # noqa: E402

from breathe import camera, config  # noqa: E402

cfg = config.load()
dev = camera.find_device(cfg["camera"].get("device", "auto"))
print("camera device:", dev)
cam = camera.V4L2Camera(cfg).open()
print("controls that worked:", cam.applied)
t0 = time.time()
for _ in range(30):
    f = cam.read_bgr()
dt = time.time() - t0
print(f"frame size {f.shape[1]}x{f.shape[0]}, {30 / dt:.1f} frames per second")
cv2.imwrite("/tmp/smoke.jpg", f)
print("saved /tmp/smoke.jpg  -> SMOKE TEST PASSED")
cam.close()
