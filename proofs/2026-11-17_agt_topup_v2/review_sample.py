"""review_sample.py TRAIN OUT.md [--full=NEW_FULL.jsonl] [--seed=20261117]: 20 random rows of the upload, readable for a human:
4 tool-call conversations, 4 dynamic windows, 6 hard cases (one per type), 6 replay (3 real, 3 synthetic). The system text is shown once in shortened form."""
import json
import random
import re
import sys

EOT = "<|eot_id|>"
ASSIST = "<|start_header_id|>assistant<|end_header_id|>\n\n"
IPY = "<|start_header_id|>ipython<|end_header_id|>\n\n"
a = [x for x in sys.argv[1:] if not x.startswith("--")]
o = {x.split("=")[0]: x.split("=", 1)[1] for x in sys.argv[1:] if x.startswith("--") and "=" in x}
rng = random.Random(int(o.get("--seed", 20261117)))
rows = [json.loads(l) for l in open(a[0], encoding="utf-8") if l.strip()]
HARD = ["hard_standby", "hard_leak", "hard_night", "hard_plateau", "hard_limits", "hard_ph"]


def pick(f, k):
    c = [r for r in rows if f(r)]
    rng.shuffle(c)
    return c[:k]


def final_of(r):
    return not r["completion"].startswith('{"tool"')


def user_body(prompt):
    u = prompt.split("<|start_header_id|>user<|end_header_id|>\n\n", 1)[1]
    return u.split(EOT)[0]


def pretty(c):
    try:
        d = json.loads(c.replace(EOT, ""))
    except Exception:  # noqa: BLE001
        return c
    if "tool" in d:
        return json.dumps(d)
    keys = ("pattern", "status", "data_quality", "severity_reason", "observations", "likely_cause", "event_active", "onset", "fault_kind", "action")
    return json.dumps({k: d[k] for k in keys if k in d}, ensure_ascii=False, indent=1)


def render(r, title):
    p = r["prompt"]
    parts = p.split(ASSIST)
    out = ["### %s" % title, "`%s`  family `%s`  stage `%s`  role `%s`  source `%s`" % (r["id"], r["family"], r.get("stage"), r.get("role"), r.get("source")), "",
           "system: Llama-3 text, %d chars (agent system prompt, unchanged)" % len(p.split(EOT)[0]), "", "**user**", "```", user_body(p), "```"]
    for seg in parts[1:-1]:
        m = re.match(r"^(.*?)" + re.escape(EOT) + re.escape(IPY) + r"(.*)" + re.escape(EOT) + "$", seg, re.S)
        out += ["", "**assistant (tool call)**", "```", m.group(1), "```", "**ipython (tool result)**", "```", m.group(2), "```"]
    out += ["", "**assistant (%s)**" % ("tool call" if not final_of(r) else "answer"), "```", pretty(r["completion"]), "```", ""]
    return "\n".join(out)


sel = []
tool_final = pick(lambda r: r.get("turn") == "final" and r["prompt"].count(ASSIST) >= 2, 40)
kinds, tf = set(), []
for r in tool_final:
    k = r.get("tool_kind", "").split("_")[0]
    if k not in kinds and len(tf) < 4:
        kinds.add(k)
        tf.append(r)
for r in tool_final:
    if len(tf) < 4 and r not in tf:
        tf.append(r)
sel += [("TOOL-CALL conversation (last turn shown with all earlier turns)", r) for r in tf]
sel += [("DYNAMIC window", r) for r in pick(lambda r: r["family"].startswith("dyn_"), 4)]
for f in HARD:
    sel += [("HARD case %s" % f, r) for r in pick(lambda r, f=f: r["family"] == f, 1)]
sel += [("REPLAY real window", r) for r in pick(lambda r: r.get("synthetic") is False, 3)]
sel += [("REPLAY synthetic", r) for r in pick(lambda r: r.get("synthetic") and r.get("source") != "synthetic_sim_v2", 3)]
head = ["# REVIEW_SAMPLE: 20 random rows of the top-up v2 upload", "",
        "Seeded sample (seed %s) of data/train.jsonl for human review: %d tool-call, %d dynamic-window, %d hard-case, %d replay rows. Real replay windows are shown "
        "because they are in the private Kaggle dataset (owner exception, logged in AGENT_REGISTRY.md); do not publish this file." % (
            o.get("--seed", 20261117), len(tf), 4, len(HARD), 6), ""]
body = [render(r, "%d. %s" % (i + 1, t)) for i, (t, r) in enumerate(sel)]
open(a[1], "w", encoding="utf-8", newline="\n").write("\n".join(head + body))
print("wrote", a[1], len(sel), "rows")
