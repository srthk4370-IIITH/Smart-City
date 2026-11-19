"""patch_trainer.py -> train_agt3b.py: the agt3 trainer with a tool+hard dev eval (turn-1 rows use the '{"' prefill and call_ok/direct_ok; others the row prefill
and gen_score). dev score = mean of the group scores (t1, t2/final, hard); early stop = score DROPS (< previous eval - .001) --patience times IN A ROW."""
import sys
src = open("/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-13_v3_train/agt/kaggle/train_agt3.py").read()
def rep(a, b):
    global src
    assert src.count(a) == 1, a
    src = src.replace(a, b)
rep('texts = [r["prompt"] + RW.prefill(r["completion"]) for r in b]',
    'pres = [\'{"\' if r["raw"].get("turn") in ("call", "direct") else RW.prefill(r["completion"]) for r in b]\n        texts = [r["prompt"] + p for r, p in zip(b, pres)]')
rep('''            for r, seq in zip(b, g[:, enc["input_ids"].shape[1]:]):
                t = RW.prefill(r["completion"]) + tok.decode(seq, skip_special_tokens=True)
                out.append(dict(RW.score(r["gold"], t), id=r["id"]))''',
'''            for r, p, seq in zip(b, pres, g[:, enc["input_ids"].shape[1]:]):
                t = p + tok.decode(seq, skip_special_tokens=True)
                out.append(dict(score_row(r, t), id=r["id"]))''')
rep('# ---------------------------------------------------------------- gen dev score\n', '''# ---------------------------------------------------------------- gen dev score
def score_row(r, t):
    turn = r["raw"].get("turn")
    if turn not in ("call", "direct"):
        return dict(RW.score(r["gold"], t), grp="final" if turn == "final" else "hard")
    d = RW.parse(t.replace("<|eot_id|>", "").strip())
    isc = isinstance(d, dict) and "tool" in d
    s = {"json": isinstance(d, dict), "grp": "t1", "status": None, "pattern": None, "cause": None, "dq": None, "ok": None}
    s["ok"] = bool(isc and d.get("tool") == r["gold"].get("tool") and d.get("args") == r["gold"].get("args")) if turn == "call" else (not isc)
    return s


def combo_score(sc):
    g = {}
    for s in sc:
        g.setdefault(s.get("grp", "hard"), []).append(s)
    v = [(sum(bool(s["ok"]) for s in x) / len(x)) if k == "t1" else RW.gen_score(x) for k, x in g.items()]
    return sum(v) / len(v) if v else 0.0


''')
rep('g = RW.gen_score(sc)', 'g = combo_score(sc)')
rep('''            gain = best["best"] is None or g > best["best"] + a.min_gain
            if gain:
                best.update(best=g, best_step=step, since=0)
            else:
                best["since"] += 1''', '''            last = best["evals"][-1]["score"] if best["evals"] else None
            if best["best"] is None or g > best["best"]:
                best.update(best=g, best_step=step)
            best["since"] = best["since"] + 1 if (last is not None and g < last - 0.001) else 0''')
open(sys.argv[1], "w", newline="\n").write(src)
