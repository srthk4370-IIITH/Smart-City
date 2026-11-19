"""Exact 'close the think block' direction in the final residual (CPU): mean over after-tool decision points of
d/dh log-odds(P(</think>) + P(newline)), through the final RMSNorm + tied unembedding. Uses saved hidden states (fit.npz, L31 out)."""
import json, numpy as np, torch, glob, os
from safetensors import safe_open
B = os.path.expanduser("~/models/qwen3.5-4b"); W = os.path.expanduser("~/we_work")
idx = json.load(open(B + "/model.safetensors.index.json"))["weight_map"]
def get(name):
    k = [x for x in idx if x.endswith(name) and "visual" not in x and "mtp" not in x][0]
    with safe_open(B + "/" + idx[k], "pt") as f:
        return f.get_tensor(k)
WU = get("embed_tokens.weight").float(); g = get("language_model.norm.weight").float()
from transformers import AutoTokenizer
tok = AutoTokenizer.from_pretrained(B)
C = [tok.convert_tokens_to_ids("</think>"), tok.encode("\n", add_special_tokens=False)[0]]
R = [json.loads(l) for l in open(W + "/fit.jsonl")]; H = np.load(W + "/fit.npz")["H"][:, 31].astype(np.float32)
T = [i for i, r in enumerate(R) if r["after"] == "tool" and r["gold_think"] is False]
U = [i for i, r in enumerate(R) if r["gold_think"]]
eps = 1e-6
def grad_at(h):
    h = torch.tensor(h, requires_grad=True)
    x = h / torch.sqrt((h * h).mean() + eps) * g                # plain RMSNorm gain (matches measured log-odds better: corr .70 vs .27)
    z = WU @ x; lp = torch.log_softmax(z, -1)
    pc = torch.logsumexp(lp[C], 0); lo = pc - torch.log1p(-torch.exp(pc).clamp(max=1 - 1e-6))
    lo.backward(); return h.grad.numpy(), float(lo)
import sys
MODE = sys.argv[1] if len(sys.argv) > 1 else "offset"
def lo_only(h, mode):
    h = torch.tensor(h); x = h / torch.sqrt((h * h).mean() + eps) * ((1 + g) if mode == "offset" else g)
    lp = torch.log_softmax(WU @ x, -1); pc = torch.logsumexp(lp[C], 0); return float(pc - torch.log1p(-torch.exp(pc).clamp(max=1 - 1e-6)))
meas = [np.log(max(R[i]["p_close"], 1e-9)) - np.log(max(1 - R[i]["p_close"], 1e-9)) for i in T[:30]]
for mode in ("offset", "plain"):
    est = [lo_only(H[i], mode) for i in T[:30]]
    print(mode, "corr %.3f, median est %.2f vs measured %.2f" % (np.corrcoef(est, meas)[0, 1], np.median(est), np.median(meas)))
if MODE == "check":
    raise SystemExit
gs, lo_t = [], []
for i in T[:120]:
    gr, lo = grad_at(H[i]); gs.append(gr); lo_t.append(lo)
d = np.mean(gs, 0)
lo_u = [grad_at(H[i])[1] for i in U[:40]]
np.save(W + "/dir_close_grad.npy", d)
cos = [float(np.dot(x, d) / (np.linalg.norm(x) * np.linalg.norm(d))) for x in gs]
print("T log-odds median %.2f | U median %.2f | |d| %.4f | cos(per-point grad, mean) p10/p50 %.2f/%.2f" % (
    np.median(lo_t), np.median(lo_u), np.linalg.norm(d), np.percentile(cos, 10), np.median(cos)))
