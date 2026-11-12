"""Serve the examples folder with a dynamic index of its reports."""

from __future__ import annotations

import argparse
import json
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

DIRECTORY = Path(__file__).resolve().parent
REPORTS_PATH = "/__reports.json"


class Handler(SimpleHTTPRequestHandler):
    """Serve static files plus a JSON list of this folder's reports."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(DIRECTORY), **kwargs)

    def do_GET(self):
        if self.path.split("?", 1)[0] == REPORTS_PATH:
            self._send_reports()
            return
        super().do_GET()

    def _send_reports(self):
        names = sorted(
            path.name for path in DIRECTORY.glob("*.html") if path.name != "index.html"
        )
        body = json.dumps(names).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        if REPORTS_PATH not in self.path:
            super().log_message(format, *args)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    with ThreadingHTTPServer((args.host, args.port), Handler) as server:
        print(f"Serving {DIRECTORY} at http://{args.host}:{args.port}/")
        server.serve_forever()


if __name__ == "__main__":
    main()
