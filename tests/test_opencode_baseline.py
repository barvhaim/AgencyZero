"""Integration test with the pinned OpenCode CLI and a local test proxy."""

import importlib.util
import json
import shutil
import subprocess
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path



SCRIPT = Path(__file__).resolve().parents[1] / "agents/opencode/baseline.py"
SPEC = importlib.util.spec_from_file_location("baseline", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
baseline = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(baseline)


@unittest.skipUnless(shutil.which("opencode"), "requires the pinned OpenCode CLI on PATH")
class TestOpenCodeBaseline(unittest.TestCase):
    def test_local_provider_receives_only_the_synthetic_task(self):
        requests = []

        class Proxy(BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                requests.append((self.path, body))
                chunks = [
                    {"delta": {"role": "assistant", "content": "Synthetic test reply."}, "finish_reason": None},
                    {"delta": {}, "finish_reason": "stop"},
                ]
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                for choice in chunks:
                    event = {"id": "test", "object": "chat.completion.chunk", "created": 1,
                             "model": body["model"], "choices": [{"index": 0, **choice}]}
                    self.wfile.write(f"data: {json.dumps(event)}\n\n".encode())
                self.wfile.write(b"data: [DONE]\n\n")

        with ThreadingHTTPServer(("127.0.0.1", 0), Proxy) as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                code = (
                    "import runpy, sys; module = runpy.run_path(sys.argv[1]); "
                    "main = module['main']; main.__globals__['PROXY_URL'] = sys.argv[2]; "
                    "sys.argv = [sys.argv[1]]; raise SystemExit(main())"
                )
                result = subprocess.run([sys.executable, "-c", code, str(SCRIPT),
                                         f"http://127.0.0.1:{server.server_port}/v1"],
                                        capture_output=True, text=True, timeout=30)
            finally:
                server.shutdown()
                thread.join()

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        events = [json.loads(line) for line in result.stdout.splitlines() if line.startswith("{")]
        self.assertTrue(any(event.get("type") == "text" and "Synthetic test reply." in json.dumps(event)
                            for event in events), result.stdout)
        prompt = json.dumps(baseline.PROMPT)
        task_count = 0
        for path, body in requests:
            self.assertEqual(path, "/v1/chat/completions")
            self.assertEqual(body["model"], "premium")
            self.assertFalse(body.get("tools"), body.get("tools"))
            messages = [msg["content"] for msg in body["messages"] if msg["role"] == "user"]
            if messages == [prompt]:
                task_count += 1
            else:
                self.assertEqual(messages, ["Generate a title for this conversation:\n", prompt])
        self.assertEqual(task_count, 1)


if __name__ == "__main__":
    unittest.main()
