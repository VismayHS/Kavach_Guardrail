#!/usr/bin/env python3
"""Let Prometheus in Docker scrape the live demo's KAVACH on Linux (stdlib only; scripts/demo_up.sh starts it).

    python3 scripts/metrics_bridge.py <docker-bridge-address> [--port 8000] [--upstream http://127.0.0.1:8000]

The demo's KAVACH listens on 127.0.0.1 with auth off. On Docker Desktop (macOS, Windows) a container reaches that as
host.docker.internal; on Linux that name is Docker's bridge address, where nothing listens, so the target stays down
and Grafana stays empty. Binding KAVACH to the bridge too would hand every container the approvals and the kill
switch, so this forwards GET /metrics and nothing else. KAVACH being down is a 502, so Prometheus shows it as down.
"""
from __future__ import annotations

import argparse
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def make_server(bind: str, port: int, upstream: str) -> ThreadingHTTPServer:
    class Bridge(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path != "/metrics":
                return self.reply(404, b"only /metrics is forwarded\n")
            try:
                with urllib.request.urlopen(upstream.rstrip("/") + "/metrics", timeout=4) as r:
                    self.reply(r.status, r.read(), r.headers.get("Content-Type", "text/plain"))
            except (urllib.error.URLError, OSError) as e:
                self.reply(502, f"KAVACH is not answering: {e}\n".encode())

        def reply(self, status: int, body: bytes, kind: str = "text/plain"):
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_):      # Prometheus scrapes every 5 s
            pass

    return ThreadingHTTPServer((bind, port), Bridge)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("bind")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--upstream", default="http://127.0.0.1:8000")
    a = ap.parse_args()
    make_server(a.bind, a.port, a.upstream).serve_forever()
