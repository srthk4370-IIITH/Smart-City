"""board_drive.py: laptop driver for a standalone board htpd (lab_serve.sh, app stopped, ONE NPU client), over adb forward tcp:18091 -> 8091.
Reasoner calls follow the app's runV3Loop (reasoner_v3.go) for profile reasoner_prompt=v4, reasoner_think=adaptive, early mode (maxCalls 1):
  prompt = v4 static prefix + user + <|im_end|>\\n<|im_start|>assistant\\n<think>\\n ; no forced schema / split (Force off when adaptive); max_new 700;
  no </think> in the answer -> one more call with the reasoning closed + '{"title": "'; one tool round at most, then the forced answer.
  Tools answer like Go incidentTools on an EMPTY device store (same retrieval surface as the host runs).
Jobs (resumable JSONL under results/board_drive/):
  setc_adaptive : Set C (sets/C_adaptive/req, ORDER) agents batches + the adaptive reasoner loop per case        -> setc_adaptive.jsonl
  bd            : Set B + D reasoner on the board, user prompts = the host full-arm prompts (runs/full/reasoner_out.jsonl, same agent findings)
                  -> bd.jsonl (board-vs-host fidelity of the reasoner; agents were host, 207/208 parity)
usage: python board_drive.py <job> [<job> ...]     (Windows python; lab_serve.sh must be serving)"""
import json, os, re, socket, subprocess, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
ADB = os.path.join(HERE, "..", "..", "Code", "platform-tools", "adb.exe")
OUTD = os.path.join(HERE, "results", "board_drive"); os.makedirs(OUTD, exist_ok=True)
LAB = os.environ.get("LAB_OUT", "/data/local/tmp/rfast/lab/serve_1126")
PORT = 18091
AOPEN = "<|im_start|>assistant\n<think>\n"
TCLOSE = "\n</think>\n\n"
APFX = '{"title": "'
CALL_RE = re.compile(r"<tool_call>\s*<function=([^>\n]+)>(.*?)</function>\s*</tool_call>", re.S)
PARAM_RE = re.compile(r"<parameter=([^>\n]+)>\n?(.*?)\n?</parameter>", re.S)


def adb(cmd):
    return subprocess.run([ADB, "shell", cmd], capture_output=True, text=True, env=dict(os.environ, MSYS_NO_PATHCONV="1")).stdout.strip()


def tmax():
    try:
        return int(adb("cat /sys/class/thermal/thermal_zone*/temp 2>/dev/null | sort -rn | head -1")) // 1000
    except Exception:
        return 99


def cool(lim=55):
    t = tmax()
    while t > lim:
        if os.path.exists(os.path.join(HERE, "BOARD_ABORT")):
            raise SystemExit("abort file")
        time.sleep(10); t = tmax()
    return t


def call(req, timeout=900):
    s = socket.create_connection(("127.0.0.1", PORT), timeout=timeout)
    t0 = time.time()
    s.sendall((json.dumps(req) + "\n").encode())
    buf = b""; final = None; first_tok = None
    while True:
        c = s.recv(1 << 16)
        if not c:
            break
        buf += c
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            if not line.strip():
                continue
            d = json.loads(line.decode("utf-8", "replace"))
            if d.get("kind") in ("tok", "toks"):
                if first_tok is None:
                    first_tok = time.time() - t0
                continue
            final = d
        if final is not None:
            break
    s.close()
    if final is None:
        raise RuntimeError("no final line (htpd died?)")
    final["_wall_s"] = round(time.time() - t0, 3); final["_first_piece_s"] = round(first_tok, 3) if first_tok else None
    return final


def meta(r):
    o = (r.get("outputs") or [{}])[0]
    return dict(wall_s=r["_wall_s"], first_piece_s=r["_first_piece_s"], tokens=o.get("tokens"), ttft_ms=o.get("ttft_ms"), ms=o.get("ms"), stop=o.get("stop"),
                reason={k: v for k, v in r.items() if k not in ("outputs",) and not k.startswith("_")})


def text_of(r):
    return ((r.get("outputs") or [{}])[0].get("text")) or ""


def tool_exec(name, args):
    if name == "related_context":
        return json.dumps({"related": [], "blocks": [], "note": "every related sensor is already in the prompt"})
    if name in ("get_action_history", "find_incidents"):
        return json.dumps({"items": [], "coverage": {"source": "device", "complete": True}})
    if name == "get_sensor_history":
        return json.dumps({"summary": [], "note": "no stored readings", "coverage": {"source": "device", "complete": False}})
    return json.dumps({"error": "unknown tool"})


