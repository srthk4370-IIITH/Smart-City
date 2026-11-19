"""Chat tool-header size in Qwen3.5 tokens: the system block the HF chat template renders for the tools (everything
before the system text, as backend/chat_header.txt), round-1 tools_v3.json["chat"] vs tools_v4.json["chat"].
  ~/venvs/rsn/bin/python measure_header.py [--model ~/models/qwen3.5-4b] -> ../data/header_tokens.json"""
import argparse
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
R1 = os.path.join(HERE, "..", "..", "2026-10-25_reasoner_final", "pipeline", "tools_v3.json")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=os.path.expanduser("~/models/qwen3.5-4b"))
    a = ap.parse_args()
    from transformers import AutoTokenizer
    tok = AutoTokenizer.from_pretrained(a.model)
    out = {"tokenizer": a.model}
    for name, path in (("round1_chat_9_tools", R1), ("v4_chat_15_tools", os.path.join(HERE, "tools_v4.json"))):
        tools = json.load(open(path, encoding="utf-8"))["chat"]
        txt = tok.apply_chat_template([{"role": "system", "content": "SYSTEMTEXT"}, {"role": "user", "content": "q"}],
                                      tools=tools, tokenize=False, enable_thinking=False)
        head = txt[:txt.index("SYSTEMTEXT")]
        out[name] = {"tokens": len(tok(head, add_special_tokens=False)["input_ids"]), "chars": len(head)}
        per = {}
        for t in tools:
            per[t["function"]["name"]] = len(tok("\n" + json.dumps(t, ensure_ascii=False), add_special_tokens=False)["input_ids"])
        out[name]["per_tool"] = per
    out["growth_tokens"] = out["v4_chat_15_tools"]["tokens"] - out["round1_chat_9_tools"]["tokens"]
    dev = os.path.join(HERE, "..", "..", "..", "Code", "smart-city-edge-agent", "app", "backend", "chat_header.txt")
    if os.path.exists(dev):
        out["device_chat_header_txt_tokens"] = len(tok(open(dev, encoding="utf-8").read(), add_special_tokens=False)["input_ids"])
    with open(os.path.join(HERE, "..", "data", "header_tokens.json"), "w") as f:
        json.dump(out, f, indent=1)
    print(json.dumps({k: (v if not isinstance(v, dict) else {kk: vv for kk, vv in v.items() if kk != "per_tool"}) for k, v in out.items()}))
    print("new tools:", {k: v for k, v in out["v4_chat_15_tools"]["per_tool"].items() if k not in out["round1_chat_9_tools"]["per_tool"]})


if __name__ == "__main__":
    main()
