"""rsn_v3 chat self-distillation on the LAPTOP GPU (llama.cpp CUDA llama-server, base Qwen3.5-4B Q8_0, -np slots,
prompt cache). Same method as kaggle/distill.py (copied, not imported: chatloop.py / select_distill.py in this folder):
K samples per question at temperature 0.7, thinking on for hard records (teacher hint in the system prompt during
generation only, think budget-forced at --think-budget tokens: phase A stops at </think> or the budget, then </think>
is written and phase B continues), off for the others (template's empty think block); tool calls executed on the
ToolsV3 training store; up to 4 calls/rounds as chatloop. Each sample is verified inline (verify_chat) only for the
status page; select_distill.py re-verifies and picks the rows.

Guards: Windows free RAM >= 1.5 GB (pause below, resume >= 2.0 GB), GPU temp < 85 C (pause, resume <= 78 C), checked
every minute; STOP file -> clean stop; wall cap --hours; heartbeat + STATUS.md; GPU_LOCK shared with other laptop GPU
jobs (wait while someone else holds it, hold it while the server runs). Resumable: append-only raw files keyed by
record id, restart skips done ids.
  ~/venvs/rsn/bin/python distill_llama.py --dir OUT --set dev=chat3_dev.jsonl --set train=chat3_train.jsonl [--limit 20]"""
import argparse
import collections
import json
import os
import copy
import random
import re
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import chatloop as CL  # noqa: E402  (puts ../pipeline on sys.path)
import verify_chat as VC  # noqa: E402
from tools_v3_impl import ToolsV3  # noqa: E402

V3 = CL.V3
LOCK = os.path.join(V3, "GPU_LOCK")
PS = "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe"
LLAMA = os.path.expanduser("~/llama-cuda-b11815")


def now():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def order_records(recs, seed=29):
    """kaggle/distill.py: stratified shuffle (round-robin over kinds) so a time-limited run covers every kind"""
    R = random.Random(seed)
    by = {}
    for r in recs:
        by.setdefault(r["kind"], []).append(r)
    for v in by.values():
        R.shuffle(v)
    kinds = sorted(by)
    R.shuffle(kinds)
    out = []
    while any(by.values()):
        for k in kinds:
            if by[k]:
                out.append(by[k].pop())
    return out


