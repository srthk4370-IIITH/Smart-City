import json, sys
from transformers import AutoTokenizer
tools_path, app9, out = sys.argv[1:4]
tools = json.load(open(tools_path, encoding="utf-8"))
res = {}
for model in ["qwen3.5-2b", "qwen3.5-4b"]:
    tok = AutoTokenizer.from_pretrained("/home/" + __import__("getpass").getuser() + "/models/" + model)
    for key in ("chat", "chat9"):
        for think in (False, True):
            txt = tok.apply_chat_template([{"role": "system", "content": "SYSTEMTEXT"}, {"role": "user", "content": "q"}],
                                          tools=tools[key], tokenize=False, enable_thinking=think)
            res[(model, key, think)] = txt[:txt.index("SYSTEMTEXT")]
vals = set(v for k, v in res.items() if k[1] == "chat")
print("distinct 15 renders:", len(vals))
print("chat9 == app header:", all(v == open(app9, encoding="utf-8", newline="").read() for k, v in res.items() if k[1] == "chat9"))
open(out, "w", encoding="utf-8", newline="").write(res[("qwen3.5-2b", "chat", True)])
print(len(tools["chat"]), [t["function"]["name"] for t in tools["chat"]])
