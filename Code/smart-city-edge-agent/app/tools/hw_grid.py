"""Hardware placement grid: where should the agents and the synthesizer run - NPU, GPU, or a hybrid?

Replays REAL incidents recorded by the app (their exact agent and synthesizer prompts) through
different placements and measures incident wall time, per-call latency, agreement with the NPU's own
answers, temperature and RAM. Same model everywhere: the NPU runs the fine-tuned w4a16 bundle via
genied; the GPU runs the SAME integer weights packed exactly into Q4_0/Q8_0 (training/export/gpu/).

Engines (reached through adb forwards):
  npu  genied on 127.0.0.1:8777 (one dialog: one call at a time)
  gpu  llama-server (OpenCL, Adreno 750) on 127.0.0.1:8080, -np slots = parallel sequences
  cpu  llama-server with -ngl 0 on 127.0.0.1:8081 (reference only)

Placements (see PLACEMENTS): all-NPU, all-GPU sequential/parallel, agents on GPU + synth on NPU,
agents on NPU + synth on GPU, agents split across NPU and GPU workers, CPU reference.

Every call stops exactly where the app stops: when the JSON object closes, or (agent calls) where the
top-level "action" key starts - policy derives action (app/backend/answerscan.go, trimscan.go).

  python hw_grid.py --placements all --incidents INC-0401,INC-0402,... --reps 3
"""
import argparse
import json
import queue
import re
import socket
import struct
import subprocess
import threading
import time
import urllib.request
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
ADB = str(HERE.parents[2] / "platform-tools" / "adb.exe")
APP = "http://127.0.0.1:8000"
AGENT_PREFILL = '{"pattern": "'

# ------------------------------------------------------------------ stop rule (mirror of the app's)


class Scanner:
    """Brace depth outside strings; stop when the object closes, or (agents) at the top-level
    "action" key. Fed with prefill first, exactly like answerScanner."""

    def __init__(self, prefill, trim_action):
        self.depth = 0
        self.in_str = self.esc = False
        self.key = None
        self.after_colon = False
        self.trim = trim_action
        self.text = ""
        self.done = False
        self.feed(prefill, count=False)

    def feed(self, s, count=True):
        for c in s:
            if count:
                self.text += c
            if self.in_str:
                if self.esc:
                    self.esc = False
                elif c == "\\":
                    self.esc = True
                elif c == '"':
                    self.in_str = False
                    if self.key is not None:
                        if self.trim and self.depth == 1 and self.key == "action":
                            # cut at the comma before "action": drop ', "action"' and close
                            self.text = re.sub(r',\s*"action"\s*$', "", self.text) + "}"
                            self.done = True
                            return True
                        self.key = None
                elif self.key is not None:
                    self.key += c
                continue
            if c == '"':
                self.in_str = True
                if self.depth == 1 and not self.after_colon:
                    self.key = ""
            elif c in "{[":
                self.depth += 1
                self.after_colon = False
            elif c in "}]":
                self.depth -= 1
                if self.depth == 0:
                    self.done = True
                    return True
            elif c == ":":
                self.after_colon = True
            elif c == ",":
                self.after_colon = False
        return False


def prefill_of(prompt):
    i = prompt.rfind("<|end_header_id|>\n\n")
    return prompt[i + len("<|end_header_id|>\n\n"):] if i >= 0 else ""


def est_tokens(s):
    return len(s) * 100 // 310 + 1


def needs_large(prompt):  # genieclient.go needsLargeWindow
    return est_tokens(prompt) * 108 // 100 + 320 + 40 > 2048


# ------------------------------------------------------------------ engines

class NPU:
    """genied protocol: -> u32 len (bit 31 = large window) + prompt; <- frames u8 kind, u32 len."""
    name = "npu"

    def __init__(self, port=8777):
        self.port = port
        self.lock = threading.Lock()  # one dialog: calls are serialised, as in the app

    def call(self, prompt, is_agent):
        body = prompt.removeprefix("<|begin_of_text|>").encode()
        n = len(body) | (1 << 31 if needs_large(prompt) else 0)
        sc = Scanner(prefill_of(prompt), is_agent)
        with self.lock:
            t0 = time.time()
            ttft = None
            toks = 0
            s = socket.create_connection(("127.0.0.1", self.port), timeout=300)
            try:
                s.sendall(struct.pack(">I", n) + body)
                f = s.makefile("rb")
                while True:
                    h = f.read(5)
                    if len(h) < 5:
                        raise RuntimeError("genied closed the connection")
                    kind, ln = h[0], struct.unpack(">I", h[1:])[0]
                    payload = f.read(ln) if ln else b""
                    if kind == 1:
                        break
                    if kind == 2:
                        raise RuntimeError("genied: " + payload.decode(errors="replace"))
                    chunk = payload.decode(errors="replace")
                    if ttft is None and chunk.strip():
                        ttft = time.time() - t0
                    toks += 1
                    if sc.feed(chunk):
                        s.sendall(b"\xff")
                        break
            finally:
                s.close()
            return {"engine": "npu", "latency_s": time.time() - t0, "ttft_s": ttft, "tokens": toks, "text": sc.text,
                    "large": bool(n >> 31)}


