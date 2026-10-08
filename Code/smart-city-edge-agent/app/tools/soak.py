"""Soak test on the device: cycle realistic alarm scenarios for ~20 min, check stability."""
import json, time, urllib.request, subprocess
B = "http://127.0.0.1:8000"; ADB = r"C:\Users\hp\Desktop\qidk\Code\platform-tools\adb.exe"
def call(p, b=None):
    r = urllib.request.Request(B + p, data=json.dumps(b).encode() if b is not None else None, headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(r, timeout=30).read())
def pid(): return subprocess.run([ADB, "shell", "pidof edge-agent"], capture_output=True, text=True).stdout.strip()
scen = [[("SR-AQ-KH03-03", "co2", 1600)], [("WM-WL-KH98-00", "level", 150)], [("EM-CR-SB00-00", "pf", 0.7)],
        [("SR-OC-GW-KH95-01", "occ", 1), ("SR-EM-KH04-01", "power_kw", 9), ("SR-AQ-KH03-03", "co2", 1500)],
        [("WE-VN04-00", "temp", 43), ("WM-WD-KH98-00", "tds", 800)], [("AQ-KN00-00", "pm25", 150)]]
p0 = pid(); t0 = time.time(); n0 = len(call("/api/incidents")); rounds = 0
while time.time() - t0 < 600:
    for sc in scen:
        call("/api/sensors", {"values": [{"node": n, "metric": m, "value": v} for n, m, v in sc]}); time.sleep(70)
        call("/api/sensors", {"reset_values": True}); time.sleep(30)
        rounds += 1
        if time.time() - t0 > 600: break
inc = call("/api/incidents"); st = call("/api/status")
bad = [i["id"] for i in inc if i["state"] != "done"]
print(f"{rounds} scenarios in {(time.time()-t0)/60:.0f} min | incidents {len(inc)-n0} | not-clean {bad}")
print(f"backend pid same: {pid() == p0} | device {st['device']}")
