#!/usr/bin/env python3
"""Host (WSL CPU) test of htpd v9h: pool + chained static prefix (M2), against v9f.

The r3 chat prefix exactly as chat.go chatStaticPrefixMode builds it (r3 header + time/fog line + r3 system + user
turn), on the rsn_v3 2B r2 GGUF (same qwen35 hybrid architecture and tokenizer as the 4B r3; the 4B does not fit the
WSL RAM next to the other jobs). Every config = one htpd process (CPU, same GGUF for agents and reasoner) with
its own disk-cache dir (the GGUF is symlinked there, so the .prefix_*.state files never touch models_stage).

  usage: host_test_v9h.py --bin-f ~/v9host/htpd_v9f --bin-h ~/v9host/htpd_v9h --model <gguf> --work ~/v9h_test --out <dir>

Tests:
  E  equivalence: 4 hourly chat questions (10:00, 11:00, 12:00 and 20:00, two different questions), greedy, 48 tokens.
     All at --reason-ctx 8192 (the r3 prefix alone is ~5k tokens: v9f at 4096 stops "ctx" at once).
     f = v9f (pool 3x8192+256, reference), h0 = v9h without the new env (must equal v9f bit for bit),
     hp = v9h HTPD_REASON_POOL=12544 (first 2), hc = v9h POOL + HTPD_REASON_CHAIN=1.
     Compared per request: text, picked tokens, and the per-pick logits (top-1/2 values + an FNV hash of all logits,
     HTPD_REASON_TRACE).
  R  restart: a new hc process on hc's disk dir, hour 13: the base must come from disk ("chain-disk").
  C  context: one ~7.2k-token prompt (prefix + a long history), 32 new tokens.
     f4  = v9f --reason-ctx 4096 (live): expect stop "ctx" at once (per-stream cap 4096).
     h8  = v9h --reason-ctx 8192 + HTPD_REASON_POOL=12544 (same KV cells as live): expect a normal answer.
     hx  = v9h --reason-ctx 8192 + HTPD_REASON_POOL=6144 (pool smaller than the prompt): expect stop "ctx",
           not "error" (pool-exhausted guard).
"""
import argparse, json, os, socket, subprocess, time, glob, shutil

B = '/mnt/c/Users/hp/Desktop/qidk/Code/smart-city-edge-agent/app/backend/'
HEADER = open(B + 'chat_header_r3.txt', encoding='utf-8').read()
SYSTEM = open(B + 'chat_system_r3.txt', encoding='utf-8').read()
DAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']


def prefix(day, hour):
    import datetime
    t = datetime.datetime(2026, 11, day, hour, 0)
    first = ("You are the operator assistant of a smart-campus edge monitor (IIIT Hyderabad) on a Qualcomm QIDK. "
             "Device time: %s IST (%s). %s Full incident records on the device since %s.\n" % (
                 t.strftime('%Y-%m-%d %H:%M'), DAYS[t.weekday()],
                 'The device is offline: the fog server is unreachable (never synced).', '2026-06-24'))
    return HEADER + first + SYSTEM + '<|im_end|>\n<|im_start|>user\n'


def prompt(pfx, q, history=''):
    return pfx + history + q + '<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n'


Q1 = 'How many incidents were there in the library block today, and which sensor raised the most?'
Q2 = 'Is the water tank level near the hostel normal right now?'


def ask(port, req, timeout=1800):
    s = socket.create_connection(('127.0.0.1', port), timeout=timeout)
    s.sendall((json.dumps(req) + '\n').encode())
    buf = b''
    while True:
        c = s.recv(1 << 16)
        if not c:
            break
        buf += c
        if buf.endswith(b'\n'):
            break
    s.close()
    lines = [json.loads(x) for x in buf.decode().split('\n') if x.strip()]
    return lines[-1] if lines else {'error': 'connection closed without a reply (htpd died?)'}


def run(a, name, binary, env_extra, ctx, reqs, fresh=True):
    d = os.path.join(a.work, name)
    if fresh and os.path.isdir(d):
        shutil.rmtree(d)
    os.makedirs(d, exist_ok=True)
    m = os.path.join(d, 'model.gguf')
    if not os.path.exists(m):
        os.symlink(a.model, m)
    tr = os.path.join(d, 'trace')
    os.makedirs(tr, exist_ok=True)
    for f in glob.glob(tr + '/*'):
        os.remove(f)
    env = {k: v for k, v in os.environ.items() if not k.startswith('HTPD_')}
    env.update({'HTPD_REASON_IDLE_MS': '600000', 'HTPD_REASON_TIMEOUT_MS': '0', 'HTPD_REASON_SPLIT_SPEC': '8',
                'HTPD_REASON_TRACE': tr})
    env.update(env_extra)
    logp = os.path.join(d, 'htpd.log' if fresh else 'htpd_restart.log')
    log = open(logp, 'w')
    cmd = ['nice', '-n', '15', binary, '-m', m, '--device', 'CPU', '-t', str(a.threads), '--agents', '2', '--agent-ctx', '1280',
           '--synth-ctx', '1024', '--port', str(a.port), '--reasoner-model', m, '--reason-streams', '3', '--reason-ctx', str(ctx)]
    p = subprocess.Popen(cmd, env=env, stdout=log, stderr=log)
    res = []
    try:
        for _ in range(900):
            if 'htpd: ready in' in open(logp, errors='replace').read():
                break
            if p.poll() is not None:
                return [dict(error='htpd died at start')]
            time.sleep(1)
        for tag, req in reqs:
            t = time.time()
            r = ask(a.port, dict(kind='reason', keep=True, **req))
            o = (r.get('outputs') or [{}])[0]
            rs = r.get('reason', {})
            res.append(dict(cfg=name, req=tag, wall_s=round(time.time() - t, 2), text=o.get('text'), tokens=o.get('tokens'),
                            stop=o.get('stop'), prefill_ms=r.get('prefill_ms'), cache=rs.get('cache'),
                            cached_tokens=rs.get('cached_tokens'), cache_ms=rs.get('cache_ms'), error=r.get('error')))
            print(json.dumps(res[-1])[:300], flush=True)
    finally:
        p.terminate()
        p.wait()
    # per-request traces (trace_000.txt ... in request order)
    for i, r in enumerate(res):
        f = os.path.join(tr, 'trace_%03d.txt' % i)
        r['trace'] = [l.split() for l in open(f)] if os.path.exists(f) else []
    return res


