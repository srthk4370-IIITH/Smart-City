"""Pool of REAL domain-agent outputs paired with the agent test gold (sft_v2/test.jsonl).

Each row: the agent's own input facts (NODE/METRIC/LIMITS/TANK/WINDOW header, EVIDENCE E1..E10), the gold labels
from the v2 test set, and one real model output (mixA50 = live model, plus v2 and other screened checkpoints for
error diversity). Output: data/real_pool.jsonl. Prints 1 summary line.
"""
import glob, hashlib, json, os, re, sys, collections

Q = "C:/Users/hp/Desktop/qidk"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
TEST = Q + "/Code/smart-city-edge-agent/data/sft_v2/test.jsonl"
# (glob, model tag); live model first
SRC = [(Q + "/proofs/2026-10-23_v2t3f/raw/*/mixA50/samples.jsonl", "mixA50"),
       (Q + "/proofs/2026-10-24_v2t3g/board_ab/mixA50/host400/samples.jsonl", "mixA50_board"),
       (Q + "/proofs/2026-10-23_v2t3f/raw/*/v2cuda/samples.jsonl", "v2"),
       (Q + "/proofs/2026-10-20_v2_post/device/test_all/samples.jsonl", "v2_board"),
       (Q + "/proofs/2026-10-24_v2t3g/board_ab/v2/host400/samples.jsonl", "v2_board"),
       (Q + "/proofs/2026-10-23_v2t3f/raw/dev/mixRep50/samples.jsonl", "mixRep50"),
       (Q + "/proofs/2026-10-23_v2t3f/raw/dev/soup3/samples.jsonl", "soup3"),
       (Q + "/proofs/2026-10-23_v2t3f/raw/dev/m50rw50/samples.jsonl", "m50rw50"),
       (Q + "/proofs/2026-10-23_app_ab_v2_vs_3d/v2t3d/host400/samples.jsonl", "v2t3d")]


def heldout_node(node):
    return int(hashlib.md5(node.encode()).hexdigest(), 16) % 10 == 0


def parse_pred(t):
    """outputs stop at the 'action' key (backend picks the action by rule): trim it and close the object"""
    t = t.strip()
    for cand in (t, re.sub(r',\s*"action"\s*:?\s*$', "", t) + "}", re.sub(r',\s*"[a-z_]*"\s*:?\s*$', "", t) + "}"):
        try:
            o = json.loads(cand)
            if isinstance(o, dict):
                return o
        except Exception:
            pass
    return None


def parse_prompt(p):
    u = p.split("user<|end_header_id|>", 1)[1].split("<|eot_id|>", 1)[0].strip()
    head, ev = [], []
    in_ev = False
    for ln in u.split("\n"):
        if ln.startswith("EVIDENCE:"):
            in_ev = True
            continue
        if in_ev:
            m = re.match(r"(E\d+) (.*)", ln)
            if m:
                ev.append([m.group(1), m.group(2)])
        elif re.match(r"(NODE|METRIC|LIMITS|TANK|WINDOW):", ln):
            head.append(ln)
    return head, ev


def main():
    test = {}
    for l in open(TEST, encoding="utf-8"):
        d = json.loads(l)
        test[d["id"]] = d
    rows, seen = [], set()
    c = collections.Counter()
    for pat, tag in SRC:
        for f in glob.glob(pat):
            for l in open(f, encoding="utf-8"):
                s = json.loads(l)
                t = test.get(s.get("id"))
                if t is None or not s.get("text"):
                    continue
                pred = parse_pred(s["text"])
                key = (s["id"], s["text"])
                if key in seen:
                    continue
                seen.add(key)
                head, ev = parse_prompt(t["prompt"])
                if len(ev) < 3:
                    continue
                rows.append({"id": s["id"], "model": tag, "role": t["role"], "node": t["node"], "metric": t["metric"],
                             "end_epoch": t["end_epoch"], "n": t["n"], "family": t["family"], "sub": t.get("sub"),
                             "gold": {k: t.get(k) for k in ("pattern", "status", "likely_cause", "fault_kind", "event_active", "onset", "action")},
                             "head": head, "ev": ev, "pred": pred, "pred_text": s["text"],
                             "split": "heldout" if heldout_node(t["node"]) else "train"})
                c[tag] += 1
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "real_pool.jsonl"), "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    wrong = sum(1 for r in rows if not r["pred"] or r["pred"].get("status") != r["gold"]["status"])
    ho = sum(r["split"] == "heldout" for r in rows)
    print("real_pool rows=%d distinct_ids=%d status_wrong=%d heldout=%d by_model=%s" % (
        len(rows), len({r["id"] for r in rows}), wrong, ho, dict(c)))


if __name__ == "__main__":
    main()
