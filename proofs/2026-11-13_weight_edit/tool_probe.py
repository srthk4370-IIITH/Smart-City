"""Quick probe (owner: max info, min time): where do chat tool failures come from? For r4 rows (unseen by r3) with gold tool calls,
teacher-forced on the gold conversation: (a) P(<tool_call>) at the start of the calling turn's answer, (b) gold tool name rank at <function=."""
import json, os, sys, collections, torch
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import we_think as WT
tok, m, layers = WT.load(); torch.set_grad_enabled(False)
tools = json.load(open(WT.TOOLS, encoding="utf-8"))["chat"]
TC = tok.convert_tokens_to_ids("<tool_call>")
want = collections.Counter(); out = []
for l in open(WT.QIDK + "/proofs/2026-11-12_topup_r4/data/final/train_new.jsonl", encoding="utf-8"):
    r = json.loads(l)
    if r.get("tools") != "chat":
        continue
    for i, msg in enumerate(r["messages"]):
        if msg["role"] != "assistant" or not msg.get("tool_calls"):
            continue
        name = msg["tool_calls"][0]["function"]["name"]
        if want[name] >= 25:
            break
        full = tok.apply_chat_template(r["messages"][:i + 1], tools=tools, tokenize=False, enable_thinking=bool(r.get("hard")))
        a = full.rfind("<tool_call>"); b = full.find("<function=", a) + len("<function=")
        ids_a = tok(full[:a], add_special_tokens=False, return_tensors="pt").input_ids.cuda()
        ids_b = tok(full[:b], add_special_tokens=False, return_tensors="pt").input_ids.cuda()
        if ids_b.shape[1] > 11000:
            break
        pa = float(torch.softmax(m(input_ids=ids_a, logits_to_keep=1).logits[0, -1].float(), -1)[TC])
        lb = m(input_ids=ids_b, logits_to_keep=1).logits[0, -1].float()
        g = tok.encode(name, add_special_tokens=False)[0]; rank = int((lb > lb[g]).sum())
        top = tok.decode([int(lb.argmax())])
        out.append({"id": r["id"], "tool": name, "hard": bool(r.get("hard")), "p_call": pa, "name_rank": rank, "top": top})
        want[name] += 1
        break
    if len(out) >= 300:
        break
json.dump(out, open(os.path.expanduser("~/we_work/tool_probe.json"), "w"))
by = collections.defaultdict(list)
for o in out: by[o["tool"]].append(o)
print("%-28s %3s %8s %8s %s" % ("tool", "n", "p_call<.5", "name_ok", "wrong tops"))
for t, v in sorted(by.items(), key=lambda kv: -len(kv[1])):
    print("%-28s %3d %8.2f %8.2f %s" % (t, len(v), sum(o["p_call"] < 0.5 for o in v) / len(v), sum(o["name_rank"] == 0 for o in v) / len(v),
                                     dict(collections.Counter(o["top"] for o in v if o["name_rank"]).most_common(3))))
