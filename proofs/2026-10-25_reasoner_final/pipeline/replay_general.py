"""Round 2 general-answer replay (retention): ~515 local prompts answered by the BASE Qwen3.5-4B itself (self-distillation;
Apache-2.0 model outputs, no third-party dataset, nothing leaves the laptop). No local instruction dataset exists on this
machine (checked ~/, ~/smartcity_runs/*/data, qidk/data: none), so prompts are generated here from templates.
  python3 replay_general.py --prompts                 # write data/replay_prompts.jsonl (CPU)
  python3 replay_general.py --url http://127.0.0.1:18097/v1/chat/completions   # answer them (GPU, after domain P2)
Answers are filtered: non-empty, < 220 words, no tool-call text, no invented sensor/incident ids. Prints one line."""
import argparse
import json
import os
import random
import re
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
D = os.path.join(HERE, "..", "data")
TERMS = ["PM2.5", "PM10", "CO2 in classrooms", "power factor", "TDS in drinking water", "pH of drinking water", "relative humidity",
         "a water tank float switch", "an energy meter", "an occupancy sensor", "sensor calibration drift", "a stuck sensor reading",
         "HVAC setpoint", "fresh-air ventilation", "a capacitor bank", "a three-phase load imbalance", "peak demand charges",
         "a rooftop weather station", "rainwater harvesting", "a heat index", "dew point", "an IoT gateway", "MQTT", "a 5-minute moving average",
         "an anomaly detector", "false alarms", "a maintenance log", "a root cause", "a checklist", "an edge device", "a NPU"]
ASKS = ["Explain {t} in two sentences for a new facilities operator.", "Why does {t} matter on a university campus?",
        "What is a common mistake people make about {t}?", "Give one practical tip about {t}.", "What does {t} mean? Keep it short."]
GENERAL = ["Write a polite two-line message asking a technician to check a sensor.", "Summarise in one sentence: the pump was restarted at 6 am and the tank refilled by 7 am.",
           "Convert 35 degrees Celsius to Fahrenheit.", "What is 15% of 240?", "Give three tips to save electricity in an office.",
           "How should I hand over an open incident to the next shift?", "Draft a short shift-end note: two incidents closed, one pending approval.",
           "What is the difference between a warning and a critical alert?", "How do I write a clear incident title?",
           "Rephrase more politely: fix the AC now.", "What should I check first if a room feels stuffy?", "What is a good password practice?",
           "Explain what an outage is to a student.", "List three safety rules near electrical panels.", "Hi, who are you?",
           "Thanks for the help!", "Can you tell me a fun fact about water?", "What is the capital of India?",
           "How many minutes are in 4.5 hours?", "Translate 'water tank' into Hindi."]


def prompts():
    R = random.Random(9)
    out = []
    for t in TERMS:
        for a in ASKS:
            out.append(a.format(t=t))
    out += GENERAL * 3
    for i in range(300):
        a, b = R.randrange(2, 99), R.randrange(2, 99)
        out.append(R.choice(["What is %d times %d?", "Add %d and %d.", "If a tank fills %d litres per minute, how long for %d litres?"]) % (a, b))
    R.shuffle(out)
    with open(os.path.join(D, "replay_prompts.jsonl"), "w", encoding="utf-8") as f:
        for i, p in enumerate(out):
            f.write(json.dumps({"id": "rp-%04d" % i, "q": p}) + "\n")
    print("replay prompts:", len(out))


def answer(url):
    rows = [json.loads(l) for l in open(os.path.join(D, "replay_prompts.jsonl"), encoding="utf-8")]
    from concurrent.futures import ThreadPoolExecutor
    from paraphrase_chat import gpu_cool

    def one(r):
        gpu_cool()
        body = {"messages": [{"role": "user", "content": r["q"]}], "temperature": 0.3, "max_tokens": 300,
                "chat_template_kwargs": {"enable_thinking": False}}
        req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=300) as x:
                return r, json.loads(x.read())["choices"][0]["message"]["content"].strip()
        except Exception:
            return r, ""
    kept = []
    with ThreadPoolExecutor(8) as pool:
        res = list(pool.map(one, rows))
    for r, a in res:
        if not a or len(a.split()) > 220 or "<tool_call>" in a or re.search(r"INC-\d+|[A-Z]{2}-[A-Z]{2}-[A-Z0-9]{4}", a):
            continue
        kept.append({"id": r["id"], "family": "replay", "tools": "none",
                     "messages": [{"role": "user", "content": r["q"]}, {"role": "assistant", "content": a}]})
    with open(os.path.join(D, "replay_train.jsonl"), "w", encoding="utf-8") as f:
        for k in kept:
            f.write(json.dumps(k, ensure_ascii=False) + "\n")
    print("replay answered %d/%d" % (len(kept), len(rows)))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompts", action="store_true")
    ap.add_argument("--url")
    a = ap.parse_args()
    prompts() if a.prompts else answer(a.url)
