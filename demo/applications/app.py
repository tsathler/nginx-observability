import json
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

APP_ID = os.environ.get("APP_ID", "unknown")


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.handle_request()

    def do_POST(self):
        self.handle_request()

    def handle_request(self):
        path = urlsplit(self.path).path
        if path == "/health":
            self.respond(200, {"app": APP_ID, "status": "ok"})
            return
        if path == "/metrics":
            body = (
                "# HELP nginx_observability_app_health Application health endpoint.\n"
                "# TYPE nginx_observability_app_health gauge\n"
                f'nginx_observability_app_health{{app="{APP_ID}"}} 1\n'
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        code = {
            "/redirect": 301,
            "/forbidden": 403,
            "/admin": 403,
            "/missing": 404,
            "/error": 500,
        }.get(path)
        if code is None:
            known_paths = {"/", "/slow", "/slower", "/redirect", "/forbidden", "/admin", "/missing", "/error"}
            code = 200 if path in known_paths else 404
        time.sleep({"/slow": 0.25, "/slower": 0.75}.get(path, 0.015))
        if code == 301:
            self.send_response(code)
            self.send_header("Location", "/")
            self.end_headers()
            return
        self.respond(code, {"app": APP_ID, "path": path, "status": code})

    def respond(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_):
        pass


ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
