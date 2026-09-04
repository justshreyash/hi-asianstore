"""
Standalone Hindi Stream Integration API Server
==============================================
Zero-dependency HTTP API microserver with full CORS support.
Run this alongside your streaming website or on your backend server:

    python api_server.py --port 8080

Endpoints:
    GET /api/hindi/list
        Lists all dramas available in Hindi in the database.

    GET /api/hindi/check?tmdb_id=297640&season=1&episode=1
        Fast check: returns whether Hindi dub is available in the database.

    GET /api/hindi/stream?tmdb_id=297640&season=1&episode=1
        On-the-fly resolver: checks database and dynamically resolves fresh
        master.m3u8 token URL directly.
"""

import sys
import json
import argparse
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from pathlib import Path

# Import the service from current folder
from hindi_stream_service import HindiStreamService

service = HindiStreamService()


class HindiApiHandler(BaseHTTPRequestHandler):
    def _send_cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Requested-With")

    def do_OPTIONS(self):
        self.send_response(204)
        self._send_cors_headers()
        self.end_headers()

    def _send_json(self, status_code: int, data: dict):
        body = json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._send_cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        params = parse_qs(parsed.query)

        # Serve demo HTML if root or /demo
        if path == "" or path == "/" or path == "/demo":
            demo_path = Path(__file__).resolve().parent / "demo_stream_player.html"
            if demo_path.exists():
                html = demo_path.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(html)))
                self._send_cors_headers()
                self.end_headers()
                self.wfile.write(html)
                return

        # 1. List available dramas
        if path == "/api/hindi/list":
            try:
                dramas = service.list_dramas()
                self._send_json(200, {"status": "success", "count": len(dramas), "dramas": dramas})
            except Exception as e:
                self._send_json(500, {"status": "error", "message": str(e)})
            return

        # 2. Check Hindi availability
        if path == "/api/hindi/check":
            tmdb_id = params.get("tmdb_id", [None])[0]
            season = int(params.get("season", [1])[0])
            episode = int(params.get("episode", [1])[0])

            if not tmdb_id:
                self._send_json(400, {"status": "error", "message": "Missing 'tmdb_id' query parameter"})
                return

            try:
                tmdb_int = int(tmdb_id)
                res = service.check_availability(tmdb_int, season=season, episode=episode)
                self._send_json(200, res)
            except Exception as e:
                self._send_json(500, {"status": "error", "message": str(e)})
            return

        # 3. Resolve fresh M3U8 on the fly
        if path == "/api/hindi/stream" or path == "/api/hindi/resolve":
            tmdb_id = params.get("tmdb_id", [None])[0]
            season = int(params.get("season", [1])[0])
            episode = int(params.get("episode", [1])[0])

            if not tmdb_id:
                self._send_json(400, {"status": "error", "message": "Missing 'tmdb_id' query parameter"})
                return

            try:
                tmdb_int = int(tmdb_id)
                res = service.resolve_stream(tmdb_int, season=season, episode=episode)
                self._send_json(200, res)
            except Exception as e:
                self._send_json(500, {"status": "error", "message": str(e)})
            return

        # 404
        self._send_json(404, {"status": "error", "message": f"Endpoint not found: {path}"})

    def log_message(self, format, *args):
        # Clean compact logging
        sys.stdout.write(f"[{self.log_date_time_string()}] {self.command} {self.path} -> {args[1]}\n")
        sys.stdout.flush()


def run_server(port: int = 8080, host: str = "0.0.0.0"):
    server_address = (host, port)
    httpd = ThreadingHTTPServer(server_address, HindiApiHandler)
    print("=" * 70)
    print(f"[+] HINDI STREAM INTEGRATION API SERVER")
    print(f"[*] Running at: http://127.0.0.1:{port}")
    print(f"[*] Endpoints:")
    print(f"    - Check Hindi Availability : http://127.0.0.1:{port}/api/hindi/check?tmdb_id=297640&episode=1")
    print(f"    - On-The-Fly M3U8 Stream   : http://127.0.0.1:{port}/api/hindi/stream?tmdb_id=297640&episode=1")
    print(f"    - List Available Dramas    : http://127.0.0.1:{port}/api/hindi/list")
    print(f"    - Interactive Demo Player  : http://127.0.0.1:{port}/demo")
    print("=" * 70)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[!] Shutting down server.")
        httpd.server_close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Hindi Stream Integration API")
    parser.add_argument("--port", type=int, default=8080, help="Port to listen on (default: 8080)")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="Host interface (default: 0.0.0.0)")
    args = parser.parse_args()
    run_server(port=args.port, host=args.host)
