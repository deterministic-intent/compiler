#!/usr/bin/env python3
"""
Deterministic fixture HTTP server for Step 19 harness.

- Serves static files from scripts/fixtures/www/
- Binds to 127.0.0.1 on a fixed port (default 8765).
- Writes fixed headers (no Date header) to avoid variable responses.
- Logs nothing except a single READY line.
"""

from __future__ import annotations

import argparse
import mimetypes
import os
import signal
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Optional


BASE = Path(__file__).resolve().parents[1]
DEFAULT_ROOT = BASE / "fixtures" / "www"


def _safe_join(root: Path, rel: str) -> Optional[Path]:
    rp = (rel or "/").split("?", 1)[0].split("#", 1)[0]
    rp = rp.lstrip("/")
    if not rp:
        rp = "page1.html"
    if any(x in rp for x in ("..", "\\", "\x00")):
        return None
    p = (root / rp).resolve()
    try:
        p.relative_to(root.resolve())
    except Exception:
        return None
    return p


class Handler(BaseHTTPRequestHandler):
    server_version = "llmhub-fixture-http/1.0"
    sys_version = ""

    def log_message(self, format, *args):
        return

    def do_GET(self):
        root = Path(getattr(self.server, "fixture_root"))

        # Health endpoint for harness readiness polling.
        if self.path.split("?", 1)[0].split("#", 1)[0] == "/health":
            body = b"ok\n"
            self.send_response_only(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            _maybe_stop_server(self.server)
            return

        p = _safe_join(root, self.path)
        if not p or not p.exists() or not p.is_file():
            body = b"not found\n"
            self.send_response_only(404)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            _maybe_stop_server(self.server)
            return

        body = p.read_bytes()
        ctype, _ = mimetypes.guess_type(str(p))
        if not ctype:
            ctype = "application/octet-stream"
        if ctype.startswith("text/") and "charset" not in ctype:
            ctype = ctype + "; charset=utf-8"

        self.send_response_only(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)
        _maybe_stop_server(self.server)


def _maybe_stop_server(server: HTTPServer) -> None:
    max_req = int(getattr(server, "max_requests", 0) or 0)
    if max_req <= 0:
        return
    n = int(getattr(server, "request_count", 0) or 0) + 1
    setattr(server, "request_count", n)
    if n >= max_req:
        threading.Thread(target=server.shutdown, daemon=True).start()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--root", default=str(DEFAULT_ROOT))
    ap.add_argument("--max-requests", type=int, default=0, help="If >0, exit after serving this many requests")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    root.mkdir(parents=True, exist_ok=True)

    httpd = HTTPServer(("127.0.0.1", int(args.port)), Handler)
    setattr(httpd, "fixture_root", str(root))
    setattr(httpd, "max_requests", int(args.max_requests or 0))
    setattr(httpd, "request_count", 0)

    def _handle_term(signum, frame):
        try:
            httpd.shutdown()
        except Exception:
            pass

    signal.signal(signal.SIGTERM, _handle_term)
    signal.signal(signal.SIGINT, _handle_term)

    # Exactly one READY line, then serve forever.
    # IMPORTANT: stdout is piped in harness, so flush explicitly to avoid deadlocks.
    print(f"FIXTURE_HTTP_READY: http://127.0.0.1:{int(args.port)}/", flush=True)
    httpd.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


