"""chat_battery.py: hands-on chat sweep. Each question -> latency, tools used, answer -> chat_battery.jsonl. usage: python chat_battery.py <set>"""
import json, sys, time, urllib.request
B = "http://127.0.0.1:8000"
SETS = {
    "a": [  # session sw1: read-only questions across the chat router's paths
        ("sw1", "What is the status of the campus right now?"),
        ("sw1", "Which sensors are offline or missing data?"),
        ("sw1", "What is the CO2 in KH level 3?"),
        ("sw1", "Show me the water pH trend for the last 2 hours."),
        ("sw1", "Is it hotter than usual outside today?"),
        ("sw1", "How many incidents were there today?"),
        ("sw1", "Which buildings and floors do you monitor?"),
        ("sw1", "What does a TDS of 500 ppm mean for drinking water?"),
        ("sw1", "Why would CO2 rise when the AC stops?"),
        ("sw1", "and what about humidity?"),
        ("sw2", "kh 3rd floor temprature kya hai abhi?"),
        ("sw2", "Compare feeder power now with this morning."),
        ("sw2", "What should I do if the power factor drops below 0.85?"),
        ("sw2", "Turn off the AC in KH level 3."),
        ("sw2", "Write me a poem about the campus."),
        ("sw2", "What's the weather forecast for tomorrow?"),
    ],
    "b": [  # after incidents exist
        ("sw3", "What incidents are open right now?"),
        ("sw3", "Explain the latest critical incident in simple words."),
        ("sw3", "Why did you say that? What evidence supports it?"),
        ("sw3", "Is the water pH problem a sensor fault or real?"),
        ("sw3", "What should the maintenance team check first for the KH level 3 issue?"),
        ("sw3", "Has this happened before on this sensor?"),
        ("sw3", "Summarise today's incidents for my manager in 3 lines."),
        ("sw3", "Which incident is the most urgent and why?"),
    ],
}


def ask(session, msg):
    t = time.time()
    r = urllib.request.Request(B + "/api/chat", data=json.dumps({"session": session, "message": msg}).encode(), headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(r, timeout=400) as x:
            d = json.loads(x.read().decode())
    except urllib.error.HTTPError as e:
        return dict(session=session, q=msg, http=e.code, err=e.read().decode()[:300], wall_s=round(time.time() - t, 1))
    m = d["messages"][-1]
    return dict(session=session, chat_id=d.get("id"), q=msg, wall_s=round(time.time() - t, 1), ms=m.get("ms"), tools=[x.get("name") for x in m.get("tools") or []],
                tool_detail=m.get("tools"), meta={k: v for k, v in m.items() if k not in ("text", "tools", "role", "at")}, a=m.get("text"))


if __name__ == "__main__":
    out = open("chat_battery.jsonl", "a", encoding="utf-8")
    sid = {}
    for s, q in SETS[sys.argv[1]]:
        sess = sid.get(s, "")  # the API keys sessions by the CHAT-xxxx id it returns
        rec = ask(sess, q); out.write(json.dumps(rec) + "\n"); out.flush()
        if rec.get("chat_id"):
            sid[s] = rec["chat_id"]
        print("%5.1fs %-40s | %s | %s" % (rec["wall_s"], q[:40], ",".join(rec.get("tools") or []), (rec.get("a") or rec.get("err") or "")[:230].replace("\n", " ")), flush=True)
