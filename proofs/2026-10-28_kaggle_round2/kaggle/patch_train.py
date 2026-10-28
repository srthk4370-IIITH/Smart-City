"""Write train_rsn_kaggle.py from the unchanged train_rsn.py: Kaggle paths, fp16+GradScaler on GPUs without bf16 (T4/P100),
no laptop heartbeat. python patch_train.py <train_rsn.py> <out.py> <ROOT> <BASE>"""
import sys
src, out, root, base = sys.argv[1:5]
s = open(src, encoding="utf-8").read()
R = [('ROOT = "/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-25_reasoner_final"', 'ROOT = %r' % root),
     ('M = os.path.expanduser("~/models/qwen3.5-4b")', 'M = %r\nDT = torch.bfloat16 if torch.cuda.get_device_capability(0)[0] >= 8 else torch.float16\n'
      'SC = torch.amp.GradScaler("cuda", enabled=(DT == torch.float16))' % base),
     ('MQ = os.path.expanduser("~/models/qwen3.5-4b-nf4")', 'MQ = "/nonexistent-nf4"'),
     ("(l / max(1, n) / a.accum).backward()", "SC.scale(l / max(1, n) / a.accum).backward()"),
     ("        torch.nn.utils.clip_grad_norm_(", "        SC.unscale_(opt)\n        torch.nn.utils.clip_grad_norm_("),
     ("        opt.step()\n", "        SC.step(opt)\n        SC.update()\n"),
     ("torch.bfloat16", "DT")]
for a, b in R:
    assert a in s, "patch anchor missing: " + a[:60]
    s = s.replace(a, b)
s = s.replace("DT = DT if", "DT = torch.bfloat16 if")       # undo the global replace inside the DT definition
open(out, "w", encoding="utf-8").write(s)
print("patched ->", out)
