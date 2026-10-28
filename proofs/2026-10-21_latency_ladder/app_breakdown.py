"""Through-the-app latency breakdown of Mode 3 incidents (no backend change needed; reads the app's own API).
Run it right after app/tools/stress_app.py (it reads that run's stress_report.json for the incident ids), or pass ids.

  py -3 app_breakdown.py OUTDIR [--report PATH] [--ids INC-0001,INC-0002] [--max-batch 10] [--pull-logs]

Per incident (full JSON saved to OUTDIR/incidents/<id>.json):
  agents phase   the NPU agents in the order the backend batches them (backend splits at htpdMaxBatch: 10, or 14
                 with the one-batch profile); a batch's wall = the largest agent latency in it (htpd reports each
                 answer's time from its own batch start), plus its largest first-token time (= the batch's prefill)
  solo re-runs   timeline lines "re-running alone" (an invalid batched answer re-run once); duration from the
                 timeline's 1 s timestamps
  synthesizer    final.latency_ms / ttft_ms / gen_tokens, prompt tokens (Llama 3.2 tokenizer if available)
  residual       total - batches - solo - synth: the 250 ms call gap, thermal pacing (>= 88 C waits up to 15 s for
                 82 C before the synth/solo call), orchestration
Also writes OUTDIR/chaos_prompts.jsonl and OUTDIR/synth_prompts.jsonl (exact app prompts, for ab_ladder.py CR / SC;
copy them next to ab_ladder.py), OUTDIR/breakdown.json and, with --pull-logs, the backend log (thermal pacing lines)
and htpd.log (draft steps per batch) from the device.
"""
import argparse, json, re, subprocess, urllib.request
from datetime import datetime
from pathlib import Path

H = Path(__file__).resolve().parent
Q = Path(r"C:\Users\hp\Desktop\qidk")
ADB = str(Q / "Code/platform-tools/adb.exe")
B = "http://127.0.0.1:8000"
STATE = "/data/local/tmp/smart_city_edge/state"
try:
    from tokenizers import Tokenizer
    _tok = Tokenizer.from_file(str(Q / "qidk_backup/ckpt_ftgptq16/tokenizer.json"))
    ntok = lambda s: len(_tok.encode(s, add_special_tokens=False).ids)
except Exception:
    ntok = lambda s: None


def get(path):
    with urllib.request.urlopen(B + path, timeout=30) as r:
        return json.loads(r.read())


def tsec(t):
    return datetime.strptime(t, "%H:%M:%S")


