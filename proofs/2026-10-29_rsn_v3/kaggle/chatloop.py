"""rsn_v3 chat loop shared by the Kaggle distiller (HF generate) and the host gate eval (llama-server /completion).

A "sample" is one attempt at the LAST user turn of a chat3 record: the prompt is the record's messages up to and
including the last user message (earlier turns stay as history), rendered with the model's own chat template, the
tools_v4 "chat" header and enable_thinking=<record is hard>. Each round the model writes [<think>..</think>] then tool
calls or the final answer; calls are executed on the bundled ToolsV3 store (read-only training store) and the
conversation is re-rendered canonically (same form as training), until a final answer, a parse error or 5 calls.

Backends implement   generate(prompts: list[str], think: list[bool]) -> list[str]   (text after the prompt, without
<|im_end|>). Thinking rows start inside an open "<think>\n" block; the backend caps it at think_budget tokens and closes
it (s1-style budget forcing). Non-thinking rows get the template's empty think block in the prompt.
"""
import copy
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
V3 = os.path.abspath(os.path.join(HERE, ".."))
PIPE = os.path.join(V3, "pipeline")
if PIPE not in sys.path:
    sys.path.insert(0, PIPE)

MAX_CALLS = 5
MAX_ROUNDS = 4
TEACHER_HINT = ("\n- Before acting, think briefly: at most two short sentences (under 50 words) about which tool numbers "
                "you need and how they answer the question.")


def load_tools(path=None):
    return json.load(open(path or os.path.join(PIPE, "tools_v4.json"), encoding="utf-8"))


def prompt_messages(rec, teacher_hint=False):
    """record messages up to and including the last user message; tool-call arguments as dicts"""
    msgs = copy.deepcopy(rec["messages"])
    last_user = max(i for i, m in enumerate(msgs) if m["role"] == "user")
    msgs = msgs[:last_user + 1]
    for m in msgs:
        for tc in m.get("tool_calls") or []:
            a = tc["function"]["arguments"]
            if isinstance(a, str):
                tc["function"]["arguments"] = json.loads(a)
    if teacher_hint and rec.get("hard") and msgs[0]["role"] == "system":
        msgs[0]["content"] = msgs[0]["content"] + TEACHER_HINT
    return msgs


def gold_messages(rec):
    """the record's own gold transcript for the last turn + the templated reference answer (fallback / dev rows)"""
    msgs = copy.deepcopy(rec["messages"])
    for m in msgs:
        for tc in m.get("tool_calls") or []:
            a = tc["function"]["arguments"]
            if isinstance(a, str):
                tc["function"]["arguments"] = json.loads(a)
    return msgs + [{"role": "assistant", "content": rec["reference_answer"]}]


def render(tok, msgs, tools, think):
    return tok.apply_chat_template(msgs, tools=tools, tokenize=False, add_generation_prompt=True, enable_thinking=bool(think))


class Sample:
    def __init__(self, rec, k, think):
        self.rec, self.k, self.think = rec, k, bool(think)
        self.new = []           # assistant/tool messages written for the last turn
        self.raw = []           # raw model text per round
        self.done, self.status, self.ncalls = False, "", 0
        self.forced = 0         # rounds whose think was closed by the budget

    def to_json(self):
        return {"k": self.k, "think": self.think, "status": self.status, "raw": self.raw, "new": self.new, "forced": self.forced}


def apply_round(s, text, ex, parse_turn):
    """parse one round of model text, execute its calls, append messages; sets s.done when finished"""
    s.raw.append(text)
    t = parse_turn(text)
    if t["err"]:
        s.done, s.status = True, "call_parse"
        return
    if not t["calls"]:
        s.new.append({"role": "assistant", "reasoning_content": t["think"], "content": t["text"]})
        s.done, s.status = True, "final"
        return
    if s.ncalls + len(t["calls"]) > MAX_CALLS or len(s.raw) >= MAX_ROUNDS:
        s.done, s.status = True, "too_many_calls"
        return
    tcs = []
    for c in t["calls"]:
        s.ncalls += 1
        tcs.append({"id": "call_%d" % s.ncalls, "type": "function", "function": {"name": c["name"], "arguments": c["args"] or {}}})
    s.new.append({"role": "assistant", "reasoning_content": t["think"], "content": "", "tool_calls": tcs})
    for tc in tcs:
        r = ex.run(tc["function"]["name"], tc["function"]["arguments"])
        s.new.append({"role": "tool", "tool_call_id": tc["id"], "content": json.dumps(r, ensure_ascii=False)})


