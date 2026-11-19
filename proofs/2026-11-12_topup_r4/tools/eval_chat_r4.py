"""Chat eval of test_chat_r4.jsonl / dev_gen_chat.jsonl: exactly post/chat_r3_eval.py --mode r3test (r3 app prompt, adaptive
think, 21-tool header, verify_chat), but every tool runs on the r4 store (build/store_r4) the records were built on.
  ~/venvs/rsn/bin/python eval_chat_r4.py --port 18098 --think 1 --out OUT.jsonl [--records ../data/final/test_chat_r4.jsonl]
then: python3 score_r4.py chat --out OUT.jsonl
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
QIDK = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, os.path.join(QIDK, "proofs", "2026-11-06_4b_local", "post"))
sys.path.insert(0, os.path.join(QIDK, "proofs", "2026-11-06_4b_local", "tools"))
import tools_r3_impl as TR  # noqa: E402
import chat_r3_eval as CE  # noqa: E402

STORE = os.path.join(HERE, "..", "build", "store_r4")
d = list(TR.ToolsR3.__init__.__defaults__)          # (fog, last_sync, fog_path, dev_path, kb_path)
d[2], d[3] = os.path.join(STORE, "fog_store_r4.sqlite"), os.path.join(STORE, "device_store_r4.sqlite")
TR.ToolsR3.__init__.__defaults__ = tuple(d)
if "--records" not in sys.argv:
    sys.argv += ["--records", os.path.join(HERE, "..", "data", "final", "test_chat_r4.jsonl")]
if "--mode" not in sys.argv:
    sys.argv += ["--mode", "r3test"]
CE.main()
