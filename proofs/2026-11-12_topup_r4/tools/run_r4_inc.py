"""Run a served GGUF (llama-server raw /completion, greedy) on test_inc_r4.jsonl / dev_gen_inc.jsonl with the APP's incident
prompt (reasoner_v3_header.txt + reasoner_v3_system.txt, = reasonerPromptV3), so the score measures what the board would see.
--think app      : open "<think>\n" only when the FLAGGED sensors span 2+ domains (the proposed app rule), else the pre-filled
                   empty think (today's v3AssistantOpen)
--think adaptive : always open "<think>\n" (the model decides)       --think off : always the empty think (today's app)
A tool call (rare: these prompts carry all evidence) is answered like eval/run_v3.py RowExec ("already in the prompt") once,
then the answer prefix is forced as the app does. Resumable. Output rows: id, raw (generated text incl. think), think, json_text.
  python3 run_r4_inc.py --port 18098 --think app --out OUT.jsonl [--rows ../data/final/test_inc_r4.jsonl] [--limit N]
"""
import argparse
import json
import os
import re
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
QIDK = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
BE = os.path.join(QIDK, "Code", "smart-city-edge-agent", "app", "backend")
OPEN_EMPTY = "<|im_start|>assistant\n<think>\n\n</think>\n\n"
OPEN_THINK = "<|im_start|>assistant\n<think>\n"
PREFIX = '{"title": "'
FLAG_RX = re.compile(r"^S\d+ \[FLAGGED\]: .* \((\w+)\)$", re.M)


def static_prefix():
    h = open(os.path.join(BE, "reasoner_v3_header.txt"), encoding="utf-8").read()
    s = open(os.path.join(BE, "reasoner_v3_system.txt"), encoding="utf-8").read()
    return h + s + "<|im_end|>\n<|im_start|>user\n"


def complete(port, prompt, n):
    body = json.dumps({"prompt": prompt, "n_predict": n, "temperature": 0, "top_k": 1, "cache_prompt": True, "stop": ["<|im_end|>"]}).encode()
    req = urllib.request.Request("http://127.0.0.1:%d/completion" % port, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as r:
        o = json.loads(r.read())
    return o.get("content", ""), o.get("tokens_predicted", 0)


def split_think(text, opened):
    if opened and "</think>" in text:
        t, rest = text.split("</think>", 1)
        return t.strip(), rest.strip()
    return ("", text.strip()) if not opened else (text.strip(), "")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--think", choices=("app", "adaptive", "off"), default="app")
    ap.add_argument("--rows", default=os.path.join(HERE, "..", "data", "final", "test_inc_r4.jsonl"))
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-new", type=int, default=1400)
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    pre = static_prefix()
    rows = [json.loads(l) for l in open(a.rows, encoding="utf-8")]
    done = {json.loads(l)["id"] for l in open(a.out, encoding="utf-8")} if os.path.exists(a.out) else set()
    n = 0
    for r in rows:
        if r["id"] in done:
            continue
        if a.limit and n >= a.limit:
            break
        user = r["messages"][1]["content"]
        multi = len(set(FLAG_RX.findall(user))) >= 2
        opened = a.think == "adaptive" or (a.think == "app" and multi)
        prompt = pre + user + "<|im_end|>\n" + (OPEN_THINK if opened else OPEN_EMPTY)
        t0 = time.time()
        text, ntok = complete(a.port, prompt, a.max_new)
        calls = 0
        if "<tool_call>" in text:   # answer once from "the prompt already holds it", then force the report prefix
            calls = 1
            prompt2 = prompt + text.split("</tool_call>")[0] + "</tool_call><|im_end|>\n<|im_start|>user\n<tool_response>\n" + json.dumps(
                {"items": [], "note": "all causally related sensors are already in the prompt"}) + "\n</tool_response><|im_end|>\n" + OPEN_EMPTY + PREFIX
            t2, k2 = complete(a.port, prompt2, a.max_new)
            text, ntok = text + "\n" + PREFIX + t2, ntok + k2
        think, js = split_think(text, opened)
        if calls:
            js = PREFIX + text.split(PREFIX, 1)[1] if PREFIX in text else js
        o = {"id": r["id"], "think_mode": a.think, "opened": opened, "multi": multi, "raw": text, "think": think, "json_text": js, "calls": calls,
             "gen_tokens": ntok, "wall_s": round(time.time() - t0, 2)}
        with open(a.out, "a", encoding="utf-8") as f:
            f.write(json.dumps(o, ensure_ascii=False) + "\n")
        n += 1
    print("run_r4_inc: %d new -> %s" % (n, a.out))


if __name__ == "__main__":
    main()
