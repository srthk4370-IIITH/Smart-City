"""v2 finalize: MANIFEST.json, MD5SUMS, SUMMARY.md; READY only when every check passed.
  python3 v2_finalize.py data/final_v2"""
import collections
import hashlib
import json
import math
import os
import re
import sys

D = sys.argv[1]
MAXLEN = 7424
J = lambda f: json.load(open(os.path.join(D, f), encoding="utf-8"))  # noqa: E731
vf, v2, tk, bs = J("verify.json"), J("verify_v2.json"), J("tokens_v4.json"), J("build_stats_v2.json")
checks = collections.OrderedDict()
checks["pass2 verify_final.py: 0 failures"] = sum(v for k, v in vf.items() if ":FAIL:" in k) == 0
checks["pass2 think rules: 0 BAD"] = sum(v for k, v in vf.items() if k.endswith("_BAD")) == 0
checks["pass2 tests overlap with train = 0"] = all(v == 0 for k, v in vf.items() if k.endswith("overlap_with_train"))
checks["pass3 v2_verify.py: 0 failures"] = v2.get("fail_total", 1) == 0
checks["longest row < max_len %d" % MAXLEN] = max(v["max_tokens"] for k, v in tk.items() if isinstance(v, dict)) < MAXLEN
checks["no generator exceptions"] = not any(k.startswith("exc:") for k in bs)
rows = collections.Counter()
blocks = collections.Counter()
ex = collections.defaultdict(list)
for fn in ("train_new.jsonl", "replay.jsonl"):
    for l in open(os.path.join(D, fn), encoding="utf-8"):
        r = json.loads(l)
        rows[fn] += 1
        b = r.get("block", "?")
        blocks[(fn, b, bool(r.get("v2_add")))] += 1
        if r.get("v2_add") and fn == "train_new.jsonl":
            key = b if not b.startswith("v4_xfloor_") else ("v4_xfloor_neg" if "neg_" in b else "v4_xfloor_pos")
            key = "v4_weak" if b.startswith("v4_weak_multihop") else key
            want = 2
            if key == "v4_agt3":
                tag = r.get("family", "").split(":")[-1]
                if any(e.get("family", "").split(":")[-1] == tag for e in ex[key]):
                    continue
            if len(ex[key]) < want:
                ex[key].append(r)
checks["train_new rows 12-15k"] = 12000 <= rows["train_new.jsonl"] <= 15000
files = sorted(os.path.join(dp, f) for dp, _, fs in os.walk(D) for f in fs if "/work" not in dp and f not in ("MD5SUMS", "READY", "SUMMARY.md", "MANIFEST.json"))
man = {"files": {}, "rows": dict(rows), "blocks": {"%s:%s%s" % (a, b, " (v2)" if c else ""): n for (a, b, c), n in sorted(blocks.items())}}
for p in files:
    rel = os.path.relpath(p, D)
    man["files"][rel] = {"md5": hashlib.md5(open(p, "rb").read()).hexdigest(),
                         "rows": sum(1 for _ in open(p, "rb")) if p.endswith(".jsonl") else None}
# tokens + ETA (--mix 0.75: 12 new + 4 replay per step)
tn = sum(v["epoch_tokens_M"] for k, v in tk.items() if k.startswith("train_new.jsonl:"))
rp_rows = sum(v["rows"] for k, v in tk.items() if k.startswith("replay.jsonl:"))
rp_tok = sum(v["epoch_tokens_M"] for k, v in tk.items() if k.startswith("replay.jsonl:"))
steps = math.ceil(rows["train_new.jsonl"] / 12)
rep_seen = steps * 4
tot = tn + rep_seen * rp_tok / max(rp_rows, 1)
hours = tot * 1e6 / 800 / 3600
man["tokens"] = {"train_new_M_per_pass": round(tn, 2), "replay_M_per_pass": round(rp_tok, 2), "steps_mix075": steps,
                 "replay_rows_seen": rep_seen, "replay_passes": round(rep_seen / max(rp_rows, 1), 2), "total_M": round(tot, 2),
                 "hours_at_800": round(hours, 1), "hours_busy_with_evals": round(hours + 1, 1)}
if os.environ.get("P2_FAMILIES") != "1":  # full v2 fine-tune plan only; the part-2 top-up trains ~220 steps (rsn_p2_train.sh)
    checks["ETA 16-20 h busy"] = 16 <= hours + 1 <= 20.5
man["checks"] = checks
json.dump(man, open(os.path.join(D, "MANIFEST.json"), "w", newline="\n"), indent=1)
with open(os.path.join(D, "MD5SUMS"), "w", newline="\n") as f:
    for p in files + [os.path.join(D, "MANIFEST.json")]:
        f.write("%s  ./%s\n" % (hashlib.md5(open(p, "rb").read()).hexdigest(), os.path.relpath(p, D)))


