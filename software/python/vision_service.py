"""Plan a': run the camera + measurement NATIVELY on the UNO Q (outside App Lab).

Use this only if the App Lab app cannot open the webcam. Start it in the board
terminal (see GUIDE.md part 8):

    ~/breathe-venv/bin/python vision_service.py

It listens on port 8765. The App Lab app (camera.source: auto or service) talks to it.
Debug with:  curl http://127.0.0.1:8765/health   and   curl http://127.0.0.1:8765/scan
"""
import json
import sys
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from breathe import config, vision

cfg = config.load()
if cfg["camera"].get("source") in ("auto", "service"):
    cfg["camera"]["source"] = "v4l2"
station = vision.Station(cfg).open()
print(f"[service] camera {station.cam.device} open; listening on :8765")


class H(BaseHTTPRequestHandler):
    def log_message(self, fmt, *a):
        sys.stderr.write("[service] " + fmt % a + "\n")

    def _send(self, obj, code=200):
        body = json.dumps(obj, default=str).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            return self._send({"ok": True, "device": station.cam.device})
        if self.path == "/scan":
            return self._send({"schema": "breathe.scan_features.v1", "source": "unoq-native", **station.scan()})
        if self.path == "/status":
            return self._send(station.status())
        self._send({"error": "not found"}, 404)

    def do_POST(self):
        if not self.path.startswith("/call/"):
            return self._send({"error": "not found"}, 404)
        name = self.path[len("/call/"):]
        if name not in vision.RemoteStation.METHODS:
            return self._send({"error": "unknown method"}, 400)
        n = int(self.headers.get("Content-Length", 0))
        args = json.loads(self.rfile.read(n) or b"{}").get("args", [])
        try:
            self._send(getattr(station, name)(*args))
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            self._send({"ok": False, "error": str(e)}, 500)


ThreadingHTTPServer(("0.0.0.0", 8765), H).serve_forever()
