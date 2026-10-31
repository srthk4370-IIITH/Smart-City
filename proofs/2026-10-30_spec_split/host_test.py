#!/usr/bin/env python3
"""Host (WSL CPU) test of htpd v9 split-spec against the unmodified htpd (v8x5 source).

Each config = one htpd process (CPU, same model for agents and reasoner), a fixed request list:
  a2      agents request (first 2 prompts of bench/agents10.json): agents path unaffected
  qNN     split-3 reason request bench/rreq_split/qNN.json (the first q10 is the warm-up: static prefix prefill)
  sNN     the same request without "split" (single-stream reason request)
Per request: wall, outputs, VmRSS of htpd after it; the htpd log per config.

usage: python3 host_test.py --model GGUF --out DIR --cfg name,binary,ENV=V;ENV=V --reqs "a2 q10 q10 ..." [--threads 6]
"""
import argparse, json, os, re, socket, subprocess, sys, time

B = '/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-27_reasoner_fast/bench'


def call(port, req, timeout=7200):
    s = socket.create_connection(("127.0.0.1", port), timeout=timeout)
    s.sendall((json.dumps(req) + "\n").encode())
    f = s.makefile("rb")
    last = None
    t0 = time.time()
    while True:
        l = f.readline()
        if not l:
            break
        d = json.loads(l)
        if "outputs" in d or "error" in d:
            last = d
            break
    s.close()
    return last, time.time() - t0


def rss_kb(pid):
    try:
        for l in open(f'/proc/{pid}/status'):
            if l.startswith('VmRSS:'):
                return int(l.split()[1])
    except OSError:
        return -1
    return -1


def make_req(r, brace=False):
    if r == 'a2':
        a = json.load(open(B + '/agents10.json'))
        a['prompts'] = a['prompts'][:2]
        for k in list(a):
            if isinstance(a[k], list) and len(a[k]) == 10:
                a[k] = a[k][:2]
        return a
    q = json.load(open(f'{B}/rreq_split/q{r[1:]}.json'))
    if brace:  # a base model (no rsn fine-tune) answers in a ```json fence: start the answer at "{" so the forcer is on
        q["prompt"] = q["prompt"] + "{"
    if r[0] == 's':
        q.pop('split', None); q.pop('split_after', None)
    return q


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--model', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--cfg', action='append', required=True)
    ap.add_argument('--reqs', required=True)
    ap.add_argument('--threads', type=int, default=6)
    ap.add_argument('--port', type=int, default=18391)
    ap.add_argument("--brace", action="store_true")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    for cfg in a.cfg:
        name, binary, envs = (cfg.split(',', 2) + [''])[:3]
        env = {k: v for k, v in os.environ.items() if not k.startswith('HTPD_')}
        env.update({'HTPD_REASON_DISK_CACHE': '0', 'HTPD_REASON_IDLE_MS': '600000', 'HTPD_REASON_TIMEOUT_MS': '0'})
        for kv in [x for x in envs.split(';') if x]:
            k, v = kv.split('=', 1); env[k] = v
        d = os.path.join(a.out, name)
        os.makedirs(d, exist_ok=True)
        log = open(os.path.join(d, 'htpd.log'), 'w')
        cmd = [binary, '-m', a.model, '--device', 'CPU', '-t', str(a.threads), '--agents', '2', '--agent-ctx', '1280',
               '--synth-ctx', '1024', '--port', str(a.port), '--reasoner-model', a.model, '--reason-streams', '3']
        json.dump(dict(cmd=cmd, env={k: v for k, v in env.items() if k.startswith('HTPD_')}), open(os.path.join(d, 'cmd.json'), 'w'), indent=1)
        p = subprocess.Popen(cmd, env=env, stdout=log, stderr=log)
        for _ in range(900):
            if 'htpd: ready in' in open(os.path.join(d, 'htpd.log'), errors='replace').read():
                break
            if p.poll() is not None:
                print(name, 'htpd died at start', flush=True); break
            time.sleep(1)
        res = []
        for k, r in enumerate(a.reqs.split()):
            if p.poll() is not None:
                res.append(dict(req=r, error='htpd dead')); break
            resp, wall = call(a.port, make_req(r, a.brace))
            rec = dict(req=r, k=k, wall_s=round(wall, 2), rss_kb=rss_kb(p.pid), resp=resp)
            res.append(rec)
            o = (resp or {}).get('outputs') or [{}]
            print(f"{name} {r}#{k}: {wall:.1f}s stop={[x.get('stop') for x in o]} tok={[x.get('tokens') for x in o]} rss={rec['rss_kb'] // 1024} MB", flush=True)
            json.dump(res, open(os.path.join(d, 'results.json'), 'w'), indent=1)
        p.terminate()
        try:
            p.wait(60)
        except subprocess.TimeoutExpired:
            p.kill()
        log.close()
        print(name, 'done', flush=True)


if __name__ == '__main__':
    main()
