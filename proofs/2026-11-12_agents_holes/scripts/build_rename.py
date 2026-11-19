"""Study A rows: 1,000 stratified dev3f rows (C.select_rows seed 2026 over eval_dev/eval3e.jsonl, 2,010 held-out windows)
+ the same windows with the NODE line renamed (novel building codes / levels / sensor numbers, type prefix kept, values
untouched) + 150 exact repeats of original rows (run-to-run noise floor). -> raw/rows_A.jsonl, raw/rename_map.json"""
import json, random, re, sys
from pathlib import Path
sys.path.insert(0, "/mnt/c/Users/hp/Desktop/qidk/Code/smart-city-edge-agent/training/v2/post")
import common_v2 as C
OUT = Path(__file__).resolve().parent.parent / "raw"
rows = C.read_jsonl(Path.home() / "smartcity_runs/agents_v2_topup3f/eval_dev/eval3e.jsonl")
pick = C.select_rows(rows, 1000, 2026)
NEW = ["BX", "DQ", "JR", "MZ", "FT", "WC", "GY", "LU", "OE", "ZA"]   # never used on campus data (AN KH KN MG PH PL SB SN TH VN)
rng = random.Random(7)
nodes = sorted({re.search(r"\nNODE: (\S+)", r["prompt"]).group(1) for r in pick})
maps = {}
for i, n in enumerate(nodes):
    line = next(re.search(r"\nNODE: (.*)\n", r["prompt"]).group(1) for r in pick if f"\nNODE: {n} " in r["prompt"])
    codes = sorted(set(re.findall(r"(?<![A-Z])(AN|KH|KN|MG|PH|PL|SB|SN|TH|VN)(?=\d|\b)", line)))
    num = {}
    for tok in re.findall(r"(?<!\d)(\d{2})(?!\d)(?! kV)", line):
        if tok not in num:
            while True:
                v = f"{rng.randint(1, 89):02d}"
                if v != tok and v not in num.values():
                    num[tok] = v; break
    cmap = {c: NEW[(i + j) % len(NEW)] for j, c in enumerate(codes)}
    new = re.sub(r"(?<![A-Z])(AN|KH|KN|MG|PH|PL|SB|SN|TH|VN)(?=\d|\b)", lambda m: cmap[m.group(1)], line)
    new = re.sub(r"(?<!\d)(\d{2})(?!\d)(?! kV)", lambda m: num[m.group(1)], new)
    assert new != line
    maps[line] = new
out = []
for r in pick:
    line = re.search(r"\nNODE: (.*)\n", r["prompt"]).group(1)
    a = dict(r); a["variant"] = "orig"; out.append(a)
    b = dict(r); b["variant"] = "ren"; b["id"] = r["id"] + "::ren"
    b["prompt"] = r["prompt"].replace(f"\nNODE: {line}\n", f"\nNODE: {maps[line]}\n", 1)
    old_id = line.split()[0]
    assert old_id not in b["prompt"] and b["prompt"].count("\n") == r["prompt"].count("\n")
    out.append(b)
for r in random.Random(11).sample(pick, 150):
    c = dict(r); c["variant"] = "rep"; c["id"] = r["id"] + "::rep"; out.append(c)
with open(OUT / "rows_A.jsonl", "w", encoding="utf-8") as fh:
    for r in out:
        fh.write(json.dumps(r, ensure_ascii=False) + "\n")
(OUT / "rename_map.json").write_text(json.dumps(maps, indent=1))
from collections import Counter
print(len(out), Counter(r["role"] for r in pick)); print(json.dumps(maps, indent=1))
