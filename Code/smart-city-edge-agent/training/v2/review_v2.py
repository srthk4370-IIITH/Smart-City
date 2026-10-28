"""Local, private review page for the v2 dataset (spec decision #22). Never published or uploaded.

  py -3 review_v2.py [--data data/sft_v2] [--n 60]   -> data/sft_v2/review.html (gitignored)

60 random TRAIN examples, stratified round-robin over (role, pattern). Each card: inline SVG chart of the 12 h
history with the window shaded and the label's onset marked, the prompt's user text (evidence), the target JSON,
an ok / wrong toggle and a note box (saved in this browser's localStorage), and an export-to-JSON button.
Single file, no external resources, no network requests.
"""
from __future__ import annotations

import argparse
import html
import json
import random
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import features_v2 as V  # noqa: E402
import generate_v2 as GV  # noqa: E402


def pick(rows, n, seed):
    rng = random.Random(seed)
    groups = defaultdict(list)
    for r in rows:
        groups[(r["role"], r["pattern"])].append(r)
    keys = sorted(groups)
    rng.shuffle(keys)
    for k in keys:
        rng.shuffle(groups[k])
    out, i = [], 0
    while len(out) < n and any(groups.values()):
        k = keys[i % len(keys)]
        if groups[k]:
            out.append(groups[k].pop())
        i += 1
    return out


def svg(r, tgt, w=560, h=150):
    ys = r["hist"]
    H, n = len(ys), r["n"]
    lo, hi = min(ys), max(ys)
    if hi - lo < 1e-9:
        hi, lo = hi + 1, lo - 1
    pad = 28
    X = lambda i: pad + (w - pad - 6) * i / max(1, H - 1)
    Y = lambda v: 8 + (h - 30) * (1 - (v - lo) / (hi - lo))
    pts = " ".join(f"{X(i):.1f},{Y(v):.1f}" for i, v in enumerate(ys))
    x0 = X(H - n)
    parts = [f'<svg viewBox="0 0 {w} {h}" width="100%" role="img" aria-label="series">',
             f'<rect x="{x0:.1f}" y="4" width="{w - 6 - x0:.1f}" height="{h - 22}" class="win"/>',
             f'<polyline points="{pts}" class="line"/>']
    if r.get("setpoint"):
        sp = r["setpoint"]
        off = H - len(sp)
        parts.append('<polyline class="sp" points="' + " ".join(f"{X(off + i):.1f},{Y(v):.1f}" for i, v in enumerate(sp)) + '"/>')
    if r.get("ac_on"):
        on = r["ac_on"]
        off = H - len(on)
        for i, v in enumerate(on):
            if v:
                parts.append(f'<rect x="{X(off + i):.1f}" y="{h - 18}" width="{(w - pad) / H:.1f}" height="4" class="on"/>')
    # onset marker: label HH:MM mapped onto the history time axis
    times = [V.idx_time(r["end_epoch"], H, i) for i in range(H)]
    if tgt.get("onset") in times:
        xo = X(times.index(tgt["onset"]))
        parts.append(f'<line x1="{xo:.1f}" x2="{xo:.1f}" y1="4" y2="{h - 18}" class="onset"/>')
        parts.append(f'<text x="{xo + 3:.1f}" y="16" class="lab">onset {tgt["onset"]}</text>')
    parts.append(f'<text x="2" y="{Y(hi) + 4:.1f}" class="lab">{hi:.4g}</text><text x="2" y="{Y(lo):.1f}" class="lab">{lo:.4g}</text>')
    parts.append(f'<text x="{pad}" y="{h - 4}" class="lab">{times[0]}</text>'
                 f'<text x="{x0:.1f}" y="{h - 4}" class="lab">window {times[H - n]}</text>'
                 f'<text x="{w - 40}" y="{h - 4}" class="lab">{times[-1]}</text></svg>')
    return "".join(parts)


CSS = """
:root{--bg:#f7f7f5;--card:#fff;--fg:#1d1d1f;--mut:#6b6b70;--line:#2f6fd6;--win:#e9f0fb;--bad:#c0392b;--ok:#1e8449;--bd:#ddd}
@media (prefers-color-scheme:dark){:root{--bg:#141416;--card:#1e1e22;--fg:#ececf0;--mut:#9a9aa3;--line:#7fb0ff;--win:#22324a;--bd:#333}}
body{background:var(--bg);color:var(--fg);font:14px/1.45 system-ui,Segoe UI,sans-serif;margin:0;padding:16px}
h1{font-size:20px;margin:0 0 4px} .mut{color:var(--mut)} .bar{display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin:8px 0 16px}
.card{background:var(--card);border:1px solid var(--bd);border-radius:10px;padding:12px 14px;margin:0 0 14px;max-width:1100px}
.card.wrong{border-color:var(--bad);box-shadow:0 0 0 2px var(--bad) inset}.card.ok{border-color:var(--ok)}
.grid{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:12px}@media(max-width:800px){.grid{grid-template-columns:1fr}}
pre{white-space:pre-wrap;word-break:break-word;font:12px/1.4 ui-monospace,Consolas,monospace;background:var(--bg);padding:8px;border-radius:6px;margin:0;max-height:360px;overflow:auto}
.line{fill:none;stroke:var(--line);stroke-width:1.4}.sp{fill:none;stroke:#e67e22;stroke-width:1;stroke-dasharray:4 3}
.win{fill:var(--win)}.onset{stroke:var(--bad);stroke-width:1.2;stroke-dasharray:3 2}.on{fill:#27ae60;opacity:.6}.lab{font-size:10px;fill:var(--mut)}
button{font:inherit;padding:4px 10px;border-radius:6px;border:1px solid var(--bd);background:var(--card);color:var(--fg);cursor:pointer}
button.sel-ok{background:var(--ok);color:#fff}button.sel-wrong{background:var(--bad);color:#fff}
textarea{width:100%;box-sizing:border-box;font:inherit;background:var(--bg);color:var(--fg);border:1px solid var(--bd);border-radius:6px;min-height:38px}
.tag{display:inline-block;padding:1px 7px;border-radius:9px;background:var(--win);margin-right:4px;font-size:12px}
"""