def short(r):
    u = next(m["content"] for m in r["messages"] if m["role"] == "user")
    a = r["messages"][-1]
    if r.get("tools", "").startswith("incident"):
        u = re.sub(r"\n  S(\d+)\.E([2-9]|10) [^\n]*", "", u)
        u = u[u.find("SITE:"):][:1400]
        th = a.get("reasoning_content")
        return "```\n%s\n```\n%s```json\n%s\n```\n" % (u, ("think: %s\n" % th) if th else "", a["content"][:700])
    conv = []
    for m in r["messages"][1:]:
        t = m.get("content") or ""
        if m.get("tool_calls"):
            t += " calls: " + json.dumps([[c["function"]["name"], c["function"]["arguments"]] for c in m["tool_calls"]])[:240]
        conv.append("%s: %s" % (m["role"], t[:260]))
    return "```\n%s\n```\n" % "\n".join(conv[:8])


S = ["# rsn fine-tune dataset v2 (2026-11-15)", "",
     "v1 (APPROVED, `data/final/`, unchanged rows, first %d lines of train_new / %d of replay byte-identical) + v2 additions. "
     "Builders: `v2_windows.py`, `v2_agent_run.py`, `v2_gen.py`, `build_v2.py` (seed 11115), `v2_verify.py`, `v2_finalize.py`; "
     "run: `v2_stage1.sh` then `v2_stage2.sh`. CPU only." % (v2.get("v1_rows_identical:train_new.jsonl", 0), v2.get("v1_rows_identical:replay.jsonl", 0)), "",
     "## Checks (training starts only when all are true)", ""]
S += ["- %s: **%s**" % (k, "PASS" if v else "FAIL") for k, v in checks.items()]
S += ["", "## Rows per block", "", "| file | block | rows |", "|---|---|---|"]
S += ["| %s | %s%s | %d |" % (a, b, " (v2)" if c else "", n) for (a, b, c), n in sorted(blocks.items())]
S += ["", "Totals: train_new %d, replay %d." % (rows["train_new.jsonl"], rows["replay.jsonl"]), "",
      "## agt_v3 real outputs", "",
      "Windows %s, outputs %s (unparsable %s). Agent right/wrong: synthetic %s/%s, real %s/%s; rows with the agent wrong %s "
      "(mistake windows rendered on 2 sites). Error kinds (gold->agent): %s." % (
          bs.get("agt_windows"), bs.get("agt_outputs"), bs.get("agt_unparsable", 0), bs.get("agt_syn:right", 0), bs.get("agt_syn:wrong", 0),
          bs.get("agt_real:right", 0), bs.get("agt_real:wrong", 0), v2.get("agt3_rows_agent_wrong", 0),
          ", ".join("%s %d" % (k[8:], v) for k, v in sorted(bs.items()) if k.startswith("agt_err:"))), "",
      "## Tokens and ETA (Qwen3.5-4B template, 600-row samples per block)", "",
      "train_new %.2f M per pass, replay %.2f M per pass (%d rows). `--mix 0.75`: %d steps, replay seen %d rows (%.2f passes) -> "
      "**%.1f M tokens, %.1f h at 800 tok/s, ~%.1f h busy with evals**." % (
          tn, rp_tok, rp_rows, steps, rep_seen, rep_seen / max(rp_rows, 1), tot, hours, hours + 1), "",
      "## Info (inherited from the approved v1 rows, not changed, not counted as failures)", ""]
S += ["- %s: %d" % (k, v) for k, v in sorted(v2.items()) if k.startswith("info_")]
S += ["", "## Examples (2 per new family, E2-E10 lines cut)", ""]
for k in sorted(ex):
    for r in ex[k]:
        S += ["### %s `%s` (%s)" % (k, r.get("family"), r.get("reasoning_type")), "", short(r)]
open(os.path.join(D, "SUMMARY.md"), "w", newline="\n").write("\n".join(S) + "\n")
ok = all(checks.values())
if ok:
    open(os.path.join(D, "READY"), "w", newline="\n").write(
        "v2 data READY (all checks pass) train_new %d md5 %s replay %d md5 %s; %.1f M tokens, %.1f h at 800 tok/s (--mix 0.75)\n" % (
            rows["train_new.jsonl"], man["files"]["train_new.jsonl"]["md5"], rows["replay.jsonl"], man["files"]["replay.jsonl"]["md5"], tot, hours))
elif os.path.exists(os.path.join(D, "READY")):
    os.remove(os.path.join(D, "READY"))
print(json.dumps({"checks": checks, "tokens": man["tokens"], "rows": dict(rows)}))
sys.exit(0 if ok else 1)