def cmp_trace(x, y):
    a, b = x['trace'], y['trace']
    n = min(len(a), len(b))
    picks = all(a[i][1] == b[i][1] for i in range(n)) and len(a) == len(b)
    hashes = sum(a[i][6] == b[i][6] for i in range(n))
    d1 = max([abs(float(a[i][3]) - float(b[i][3])) for i in range(n)] or [0])
    return dict(steps=n, same_picks=picks, same_text=x['text'] == y['text'], bitexact_logit_steps=hashes, max_top1_logit_diff=round(d1, 6))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--bin-f', required=True); ap.add_argument('--bin-h', required=True)
    ap.add_argument('--model', required=True); ap.add_argument('--work', required=True); ap.add_argument('--out', required=True)
    ap.add_argument('--threads', type=int, default=6); ap.add_argument('--port', type=int, default=8197)
    ap.add_argument('--only', default='ERC')
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    out = {}
    E = [('h10_q1', dict(prompt=prompt(prefix(15, 10), Q1), prefix=prefix(15, 10), max_new=48)),
         ('h11_q2', dict(prompt=prompt(prefix(15, 11), Q2), prefix=prefix(15, 11), max_new=48)),
         ('h12_q1', dict(prompt=prompt(prefix(15, 12), Q1), prefix=prefix(15, 12), max_new=48)),
         ('h20_q2', dict(prompt=prompt(prefix(15, 20), Q2), prefix=prefix(15, 20), max_new=48))]
    POOL = {'HTPD_REASON_POOL': '12544'}
    CH = dict(POOL, HTPD_REASON_CHAIN='1')
    if 'E' in a.only:
        f = run(a, 'f', a.bin_f, {}, 8192, E)
        h0 = run(a, 'h0', a.bin_h, {}, 8192, E)
        hp = run(a, 'hp', a.bin_h, POOL, 8192, E[:2])
        hc = run(a, 'hc', a.bin_h, CH, 8192, E)
        out['E'] = dict(f=f, h0=h0, hp=hp, hc=hc, hp_vs_f=[cmp_trace(x, y) for x, y in zip(hp, f)], hc_vs_hp=[cmp_trace(x, y) for x, y in zip(hc, hp)],
                        h0_vs_f=[cmp_trace(x, y) for x, y in zip(h0, f)],
                        hc_vs_f=[cmp_trace(x, y) for x, y in zip(hc, f)])
    if 'R' in a.only:
        R = [('h13_q1', dict(prompt=prompt(prefix(15, 13), Q1), prefix=prefix(15, 13), max_new=48))]
        fr = run(a, 'f13', a.bin_f, {}, 8192, R)
        hr = run(a, 'hc', a.bin_h, CH, 8192, R, fresh=False)
        out['R'] = dict(f=fr, hc_restart=hr, hc_vs_f=[cmp_trace(x, y) for x, y in zip(hr, fr)])
    if 'C' in a.only:
        hist = ''
        k = 0
        while len(hist) < 9000:  # ~2.1k tokens of earlier exchanges
            k += 1
            hist += ('Which sensors in block %d reported anomalies this week?<|im_end|>\n<|im_start|>assistant\n'
                     'Block %d had 3 incidents: humidity drift on sensor H-%d (2 alerts), a stuck CO2 reading on C-%d and one '
                     'temperature spike on T-%d at 14:20 that cleared within ten minutes. All were reviewed.<|im_end|>\n'
                     '<|im_start|>user\n') % (k, k, k * 3, k * 5, k * 7)
        C = [('long', dict(prompt=prompt(prefix(15, 10), Q1, hist), prefix=prefix(15, 10), max_new=32))]
        out['C'] = dict(f4=run(a, 'f4', a.bin_f, {}, 4096, C),
                        h8=run(a, 'h8', a.bin_h, POOL, 8192, C),
                        hx=run(a, 'hx', a.bin_h, {'HTPD_REASON_POOL': '6144'}, 8192, C))
    for v in out.values():
        for k2, rr in v.items():
            if isinstance(rr, list):
                for r in rr:
                    if isinstance(r, dict) and 'trace' in r:
                        r['trace_steps'] = len(r.pop('trace'))
    json.dump(out, open(os.path.join(a.out, 'host_results_%s.json' % a.only), 'w'), indent=1)
    print('DONE')


if __name__ == '__main__':
    main()