def run_samples(backend, tok, tools, samples, make_executor, parse_turn, teacher_hint=False, log=None):
    """round-wise batched loop over all samples (one executor per sample, query ids restart at q1 like the gold)"""
    exs = {id(s): make_executor() for s in samples}
    for ex in exs.values():
        ex.qid = 0
    base = {id(s): prompt_messages(s.rec, teacher_hint) for s in samples}
    for rnd in range(MAX_ROUNDS):
        act = [s for s in samples if not s.done]
        if not act:
            break
        prompts = [render(tok, base[id(s)] + s.new, tools, s.think) for s in act]
        outs = backend.generate(prompts, [s.think for s in act])
        for s, o in zip(act, outs):
            if isinstance(o, tuple):
                o, forced = o
                s.forced += int(forced)
            apply_round(s, o, exs[id(s)], parse_turn)
        if log:
            log("round %d: %d active -> %d done" % (rnd, len(act), sum(1 for s in samples if s.done)))
    for s in samples:
        if not s.done:
            s.done, s.status = True, "no_final"
    return samples


def candidate(s):
    """verify_chat candidate form: list of message dicts (assistant with reasoning_content, tool results)"""
    return list(s["new"]) if isinstance(s, dict) else list(s.new)


# ------------------------------------------------------------------------------------------------ backends
class HFBackend:
    """transformers generate, left-padded micro-batches sorted by length; thinking rows get a logits processor that
    forces </think> after think_budget generated tokens (single pass, no re-prefill)."""
    def __init__(self, model, tok, temperature=0.7, top_p=0.95, top_k=20, think_budget=128, max_new=420, tok_budget=40000,
                 max_batch=16, log=print):
        import torch
        self.torch, self.m, self.tok = torch, model, tok
        self.temperature, self.top_p, self.top_k = temperature, top_p, top_k
        self.think_budget, self.max_new, self.tok_budget, self.max_batch, self.log = think_budget, max_new, tok_budget, max_batch, log
        self.end_think = tok.convert_tokens_to_ids("</think>")
        self.im_end = tok.convert_tokens_to_ids("<|im_end|>")
        tok.padding_side = "left"
        if tok.pad_token is None:
            tok.pad_token = tok.eos_token

    def _proc(self, think_rows, plen):
        import torch
        from transformers import LogitsProcessor
        et, budget = self.end_think, self.think_budget
        forced = [False] * len(think_rows)

        class ForceEndThink(LogitsProcessor):
            def __call__(self, input_ids, scores):
                gen = input_ids[:, plen:]
                n = gen.shape[1]
                if n < budget:
                    return scores
                for i, th in enumerate(think_rows):
                    if th and not bool((gen[i] == et).any()):
                        scores[i, :] = -float("inf")
                        scores[i, et] = 0.0
                        forced[i] = True
                return scores
        return ForceEndThink(), forced

    def _gen(self, prompts, think):
        torch = self.torch
        enc = self.tok(prompts, return_tensors="pt", padding=True, add_special_tokens=False).to(self.m.device)
        plen = enc["input_ids"].shape[1]
        proc, forced = self._proc(think, plen)
        from transformers import LogitsProcessorList
        with torch.no_grad():
            samp = dict(do_sample=True, temperature=self.temperature, top_p=self.top_p, top_k=self.top_k) if self.temperature > 0 else dict(do_sample=False)
            out = self.m.generate(**enc, max_new_tokens=self.max_new + (self.think_budget if any(think) else 0), use_cache=True,
                                  logits_processor=LogitsProcessorList([proc]), eos_token_id=[self.im_end], pad_token_id=self.tok.pad_token_id, **samp)
        res = []
        for i, o in enumerate(out):
            t = self.tok.decode(o[plen:], skip_special_tokens=False)
            t = t.split("<|im_end|>")[0].replace(self.tok.pad_token, "")
            if think[i]:
                t = "<think>\n" + t        # the prompt opened the block
            res.append((t, forced[i]))
        return res

    def generate(self, prompts, think):
        lens = [len(self.tok(p, add_special_tokens=False)["input_ids"]) for p in prompts]
        order = sorted(range(len(prompts)), key=lambda i: lens[i])
        out = [None] * len(prompts)
        i = 0
        while i < len(order):
            j = i
            while j < len(order) and (j - i) < self.max_batch and (j - i + 1) * (lens[order[j]] + self.max_new) <= self.tok_budget:
                j += 1
            j = max(j, i + 1)
            idx = order[i:j]
            try:
                res = self._gen([prompts[k] for k in idx], [think[k] for k in idx])
            except (self.torch.OutOfMemoryError, RuntimeError) as e:
                if not isinstance(e, self.torch.OutOfMemoryError) and "out of memory" not in str(e):
                    raise
                self.torch.cuda.empty_cache()
                if len(idx) == 1:
                    res = [("", False)]
                else:
                    self.tok_budget = max(8000, self.tok_budget // 2)
                    self.log("OOM: token budget -> %d" % self.tok_budget)
                    continue
            for k, r in zip(idx, res):
                out[k] = r
            i = j
        return out


class LlamaServerBackend:
    """llama-server raw /completion (greedy by default); thinking rows: phase A up to think_budget tokens stopped at
    </think>, closed by force when the budget is hit, then phase B for the rest (prompt cache makes B cheap)."""
    def __init__(self, port, temperature=0.0, think_budget=128, max_new=420, timeout=600):
        self.url = "http://127.0.0.1:%d/completion" % port
        self.temperature, self.think_budget, self.max_new, self.timeout = temperature, think_budget, max_new, timeout
        self.tokens = 0

    def _post(self, prompt, n, stop):
        import urllib.request
        body = {"prompt": prompt, "n_predict": n, "temperature": self.temperature, "stop": stop, "cache_prompt": True}
        if self.temperature == 0:
            body["top_k"] = 1
        req = urllib.request.Request(self.url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
        o = json.loads(urllib.request.urlopen(req, timeout=self.timeout).read())
        self.tokens += int(o.get("tokens_predicted") or 0)
        return o.get("content", ""), bool(o.get("stopped_limit")) or o.get("stop_type") == "limit"

    def generate(self, prompts, think):
        out = []
        for p, th in zip(prompts, think):
            pre, forced = "", False
            if th:
                a, lim = self._post(p, self.think_budget, ["</think>", "<|im_end|>"])
                forced = lim
                pre = "<think>\n" + a.rstrip() + "\n</think>\n\n"
                p = p + a.rstrip() + "\n</think>\n\n"
            b, _ = self._post(p, self.max_new, ["<|im_end|>"])
            out.append((pre + b, forced))
        return out


def run_mock(samples, make_executor, parse_turn, render_calls):
    """dry-run generator: replays the gold calls round by round and writes the reference answer; sample k=2 gets a
    wrong number and hard sample k=3 a long think, so the select/verify paths see passes and failures."""
    for s in samples:
        ex = make_executor()
        ex.qid = 0
        rounds = {}
        for g in s.rec["gold_calls"]:
            rounds.setdefault(g["round"], []).append({"name": g["name"], "args": g["args"]})
        th = ""
        if s.think:
            th = ("Need the tool numbers first. " * (30 if s.k == 3 else 1)).strip()
        for r in sorted(rounds):
            text = ("<think>\n%s\n</think>\n\n" % th if s.think else "") + render_calls(rounds[r])
            apply_round(s, text, ex, parse_turn)
            if s.done:
                break
        if not s.done:
            ans = s.rec["reference_answer"]
            if s.k == 2:
                ans = re.sub(r"\d+(\.\d+)?", lambda m: str(float(m.group(0)) + 17.3), ans, count=1) if re.search(r"\d", ans) else ans + " 977"
            apply_round(s, ("<think>\n%s\n</think>\n\n" % th if s.think else "") + ans, ex, parse_turn)
    return samples
