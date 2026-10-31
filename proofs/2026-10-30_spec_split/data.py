# data.py: evaluated board reports (with their htpd log stream counts) and the corpus of past reports.
import json, glob, os, re

P = '/mnt/c/Users/hp/Desktop/qidk/proofs'
REQ = P + '/2026-10-27_reasoner_fast/bench/rreq_split/q%d.json'


def load_req(q):
    r = json.load(open(REQ % q))
    p = r['prompt'] if isinstance(r['prompt'], str) else r['prompt'][0]
    return dict(prompt=p, schema=r['schema'], id=r['id'].split(':')[-1], split=r.get('split'))


def parse_log(path):
    """per reason request: split tokens, per-stream tokens/forced, steps, mean rows"""
    out, cur = [], None
    for l in open(path, errors='replace'):
        m = re.search(r'split at (\d+) tokens into (\d+) streams', l)
        if m: cur = dict(split=int(m.group(1)), streams={}); continue
        if cur is None: continue
        m = re.search(r'reason step profile: (\d+) steps, rows ([\d.]+)/step', l)
        if m: cur['steps'] = int(m.group(1)); cur['rows'] = float(m.group(2)); continue
        m = re.search(r'reason stream (\d+): (\d+) tokens \((\d+) forced', l)
        if m: cur['streams'][int(m.group(1))] = (int(m.group(2)), int(m.group(3))); continue
        m = re.search(r'reason (\d+) streams, (\d+) decode steps', l)
        if m: cur['steps2'] = int(m.group(2)); out.append(cur); cur = None
    return out


def eval_reports():
    """list of dict(file, q, run, text, log)"""
    res = []
    L = P + '/2026-10-29_latency'
    for cfg, d, logf in [('base', 'rp29_ab', 'htpd_base.log'), ('rb29', 'rp29_ab', 'htpd_rb29.log'),
                         ('rp29', 'rp29_ab', 'htpd_rp29.log'), ('base0', 'rp29_ab', None), ('4b', 'q2b_ab', 'htpd_4b.log')]:
        files = glob.glob(f'{L}/{d}/{cfg}_q1*.json')
        files.sort(key=lambda f: int(re.search(r'_(\d+)\.json$', f).group(1)))
        logs = parse_log(f'{L}/{d}/{logf}') if logf else []
        logs = logs[-len(files):] if logs else []
        for i, f in enumerate(files):
            j = json.load(open(f))
            q = int(re.search(r'_q(\d+)_', f).group(1))
            res.append(dict(file=os.path.relpath(f, P), cfg=cfg, q=q, text=j['outputs'][0]['text'],
                            tokens=j['outputs'][0].get('tokens'), forced=j['outputs'][0].get('forced'),
                            log=logs[i] if i < len(logs) and len(logs) == len(files) else None))
    return res


def corpus():
    """list of dict(src, inc, text): reports produced by the reasoner model (Qwen3.5-4B rsn_v1)"""
    docs = []
    # 1) rsn_v1 laptop-CUDA generations on train-split incidents (retrieval seed run, same GGUF as the board)
    for l in open(P + '/2026-10-28_master/rag_seed/gen_rsn_v1.jsonl'):
        r = json.loads(l)
        t = ((r.get('final') or {}).get('content') or '')
        if t.startswith('{"title"'): docs.append(dict(src='gen_rsn_v1', inc=r['id'], text=t))
    # 2) v1_106: rsn_v1 Q4_0 host eval on the 106 RWH incidents (same incident ids as the evaluated requests)
    for l in open(P + '/2026-10-25_reasoner_final/eval/results/v1_106/rwh.jsonl'):
        r = json.loads(l)
        t = ((r.get('final') or {}).get('content') or '')
        if t.startswith('{"title"'): docs.append(dict(src='v1_106_rwh', inc=r['id'], text=t))
    # 3) live board incidents whose final reasoner raw output is a v3 report (qwen3.5-4b htpd)
    seen = set()
    for fn in ['board_incidents_b50.jsonl', 'board_incidents.jsonl']:
        for l in open(P + '/2026-10-27_reasoner_fast/raw/' + fn):
            r = json.loads(l)
            t = ((r.get('final') or {}).get('raw') or '')
            if t.startswith('{"title"') and t not in seen:
                seen.add(t); docs.append(dict(src='board_live', inc=r['id'], text=t))
    # 4) board A/B outputs (same model) of the bench requests; tagged by request incident id
    for f in sorted(glob.glob(P + '/2026-10-29_latency/*_ab/*_q*.json')):
        b = os.path.basename(f)
        if b.startswith('2b_'): continue  # Qwen3.5-2B: a different model
        q = int(re.search(r'_q(\d+)_', b).group(1))
        t = json.load(open(f))['outputs'][0]['text']
        if t.startswith('{"title"'):
            docs.append(dict(src='board_ab', inc=load_req(q)['id'] if os.path.exists(REQ % q) else 'q%d' % q, text=t, file=b))
    return docs
