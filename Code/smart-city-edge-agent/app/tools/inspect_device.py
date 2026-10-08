"""Print incidents + agent outputs from the edge-agent running on the QIDK (via adb)."""
import json, subprocess, sys
ADB = r"C:\Users\hp\Desktop\qidk\Code\platform-tools\adb.exe"
def get(path):
    out = subprocess.run([ADB, "shell", f"curl -s 127.0.0.1:8000{path}"], capture_output=True, text=True, encoding="utf-8").stdout
    return json.loads(out)
incs = get("/api/incidents")
for i in incs:
    print(i["id"], i["state"], "mode", i["mode"], i["severity"], i["title"][:70], "npu", i["npu_calls"], round(i["total_ms"] / 1000, 1), "s", i["label"])
n = int(sys.argv[1]) if len(sys.argv) > 1 else 2
for i in [x for x in incs if x["state"] != "running"][:n]:
    d = get(f"/api/incidents/{i['id']}")
    print("=====", d["id"], d["title"])
    for a in d["agents"] or []:
        print(" AGENT", a["role"], "fine_tuned" if a["fine_tuned"] else "base", round(a["latency_ms"] / 1000, 1), "s | ttft", a.get("ttft_ms"), "ms | tokens", a.get("gen_tokens"), "|", round(a.get("tokens_per_s") or 0, 1), "tok/s | early", a.get("early_stopped"), "| valid", a["valid"], a["errors"])
        print("   raw:", a["raw"][:600].replace("\n", " "))
    f = d["final"]
    if f:
        print(" FINAL", f["model"][:40], "valid", f["valid"], f["errors"], round(f["latency_ms"] / 1000, 1), "s | ttft", f.get("ttft_ms"), "| tokens", f.get("gen_tokens"), "| early", f.get("early_stopped"))
        print("   raw:", f["raw"][:800].replace("\n", " "))
