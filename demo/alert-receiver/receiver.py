"""Local-only webhook sink for exercising Grafana alert delivery."""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Lock

events = []
lock = Lock()


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/health":
            return self.respond(200, {"status": "ok"})
        if self.path == "/received":
            with lock:
                return self.respond(200, {"count": len(events), "events": list(events)})
        return self.respond(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/alerts":
            return self.respond(404, {"error": "not found"})
        try:
            payload = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
        except (ValueError, json.JSONDecodeError):
            return self.respond(400, {"error": "invalid JSON"})
        statuses = []
        for alert in payload.get("alerts", []):
            labels = alert.get("labels", {})
            statuses.append({
                "status": alert.get("status", payload.get("status", "unknown")),
                "alertname": labels.get("alertname", "unknown"),
                "app": labels.get("app", ""),
                "severity": labels.get("severity", ""),
                "component": labels.get("component", ""),
            })
        with lock:
            events.extend(statuses)
            del events[:-500]
        return self.respond(202, {"accepted": len(statuses)})

    def respond(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_):
        pass


ThreadingHTTPServer(("0.0.0.0", 8081), Handler).serve_forever()
