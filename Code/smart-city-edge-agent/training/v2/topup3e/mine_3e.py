"""Mine v2's own mistakes on the train-month pool (GPU, nf4 base + v2 adapter = the training-time model).

Teacher-forced argmax on the gold completion: pattern is the first decision after the prefill, so its argmax IS
greedy; status is conditioned on the gold pattern. For the first wrong field (pattern, else status) the model's own
greedy value is generated from the gold prefix and a preference pair (gold vs own value) is built with reference
(= v2) log-probs. Resumable (appends to mined.jsonl).

  python mine_3e.py --pool pool.jsonl --out mined.jsonl [--limit N]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

import torch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "topup"))
import common3e as K  # noqa: E402
import decision_eval as DE  # noqa: E402


def amp_info(r):
    try:
        import diag_data as DD
        if r.get("d") and r.get("hist") and r.get("pattern") not in ("stable", None):
            v = DD.visibility(r)
            return None if v is None else v["amp"]
    except Exception:  # noqa: BLE001
        return None
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pool", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--hot", type=int, default=76)
    ap.add_argument("--cool", type=int, default=68)
    ap.add_argument("--adapter", default=K.V2_ADAPTER)
    a = ap.parse_args()
    rows = K.read_jsonl(a.pool)
    rows.sort(key=lambda r: hashlib.md5((r["id"] + "|mine").encode()).hexdigest())
    if a.limit:
        rows = rows[:a.limit]
    outp = Path(a.out)
    done = {json.loads(l)["id"] for l in open(outp)} if outp.exists() else set()
    todo = [r for r in rows if r["id"] not in done]
    print(f"{len(todo)} of {len(rows)} to mine", flush=True)
    tok, model = K.load_model(a.adapter)
    model.eval()
    fh = open(outp, "a")
    t0, nerr = time.time(), 0
    import subprocess

    def gpu_t():
        try:
            return int(subprocess.run(["nvidia-smi", "--query-gpu=temperature.gpu", "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=15).stdout.split()[0])
        except Exception:  # noqa: BLE001
            return 99
    for n, r in enumerate(todo, 1):
        if n % 10 == 0 and gpu_t() >= a.hot:
            while gpu_t() > a.cool:
                time.sleep(10)
        p = K.tok_ids(tok, r["prompt"])
        c, fields = DE.field_tokens(tok, r["completion"])
        x = torch.tensor([p + c], device="cuda")
        with torch.no_grad(), torch.autocast("cuda", dtype=torch.bfloat16):
            lg = model(input_ids=x, attention_mask=torch.ones_like(x), num_logits_to_keep=len(c) + 1).logits[0, :-1]
        am = lg.argmax(-1).tolist()
        ok = {k: all(am[i] == c[i] for i in idx) for k, idx in fields.items() if idx}
        g = DE.gold(r)
        rec = {"id": r["id"], "role": r["role"], "bucket": r.get("topup_bucket"), "stage": r.get("stage"), "d": r.get("d"),
               "n": r.get("n"), "slices": r.get("slices", []), "learnable": r.get("learnable", True), "amp": amp_info(r),
               "gold_pattern": g["pattern"], "gold_status": g["status"], "ok": ok}
        wrong = next((f for f in K.FIELDS if f in ok and not ok[f]), None)
        if wrong:
            s, _ = K.value_span(r["completion"], wrong)
            pre = K.tok_ids(tok, r["completion"][:s])
            xi = torch.tensor([p + pre], device="cuda")
            with torch.no_grad(), torch.autocast("cuda", dtype=torch.bfloat16):
                gen = model.generate(input_ids=xi, attention_mask=torch.ones_like(xi), max_new_tokens=10, do_sample=False,
                                     temperature=None, top_p=None, pad_token_id=tok.pad_token_id)
            pred = tok.decode(gen[0, xi.shape[1]:], skip_special_tokens=True).split('"')[0]
            rec.update(wrong_field=wrong, pred=pred)
            if pred and pred != g[wrong]:
                pr = K.make_pair(tok, r["completion"], wrong, pred)
                with torch.no_grad(), torch.autocast("cuda", dtype=torch.bfloat16):
                    rc, _ = K.span_logp(model, p, pr["c_ids"], pr["lo"], pr["c_hi"])
                    rr, _ = K.span_logp(model, p, pr["r_ids"], pr["lo"], pr["r_hi"])
                pr.update(ref_c=float(rc), ref_r=float(rr))
                rec["pair"] = pr
                nerr += 1
        fh.write(json.dumps(rec) + "\n")
        fh.flush()
        if n % 100 == 0:
            el = time.time() - t0
            print(f"{n}/{len(todo)} {el / n:.2f}s/row pairs {nerr} eta {(len(todo) - n) * el / n / 60:.0f} min", flush=True)
    print("DONE", time.time() - t0, flush=True)


if __name__ == "__main__":
    main()
