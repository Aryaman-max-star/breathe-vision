"""Arduino USB Camera (SKU TPX00246, Sony IMX376, UVC) via OpenCV/V4L2, with manual controls.

The camera is plugged into the powered USB-C hub on the UNO Q. It is a standard UVC webcam,
so the same code works with any UVC camera. Controls the camera does not offer are skipped
and reported in `applied` (shown on the dashboard).
"""
from __future__ import annotations

import glob
import os
import shutil
import subprocess
import time

import cv2
import numpy as np

SKIP_NAMES = ("venus", "qcom", "iris", "camss", "msm", "codec", "enc", "dec")


def find_device(pref: str = "auto") -> str:
    """Return a device path for the webcam. Never the Qualcomm codec nodes."""
    if pref and pref != "auto":
        return pref
    for pat in ("/dev/v4l/by-id/*[Aa]rduino*video-index0", "/dev/v4l/by-id/*[Cc]amera*video-index0",
                "/dev/v4l/by-id/*[Ww]ebcam*video-index0", "/dev/v4l/by-id/usb-*video-index0"):
        hits = sorted(glob.glob(pat))
        if hits:
            return hits[0]
    # no by-id links (e.g. inside a container): look at the names in sysfs
    for node in sorted(glob.glob("/sys/class/video4linux/video*"), key=lambda p: int(p.rsplit("video", 1)[1])):
        try:
            name = open(os.path.join(node, "name")).read().strip().lower()
            idx = open(os.path.join(node, "index")).read().strip() if os.path.exists(os.path.join(node, "index")) else "0"
        except OSError:
            continue
        if idx != "0" or any(s in name for s in SKIP_NAMES):
            continue
        return "/dev/" + os.path.basename(node)
    raise RuntimeError("No USB camera found. Is the Arduino USB Camera plugged into the POWERED hub?")


def _v4l2(dev: str, ctrl: str, value) -> bool:
    if not shutil.which("v4l2-ctl"):
        return False
    r = subprocess.run(["v4l2-ctl", "-d", dev, "-c", f"{ctrl}={value}"], capture_output=True, text=True)
    return r.returncode == 0


def _v4l2_any(dev: str, names: list[str], value) -> bool:
    return any(_v4l2(dev, n, value) for n in names)


def list_controls(dev: str) -> dict:
    """{name: (min, max, step)} from `v4l2-ctl --list-ctrls` (empty if v4l2-ctl is missing)."""
    if not shutil.which("v4l2-ctl"):
        return {}
    r = subprocess.run(["v4l2-ctl", "-d", dev, "--list-ctrls"], capture_output=True, text=True)
    out = {}
    for line in r.stdout.splitlines():
        parts = line.split()
        if not parts:
            continue
        kv = dict(p.split("=", 1) for p in parts if "=" in p)
        try:
            out[parts[0]] = (int(kv.get("min", 0)), int(kv.get("max", 0)), int(kv.get("step", 1)))
        except ValueError:
            continue
    return out