def reason_loop(prefix, user, max_new=700, max_calls=1):
    """Go runV3Loop, adaptive, one tool round."""
    p0 = prefix + user + "<|im_end|>\n" + AOPEN
    base = {"kind": "reason", "keep": True, "prefix": prefix, "max_new": max_new, "stream": True}
    calls, steps = [], []
    r = call(dict(base, prompt=p0)); steps.append(meta(r)); txt = text_of(r)
    if "</think>" not in txt:          # reasoning ran out of max_new: close it, force the answer
        p = p0 + txt.strip() + TCLOSE + APFX
        r = call(dict(base, prompt=p)); steps.append(meta(r))
        return dict(final=APFX + text_of(r), think=txt.strip(), forced=True, calls=calls, steps=steps)
    i = txt.find("</think>"); think = txt[:i].strip(); ans = txt[i + len("</think>"):].lstrip()
    cs = CALL_RE.findall(ans)
    if not cs:
        return dict(final=ans, think=think, forced=False, calls=calls, steps=steps)
    cs = cs[:max_calls]
    turn = think + TCLOSE
    res = []
    for k, (nm, body) in enumerate(cs):
        args = {a.strip(): v for a, v in PARAM_RE.findall(body)}
        out = tool_exec(nm.strip(), args); calls.append(dict(name=nm.strip(), args=args, result=out)); res.append(out)
        turn += ("\n" if k else "") + "<tool_call>\n<function=" + nm.strip() + ">\n" + "".join("<parameter=%s>\n%s\n</parameter>\n" % (a, v) for a, v in args.items()) + "</function>\n</tool_call>"
    turn += "<|im_end|>\n<|im_start|>user\n" + "\n".join("<tool_response>\n%s\n</tool_response>" % x for x in res) + "<|im_end|>\n" + AOPEN
    p = p0 + turn + TCLOSE + APFX      # used >= maxCalls: forced answer
    r = call(dict(base, prompt=p)); steps.append(meta(r))
    return dict(final=APFX + text_of(r), think=think, forced=True, calls=calls, steps=steps)


def done_ids(f):
    return {json.loads(l)["id"] for l in open(f, encoding="utf-8")} if os.path.exists(f) else set()


def job_setc():
    D = os.path.join(HERE, "sets", "C_adaptive", "req"); out = os.path.join(OUTD, "setc_adaptive.jsonl"); done = done_ids(out)
    order = open(os.path.join(D, "ORDER")).read().split()
    for c in order:
        if c in done:
            continue
        t0 = cool()
        ag = []
        for f in sorted(x for x in os.listdir(D) if re.fullmatch(re.escape(c) + r"_a\d+\.json", x)):
            r = call(json.load(open(os.path.join(D, f), encoding="utf-8")))
            ag.append(dict(file=f, wall_s=r["_wall_s"], n=len(r.get("outputs") or []), outs=[{k: o.get(k) for k in ("tokens", "ttft_ms", "ms", "stop")} for o in r.get("outputs") or []],
                           reason={k: v for k, v in r.items() if k != "outputs" and not k.startswith("_")}))
        rq = json.load(open(os.path.join(D, c + "_r.json"), encoding="utf-8"))
        pre = rq["prefix"]; user = rq["prompt"][len(pre):-len("<|im_end|>\n" + AOPEN)]
        t1 = time.time(); rl = reason_loop(pre, user); rwall = round(time.time() - t1, 3)
        rec = dict(id=c, t_start=t0, t_end=tmax(), agents=ag, agents_wall_s=round(sum(a["wall_s"] for a in ag), 3), reasoner_wall_s=rwall, reasoner=rl)
        open(out, "a", encoding="utf-8", newline="\n").write(json.dumps(rec) + "\n")
        print(time.strftime("%H:%M:%S"), c, "agents %.1fs reasoner %.1fs calls %d forced %s t %d->%d" % (rec["agents_wall_s"], rwall, len(rl["steps"]), rl["forced"], t0, rec["t_end"]), flush=True)


def job_bd():
    sys.path.insert(0, HERE)
    rq = json.load(open(os.path.join(HERE, "sets", "C_adaptive", "req", "n01_r0_r.json"), encoding="utf-8")); pre = rq["prefix"]
    host = {}
    for l in open(os.path.join(HERE, "runs", "full", "reasoner_out.jsonl"), encoding="utf-8"):
        o = json.loads(l); host[o["id"]] = o
    ids = [i for i in sorted(host) if i[0] in "BD"]
    out = os.path.join(OUTD, "bd.jsonl"); done = done_ids(out)
    for i in ids:
        if i in done:
            continue
        t0 = cool()
        t1 = time.time(); rl = reason_loop(pre, host[i]["user"]); rwall = round(time.time() - t1, 3)
        rec = dict(id=i, t_start=t0, t_end=tmax(), reasoner_wall_s=rwall, reasoner=rl)
        open(out, "a", encoding="utf-8", newline="\n").write(json.dumps(rec) + "\n")
        print(time.strftime("%H:%M:%S"), i, "reasoner %.1fs calls %d forced %s t %d->%d" % (rwall, len(rl["steps"]), rl["forced"], t0, rec["t_end"]), flush=True)


if __name__ == "__main__":
    subprocess.run([ADB, "forward", "tcp:%d" % PORT, "tcp:8091"], check=True)
    try:
        for j in sys.argv[1:]:
            {"setc_adaptive": job_setc, "bd": job_bd}[j]()
    finally:
        adb("touch %s/STOP" % LAB)
        subprocess.run([ADB, "forward", "--remove", "tcp:%d" % PORT])
        print("STOP sent", flush=True)
