"""The Linux metrics bridge forwards /metrics and nothing else: containers must not reach the auth-off console."""
import sys
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.metrics_bridge import make_server  # noqa: E402


class FakeKavach(BaseHTTPRequestHandler):
    def do_GET(self):
        body = b"kavach_decisions_total 3\n"
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; version=0.0.4")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_):
        pass


def serve(server):
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def status(url, method="GET"):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, method=method), timeout=5) as r:
            return r.status, r.read(), r.headers.get("Content-Type")
    except urllib.error.HTTPError as e:
        return e.code, e.read(), e.headers.get("Content-Type")


def test_forwards_metrics_only():
    upstream = serve(HTTPServer(("127.0.0.1", 0), FakeKavach))
    bridge = serve(make_server("127.0.0.1", 0, f"http://127.0.0.1:{upstream.server_port}"))
    base = f"http://127.0.0.1:{bridge.server_port}"
    try:
        code, body, kind = status(base + "/metrics")
        assert (code, body) == (200, b"kavach_decisions_total 3\n") and kind.startswith("text/plain; version=0.0.4")
        for path in ("/", "/api/hitl", "/api/kill", "/mcp", "/metrics/../api/hitl", "/metrics?x=1"):
            assert status(base + path)[0] == 404, path
        assert status(base + "/mcp", "POST")[0] == 501           # GET is the only method it knows
        assert status(base + "/api/kill", "DELETE")[0] == 501
    finally:
        bridge.shutdown()
        upstream.shutdown()


def test_kavach_down_is_a_failed_scrape():
    with HTTPServer(("127.0.0.1", 0), FakeKavach) as closed:
        port = closed.server_port                                # nothing listens here once it closes
    bridge = serve(make_server("127.0.0.1", 0, f"http://127.0.0.1:{port}"))
    try:
        assert status(f"http://127.0.0.1:{bridge.server_port}/metrics")[0] == 502
    finally:
        bridge.shutdown()
