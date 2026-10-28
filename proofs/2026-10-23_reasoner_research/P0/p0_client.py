#!/usr/bin/env python3
"""P0 device client: send named requests from device_inputs/requests.jsonl to htpd (adb-forwarded 127.0.0.1:8091),
one at a time, and append {"tag","name","resp","wall_s","progress_lines"} lines to OUT.

usage (Windows): py -3 p0_client.py --tag v7_r1 --names agents0,agents1,synth0 --out results/device.jsonl [--port 8091]
"""
import argparse, json, os, socket, time

HERE = os.path.dirname(os.path.abspath(__file__))


def call(port, req, timeout):
    s = socket.create_connection(("127.0.0.1", port), timeout=timeout)
    s.sendall((json.dumps(req) + "\n").encode())
    f = s.makefile("rb")
    t0 = time.time()
    n_prog, first_prog = 0, None
    while True:
        line = f.readline()
        if not line:
            raise RuntimeError("connection closed (htpd died?)")
        d = json.loads(line)
        if d.get("kind") == "toks":
            n_prog += 1
            first_prog = first_prog or time.time() - t0
            continue
        s.close()
        return d, time.time() - t0, n_prog, first_prog


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True)
    ap.add_argument("--names", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--port", type=int, default=8091)
    ap.add_argument("--timeout", type=float, default=180)
    ap.add_argument("--inputs", default=os.path.join(HERE, "device_inputs", "requests.jsonl"))
    a = ap.parse_args()
    reqs = {}
    for l in open(a.inputs, encoding="utf-8"):
        r = json.loads(l)
        reqs[r["name"]] = r["req"]
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    rc = 0
    with open(a.out, "a", encoding="utf-8") as fo:
        for n in a.names.split(","):
            try:
                d, wall, n_prog, first_prog = call(a.port, reqs[n], a.timeout)
            except Exception as e:  # a dead daemon ends the phase; the shell script stops everything
                print(f"{a.tag} {n} FAILED: {e}", flush=True)
                fo.write(json.dumps({"tag": a.tag, "name": n, "error": str(e)}) + "\n")
                rc = 2
                break
            fo.write(json.dumps({"tag": a.tag, "name": n, "resp": d, "wall_s": wall, "progress_lines": n_prog,
                                 "first_progress_s": first_prog}) + "\n")
            fo.flush()
            outs = d.get("outputs", [])
            print(f"{a.tag} {n} {wall:.1f}s prefill {d.get('prefill_ms')} ms lora {d.get('lora_scale')} "
                  f"{[(o.get('stop'), o.get('tokens')) for o in outs][:12]}", flush=True)
    raise SystemExit(rc)


if __name__ == "__main__":
    main()
