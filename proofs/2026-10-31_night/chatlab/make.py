import json, subprocess, os
N = "/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-31_night"; B = "/mnt/c/Users/hp/Desktop/qidk/Code/smart-city-edge-agent/app/backend"
TOK = os.path.expanduser("~/tok"); VOC = os.path.expanduser("~/gpu_work/llama.cpp/models/ggml-vocab-qwen35.gguf")
hdr = open(B + "/chat_header.txt").read(); sysp = open(B + "/chat_system.txt").read()
first = "You are the operator assistant of a smart-campus edge monitor (IIIT Hyderabad) on a Qualcomm QIDK. Device time: 2026-10-15 10:00 IST (Thursday). The device is offline: the fog server is unreachable.\n"
prefix = hdr + first + sysp + "<|im_end|>\n<|im_start|>user\n"
OPEN = "<|im_start|>assistant\n<think>\n\n</think>\n\n"
def call_text(name, a):
    s = "<tool_call>\n<function=" + name + ">\n"
    for k, v in a.items(): s += "<parameter=" + k + ">\n" + (v if isinstance(v, str) else json.dumps(v)) + "\n</parameter>\n"
    return s + "</function>\n</tool_call>"
d = json.load(open(N + "/raw/chats.json")); d = d.get("S", d) if isinstance(d, dict) else d
sess = sorted(d.values() if isinstance(d, dict) else d, key=lambda s: s.get("created", 0))
items = []  # (question, prompt, expected_output)
for s in sess:
    m = s.get("messages") or []
    for i, a in enumerate(m):
        if a.get("role") != "assistant" or a.get("busy") or a.get("error") or i == 0 or (a.get("ms") or 0) < 3000: continue
        q = m[i - 1]["text"].strip(); p = prefix + q + "<|im_end|>\n" + OPEN
        for t in a.get("tools") or []:
            try: ar = json.loads(t.get("args") or "{}")
            except Exception: ar = {}
            items.append((q, p, call_text(t["name"], ar) + "<|im_end|>"))
            p += call_text(t["name"], ar) + "<|im_end|>\n<|im_start|>user\n<tool_response>\n" + (t.get("result") or "") + "\n</tool_response><|im_end|>\n" + OPEN
        items.append((q, p, (a.get("text") or "") + "<|im_end|>"))
# test = last 2 rounds of the 5 most recent distinct questions (newest first), corpus = outputs of other questions
qs = []
for q, _, _ in reversed(items):
    if q.lower() not in [x.lower() for x in qs]: qs.append(q)
    if len(qs) == 5: break
test = [it for it in items if it[0] in qs]
seen = {}; T = []
for it in reversed(test):
    if seen.get(it[0], 0) < 2 and it[1] not in [x[1] for x in T]: T.append(it); seen[it[0]] = seen.get(it[0], 0) + 1
corp = [it[2] for it in items if it[0].lower() not in [x.lower() for x in qs]]
ids = subprocess.run([TOK, VOC], input="\x1e".join(corp).encode(), capture_output=True).stdout.decode().splitlines()
with open(N + "/chatlab/chat_corpus_lab.jsonl", "w") as f:
    for l in ids: f.write("[" + ",".join(l.split()) + "]\n")
for k, (q, p, _) in enumerate(T):
    json.dump({"kind": "reason", "prompt": p, "prefix": prefix, "keep": True, "max_new": 220, "id": f"chat{k}"}, open(f"{N}/chatlab/req/c{k}.json", "w"))
    open(f"{N}/chatlab/req/c{k}.json", "a").write("\n")
print(len(items), "rounds;", len(T), "test reqs;", len(corp), "corpus docs; questions", qs)
