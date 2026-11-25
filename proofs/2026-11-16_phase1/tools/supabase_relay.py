"""Laptop fog relay (owner 2026-11-20): the board has no internet, so it posts Supabase rows to
http://127.0.0.1:8095 (adb reverse) and this forwards them over HTTPS to the project URL from
proofs/secrets/supabase.env. Only /rest/v1/ POSTs to the 4 report tables pass (reports only, no raw data).
Usage: python supabase_relay.py   (listens on 127.0.0.1:8095)"""
import http.server, os, urllib.request, urllib.error

ENV = os.path.join(os.path.dirname(__file__), "..", "..", "secrets", "supabase.env")
URL = next(l.split("=", 1)[1].strip() for l in open(ENV, encoding="utf-8") if l.startswith("SUPABASE_URL=")).rstrip("/")
TABLES = ("boards", "incident_reports", "decisions", "board_health")
PASS = ("apikey", "authorization", "content-type", "prefer")


class H(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        path = self.path.split("?")[0]
        if not path.startswith("/rest/v1/") or path[len("/rest/v1/"):] not in TABLES:
            self.send_error(403, "not a report table")
            return
        n = int(self.headers.get("Content-Length") or 0)
        if n > 2_000_000:
            self.send_error(413)
            return
        body = self.rfile.read(n)
        req = urllib.request.Request(URL + self.path, data=body, method="POST",
                                     headers={k: v for k, v in self.headers.items() if k.lower() in PASS})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                code, data = r.status, r.read()
        except urllib.error.HTTPError as e:
            code, data = e.code, e.read()
        except Exception as e:  # network down: the board keeps the rows queued and retries
            self.send_error(502, str(e)[:120])
            return
        self.send_response(code)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    http.server.ThreadingHTTPServer(("127.0.0.1", 8095), H).serve_forever()
