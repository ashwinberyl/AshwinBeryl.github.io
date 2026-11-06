import os
import signal
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

VERSION = os.environ.get("VERSION", "v1")
GREETING = os.environ.get("GREETING", "Hello from the port")
DATA_DIR = os.environ.get("DATA_DIR", "/data")
HOST = socket.gethostname()

healthy = True
hog = []  # keeps memory allocated by /burn


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body):
        data = (body + "\n").encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt, *args):
        print(f"{HOST} {self.path} {args[1] if len(args) > 1 else ''}", flush=True)

    def do_GET(self):
        global healthy
        path, _, query = self.path.partition("?")
        arg = int(query.split("=", 1)[1]) if "=" in query else None

        if path == "/healthz":
            return self._send(200 if healthy else 500, "ok" if healthy else "broken")
        if path == "/break":
            healthy = False
            return self._send(200, "now unhealthy")
        if path == "/secret":
            token = os.environ.get("SECRET_TOKEN")
            state = f"set ({len(token)} chars)" if token else "NOT set"
            return self._send(200, f"SECRET_TOKEN is {state}")
        if path == "/visit":
            if not os.path.isdir(DATA_DIR):
                return self._send(500, f"{DATA_DIR} does not exist")
            log = os.path.join(DATA_DIR, "visits.log")
            with open(log, "a") as f:
                f.write(HOST + "\n")
            with open(log) as f:
                n = sum(1 for _ in f)
            return self._send(200, f"visit #{n} recorded by {HOST}")
        if path == "/burn":
            mb = arg or 50
            hog.append(bytearray(b"x") * (mb * 1024 * 1024))
            return self._send(200, f"holding {sum(len(b) for b in hog) // 1048576} MiB")
        if path == "/spin":
            end = time.time() + (arg or 5)
            while time.time() < end:
                pass
            return self._send(200, "done spinning")
        return self._send(200, f"{GREETING} | pod={HOST} | version={VERSION}")


server = ThreadingHTTPServer(("0.0.0.0", 8080), Handler)
signal.signal(signal.SIGTERM, lambda s, f: threading.Thread(target=server.shutdown).start())
print(f"{HOST} listening on :8080 ({VERSION})", flush=True)
server.serve_forever()
