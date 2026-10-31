"""General-language replay rows (anti-forgetting): ~1,000 local template prompts (round 1's 515 set + more with new seeds, from
pipeline/replay_general.py's term/ask/general lists) answered by the BASE Qwen3.5-4B on a local llama-server (thinking off,
temperature 0.3), filtered like round 2 (non-empty, < 220 words, no tool-call text, no sensor/incident ids).
  python3 make_replay.py --port 18112 --out replay_train.jsonl [--n 1000]   (resumable: answered ids are skipped)"""
import argparse
import json
import os
import random
import re
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
R1P = os.path.abspath(os.path.join(HERE, "..", "..", "..", "2026-10-25_reasoner_final", "pipeline"))
sys.path.insert(0, R1P)
import replay_general as RG  # noqa: E402

EXTRA_ASKS = ["How would you explain {t} to a first-year student?", "Name one sign that {t} needs attention.",
              "In one sentence, how is {t} measured or used?"]
EXTRA = ["Write a two-sentence status update for a facilities manager.", "What is the difference between accuracy and precision?",
         "Give two tips for writing a clear maintenance request.", "What is 3/4 as a percentage?", "Explain what a median is.",
         "Rewrite more concisely: the sensor that is in the lab seems to be giving readings that are not right.",
         "What should a night-shift operator check at the start of a shift?", "Say good morning to the team in one line.",
         "What is the boiling point of water at sea level in Celsius?", "How many seconds are in a day?"]


def prompts(n):
    base = [json.loads(l)["q"] for l in open(os.path.join(R1P, "..", "data", "replay_prompts.jsonl"), encoding="utf-8")]
    R = random.Random(23)
    more = [a.format(t=t) for t in RG.TERMS for a in EXTRA_ASKS] + EXTRA * 2
    while len(base) + len(more) < n:
        a, b = R.randrange(2, 99), R.randrange(2, 99)
        more.append(R.choice(["What is %d times %d?", "Subtract %d from %d.", "Round %d.%d to the nearest whole number.",
                              "If %d people share %d sandwiches equally, how many does each get (with remainder)?"]) % (a, b))
    out = base + more
    return [{"id": "rp3-%05d" % i, "q": q} for i, q in enumerate(out[:n])]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--n", type=int, default=1000)
    a = ap.parse_args()
    rows = prompts(a.n)
    done = set()
    if os.path.exists(a.out + ".all"):
        done = {json.loads(l)["id"] for l in open(a.out + ".all", encoding="utf-8")}
    url = "http://127.0.0.1:%d/v1/chat/completions" % a.port

    def one(r):
        body = {"messages": [{"role": "user", "content": r["q"]}], "temperature": 0.3, "max_tokens": 300,
                "chat_template_kwargs": {"enable_thinking": False}}
        req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=300) as x:
                return r, json.loads(x.read())["choices"][0]["message"]["content"].strip()
        except Exception:
            return r, ""
    todo = [r for r in rows if r["id"] not in done]
    with ThreadPoolExecutor(4) as pool, open(a.out + ".all", "a", encoding="utf-8") as f:
        for r, ans in pool.map(one, todo):
            f.write(json.dumps({"id": r["id"], "q": r["q"], "a": ans}, ensure_ascii=False) + "\n")
            f.flush()
    kept = []
    for l in open(a.out + ".all", encoding="utf-8"):
        o = json.loads(l)
        ans = o["a"]
        if not ans or len(ans.split()) > 220 or "<tool_call>" in ans or "<think>" in ans or re.search(r"INC-\d+|[A-Z]{2}-[A-Z]{2}-[A-Z0-9]{4}", ans):
            continue
        kept.append({"id": o["id"], "family": "replay", "tools": "none", "think": False,
                     "messages": [{"role": "user", "content": o["q"]}, {"role": "assistant", "content": ans}]})
    with open(a.out, "w", encoding="utf-8") as f:
        for k in kept:
            f.write(json.dumps(k, ensure_ascii=False) + "\n")
    print("replay: %d prompts, %d kept -> %s" % (len(rows), len(kept), a.out))


if __name__ == "__main__":
    main()
