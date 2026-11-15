"""Stand-ins for App Lab's Bridge, App and WebUI so main.py also runs on a laptop.

Only used when `arduino.app_utils` is not importable (i.e. NOT on the UNO Q).
It serves ../assets on http://localhost:7000 and fakes the Modulino Thermo.
"""
from __future__ import annotations

import json
import math
import mimetypes
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ASSETS = Path(__file__).resolve().parent.parent.parent / "assets"


class _Bridge:
    def __init__(self):
        self.provided = {}
        self.fake_temp = 22.0
        self.fake_rh = 45.0

    def provide(self, name, fn):
        self.provided[name] = fn
        if name == "thermo":
            threading.Thread(target=self._fake_thermo, daemon=True).start()

    def _fake_thermo(self):
        t0 = time.time()
        while True:
            t = self.fake_temp + 0.05 * math.sin((time.time() - t0) / 20)
            try:
                self.provided["thermo"](t, self.fake_rh)
            except Exception as e:  # noqa: BLE001
                print("[devshim] thermo callback error", e)
            time.sleep(1.0)

    def notify(self, name, *args):
        print(f"[devshim] -> MCU {name}{args}")

    def call(self, name, *args):
        self.notify(name, *args)
        return None


Bridge = _Bridge()


class _App:
    @staticmethod
    def run(user_loop=None):
        print("[devshim] running - open http://localhost:7000  (Ctrl+C to stop)")
        while True:
            if user_loop:
                user_loop()
            else:
                time.sleep(1)


App = _App()


class WebUI:
    def __init__(self, port: int = 7000):
        self.routes = {}
        ui = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                path = urllib.parse.urlparse(self.path).path
                key = ("GET", path)
                if key in ui.routes:
                    try:
                        body = json.dumps(ui.routes[key](), default=str).encode()
                        code = 200
                    except Exception as e:  # noqa: BLE001
                        body, code = json.dumps({"error": str(e)}).encode(), 500
                    self.send_response(code)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(body)
                    return
                f = ASSETS / ("index.html" if path in ("/", "") else path.lstrip("/"))
                if f.is_file() and ASSETS in f.resolve().parents:
                    self.send_response(200)
                    self.send_header("Content-Type", mimetypes.guess_type(str(f))[0] or "application/octet-stream")
                    self.end_headers()
                    self.wfile.write(f.read_bytes())
                else:
                    self.send_response(404)
                    self.end_headers()

        self.server = ThreadingHTTPServer(("0.0.0.0", port), H)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def expose_api(self, method, path, fn):
        self.routes[(method.upper(), path)] = fn

    def send_message(self, *a, **k):
        pass

    def on_message(self, *a, **k):
        pass
