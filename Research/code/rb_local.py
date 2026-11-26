"""rb_local.py: verbatim copy of Client / parse_text_tool_calls / run_loop from proofs/2026-10-25_reasoner_final/eval/p0/run_bench.py (lines 72-217);
the original cannot be imported any more (tools.json of that tree is gone). Same greedy decoding, tool loop and 5-call cap as the gate runs."""
import json, os, re, sys, time, urllib.request, urllib.error

class Client:
    def __init__(self, port, max_tokens):
        self.url = "http://127.0.0.1:%d/v1/chat/completions" % port
        self.max_tokens = max_tokens

    def chat(self, messages, tools, tool_choice="auto", max_tokens=None):
        body = {"messages": messages, "temperature": 0.0, "top_k": 1, "top_p": 1.0, "seed": 1, "cache_prompt": True,
                "max_tokens": max_tokens or self.max_tokens, "chat_template_kwargs": {"enable_thinking": False}}
        if tools:
            body["tools"] = tools
            body["tool_choice"] = tool_choice
        t0 = time.time()
        raw_mode = False
        for attempt in range(3):
            req = urllib.request.Request(self.url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=1800) as r:
                    d = json.loads(r.read())
                break
            except urllib.error.HTTPError as e:
                err = e.read().decode(errors="replace")
                if "does not match" in err and not raw_mode:
                    # llama.cpp's tool-call parser rejected the output (e.g. a JSON report that starts like a Llama-3
                    # tool call). Same rendered prompt (/apply-template, model's own template + tools), same greedy
                    # decode via /completion; tool calls in the raw text are then parsed here.
                    return self.raw(body, t0)
                if attempt == 2:
                    return {"error": "HTTP %d: %s" % (e.code, err[:500])}, {}, time.time() - t0
                time.sleep(3)
            except Exception as e:
                if attempt == 2:
                    return {"error": str(e)}, {}, time.time() - t0
                time.sleep(5)
        msg = d["choices"][0]["message"]
        tim = d.get("timings", {})
        tim["finish_reason"] = d["choices"][0].get("finish_reason")
        tim["raw_mode"] = raw_mode
        if (raw_mode or not msg.get("tool_calls")) and tools and tool_choice != "none":
            tc = parse_text_tool_calls(msg.get("content") or "", {t["function"]["name"] for t in tools})
            if tc:
                msg = {"role": "assistant", "content": "", "tool_calls": tc}
                tim["text_tool_call"] = True
        return msg, tim, time.time() - t0

    def raw(self, body, t0):
        base = self.url.rsplit("/v1/", 1)[0]
        tb = {k: body[k] for k in ("messages", "tools", "tool_choice", "chat_template_kwargs") if k in body}
        try:
            req = urllib.request.Request(base + "/apply-template", data=json.dumps(tb).encode(), headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=600) as r:
                prompt = json.loads(r.read())["prompt"]
            cb = {"prompt": prompt, "n_predict": body["max_tokens"], "temperature": 0.0, "top_k": 1, "top_p": 1.0, "seed": 1,
                  "cache_prompt": True}
            req = urllib.request.Request(base + "/completion", data=json.dumps(cb).encode(), headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=1800) as r:
                d = json.loads(r.read())
        except Exception as e:
            return {"error": "raw fallback failed: %s" % e}, {}, time.time() - t0
        text = d.get("content") or ""
        tm = d.get("timings", {})
        tim = {"prompt_n": tm.get("prompt_n"), "prompt_ms": tm.get("prompt_ms"), "predicted_n": tm.get("predicted_n"),
               "predicted_ms": tm.get("predicted_ms"), "finish_reason": d.get("stop_type"), "raw_mode": True}
        msg = {"role": "assistant", "content": text}
        if body.get("tools") and body.get("tool_choice") != "none":
            tc = parse_text_tool_calls(text, {t["function"]["name"] for t in body["tools"]})
            if tc:
                msg = {"role": "assistant", "content": "", "tool_calls": tc}
                tim["text_tool_call"] = True
        return msg, tim, time.time() - t0


