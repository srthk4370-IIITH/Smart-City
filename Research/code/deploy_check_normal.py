import json, random, subprocess, time, urllib.request
ADB=r"C:\Users\hp\Desktop\qidk\Code\platform-tools\adb.exe"; B="http://127.0.0.1:8000"
def sh(c): return subprocess.run([ADB,"shell",c],capture_output=True,text=True).stdout
def req(p,b):
    r=urllib.request.Request(B+p,data=json.dumps(b).encode(),headers={"Content-Type":"application/json"})
    try:
        with urllib.request.urlopen(r,timeout=60) as x: return x.status, x.read().decode()
    except urllib.error.HTTPError as e: return e.code, e.read().decode()
t=int(sh("date +%s").strip())+int(sh("cat /data/local/tmp/smart_city_edge/state/clock_offset_s").strip())
end=t//300*300  # last closed bucket
rd=[{"node":"EM-CR-SB00-00","metric":"pf","value":round(0.95+random.gauss(0,0.004),3),"ts":end-300*(49-i)+7} for i in range(50)]
rd.append({"node":"EM-CR-SB00-00","metric":"pf","value":0.951,"ts":t+1 if (t+1)%300 else t+2})
print("ingest",req("/api/ingest",{"readings":rd}))
time.sleep(3)
print("analyze",req("/api/analyze",{"node":"EM-CR-SB00-00","metric":"pf","system_check":True}))
