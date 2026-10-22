"""Local HTTP protocol fixture; never uses a real credential or external service."""

from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
import time


def completion(content):
    return {"choices": [{"message": {"role": "assistant", "content": content}, "finish_reason": "stop"}]}


@contextmanager
def http_service(actions=None, responder=None):
    requests = []
    actions = list(actions or [])

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            record = {"path": self.path, "authorization": self.headers.get("Authorization"),
                      "body": json.loads(body)}
            requests.append(record)
            action = responder(record) if responder is not None else actions.pop(0)
            time.sleep(action.get("delay", 0))
            payload = action.get("body", completion("{}"))
            payload = json.dumps(payload).encode("utf-8") if not isinstance(payload, bytes) else payload
            try:
                self.send_response(action.get("status", 200))
                for key, value in action.get("headers", {}).items():
                    self.send_header(key, value)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": .01}, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/v1", requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
