# Live check from the laptop: anon can INSERT a board_health row, cannot SELECT. Never prints the key.
import json, os, sys, urllib.request, urllib.error
env = {}
for ln in open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "secrets", "supabase.env"), encoding="utf-8"):
    if "=" in ln and not ln.startswith("#"):
        k, v = ln.strip().split("=", 1); env[k] = v.strip().strip('"')
url, key = env["SUPABASE_URL"].rstrip("/"), env["SUPABASE_ANON_KEY"]
def call(method, path, body=None, prefer=None):
    h = {"apikey": key, "Authorization": "Bearer " + key, "Content-Type": "application/json"}
    if prefer: h["Prefer"] = prefer
    r = urllib.request.Request(url + "/rest/v1/" + path, data=json.dumps(body).encode() if body is not None else None, headers=h, method=method)
    try:
        with urllib.request.urlopen(r, timeout=20) as x: return x.status, x.read().decode()[:200]
    except urllib.error.HTTPError as e: return e.code, e.read().decode()[:200]
s1, _ = call("POST", "board_health", {"board_id": "laptop-test", "app_version": "live-check"}, "return=minimal")
s2, b2 = call("GET", "board_health?board_id=eq.laptop-test&select=id")
s3, _ = call("PATCH", "board_health?board_id=eq.laptop-test", {"app_version": "x"}, "return=representation")
ok_ins = s1 in (200, 201, 204)
ok_sel = (s2 in (401, 403)) or (s2 == 200 and b2.strip() == "[]")
print(f"insert status={s1} ok={ok_ins}")
print(f"anon select status={s2} body={b2[:60]!r} blocked={ok_sel}")
print(f"anon update status={s3} (no rows visible/affected expected)")
sys.exit(0 if ok_ins and ok_sel else 1)
