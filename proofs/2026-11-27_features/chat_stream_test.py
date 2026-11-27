"""chat_stream_test.py: POST /api/chat with a stream id while listening to /api/events; logs when the first step / first
draft text / final reply arrived -> chat_stream.jsonl. usage: python chat_stream_test.py "question" ["question" ...]"""
import json, sys, threading, time, urllib.request
B = "http://127.0.0.1:8000"
out = open("chat_stream.jsonl", "a", encoding="utf-8")
for q in sys.argv[1:]:
    sid = "cs%d" % int(time.time() * 1000)
    ev = {"steps": [], "first_text": None, "drafts": 0, "last_draft": ""}
    t0 = time.time()
    stop = threading.Event()

    def listen():
        r = urllib.request.urlopen(B + "/api/events", timeout=600)
        kind = None
        for raw in r:
            if stop.is_set():
                return
            line = raw.decode("utf-8", "replace").rstrip("\n")
            if line.startswith("event: "):
                kind = line[7:]
            elif line.startswith("data: ") and kind == "chat_piece":
                d = json.loads(line[6:])
                if d.get("stream") != sid:
                    continue
                if d.get("step"):
                    ev["steps"].append((round(time.time() - t0, 1), d["step"]))
                if d.get("text"):
                    ev["drafts"] += 1; ev["last_draft"] = d["text"]
                    if ev["first_text"] is None:
                        ev["first_text"] = round(time.time() - t0, 1)

    th = threading.Thread(target=listen, daemon=True); th.start(); time.sleep(1); t0 = time.time()
    r = urllib.request.Request(B + "/api/chat", data=json.dumps({"session": "", "message": q, "stream": sid}).encode(), headers={"Content-Type": "application/json"})
    d = json.loads(urllib.request.urlopen(r, timeout=400).read())
    stop.set()
    m = d["messages"][-1]
    rec = dict(q=q, total_s=round(time.time() - t0, 1), first_text_s=ev["first_text"], drafts=ev["drafts"], steps=ev["steps"],
               draft_end=ev["last_draft"][:300], final=m.get("text", "")[:300], tools=[x.get("name") for x in m.get("tools") or []])
    out.write(json.dumps(rec) + "\n"); out.flush()
    print(json.dumps(rec, ensure_ascii=False)[:700], flush=True)