class V4L2Camera:
    is_synthetic = False

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.c = cfg["camera"]
        self.cap = None
        self.device = None
        self.focus = None            # last focus set (re-applied after a reconnect)
        self.reconnects = 0          # how often the camera dropped out and was reconnected
        self.last_drop = None
        self.last_error = None       # None while healthy

    def open(self):
        self.device = find_device(self.c.get("device", "auto"))
        cap = cv2.VideoCapture(self.device, cv2.CAP_V4L2)
        if not cap.isOpened():
            raise RuntimeError(f"OpenCV could not open {self.device}")
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*self.c.get("fourcc", "MJPG")))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.c["width"])
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.c["height"])
        cap.set(cv2.CAP_PROP_FPS, self.c.get("fps", 30))
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        if hasattr(cv2, "CAP_PROP_READ_TIMEOUT_MSEC"):      # don't hang for long on a stalled camera
            cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, 3000)
        self.cap = cap
        for _ in range(10):
            cap.read()
        ok, f = cap.read()
        if not ok or f is None:
            raise RuntimeError(f"{self.device} opened but gives no frames")
        h, w = f.shape[:2]
        if (w, h) != (self.c["width"], self.c["height"]):
            # the camera chose another size: use what it really delivers
            print(f"[camera] asked {self.c['width']}x{self.c['height']}, camera gives {w}x{h}; using {w}x{h}")
            self.c["width"], self.c["height"] = w, h
        self.controls = list_controls(self.device)
        self.apply_controls(focus=self.focus)
        self.settle()
        return self

    def settle(self, max_s: float = 6.0, frac: float = 0.015) -> bool:
        """After (re)connecting, the camera's exposure/white balance drift for a few seconds.
        Read frames until the brightness of the last 6 frames agrees within 1.5 %."""
        means, t_end = [], time.time() + max_s
        while time.time() < t_end:
            ok, f = self.cap.read()
            if not ok or f is None:
                continue
            means.append(float(f[::32, ::32].mean()))
            if len(means) >= 6:
                last = means[-6:]
                if max(last) - min(last) <= frac * max(float(np.mean(last)), 1.0):
                    self.settled = True
                    return True
        self.settled = False                    # did not settle in time: still usable, frames get checked
        return False

    def apply_controls(self, focus=None):
        """Lock focus, exposure, white balance, gain; switch the LED ring light off if the camera
        exposes a control for it. Uses v4l2-ctl if present, else OpenCV. Records what worked."""
        dev, c, cap = self.device, self.c, self.cap
        focus = c.get("focus_absolute", 200) if focus is None else focus
        self.focus = focus
        a = {}
        a["autofocus_off"] = _v4l2_any(dev, ["focus_automatic_continuous", "focus_auto"], 0)
        a["focus"] = _v4l2_any(dev, ["focus_absolute"], int(focus))
        a["manual_exposure"] = _v4l2_any(dev, ["auto_exposure", "exposure_auto"], 1)
        _v4l2_any(dev, ["exposure_dynamic_framerate", "exposure_auto_priority"], 0)
        a["exposure"] = _v4l2_any(dev, ["exposure_time_absolute", "exposure_absolute"], int(c.get("exposure_100us", 100)))
        a["gain"] = _v4l2_any(dev, ["gain"], int(c.get("gain", 0)))
        a["wb_manual"] = _v4l2_any(dev, ["white_balance_automatic", "white_balance_temperature_auto"], 0)
        _v4l2_any(dev, ["white_balance_temperature"], int(c.get("wb_k", 4500)))
        _v4l2_any(dev, ["power_line_frequency"], 1 if int(c.get("power_line_hz", 50)) == 50 else 2)
        _v4l2_any(dev, ["sharpness"], int(c.get("sharpness", 0)))
        ring = str(c.get("ring_light", "leave")).lower()
        if ring in ("on", "off"):              # the control name differs per camera; try the usual ones
            names = [n for n in (getattr(self, "controls", {}) or {}) if "led" in n or "light" in n or "torch" in n]
            names = names or ["led1_mode", "led_mode", "led", "light", "led_brightness", "illumination", "torch"]
            val = 0 if ring == "off" else 1
            ok = False
            for n in names:
                hi = (getattr(self, "controls", {}) or {}).get(n, (0, 1, 1))[1]
                ok |= _v4l2(dev, n, val if ring == "off" else max(1, hi))
            a["ring_light"] = f"{ring} {'set' if ok else 'not settable'}"
        # OpenCV fallback (works without v4l2-ctl, e.g. inside the App Lab container)
        if cap is not None:
            a["autofocus_off"] |= bool(cap.set(cv2.CAP_PROP_AUTOFOCUS, 0))
            a["focus"] |= bool(cap.set(cv2.CAP_PROP_FOCUS, int(focus)))
            a["manual_exposure"] |= bool(cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 1))     # V4L2: 1 = manual
            a["exposure"] |= bool(cap.set(cv2.CAP_PROP_EXPOSURE, int(c.get("exposure_100us", 100))))
            a["gain"] |= bool(cap.set(cv2.CAP_PROP_GAIN, int(c.get("gain", 0))))
            a["wb_manual"] |= bool(cap.set(cv2.CAP_PROP_AUTO_WB, 0))
            cap.set(cv2.CAP_PROP_WB_TEMPERATURE, int(c.get("wb_k", 4500)))
            cap.set(cv2.CAP_PROP_SHARPNESS, int(c.get("sharpness", 0)))
        self.applied = a
        return a

    def focus_values(self):
        """Values to try in the focus sweep (from the camera's own range when known)."""
        if getattr(self, "controls", None) and "focus_absolute" in self.controls:
            lo, hi, step = self.controls["focus_absolute"]
            step = max(step, (hi - lo) // 30 or 1)
            return list(range(lo, hi + 1, step))
        return list(range(0, 256, 8))

    def set_focus(self, value: int):
        self.focus = int(value)
        if not _v4l2(self.device, "focus_absolute", int(value)):
            self.cap.set(cv2.CAP_PROP_AUTOFOCUS, 0)
            self.cap.set(cv2.CAP_PROP_FOCUS, int(value))

    def read_bgr(self) -> np.ndarray:
        for attempt in range(3):
            ok, f = self.cap.read() if self.cap is not None else (False, None)
            if ok and f is not None:
                return f
            time.sleep(0.05)
        # The camera stopped sending pictures: usually it dropped off USB for a moment (power dip)
        # and came back, possibly as a different /dev/videoN. Reconnect instead of staying offline.
        last = None
        for k in range(5):
            try:
                self.close()
                time.sleep(1.0 + k)
                self.open()
                ok, f = self.cap.read()
                if ok and f is not None:
                    self.reconnects += 1
                    self.last_drop = time.time()
                    self.last_error = None
                    print(f"[camera] reconnected after a drop-out (#{self.reconnects}) on {self.device}")
                    return f
            except Exception as e:  # noqa: BLE001
                last = e
        self.last_error = f"camera not answering ({last})"
        raise RuntimeError(f"camera stopped sending pictures and could not be reconnected yet ({last}). "
                           "It keeps retrying. Check the USB cable and the hub's power.")

    def read_gray(self) -> np.ndarray:
        """One channel as float32: 'red' by default (orange screen bright, dark cells dark)."""
        f = self.read_bgr()
        ch = str(self.c.get("channel", "gray")).lower()
        idx = {"blue": 0, "green": 1, "red": 2}.get(ch)
        if idx is None:
            return cv2.cvtColor(f, cv2.COLOR_BGR2GRAY).astype(np.float32)
        return f[:, :, idx].astype(np.float32)

    def close(self):
        if self.cap is not None:
            try:
                self.cap.release()
            except Exception:  # noqa: BLE001
                pass
            self.cap = None


def frame_ok(g: np.ndarray, ref_mean: float | None = None) -> bool:
    """Reject frames damaged by a USB/power glitch: flat (blank) frames, frames whose brightness
    jumps, and frames with a large uniform block (a JPEG cut off part-way)."""
    small = g[::16, ::16]
    if float(small.std()) < 3.0:                       # blank / grey frame
        return False
    if ref_mean is not None and ref_mean > 1 and abs(float(small.mean()) - ref_mean) > 0.35 * ref_mean:
        return False                                   # sudden brightness jump
    bottom = small[-max(2, small.shape[0] // 6):]
    if float(np.ptp(bottom)) < 2 and 20 < float(bottom.mean()) < 235:   # cut-off picture: flat grey band
        return False
    return True


def grab_average(cam, n: int, discard: int = 2) -> np.ndarray:
    """Average n good grey frames (noise drops by sqrt(n)).
    Damaged frames are skipped; if the camera reconnects part-way, the average restarts so that
    frames from before and after a drop-out (possibly with different exposure) are never mixed."""
    for attempt in range(4):
        start_rc = getattr(cam, "reconnects", 0)
        for _ in range(discard):
            cam.read_gray()
        acc, got, bad, means = None, 0, 0, []
        while got < n:
            g = cam.read_gray()
            if getattr(cam, "reconnects", 0) != start_rc:
                break                                  # camera reconnected mid-average: start again
            ref = float(np.median(means)) if len(means) >= 3 else None
            if not frame_ok(g, ref):
                bad += 1
                if bad > n:                            # mostly bad frames: give up and say so
                    raise RuntimeError("camera pictures are damaged or flickering (power, cable or lighting)")
                continue
            means.append(float(g[::16, ::16].mean()))
            acc = g.astype(np.float32) if acc is None else acc + g
            got += 1
        if got == n:
            return acc / float(n)
    raise RuntimeError("camera kept dropping out during the scan")
