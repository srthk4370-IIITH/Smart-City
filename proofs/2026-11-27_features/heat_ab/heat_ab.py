"""A/B the reasoner on the board's heat prompts (feature runs 2 and 3): original vs added facts.
Variants:
  A  original board prompt
  B  + AGREE line (two same-room temperature sensors rose together, with start/end values)
  C  memory filtered to the incident metric (drops the rh 'sensor offset' M1)
  D  B + C
  E  related temperature sensor keeps its min/max lines (S2.E2, S2.E3)
"""
import json, sys, time, urllib.request, re, concurrent.futures as cf

H = r"C:\Users\hp\AppData\Local\Temp\claude\5cb597a87cde10fb\125df7ac-c9eb-46de-b63b-ce87f4c7e8ce\scratchpad\heat"
URL = "http://127.0.0.1:8291/completion"
SEEDS = [None, 1, 2, 3, 4, 5, 6, 7]

AGREE = {
    "run2": "AGREE: S1 temp and S2 room_temp are two independent temperature sensors in the same room; both rose over the window: S1 24.6 -> 34.5 C, S2 24.1 -> 33.5 C (now 1.0 C apart).",
    "run3": "AGREE: S1 temp and S2 room_temp are two independent temperature sensors in the same room; both rose over the window: S1 24.6 -> 34.5 C, S2 24.1 -> 33.5 C (now 1.0 C apart).",
}


def variants(run, p):
    out = {"A": p}
    i = p.index("MEMORY (past")
    b = p[:i] + AGREE[run] + "\n" + p[i:]
    out["B"] = b
    mem_re = re.compile(r"  M1 [^\n]*Room humidity[^\n]*\n")
    c = mem_re.sub("", p).replace("  M2 ", "  M1 ").replace("  M3 ", "  M2 ")
    assert c != p
    out["C"] = c
    out["D"] = mem_re.sub("", b).replace("  M2 ", "  M1 ").replace("  M3 ", "  M2 ")
    j = p.index("  S2.E4 trend")
    out["E"] = p[:j] + "  S2.E2 max = 33.5 C at %s\n  S2.E3 min = 24.1 C at 12:45\n" % ("14:45" if run == "run2" else "15:25") + p[j:]
    return out


def call(prompt, seed):
    body = {"prompt": prompt, "n_predict": 3000, "cache_prompt": True}
    if seed is None:
        body.update(temperature=0, top_k=1)
    else:
        body.update(temperature=0.7, top_p=0.9, seed=seed)
    req = urllib.request.Request(URL, json.dumps(body).encode(), {"Content-Type": "application/json"})
    t = time.time()
    r = json.load(urllib.request.urlopen(req, timeout=600))
    return r["content"], time.time() - t


def verdict(txt):
    tail = txt.split("</think>")[-1]
    m = re.search(r"\{.*\}", tail, re.S)
    try:
        j = json.loads(m.group(0))
    except Exception:
        return {"sev": "PARSE_FAIL", "label": "", "title": tail[:80]}
    return {"sev": j.get("severity"), "label": j.get("label"), "title": j.get("title", "")[:90],
            "suspect": j.get("suspect_sensors"), "expl": j.get("explanation", "")[:160]}


def main():
    jobs = []
    for run in ("run2", "run3"):
        p = open(f"{H}\\{run}_prompt.txt", encoding="utf-8").read()
        for v, pr in variants(run, p).items():
            for s in SEEDS:
                jobs.append((run, v, s, pr))
    out = open(f"{H}\\heat_ab.jsonl", "w", encoding="utf-8")
    with cf.ThreadPoolExecutor(2) as ex:
        futs = {ex.submit(call, pr, s): (run, v, s) for run, v, s, pr in jobs}
        for f in cf.as_completed(futs):
            run, v, s = futs[f]
            txt, dt = f.result()
            row = {"run": run, "variant": v, "seed": s, "s": round(dt, 1), **verdict(txt), "raw": txt}
            out.write(json.dumps(row) + "\n"); out.flush()
            print(run, v, s, row["sev"], row["label"], "|", row["title"], f"{dt:.0f}s", flush=True)


if __name__ == "__main__":
    main()