class Job:
    def __init__(self, a):
        self.a = a
        self.t0 = time.time()
        self.stop = threading.Event()
        self.go = threading.Event()
        self.go.set()
        self.lock = threading.Lock()
        self.stat = collections.defaultdict(collections.Counter)   # (set, kind) -> counters
        self.stat_c = collections.Counter()
        self.tok_gen = 0
        self.gen_s = 0.0
        self.prompt_n = 0
        self.req = 0
        self.done_new = 0
        self.pause_reason = ""
        self.pauses = 0
        self.server = None
        self.server_restarts = 0
        self.have_lock = False
        self.log_f = open(os.path.join(a.dir, "distill.log"), "a")
        self.todo_total = 0
        self.stop_reason = ""

    def log(self, m):
        line = "[%s] %s" % (now(), m)
        print(line, flush=True)
        self.log_f.write(line + "\n")
        self.log_f.flush()

    # ------------------------------------------------------------------ guards
    def win_free_mb(self):
        try:
            o = subprocess.run([PS, "-NoProfile", "-Command", "(Get-CimInstance Win32_PerfFormattedData_PerfOS_Memory).AvailableMBytes"],
                               capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL).stdout
            # available = free + standby (what Windows can hand out); FreePhysicalMemory alone excludes the standby cache
            return int("".join(c for c in o if c.isdigit()))
        except Exception:
            return None

    def gpu(self):
        try:
            o = subprocess.run(["nvidia-smi", "--query-gpu=temperature.gpu,memory.used,utilization.gpu", "--format=csv,noheader,nounits"],
                               capture_output=True, text=True, timeout=30).stdout.strip().split(",")
            return [int(x.strip()) for x in o]
        except Exception:
            return [None, None, None]

    def take_lock(self):
        name = self.a.name
        while os.path.exists(LOCK):
            try:
                c = open(LOCK).read()
            except Exception:
                c = ""
            if c.startswith(name + " "):
                self.log("GPU_LOCK held by an earlier run of this job (%s): taking it over" % c.strip())
                break
            self.log("waiting: GPU_LOCK held by %r" % c.strip())
            if self.stop_requested():
                return False
            time.sleep(60)
        open(LOCK, "w").write("%s %s pid=%d\n" % (name, now(), os.getpid()))
        self.have_lock = True
        return True

    def release_lock(self):
        if self.have_lock:
            try:
                if open(LOCK).read().startswith(self.a.name + " "):
                    os.remove(LOCK)
            except Exception:
                pass
            self.have_lock = False

    def stop_requested(self):
        if os.path.exists(os.path.join(self.a.dir, "STOP")):
            self.stop_reason = self.stop_reason or "STOP file"
            return True
        if (time.time() - self.t0) / 3600 > self.a.hours:
            self.stop_reason = self.stop_reason or "wall cap %.1f h" % self.a.hours
            return True
        return self.stop.is_set()

    # ------------------------------------------------------------------ server
    def start_server(self):
        env = dict(os.environ, LD_LIBRARY_PATH=os.path.join(LLAMA, "bin"))
        cmd = ["nice", "-n", "10", os.path.join(LLAMA, "bin", "llama-server"), "-m", self.a.gguf, "-ngl", "99",
               "-c", str(self.a.ctx_slot * self.a.np), "-np", str(self.a.np), "-t", "4", "-tb", "4", "--host", "127.0.0.1",
               "--port", str(self.a.port), "--no-webui"] + self.a.server_args.split()
        self.log("server: " + " ".join(cmd))
        self.server = subprocess.Popen(cmd, stdout=open(os.path.join(self.a.dir, "server.log"), "a"), stderr=subprocess.STDOUT,
                                       stdin=subprocess.DEVNULL, env=env, start_new_session=True)
        for _ in range(180):
            time.sleep(2)
            if self.server.poll() is not None:
                raise RuntimeError("llama-server exited (%s), see server.log" % self.server.returncode)
            try:
                if b"ok" in urllib.request.urlopen("http://127.0.0.1:%d/health" % self.a.port, timeout=5).read():
                    self.log("server up (pid %d)" % self.server.pid)
                    return
            except Exception:
                pass
        raise RuntimeError("llama-server not healthy after 360 s")

    def stop_server(self):
        if self.server and self.server.poll() is None:
            try:
                os.killpg(self.server.pid, signal.SIGCONT)
            except Exception:
                pass
            self.server.terminate()
            try:
                self.server.wait(30)
            except Exception:
                self.server.kill()
        self.server = None

    # ------------------------------------------------------------------ backend
    def post(self, prompt, n, stop, temperature=None):
        body = {"prompt": prompt, "n_predict": n, "temperature": self.a.temperature if temperature is None else temperature, "top_p": self.a.top_p, "top_k": self.a.top_k,
                "stop": stop, "cache_prompt": True, "seed": random.randrange(1 << 30)}
        data = json.dumps(body).encode()
        for attempt in range(40):
            self.go.wait()
            if self.stop.is_set():
                raise InterruptedError()
            try:
                req = urllib.request.Request("http://127.0.0.1:%d/completion" % self.a.port, data=data,
                                             headers={"Content-Type": "application/json"})
                o = json.loads(urllib.request.urlopen(req, timeout=900).read())
                break
            except (urllib.error.URLError, ConnectionError, TimeoutError, OSError) as e:
                if attempt % 5 == 0:
                    self.log("request failed (%s), retry %d" % (e, attempt))
                time.sleep(15)
        else:
            raise RuntimeError("server unreachable")
        tm = o.get("timings") or {}
        with self.lock:
            self.req += 1
            self.tok_gen += int(o.get("tokens_predicted") or 0)
            self.gen_s += float(tm.get("predicted_ms") or 0) / 1000
            self.prompt_n += int(tm.get("prompt_n") or 0)
        return o.get("content", ""), bool(o.get("stopped_limit")) or o.get("stop_type") == "limit"

    def generate(self, prompts, think):
        out = []
        for p, th in zip(prompts, think):
            pre, forced = "", False
            if th:
                a, lim = self.post(p, self.a.think_budget, ["</think>", "<|im_end|>"])
                forced = lim
                pre = "<think>\n" + a.rstrip() + "\n</think>\n\n"
                p = p + a.rstrip() + "\n</think>\n\n"
            b, _ = self.post(p, self.a.max_new, ["<|im_end|>"])
            out.append((pre + b, forced))
        return out

    # ------------------------------------------------------------------ work
    def compress_think(self, rec, s, tok):
        """second pass for a long-think sample: the same (base) model rewrites each round's reasoning into <= think_target
        tokens ("summarise the reasoning steps that lead to this exact action/answer"); numbers in the rewrite must
        appear in the original reasoning, the question, the action or the tool results. True if every round now fits."""
        q = [m["content"] for m in rec["messages"] if m["role"] == "user"][-1]
        tool_txt = " ".join(m["content"] for m in s.new if m["role"] == "tool")
        orig = [m.get("reasoning_content") or "" for m in s.new if m["role"] == "assistant"]
        s.think_orig = orig
        for m in s.new:
            if m["role"] != "assistant":
                continue
            th = m.get("reasoning_content") or ""
            if VC.think_tokens(th) <= self.a.think_target:
                continue
            if m.get("tool_calls"):
                act = "it called " + "; ".join("%s(%s)" % (c["function"]["name"], json.dumps(c["function"]["arguments"], ensure_ascii=False))
                                              for c in m["tool_calls"])
            else:
                act = "it answered: " + (m.get("content") or "")
            msgs = [{"role": "system", "content": "You shorten an assistant's private reasoning. Reply with the shortened reasoning only."},
                    {"role": "user", "content": "Operator question: %s\nWhat the assistant did next: %s\n\nOriginal reasoning:\n%s\n\n"
                     "Summarise the reasoning steps that lead to this exact action/answer in at most two short sentences "
                     "(under 45 words). Use only tool names, facts and numbers that appear above." % (q, act, th)}]
            prompt = tok.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True, enable_thinking=False)
            src_nums = set(re.findall(r"\d+(?:\.\d+)?", " ".join((th, q, tool_txt, act))))
            best = None
            for t in (0.3, 0.7):
                txt, _ = self.post(prompt, 140, ["<|im_end|>"], temperature=t)
                txt = re.sub(r"</?think>", "", txt).strip().strip('"').strip()
                if not txt or VC.think_tokens(txt) > self.a.think_target:
                    continue
                if any(n not in src_nums for n in re.findall(r"\d+(?:\.\d+)?", txt)):
                    continue
                best = txt
                break
            if best is None:
                return False
            m["reasoning_content"] = best
        return True

    def do_record(self, rec, tok, tools):
        hard = bool(rec.get("hard"))
        K = self.a.k_hard if hard else self.a.k_easy
        out, seen = [], set()
        for k in range(K):
            s = CL.Sample(rec, k, hard)
            CL.run_samples(self, tok, tools, [s], ToolsV3, VC.parse_turn, teacher_hint=True)
            j = None
            if s.status == "final" and s.new:
                ex = ToolsV3()
                ex.qid = 0
                v = VC.verify(rec, CL.candidate(s), executor=ex)
                rs = [x.split(":")[0] for x in v["reasons"]]
                comp = False
                if hard and rs == ["think_too_long"]:
                    new_long = copy.deepcopy(s.new)
                    ok = self.compress_think(rec, s, tok)
                    v2 = None
                    if ok:
                        ex.qid = 0
                        v2 = VC.verify(rec, CL.candidate(s), executor=ex)
                    if v2 is not None and v2["pass"]:
                        v, comp = v2, True
                        with self.lock:
                            self.stat_c["compressed_ok"] += 1
                    else:
                        s.new = new_long          # keep the long-think transcript (select: long kept only if no short pass)
                        with self.lock:
                            self.stat_c["compressed_fail"] += 1
                j = s.to_json()
                j["compressed"] = comp
                if comp:
                    j["think_orig"] = s.think_orig
                j["v"] = {"pass": v["pass"], "reasons": v["reasons"], "think_tokens": v["think_tokens"]}
                if v["pass"]:
                    seen.add((v["final"].strip().lower(), json.dumps([(c["name"], c["args"]) for c in v["calls"]], sort_keys=True, default=str)))
            out.append(j or s.to_json())
            if len(seen) >= self.a.keep:         # enough distinct verified samples: further ones would be discarded
                break
        return out

    def worker(self, q, tok, tools):
        while not self.stop.is_set():
            with self.lock:
                if not q:
                    return
                setname, path, rec = q.pop(0)
            try:
                ss = self.do_record(rec, tok, tools)
            except InterruptedError:
                return
            except Exception as e:
                self.log("record %s failed: %r (left for a rerun)" % (rec["id"], e))
                continue
            row = {"id": rec["id"], "kind": rec["kind"], "hard": bool(rec.get("hard")), "t": now(), "samples": ss}
            with self.lock:
                with open(path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(row, ensure_ascii=False) + "\n")
                self.count(setname, row)
                self.done_new += 1

    def count(self, setname, row):
        st = self.stat[(setname, row["kind"])]
        st["records"] += 1
        st["hard"] = int(row["hard"])
        anyp = False
        for s in row["samples"]:
            st["samples"] += 1
            v = s.get("v")
            if v and v["pass"]:
                st["pass"] += 1
                anyp = True
            elif v and [x.split(":")[0] for x in v["reasons"]] == ["think_too_long"]:
                st["pass_long"] += 1
            if s.get("forced"):
                st["forced"] += 1
        st["q_pass"] += int(anyp)

    # ------------------------------------------------------------------ status
    def status(self, final=False):
        el = time.time() - self.t0
        with self.lock:
            done_new, toks, gs, req, pn = self.done_new, self.tok_gen, self.gen_s, self.req, self.prompt_n
            stat = {k: dict(v) for k, v in self.stat.items()}
        left = max(0, self.todo_total - done_new)
        rate = done_new / max(1e-9, el - self.pause_s()) * 3600
        eta = left / rate if rate > 0 else None
        t, mem, util = self.gpu()
        L = ["# rsn_v3 laptop chat distillation: STATUS (%s)" % ("FINAL" if final else "running"), "",
             "- updated %s, elapsed %.2f h (paused %.2f h), job %s, pid %d" % (now(), el / 3600, self.pause_s() / 3600, self.a.name, os.getpid()),
             "- records done this run %d / %d to do (%.0f rec/h); ETA %s" % (done_new, self.todo_total, rate,
                                                                           "%.1f h" % eta if eta is not None else "n/a"),
             "- generated tokens %d in %d requests; aggregate %.1f tok/s wall, per-request decode %.1f tok/s; mean prompt tokens"
             " evaluated (not cached) %.0f" % (toks, req, toks / max(1, el - self.pause_s()), toks / max(1e-9, gs), pn / max(1, req)),
             "- GPU %s C, %s MiB, %s%% util; Windows free RAM %s MB; paused: %s (%d pauses); server restarts %d" % (
                 t, mem, util, self.last_free, self.pause_reason or "no", self.pauses, self.server_restarts),
             "- stop: %s; think compression: %s" % (self.stop_reason or "-", dict(self.stat_c)), "",
             "| set | kind | hard | records | samples | pass | pass_long | forced | sample pass | question pass |", "|---|---|---|---|---|---|---|---|---|---|"]
        tot = collections.defaultdict(collections.Counter)
        for (sn, k), st in sorted(stat.items()):
            L.append("| %s | %s | %d | %d | %d | %d | %d | %d | %.2f | %.2f |" % (sn, k, st.get("hard", 0), st["records"], st["samples"],
                     st.get("pass", 0), st.get("pass_long", 0), st.get("forced", 0), st.get("pass", 0) / max(1, st["samples"]),
                     st.get("q_pass", 0) / max(1, st["records"])))
            tot[sn].update(st)
        for sn, st in tot.items():
            L.append("| %s | ALL | | %d | %d | %d | %d | %d | %.3f | %.3f |" % (sn, st["records"], st["samples"], st["pass"], st["pass_long"],
                     st["forced"], st["pass"] / max(1, st["samples"]), st["q_pass"] / max(1, st["records"])))
        L += ["", "(inline verify_chat; selection/final report: select_distill.py. Stop cleanly: create STOP in this folder.)"]
        open(os.path.join(self.a.dir, "STATUS.md.part"), "w").write("\n".join(L) + "\n")
        os.replace(os.path.join(self.a.dir, "STATUS.md.part"), os.path.join(self.a.dir, "STATUS.md"))
        open(os.path.join(self.a.dir, "HEARTBEAT"), "w").write(now() + "\n")

    def pause_s(self):
        return self._paused + (time.time() - self._pause_t0 if self._pause_t0 else 0)

    def monitor(self):
        self._paused, self._pause_t0, self.last_free = 0.0, None, None
        while not self.stop.is_set():
            if self.stop_requested():
                self.log("stopping: %s" % self.stop_reason)
                self.stop.set()
                self.go.set()
                break
            free = self.win_free_mb()
            self.last_free = free
            t = self.gpu()[0]
            low = free is not None and free < self.a.ram_pause_mb
            hot = t is not None and t >= 85
            if self.go.is_set() and (low or hot):
                self.pause_reason = "Windows free %s MB" % free if low else "GPU %s C" % t
                self.log("PAUSE: %s" % self.pause_reason)
                self.go.clear()
                self.pauses += 1
                self._pause_t0 = time.time()
            elif not self.go.is_set() and (free is None or free >= self.a.ram_pause_mb + 256) and (t is None or t <= 78):
                self.log("RESUME (free %s MB, GPU %s C)" % (free, t))
                self._paused += time.time() - self._pause_t0
                self._pause_t0 = None
                self.pause_reason = ""
                self.go.set()
            if self.server is not None and self.server.poll() is not None and not self.stop.is_set():
                self.log("llama-server died (rc %s): restarting" % self.server.returncode)
                self.server_restarts += 1
                try:
                    self.start_server()
                except Exception as e:
                    self.log("restart failed: %r -> stop" % e)
                    self.stop_reason = "server restart failed"
                    self.stop.set()
                    self.go.set()
                    break
            try:
                self.status()
            except Exception as e:
                self.log("status error %r" % e)
            for _ in range(self.a.guard_every):
                if self.stop.is_set():
                    break
                time.sleep(1)


