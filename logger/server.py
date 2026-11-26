import hmac
import json
import os
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

LOG_FILE = Path("/data/logs/inspector.jsonl")
MAX_REQUEST_SIZE = 1_000_000
MAX_LOG_BYTES = int(os.environ.get("INSPECTOR_MAX_LOG_BYTES", str(100 * 1024 * 1024)))

INSPECTOR_KEY = os.environ.get("INSPECTOR_KEY", "")

write_lock = threading.Lock()


def check_log_writable() -> bool:
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with LOG_FILE.open("a", encoding="utf-8"):
            pass
        return True
    except OSError:
        return False


class LoggerHandler(BaseHTTPRequestHandler):
    # Drop slow or stalled clients instead of holding a thread forever.
    timeout = 10

    def _respond(self, code: int, body: bytes = b"") -> None:
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            if check_log_writable():
                self._respond(200, b"OK")
            else:
                self._respond(503, b"Log directory not writable")
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path != "/event":
            self.send_error(404)
            return

        # Authenticate before reading the request body.
        # Compare as bytes: compare_digest raises TypeError on non-ASCII str.
        auth = self.headers.get("Authorization", "").encode("utf-8", "replace")
        expected = f"Bearer {INSPECTOR_KEY}".encode("utf-8")

        if not INSPECTOR_KEY or not hmac.compare_digest(auth, expected):
            self.send_error(401, "Unauthorized")
            return

        try:
            raw_length = self.headers.get("Content-Length")
            if raw_length is None:
                self.send_error(411, "Content-Length required")
                return

            try:
                length = int(raw_length)
            except ValueError:
                self.send_error(400, "Invalid Content-Length")
                return

            if length <= 0:
                self.send_error(400, "Empty request body")
                return
            if length > MAX_REQUEST_SIZE:
                self.send_error(413, "Request too large")
                return

            body = self.rfile.read(length)
            if len(body) != length:
                self.send_error(400, "Incomplete request body")
                return

            event = json.loads(body)  # UnicodeDecodeError/JSONDecodeError are ValueErrors

            if not isinstance(event, dict):
                self.send_error(400, "Expected a JSON object")
                return

            entry = {
                "received_at": datetime.now(timezone.utc).isoformat(),
                "event": event,
            }
            encoded = (json.dumps(entry, ensure_ascii=False) + "\n").encode("utf-8")

            limit_reached = False
            with write_lock:
                LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
                current_size = LOG_FILE.stat().st_size if LOG_FILE.exists() else 0

                if current_size + len(encoded) > MAX_LOG_BYTES:
                    limit_reached = True
                else:
                    with LOG_FILE.open("ab") as f:
                        f.write(encoded)

            if limit_reached:
                self.send_error(507, "Inspector log size limit reached")
                return

            self._respond(200, b"OK")

        except ValueError:
            self.send_error(400, "Invalid request")
        except OSError:
            self.send_error(500, "Could not write event")

    def log_message(self, format, *args):
        # Avoid duplicating every event in Docker's ordinary logs.
        pass


if __name__ == "__main__":
    if not INSPECTOR_KEY:
        raise SystemExit("FATAL: INSPECTOR_KEY is not set")
    if not check_log_writable():
        raise SystemExit("FATAL: Log file is not writable")

    server = ThreadingHTTPServer(("0.0.0.0", 9000), LoggerHandler)
    server.serve_forever()