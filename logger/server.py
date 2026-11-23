
import json
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

LOG_FILE = Path("/data/logs/inspector.jsonl")
MAX_REQUEST_SIZE = 1_000_000

write_lock = threading.Lock()


class LoggerHandler(BaseHTTPRequestHandler):

    def do_GET(self):
        if self.path == "/health":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"OK")
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path != "/event":
            self.send_error(404)
            return

        try:
            length = int(self.headers.get("Content-Length", 0))

            if length <= 0 or length > MAX_REQUEST_SIZE:
                self.send_error(413)
                return

            event = json.loads(self.rfile.read(length))

            if not isinstance(event, dict):
                self.send_error(400, "Expected a JSON object")
                return

            entry = {
                "received_at": datetime.now(timezone.utc).isoformat(),
                "event": event,
            }

            with write_lock:
                with LOG_FILE.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")

            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"OK")

        except (ValueError, json.JSONDecodeError):
            self.send_error(400, "Invalid JSON")
        except OSError:
            self.send_error(500, "Could not write event")

    def log_message(self, format, *args):
        # Avoid duplicating every event in Docker's ordinary logs.
        pass


if __name__ == "__main__":
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(("0.0.0.0", 9000), LoggerHandler)
    server.serve_forever()
