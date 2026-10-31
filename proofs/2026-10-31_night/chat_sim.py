#!/usr/bin/env python3
"""Offline sim: speculative drafts for single-stream chat decode (htpd plain path 85 ms/step).
Input: chats.json (board state/chats.json). Per assistant answer, rebuilds the generated rounds (tool-call rounds
from the stored tool args, final answer text) and the context the model saw (system prefix approximated by
chat_system.txt, question, tool results). Tokenizes with ~/tok + qwen35 vocab. Proposer = longest suffix match
(n-gram up to MAXM) in context ("prompt"), and/or in earlier outputs ("corpus", chronological, leave-future-out).
Draft only when match >= G. Kept = longest agreeing prefix (greedy verify, exact). Prints steps + modeled ms.
usage: python3 chat_sim.py chats.json"""
import json, subprocess, sys, os
TOK = os.path.expanduser("~/tok"); VOC = os.path.expanduser("~/gpu_work/llama.cpp/models/ggml-vocab-qwen35.gguf")
SYS = "/mnt/c/Users/hp/Desktop/qidk/Code/smart-city-edge-agent/app/backend/chat_system.txt"
def cost(rows):  # ms per decode step on the board, single stream (HANDBOOK 2.47/2.63; deploy15 drafts 126 ms)
    return 85 if rows == 1 else 110 if rows <= 3 else 130 if rows <= 5 else 120

def toks(texts):
    out = subprocess.run([TOK, VOC], input="\x1e".join(texts).encode(), capture_output=True).stdout.decode().splitlines()
    return [[int(x) for x in l.split()] for l in out]

def call_text(name, args):
    s = "<tool_call>\n<function=" + name + ">\n"
    for k, v in (args or {}).items():
        s += "<parameter=" + k + ">\n" + (v if isinstance(v, str) else json.dumps(v)) + "\n</parameter>\n"
    return s + "</function>\n</tool_call>"

def main():
    d = json.load(open(sys.argv[1]))
    d = d.get("S", d) if isinstance(d, dict) else d
    sess = sorted(d.values() if isinstance(d, dict) else d, key=lambda s: s.get("created", 0))
    ex = []; QS = []; EQ = []  # (ctx_text, out_text)
    sysp = open(SYS).read()
    for s in sess:
        msgs = s.get("messages") or []
        for i, m in enumerate(msgs):
            if m.get("role") != "assistant" or m.get("busy") or m.get("error") or i == 0 or (m.get("ms") or 0) < 3000: continue
            QS.append(msgs[i - 1].get("text", ""))
            q = msgs[i - 1].get("text", ""); ctx = sysp + q
            for t in m.get("tools") or []:
                try: a = json.loads(t.get("args") or "{}")
                except Exception: a = {}
                ex.append((ctx, call_text(t["name"], a))); EQ.append(q)
                ctx += "\n" + call_text(t["name"], a) + "<tool_response>\n" + (t.get("result") or "") + "\n</tool_response>"
            ex.append((ctx, (m.get("text") or "") + "<|im_end|>")); EQ.append(q)
    T = toks([x for e in ex for x in e])
    pairs = [(T[2 * i], T[2 * i + 1]) for i in range(len(ex))]
    print(f"{len(QS)} model answers, {len(set(QS))} distinct questions; {len(sess)} sessions, {len(pairs)} generated rounds, {sum(len(o) for _, o in pairs)} output tokens")
    NS = (8, 6, 4, 3, 2, 1)
    def add(ix, seq, start):  # index n-grams ending at positions >= start: key -> position after the n-gram
        for e in range(max(start, 1), len(seq) + 1):
            for n in NS:
                if e - n >= 0: ix[n][tuple(seq[e - n:e])] = (seq, e)
    for K, G, use_p, use_c in [(4, 2, 1, 0), (8, 2, 1, 0), (8, 4, 1, 0), (8, 6, 1, 0), (8, 4, 0, 1), (8, 4, 1, 1), (8, 6, 1, 1), (16, 8, 1, 1), (4, 3, 1, 1), (8, 3, 1, 1)]:
        steps = plain = 0; ms = pms = 0.0; cix = {n: {} for n in NS}
        HELD = os.environ.get("HELD") == "1"
        if HELD:
            qix = {}
            for qq in set(EQ):
                qix[qq] = {n: {} for n in NS}
                for (c2, o2), q2 in zip(pairs, EQ):
                    if q2.strip().lower() != qq.strip().lower(): add(qix[qq], list(o2), 1)
        for pi, (ctx, out) in enumerate(pairs):
            if HELD: cix = qix[EQ[pi]]
            h = list(ctx); j = 0; pix = {n: {} for n in NS}; add(pix, h, 1); done = len(h)
            while j < len(out):
                dr = []
                for n in NS:
                    if n < G or len(h) < n: continue
                    key = tuple(h[-n:]); hit = None
                    if use_p and key in pix[n] and pix[n][key][1] < len(h): hit = pix[n][key]
                    elif use_c and key in cix[n]: hit = cix[n][key]
                    if hit: dr = hit[0][hit[1]:hit[1] + K]; break
                k = 0
                while k < len(dr) and j + k < len(out) and dr[k] == out[j + k]: k += 1
                adv = min(k + 1, len(out) - j)
                steps += 1; ms += cost(1 + len(dr)); h += out[j:j + adv]; j += adv
                # prompt index includes generated tokens except the last n-gram ending at len(h)
                add(pix, h[:-1], done); done = len(h) - 1
            plain += len(out); pms += 85 * len(out)
            if not HELD: add(cix, list(out), 1)
        print(f"K{K} G{G} prompt={use_p} corpus={use_c}: steps {steps} vs {plain} ({100*(steps/plain-1):+.0f}%), ms {ms/1000:.1f} vs {pms/1000:.1f} s ({100*(ms/pms-1):+.0f}%)")

if __name__ == "__main__":
    main()
