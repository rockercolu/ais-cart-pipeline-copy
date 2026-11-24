"""Vercel function: POST /api/ad. All logic lives in aiscart/web.py."""
import sys
from http.server import BaseHTTPRequestHandler
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from aiscart.web import handle  # noqa: E402

ROUTE = "/api/ad"


class handler(BaseHTTPRequestHandler):
    def _run(self, method):
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n) if n else b""
        status, headers, out = handle(method, ROUTE, dict(self.headers), body)
        self.send_response(status)
        for k, v in headers.items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def do_POST(self):
        self._run("POST")

    def do_GET(self):
        self._run("GET")

    def do_OPTIONS(self):
        self._run("OPTIONS")