def validate_render(job, tok, tools, recs, n=5):
    """the generation prompt must be a prefix of the training render (train_rsn3.encode: enable_thinking=True for chat
    rows) of the same record with its gold continuation, and llama-server must tokenize it exactly like the HF tokenizer"""
    pick = [r for r in recs if r.get("hard")][:2] + [r for r in recs if not r.get("hard") and r.get("session_turns", 1) > 1][:2] + \
           [r for r in recs if not r.get("hard") and r.get("session_turns", 1) == 1][:1]
    res = []
    for r in pick[:n]:
        p = CL.render(tok, CL.prompt_messages(r), tools, r.get("hard"))
        full = tok.apply_chat_template(CL.gold_messages(r), tools=tools, tokenize=False, enable_thinking=True)
        ids = tok(p, add_special_tokens=False)["input_ids"]
        req = urllib.request.Request("http://127.0.0.1:%d/tokenize" % job.a.port, data=json.dumps({"content": p, "add_special": False,
                                     "parse_special": True}).encode(), headers={"Content-Type": "application/json"})
        sids = json.loads(urllib.request.urlopen(req, timeout=60).read())["tokens"]
        tail = "<think>\n" if r.get("hard") else "<think>\n\n</think>\n\n"
        res.append({"id": r["id"], "kind": r["kind"], "hard": bool(r.get("hard")), "turns": r.get("session_turns"),
                    "prompt_tokens": len(ids), "prefix_of_training_render": full.startswith(p), "ends_with": p.endswith(tail),
                    "server_tokens_equal_hf": sids == ids, "server_tokens": len(sids)})
    ok = all(x["prefix_of_training_render"] and x["ends_with"] and x["server_tokens_equal_hf"] for x in res)
    json.dump({"ok": ok, "checks": res}, open(os.path.join(job.a.dir, "render_check.json"), "w"), indent=1)
    job.log("render check: %s %s" % ("OK" if ok else "FAIL", res))
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True)
    ap.add_argument("--name", default="distill_laptop")
    ap.add_argument("--set", action="append", required=True, help="name=records.jsonl (raw output raw_<name>.jsonl)")
    ap.add_argument("--gguf", default=os.path.expanduser("~/models/qwen3.5-4b-gguf/qwen3.5-4b-q8_0.gguf"))
    ap.add_argument("--tokenizer", default=os.path.expanduser("~/models/qwen3.5-4b"))
    ap.add_argument("--port", type=int, default=18111)
    ap.add_argument("--np", type=int, default=6)
    ap.add_argument("--ctx-slot", type=int, default=7680)
    ap.add_argument("--server-args", default="--load-mode none -fa on -ctk q8_0 -ctv q8_0 -b 2048 -ub 512 -cram 256 -ctxcp 8 -cms 128")
    ap.add_argument("--workers", type=int, default=0, help="default = np")
    ap.add_argument("--k-hard", type=int, default=4)
    ap.add_argument("--k-easy", type=int, default=2)
    ap.add_argument("--keep", type=int, default=2, help="stop sampling a question once this many distinct samples pass")
    ap.add_argument("--think-target", type=int, default=80, help="verify_chat THINK_MAX: longer passing thinks get compressed")
    ap.add_argument("--temperature", type=float, default=0.7)
    ap.add_argument("--top-p", type=float, default=0.95)
    ap.add_argument("--top-k", type=int, default=20)
    ap.add_argument("--think-budget", type=int, default=384)
    ap.add_argument("--max-new", type=int, default=420)
    ap.add_argument("--hours", type=float, default=14)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--guard-every", type=int, default=60)
    ap.add_argument("--hard-first", type=int, default=1)
    ap.add_argument("--ram-pause-mb", type=int, default=1024, help="pause below this Windows available RAM (owner: 1.0 GB)")
    a = ap.parse_args()
    os.makedirs(a.dir, exist_ok=True)
    job = Job(a)
    job._paused, job._pause_t0, job.last_free = 0.0, None, None
    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(sig, lambda *_: (setattr(job, "stop_reason", job.stop_reason or "signal"), job.stop.set(), job.go.set()))
    from transformers import AutoTokenizer
    tok = AutoTokenizer.from_pretrained(a.tokenizer)
    tools = CL.load_tools()["chat"]
    q, allrecs = [], []
    for spec in a.set:
        name, path = spec.split("=", 1)
        recs = order_records([json.loads(l) for l in open(path, encoding="utf-8")])
        if a.limit:
            recs = recs[:a.limit]
        allrecs += recs
        out = os.path.join(a.dir, "raw_%s.jsonl" % name)
        done = set()
        if os.path.exists(out):
            for l in open(out, encoding="utf-8"):
                try:
                    o = json.loads(l)
                    done.add(o["id"])
                    job.count(name + "(earlier)", o)
                except Exception:
                    pass
        todo = [r for r in recs if r["id"] not in done]
        job.log("set %s: %d records, %d done earlier, %d to do" % (name, len(recs), len(done), len(todo)))
        q += [(name, out, r) for r in todo]
    if a.hard_first:     # per set: hard records first (they gain reasoning; easy ones fall back to an equivalent reference)
        si = {spec.split("=", 1)[0]: i for i, spec in enumerate(a.set)}
        q.sort(key=lambda x: (si[x[0]], not x[2].get("hard")))
    job.todo_total = len(q)
    if not q:
        job.log("nothing to do")
        return
    if not job.take_lock():
        job.log("stopped while waiting for GPU_LOCK")
        return
    try:
        t, mem, _ = job.gpu()
        if mem is not None and mem > 800:
            job.log("GPU busy (%s MiB used): not starting" % mem)
            return
        job.start_server()
        if not validate_render(job, tok, tools, allrecs):
            job.log("render check failed: not distilling")
            return
        mon = threading.Thread(target=job.monitor, daemon=True)
        mon.start()
        ws = [threading.Thread(target=job.worker, args=(q, tok, tools), daemon=True) for _ in range(a.workers or a.np)]
        for w in ws:
            w.start()
        while any(w.is_alive() for w in ws):
            time.sleep(5)
        if not q and not job.stop_reason:
            job.stop_reason = "all records done"
        job.stop.set()
        job.go.set()
        mon.join(timeout=120)
        job.status(final=True)
        job.log("exit: %s; %d records this run" % (job.stop_reason, job.done_new))
    finally:
        job.stop_server()
        job.release_lock()


if __name__ == "__main__":
    main()
