#!/usr/bin/env python3
"""Dead-man monitor for edge-agent heartbeats (backend/prod_heartbeat.go). Stdlib only; runs on the laptop / fog box.

The board POSTs a health snapshot to http://<this host>:<port>/heartbeat every heartbeat_s (htpd_profile
heartbeat_url=http://<laptop>:8787/heartbeat). When a board that was seen goes silent for --dead-s seconds this prints
an ALERT line and, with --alert-url, POSTs {"text": ...} once (ntfy/Slack/any webhook); when it comes back it sends a
"recovered" message. Also alerts on a reboot (uptime went down) and on clock_valid=false or htpd_up=false.

  python3 heartbeat_monitor.py --port 8787 --dead-s 300 --alert-url https://ntfy.sh/my-topic
  GET http://<host>:8787/status  -> last snapshot per board and its age
"""
import argparse
import json
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

boards = {}  # board id -> {"at": monotonic, "snap": dict, "dead": bool}
lock = threading.Lock()
args = None


def alert(text):
    line = "%s ALERT %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), text)
    print(line, flush=True)
    if args.alert_url:
        try:
            req = urllib.request.Request(args.alert_url, data=json.dumps({"text": text}).encode(),
                                         headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=10).read()
        except Exception as e:  # the monitor itself must keep running
            print("alert delivery failed: %s" % e, file=sys.stderr, flush=True)


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        if self.path.rstrip("/") != "/heartbeat":
            self.send_error(404)
            return
        if args.token and self.headers.get("Authorization") != "Bearer " + args.token:
            self.send_error(401)
            return
        try:
            snap = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0)) or 0) or b"{}")
        except ValueError:
            self.send_error(400)
            return
        bid = snap.get("board_id") or self.client_address[0]
        msgs = []
        with lock:
            prev = boards.get(bid)
            if prev and prev["dead"]:
                msgs.append("board %s recovered (silent %.0f s)" % (bid, time.monotonic() - prev["at"]))
            if prev and snap.get("uptime_s", 0) < prev["snap"].get("uptime_s", 0):
                msgs.append("board %s restarted (uptime %s s)" % (bid, snap.get("uptime_s")))
            if snap.get("clock_valid") is False and not (prev and prev["snap"].get("clock_valid") is False):
                msgs.append("board %s clock invalid" % bid)
            npu = snap.get("npu") or {}
            if npu.get("htpd_up") is False and not (prev and (prev["snap"].get("npu") or {}).get("htpd_up") is False):
                msgs.append("board %s: htpd (NPU engine) down" % bid)
            boards[bid] = {"at": time.monotonic(), "snap": snap, "dead": False}
        for m in msgs:
            alert(m)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"ok":true}')

    def do_GET(self):
        if self.path.rstrip("/") != "/status":
            self.send_error(404)
            return
        with lock:
            out = {b: {"age_s": round(time.monotonic() - v["at"], 1), "dead": v["dead"], "snap": v["snap"]} for b, v in boards.items()}
        body = json.dumps(out).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)


def watch():
    while True:
        time.sleep(args.check_s)
        now, msgs = time.monotonic(), []
        with lock:
            for b, v in boards.items():
                if not v["dead"] and now - v["at"] > args.dead_s:
                    v["dead"] = True
                    msgs.append("board %s silent for %.0f s (no heartbeat): check power, Wi-Fi and the app" % (b, now - v["at"]))
        for m in msgs:
            alert(m)


def main():
    global args
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8787)
    ap.add_argument("--dead-s", type=float, default=300)
    ap.add_argument("--check-s", type=float, default=10)
    ap.add_argument("--alert-url", default="")
    ap.add_argument("--token", default="", help="require Authorization: Bearer <token> (htpd_profile heartbeat_token)")
    args = ap.parse_args()
    threading.Thread(target=watch, daemon=True).start()
    print("heartbeat monitor on %s:%d (dead after %.0f s)" % (args.host, args.port, args.dead_s), flush=True)
    ThreadingHTTPServer((args.host, args.port), H).serve_forever()


if __name__ == "__main__":
    main()