class Llama:
    """llama-server /completion, streamed; closing the stream stops generation."""

    def __init__(self, name, port, cache_prompt=False):
        self.name, self.port, self.cache_prompt = name, port, cache_prompt

    def call(self, prompt, is_agent):
        body = {"prompt": prompt.removeprefix("<|begin_of_text|>"), "n_predict": 320, "temperature": 0, "top_k": 1,
                "stream": True, "cache_prompt": self.cache_prompt, "add_special": True}
        sc = Scanner(prefill_of(prompt), is_agent)
        t0 = time.time()
        ttft, toks, timings = None, 0, None
        r = urllib.request.Request(f"http://127.0.0.1:{self.port}/completion", data=json.dumps(body).encode(),
                                   headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(r, timeout=600) as resp:
            for line in resp:
                line = line.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                d = json.loads(line[5:])
                chunk = d.get("content", "")
                if chunk:
                    if ttft is None and chunk.strip():
                        ttft = time.time() - t0
                    toks += 1
                    if sc.feed(chunk):
                        break  # closing the response cancels the slot's generation
                if d.get("stop"):
                    timings = d.get("timings")
                    break
        return {"engine": self.name, "latency_s": time.time() - t0, "ttft_s": ttft, "tokens": toks, "text": sc.text,
                "timings": timings}


# ------------------------------------------------------------------ placements

def run_incident(inc, placement, engines):
    """Returns (wall seconds, call records). placement = dict(agents=[(engine, workers)...], synth=engine|'first')."""
    jobs = queue.Queue()
    for i, a in enumerate(inc["agents"]):
        jobs.put((i, a))
    out = [None] * len(inc["agents"])
    t0 = time.time()

    def worker(eng):
        while True:
            try:
                i, a = jobs.get_nowait()
            except queue.Empty:
                return
            st = time.time() - t0
            try:
                r = engines[eng].call(a["prompt"], True)
            except Exception as e:
                r = {"engine": eng, "error": str(e), "latency_s": None, "text": ""}
            r.update(kind="agent", idx=i, start_s=round(st, 3), end_s=round(time.time() - t0, 3), ref=a["ref"])
            out[i] = r

    ths = [threading.Thread(target=worker, args=(eng,)) for eng, n in placement["agents"] for _ in range(n)]
    for t in ths:
        t.start()
    for t in ths:
        t.join()
    calls = [c for c in out if c]
    if inc.get("synth") and placement.get("synth"):
        eng = placement["synth"]
        st = time.time() - t0
        try:
            r = engines[eng].call(inc["synth"]["prompt"], False)
        except Exception as e:
            r = {"engine": eng, "error": str(e), "latency_s": None, "text": ""}
        r.update(kind="synth", start_s=round(st, 3), end_s=round(time.time() - t0, 3))
        calls.append(r)
    return time.time() - t0, calls


PLACEMENTS = {
    "npu_all":            {"agents": [("npu", 1)], "synth": "npu"},
    "gpu_seq":            {"agents": [("gpu", 1)], "synth": "gpu"},
    "gpu_par2":           {"agents": [("gpu", 2)], "synth": "gpu"},
    "gpu_par4":           {"agents": [("gpu", 4)], "synth": "gpu"},
    "gpu_par4_synth_npu": {"agents": [("gpu", 4)], "synth": "npu"},
    "npu_agents_synth_gpu": {"agents": [("npu", 1)], "synth": "gpu"},
    "split_npu1_gpu1":    {"agents": [("npu", 1), ("gpu", 1)], "synth": "npu"},
    "split_npu1_gpu2":    {"agents": [("npu", 1), ("gpu", 2)], "synth": "npu"},
    "split_npu1_gpu4":    {"agents": [("npu", 1), ("gpu", 4)], "synth": "npu"},
    "cpu_seq":            {"agents": [("cpu", 1)], "synth": "cpu"},
    "gpu_agents_only":    {"agents": [("gpu", 1)], "synth": None},
    # llama.cpp Hexagon backend on the NPU (same Q4_0 weights), slots = parallel sequences
    "htp_seq":            {"agents": [("htp", 1)], "synth": "htp"},
    "htp_par4":           {"agents": [("htp", 4)], "synth": "htp"},
    "htp_par8":           {"agents": [("htp", 8)], "synth": "htp"},
    "htp_par13":          {"agents": [("htp", 13)], "synth": "htp"},
    "npu_agents_only":    {"agents": [("npu", 1)], "synth": None},
    "split_npu1_gpu1_ns": {"agents": [("npu", 1), ("gpu", 1)], "synth": None},
}

# ------------------------------------------------------------------ helpers


def adb(cmd, timeout=30):
    try:
        return subprocess.run([ADB, "shell", cmd], capture_output=True, text=True, timeout=timeout).stdout.strip()
    except Exception as e:
        return f"adb error: {e}"


def get(path):
    with urllib.request.urlopen(APP + path, timeout=30) as r:
        return json.loads(r.read())


def board():
    # Power rails, fuel gauge and PMIC ADCs are all closed to the shell user on this board (checked
    # 2026-10-16), so utilisation is the free proxy: GPU busy/total (kgsl gpubusy, a window of the
    # last ~1 s) and CPU jiffies from /proc/stat.
    raw = adb("for z in /sys/class/thermal/thermal_zone*; do echo $(cat $z/type) $(cat $z/temp); done; "
              "grep MemAvailable /proc/meminfo; echo gpubusy $(cat /sys/class/kgsl/kgsl-3d0/gpubusy); head -1 /proc/stat")
    t = {}
    mem = gpu_busy = cpu = None
    for line in raw.splitlines():
        p = line.split()
        if line.startswith("MemAvailable"):
            mem = int(p[1]) // 1024
        elif p and p[0] == "gpubusy" and len(p) == 3 and p[2] != "0":
            gpu_busy = round(int(p[1]) / int(p[2]), 3)
        elif p and p[0] == "cpu":
            cpu = [int(x) for x in p[1:8]]
        elif len(p) == 2 and p[1].lstrip("-").isdigit():
            t[p[0]] = int(p[1]) / 1000
    npu = max([v for k, v in t.items() if k.startswith("nsp")] or [0])
    gpu = max([v for k, v in t.items() if k.startswith("gpu")] or [0])
    return {"npu_c": npu, "gpu_c": gpu, "max_c": max(t.values() or [0]), "mem_avail_mb": mem,
            "gpu_busy": gpu_busy, "cpu_jiffies": cpu}


class Sampler(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.samples, self.stop = [], threading.Event()

    def run(self):
        while not self.stop.is_set():
            self.samples.append({"t": time.time(), **board()})
            self.stop.wait(1.0)


def cool(limit):
    t0 = time.time()
    while board()["max_c"] >= limit and time.time() - t0 < 900:
        time.sleep(10)
    return round(time.time() - t0, 1)


WORKLOAD_DIR = None


def load_incident(iid):
    # recorded incidents exported to files (proofs/<run>/workload_<id>.json) let GPU-only runs go
    # without the app, whose NPU daemon holds ~3 GB of the unmovable memory the GPU also needs
    f = Path(WORKLOAD_DIR) / f"workload_{iid}.json" if WORKLOAD_DIR else None
    d = json.loads(f.read_text(encoding="utf-8")) if f and f.exists() else get(f"/api/incidents/{iid}")
    agents = [{"ref": a["ref"], "prompt": a["prompt"], "npu_raw": a.get("raw"), "npu_parsed": a.get("parsed")}
              for a in d.get("agents") or [] if a.get("prompt")]
    f = d.get("final") or {}
    synth = {"prompt": f["prompt"], "npu_raw": f.get("raw"), "npu_parsed": f.get("parsed")} \
        if f.get("prompt") and "agent finding" not in (f.get("model") or "") and len(agents) > 1 else None
    return {"id": iid, "title": d.get("title"), "agents": agents, "synth": synth}


def agree(call, ref_parsed, keys, prefill):
    try:
        got = json.loads(prefill + call["text"])  # the prompt already holds the start of the object
    except Exception:
        return {"json_ok": False}
    r = {"json_ok": True}
    for k in keys:
        if ref_parsed and k in ref_parsed:
            r[k] = got.get(k) == ref_parsed.get(k)
    return r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--incidents", required=True, help="comma list of app incident ids to replay")
    ap.add_argument("--placements", default="all")
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--cool", type=float, default=55)
    ap.add_argument("--out", default=str(REPO / "proofs" / f"{datetime.now():%Y-%m-%d}_hw_grid"))
    ap.add_argument("--gpu-port", type=int, default=8080)
    ap.add_argument("--cpu-port", type=int, default=8081)
    ap.add_argument("--htp-port", type=int, default=8090)
    ap.add_argument("--note", default="")
    ap.add_argument("--workload-dir", default=None, help="read workload_<id>.json files instead of the app API")
    a = ap.parse_args()
    global WORKLOAD_DIR
    WORKLOAD_DIR = a.workload_dir
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    for p in (8000, 8777, a.gpu_port, a.cpu_port, a.htp_port):
        subprocess.run([ADB, "forward", f"tcp:{p}", f"tcp:{p}"], capture_output=True)
    engines = {"npu": NPU(), "gpu": Llama("gpu", a.gpu_port), "cpu": Llama("cpu", a.cpu_port),
               "htp": Llama("htp", a.htp_port)}
    names = list(PLACEMENTS) if a.placements == "all" else a.placements.split(",")
    incs = [load_incident(i) for i in a.incidents.split(",")]
    logf = open(out / "log.txt", "a", encoding="utf-8")

    def log(m):
        line = f"[{datetime.now():%H:%M:%S}] {m}"
        print(line, flush=True)
        logf.write(line + "\n")
        logf.flush()

    man = out / "manifest.json"
    meta = json.loads(man.read_text()) if man.exists() else {
        "what": "hardware placement grid: same model on NPU (w4a16 bundle) and GPU (exact Q4_0/Q8_0 repack)",
        "created": datetime.now().isoformat(timespec="seconds"),
        "git": subprocess.run(["git", "-C", str(REPO), "describe", "--always", "--dirty"], capture_output=True, text=True).stdout.strip(),
        "device": adb("getprop ro.serialno") + " " + adb("getprop ro.board.platform"), "runs": []}
    meta["runs"].append({"command": " ".join(__import__("sys").argv), "placements": names, "incidents": a.incidents,
                         "reps": a.reps, "note": a.note, "started": datetime.now().isoformat(timespec="seconds"),
                         "gpu_server": adb("ps -A -o ARGS | grep llama-server | grep -v grep")})
    man.write_text(json.dumps(meta, indent=1), encoding="utf-8")

    for rep in range(a.reps):
        for inc in incs:
            for pn in names:
                pl = PLACEMENTS[pn]
                waited = cool(a.cool)
                b0 = board()
                smp = Sampler()
                smp.start()
                try:
                    wall, calls = run_incident(inc, pl, engines)
                    err = None
                except Exception as e:
                    wall, calls, err = None, [], str(e)
                smp.stop.set()
                smp.join()
                for c in calls:
                    if c["kind"] == "agent":
                        c["agree_npu"] = agree(c, inc["agents"][c["idx"]]["npu_parsed"], ["pattern", "status", "likely_cause"],
                                             prefill_of(inc["agents"][c["idx"]]["prompt"]))
                    else:
                        c["agree_npu"] = agree(c, inc["synth"]["npu_parsed"], ["label", "action"], prefill_of(inc["synth"]["prompt"]))
                peak = max((s["max_c"] for s in smp.samples), default=None)
                rec = {"rep": rep, "incident": inc["id"], "n_agents": len(inc["agents"]), "synth": bool(inc["synth"]),
                       "placement": pn, "wall_s": wall, "error": err, "cooldown_s": waited, "board_start": b0,
                       "peak_c": peak, "min_mem_mb": min((s["mem_avail_mb"] or 0 for s in smp.samples), default=None),
                       "thermal": smp.samples, "calls": calls}
                with open(out / "samples.jsonl", "a", encoding="utf-8") as f:
                    f.write(json.dumps(rec) + "\n")
                ok = sum(1 for c in calls if c.get("agree_npu", {}).get("json_ok"))
                log(f"rep{rep} {inc['id']} ({len(inc['agents'])}a{'+s' if inc['synth'] else ''}) {pn:22s} "
                    f"{(wall or 0):6.1f}s  json {ok}/{len(calls)}  peak {peak} C" + (f"  ERROR {err}" if err else ""))
    log("done")


if __name__ == "__main__":
    main()