def parse_text_tool_calls(text, names):
    """Tool calls written as text: Llama-3 JSON {"name": .., "parameters": ..} or Qwen <tool_call> (JSON or XML)."""
    out = []
    t = text.strip()
    for m in re.finditer(r"<tool_call>\s*(.*?)\s*</tool_call>", t, re.S):
        body = m.group(1)
        fm = re.search(r"<function=([\w-]+)>(.*?)</function>", body, re.S)
        if fm:
            args = {}
            for pm in re.finditer(r"<parameter=([\w-]+)>\s*(.*?)\s*</parameter>", fm.group(2), re.S):
                v = pm.group(2)
                try:
                    v = json.loads(v)
                except Exception:
                    pass
                args[pm.group(1)] = v
            if fm.group(1) in names:
                out.append({"id": "t%d" % len(out), "type": "function", "function": {"name": fm.group(1), "arguments": json.dumps(args)}})
        else:
            try:
                o = json.loads(body)
                if o.get("name") in names:
                    out.append({"id": "t%d" % len(out), "type": "function",
                                "function": {"name": o["name"], "arguments": json.dumps(o.get("arguments") or o.get("parameters") or {})}})
            except Exception:
                pass
    if out:
        return out
    if t.startswith("{") or t.startswith("<|python_tag|>"):
        t2 = t.replace("<|python_tag|>", "").strip()
        try:
            o = json.loads(t2)
        except Exception:
            return []
        if isinstance(o, dict) and o.get("name") in names and isinstance(o.get("parameters", o.get("arguments", {})), dict):
            return [{"id": "t0", "type": "function", "function": {"name": o["name"], "arguments": json.dumps(o.get("parameters") or o.get("arguments") or {})}}]
    return []


def run_loop(cli, ex, system, user_msgs, tools, max_calls=5, max_tokens=None):
    msgs = [{"role": "system", "content": system}] + user_msgs
    calls, turns = [], []
    final = None
    nudged = False
    while True:
        if len(calls) >= max_calls and not nudged:
            # budget used: say so and ask for the final answer; no tools are offered on this last request
            msgs.append({"role": "user", "content": "Tool call limit reached. Do not call any more tools. Give your final answer now "
                                                    "using only the information above."})
            nudged = True
        msg, tim, wall = cli.chat(msgs, None if nudged else tools, tool_choice="auto", max_tokens=max_tokens)
        turns.append({"prompt_n": tim.get("prompt_n"), "prompt_ms": tim.get("prompt_ms"), "predicted_n": tim.get("predicted_n"),
                      "predicted_ms": tim.get("predicted_ms"), "wall_s": round(wall, 3), "finish": tim.get("finish_reason"),
                      "raw_mode": tim.get("raw_mode"), "text_tool_call": tim.get("text_tool_call", False)})
        if "error" in msg:
            final = {"error": msg["error"]}
            break
        tcs = msg.get("tool_calls") or []
        if tcs and len(calls) < max_calls:
            msgs.append({"role": "assistant", "content": msg.get("content") or "", "tool_calls": tcs})
            for t in tcs:
                name = t["function"]["name"]
                raw = t["function"].get("arguments") or "{}"
                try:
                    args = json.loads(raw) if isinstance(raw, str) else raw
                except Exception:
                    args = raw
                res = ex.run(name, args) if len(calls) < max_calls else {"error": "tool call limit reached"}
                calls.append({"name": name, "args": args, "result": res})
                msgs.append({"role": "tool", "tool_call_id": t.get("id") or name, "content": json.dumps(res)})
            continue
        final = {"content": msg.get("content") or "", "reasoning_content": msg.get("reasoning_content")}
        break
    return {"calls": calls, "final": final, "turns": turns, "messages": msgs}