JS = """
const KEY='sft_v2_review_'+document.body.dataset.hash;
function load(){try{return JSON.parse(localStorage.getItem(KEY)||'{}')}catch(e){return {}}}
function save(s){try{localStorage.setItem(KEY,JSON.stringify(s))}catch(e){}}
let S=load();
function paint(){let ok=0,bad=0;document.querySelectorAll('.card').forEach(c=>{const v=(S[c.id]||{}).verdict;c.classList.toggle('ok',v==='ok');c.classList.toggle('wrong',v==='wrong');
 c.querySelector('.b-ok').classList.toggle('sel-ok',v==='ok');c.querySelector('.b-wrong').classList.toggle('sel-wrong',v==='wrong');
 const t=c.querySelector('textarea');if(document.activeElement!==t)t.value=(S[c.id]||{}).note||'';if(v==='ok')ok++;if(v==='wrong')bad++;});
 document.getElementById('cnt').textContent=ok+' ok, '+bad+' wrong, '+(document.querySelectorAll('.card').length-ok-bad)+' open';}
document.querySelectorAll('.card').forEach(c=>{
 c.querySelector('.b-ok').onclick=()=>{S[c.id]=Object.assign(S[c.id]||{},{verdict:'ok'});save(S);paint()};
 c.querySelector('.b-wrong').onclick=()=>{S[c.id]=Object.assign(S[c.id]||{},{verdict:'wrong'});save(S);paint()};
 c.querySelector('textarea').oninput=e=>{S[c.id]=Object.assign(S[c.id]||{},{note:e.target.value});save(S)};});
document.getElementById('exp').onclick=()=>{const out=[...document.querySelectorAll('.card')].map(c=>({id:c.id,verdict:(S[c.id]||{}).verdict||null,note:(S[c.id]||{}).note||'',meta:JSON.parse(c.dataset.meta)}));
 const a=document.createElement('a');a.href='data:application/json;charset=utf-8,'+encodeURIComponent(JSON.stringify(out,null,1));a.download='sft_v2_review.json';a.click();};
document.getElementById('clr').onclick=()=>{if(confirm('Clear all verdicts and notes?')){S={};save(S);paint();}};
paint();
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(GV.DATA / "sft_v2"))
    ap.add_argument("--n", type=int, default=60)
    ap.add_argument("--seed", type=int, default=60)
    a = ap.parse_args()
    d = Path(a.data)
    rows = [json.loads(l) for l in open(d / "train.jsonl", encoding="utf-8")]
    man = json.loads((d / "manifest.json").read_text())
    sel = pick(rows, a.n, a.seed)
    cards = []
    for r in sel:
        tgt = json.loads(r["completion"][: -len("<|eot_id|>")])
        meta = {k: r.get(k) for k in ("id", "role", "node", "metric", "family", "sub", "n", "d", "size", "pattern", "status", "seen")}
        tags = "".join(f'<span class="tag">{html.escape(str(x))}</span>' for x in
                       (r["role"], r["family"], r.get("sub"), f"N={r['n']} ({V.hours_str(r['n'])} h)",
                        f"age {r['d']} readings" if r.get("d") is not None else "age n/a",
                        f"size {r['size']}x" if r.get("size") else "", f"{r['metric']}"))
        cards.append(
            f'<div class="card" id="{html.escape(r["id"])}" data-meta="{html.escape(json.dumps(meta))}">'
            f'<div class="bar"><b>{html.escape(r["id"])}</b> {tags}<span class="mut">{html.escape(r["node"])}</span>'
            f'<button class="b-ok">ok</button><button class="b-wrong">wrong</button></div>'
            f'{svg(r, tgt)}<div class="grid"><div><div class="mut">prompt (user turn)</div><pre>{html.escape(V.user_text(r["prompt"]))}</pre></div>'
            f'<div><div class="mut">target</div><pre>{html.escape(json.dumps(tgt, indent=1, ensure_ascii=False))}</pre>'
            f'<div class="mut" style="margin-top:8px">note</div><textarea placeholder="what is wrong?"></textarea></div></div></div>')
    page = (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>SFT v2 review</title><style>{CSS}</style></head>'
            f'<body data-hash="{man["splits"]["train"]["sha256_16"]}"><h1>SFT v2 spot-check</h1>'
            f'<div class="mut">Local and private. {len(sel)} random train examples (of {len(rows)}), stratified by role and pattern; '
            f'train sha256/16 {man["splits"]["train"]["sha256_16"]}. Chart: 12 h history, window shaded, dashed red = label onset'
            f'{", orange = setpoint, green = AC on" if any(r["role"] == "hvac" for r in sel) else ""}. Verdicts stay in this browser.</div>'
            f'<div class="bar"><span id="cnt"></span><button id="exp">export JSON</button><button id="clr">clear</button></div>'
            + "".join(cards) + f"<script>{JS}</script></body></html>")
    out = d / "review.html"
    out.write_text(page, encoding="utf-8")
    print(f"{out} ({len(sel)} cards, {len(page) / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
