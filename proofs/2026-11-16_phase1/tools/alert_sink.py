"""Laptop alert sink for the Phase 1 board test (alert_webhook=http://<laptop>:8094/alert): prints and logs every POST.
usage: python3 alert_sink.py [port]   (LAN only; nothing leaves the laptop)"""
import http.server
import json
import sys
import time

LOG = "alerts_received.jsonl"


class H(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n).decode("utf-8", "replace")
        rec = {"t": time.strftime("%Y-%m-%dT%H:%M:%S"), "path": self.path, "body": body[:4000]}
        with open(LOG, "a") as f:
            f.write(json.dumps(rec) + "\n")
        print(rec["t"], body[:200], flush=True)
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *a):
        pass


http.server.ThreadingHTTPServer(("0.0.0.0", int(sys.argv[1]) if len(sys.argv) > 1 else 8094), H).serve_forever()
