#!/usr/bin/env python3
"""
AI Pulse — Zero-Dependency Local Live Server.

Serves the web/mobile app on 0.0.0.0:8090 and handles:
  - GET  /api/health  -> backend status & whether GEMINI_API_KEY is configured
  - POST /api/sync    -> runs fetch_pulse.run_sync() server-side (no CORS limits)
                         fetching live Artificial Analysis leaderboard, Yahoo Finance
                         stocks, AMFI SIP NAVs, Hacker News, RSS feeds, and Gemini brief.

Usage:
  python3 server.py
"""

from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import threading

import fetch_pulse

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8090"))
SYNC_LOCK = threading.Lock()


class PulseHandler(SimpleHTTPRequestHandler):
    """Serves static UI files plus /api/health and /api/sync endpoints."""

    def _send_json(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def end_headers(self):
        # Prevent mobile browsers from caching stale JSON or HTML
        if self.path.startswith("/data/") or self.path in ("/", "/index.html"):
            self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_GET(self):
        if self.path.split("?", 1)[0] == "/api/health":
            return self._send_json(
                200,
                {
                    "ok": True,
                    "has_server_key": bool(os.environ.get("GEMINI_API_KEY", "").strip()),
                },
            )
        return super().do_GET()

    def do_POST(self):
        if self.path.split("?", 1)[0] != "/api/sync":
            return self._send_json(404, {"ok": False, "error": "Not found"})

        api_key = None
        try:
            length = int(self.headers.get("Content-Length") or 0)
            if length > 0 and length < 8192:
                raw = self.rfile.read(length).decode("utf-8", errors="replace")
                body = json.loads(raw)
                api_key = (body.get("api_key") or "").strip() or None
        except Exception:
            pass

        if not SYNC_LOCK.acquire(blocking=False):
            return self._send_json(
                429,
                {"ok": False, "error": "Sync already in progress — please wait a few seconds."},
            )

        try:
            payload = fetch_pulse.run_sync(api_key=api_key)
            return self._send_json(200, {"ok": True, "data": payload})
        except Exception as exc:
            return self._send_json(500, {"ok": False, "error": str(exc)[:200]})
        finally:
            SYNC_LOCK.release()


def main():
    handler = partial(PulseHandler, directory=BASE_DIR)
    server = ThreadingHTTPServer((HOST, PORT), handler)
    print(f"[AI Pulse Server] Listening on http://{HOST}:{PORT}")
    print(f"[AI Pulse Server] Mac: http://localhost:{PORT}  |  Live Sync API: POST /api/sync")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[AI Pulse Server] Shutting down.")
        server.server_close()


if __name__ == "__main__":
    main()
