#!/usr/bin/env python3
"""Build the htpd v9 split-spec draft corpus (HTPD_REASON_CORPUS) from past incident reports.

Input: incidents.jsonl-style files (one JSON object per line with "id" and "final": {"raw" or "content"}: the board's
board_incidents*.jsonl, the rag_seed gen_rsn_v1.jsonl, eval rwh.jsonl). Only v3 reports ('{"title"...') are used.
Each report is tokenized as htpd emits it (the reasoner tokenizer + the Forcer replay of recon.py: model picks + forced
tokens, full schema of --schema-req); a report that does not replay cleanly is tokenized by plain BPE.
Output: one JSON array of token ids per line (deduplicated), plus <out>.manifest.json.

usage (WSL, ~/venvs/rsn): python3 build_corpus.py --schema-req q10.json --out corpus.jsonl
          [--exclude rwh-00098,rwh-00147 | --exclude-reqs q10.json,q11.json] [--tokenizer tokenizer.json] inputs...
Excluded ids are compared after the last ':' (request id "rwh:rwh-00098" = incident "rwh-00098").
"""
import argparse, hashlib, json, os, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from recon import Tok, replay, TOK_PATH  # noqa: E402


def norm_id(x):
    return str(x).split(':')[-1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--schema-req', required=True, help='a reason request JSON whose "schema" the reports follow')
    ap.add_argument('--out', required=True)
    ap.add_argument('--exclude', default='', help='comma-separated incident ids')
    ap.add_argument('--exclude-reqs', default='', help='comma-separated request JSON files: their ids are excluded')
    ap.add_argument('--tokenizer', default=TOK_PATH)
    ap.add_argument('inputs', nargs='+')
    a = ap.parse_args()
    t0 = time.time()
    excl = {norm_id(x) for x in a.exclude.split(',') if x.strip()}
    for f in [x for x in a.exclude_reqs.split(',') if x.strip()]:
        excl.add(norm_id(json.load(open(f))['id']))
    S = json.load(open(a.schema_req))['schema']
    tok = Tok(a.tokenizer)
    seen, docs, stats = set(), [], {}
    for fn in a.inputs:
        st = stats.setdefault(os.path.basename(fn), dict(lines=0, reports=0, excluded=0, dup=0, replay_ok=0, bpe=0))
        for line in open(fn, encoding='utf-8'):
            line = line.strip()
            if not line:
                continue
            st['lines'] += 1
            r = json.loads(line)
            fin = r.get('final') or {}
            text = fin.get('raw') or fin.get('content') or ''
            if not text.startswith('{"title"'):
                continue
            st['reports'] += 1
            if norm_id(r.get('id', '')) in excl:
                st['excluded'] += 1
                continue
            if text in seen:
                st['dup'] += 1
                continue
            seen.add(text)
            rp = replay(tok, S, text.encode('utf-8'))
            if rp['mism'] == 0 and rp['stop'] == 'json':
                ids = rp['toks']; st['replay_ok'] += 1
            else:
                ids = tok.enc(text.encode('utf-8')); st['bpe'] += 1
            docs.append(ids)
    with open(a.out, 'w') as f:
        for d in docs:
            f.write(json.dumps(d, separators=(',', ':')) + '\n')
    md5 = hashlib.md5(open(a.out, 'rb').read()).hexdigest()
    man = dict(out=os.path.abspath(a.out), md5=md5, docs=len(docs), tokens=sum(len(d) for d in docs), excluded_ids=sorted(excl),
               inputs=[os.path.abspath(x) for x in a.inputs], per_input=stats, schema_req=os.path.abspath(a.schema_req),
               tokenizer=a.tokenizer, seconds=round(time.time() - t0, 1))
    json.dump(man, open(a.out + '.manifest.json', 'w'), indent=1)
    print(json.dumps(dict(docs=len(docs), tokens=man['tokens'], md5=md5, per_input=stats)))


if __name__ == '__main__':
    main()