def breakdown(inc, max_batch):
    llm = [a for a in inc.get("agents") or [] if a.get("prompt")]
    batches = [llm[i:i + max_batch] for i in range(0, len(llm), max_batch)] if len(llm) > 1 else []
    bw = [round(max(a.get("latency_ms") or 0 for a in b)) for b in batches]
    bp = [round(max(a.get("ttft_ms") or 0 for a in b)) for b in batches]
    tl = inc.get("timeline") or []
    solo = []
    for i, e in enumerate(tl):
        if "re-running alone" in e["msg"] and i + 1 < len(tl):
            solo.append((tsec(tl[i + 1]["t"]) - tsec(e["t"])).total_seconds() * 1000)
    fin = inc.get("final") or {}
    syn_ms = fin.get("latency_ms") or 0
    synth = None
    if syn_ms:
        synth = dict(ms=round(syn_ms), ttft_ms=round(fin.get("ttft_ms") or 0), tokens=fin.get("gen_tokens"),
                     tok_s=round(fin.get("tokens_per_s") or 0, 1), prompt_tokens=ntok(fin.get("prompt") or ""))
    single = None
    if len(llm) == 1:
        a = llm[0]
        single = dict(role=a.get("role"), ms=round(a.get("latency_ms") or 0), ttft_ms=round(a.get("ttft_ms") or 0),
                      tokens=a.get("gen_tokens"), tok_s=round(a.get("tokens_per_s") or 0, 1), prompt_tokens=ntok(a["prompt"]))
    total = inc.get("total_ms") or 0
    agents_ms = sum(bw) if batches else (single or {}).get("ms", 0)
    resid = total - agents_ms - sum(solo) - syn_ms
    return dict(id=inc["id"], state=inc.get("state"), refine_stage=inc.get("refine_stage"), total_ms=round(total),
                npu_calls=inc.get("npu_calls"), llm_agents=len(llm), roles=[a.get("role") for a in llm],
                batch_sizes=[len(b) for b in batches], batch_wall_ms=bw, batch_prefill_ms=bp,
                agent_tokens_max=[max((a.get("gen_tokens") or 0) for a in b) for b in batches],
                solo_reruns=len(solo), solo_ms_timeline=solo, synth=synth, single=single,
                residual_ms=round(resid), invalid=[a.get("ref") for a in llm if not a.get("valid")])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--report", default=str(Q / "Code/smart-city-edge-agent/app/tools/stress_report.json"))
    ap.add_argument("--ids")
    ap.add_argument("--max-batch", type=int, default=10)
    ap.add_argument("--pull-logs", action="store_true")
    a = ap.parse_args()
    out = Path(a.out)
    (out / "incidents").mkdir(parents=True, exist_ok=True)
    ids = a.ids.split(",") if a.ids else [i["id"] for i in json.load(open(a.report, encoding="utf-8")).get("incidents", [])]
    rows, chaos, synth = [], [], []
    for iid in ids:
        inc = get(f"/api/incidents/{iid}")
        json.dump(inc, open(out / "incidents" / f"{iid}.json", "w", encoding="utf-8"), indent=1)
        r = breakdown(inc, a.max_batch)
        rows.append(r)
        llm = [x for x in inc.get("agents") or [] if x.get("prompt")]
        if len(llm) >= 8:
            chaos.append({"id": iid, "prompts": [x["prompt"] for x in llm]})
        if (inc.get("final") or {}).get("prompt") and (inc.get("final") or {}).get("latency_ms"):
            synth.append({"id": iid, "sensors": len(inc.get("sensors") or []), "prompt": inc["final"]["prompt"]})
        s = r["synth"] or {}
        print(f"{iid}: total {r['total_ms']/1e3:.1f}s, {r['llm_agents']} agents in batches {r['batch_sizes']} "
              f"walls {r['batch_wall_ms']} (prefill {r['batch_prefill_ms']}), solo {r['solo_reruns']}, "
              f"synth {s.get('ms')} ms ({s.get('prompt_tokens')} prompt tok, {s.get('tokens')} out), residual {r['residual_ms']} ms"
              + (f", single {r['single']}" if r["single"] else ""))
    json.dump(rows, open(out / "breakdown.json", "w"), indent=1)
    for name, items in (("chaos_prompts.jsonl", chaos), ("synth_prompts.jsonl", synth)):
        with open(out / name, "w", encoding="utf-8", newline="\n") as fh:
            for it in items:
                fh.write(json.dumps(it, ensure_ascii=False) + "\n")
    if a.pull_logs:
        for f in ("agent.log", "htpd.log"):
            subprocess.run([ADB, "pull", f"{STATE}/{f}", str(out / f)], capture_output=True, timeout=120)
        lg = out / "agent.log"
        if lg.exists():
            pac = [l.strip() for l in open(lg, errors="replace") if "thermal pacing" in l]
            (out / "thermal_pacing.txt").write_text("\n".join(pac[-50:]) + "\n", encoding="utf-8")
            print(f"thermal pacing lines in agent.log: {len(pac)} (last 50 in thermal_pacing.txt)")
    print(f"wrote {out / 'breakdown.json'}, {len(chaos)} chaos prompt sets, {len(synth)} synth prompts")


if __name__ == "__main__":
    main()
