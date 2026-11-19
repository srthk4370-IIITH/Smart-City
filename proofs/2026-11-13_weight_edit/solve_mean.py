"""Rank-1 mean-key edit (ROME style) for think-gating; generalizes where the per-point MEMIT solve memorised (m2 eval: +0.01).
Per layer L: m_t = mean key after a tool result (gold no think), m_p = mean key after a user message.
k = C^-1 M (M^T C^-1 M)^-1 e1, M = [m_t, m_p]   ->  k.m_t = 1, k.m_p = 0, minimal C-norm (C = token key covariance + ridge)
dW = r k^T, r = -beta * s_L * u_L    (output change for key a: r * (k.a))
Prints the push on every training key (spread) so generalisation can be judged before GPU eval.
  python solve_mean.py KEYS.pt DIRS.npz OUT_PREFIX grid.json
"""
import json, sys, numpy as np, torch
K = torch.load(sys.argv[1]); U = np.load(sys.argv[2])["u"]; pre = sys.argv[3]; grid = json.load(open(sys.argv[4]))
meta = K["meta"]
T = [i for i, m in enumerate(meta) if m["after"] == "tool" and m["gold_think"] is False]
P = [i for i, m in enumerate(meta) if m["after"] == "user"]
PT = [i for i, m in enumerate(meta) if m["after"] == "user" and m["gold_think"]]
for g in grid:
    dws = {}
    for L in g["layers"]:
        X = K["keys"][L].double()
        C = K["C"][L].double() / K["nC"][L]
        C.diagonal().add_(g.get("ridge", 1e-2) * float(C.diagonal().mean()))
        M = torch.stack([X[T].mean(0), X[P].mean(0)], 1)            # 9216 x 2
        CiM = torch.linalg.solve(C, M)
        k = CiM @ torch.linalg.solve(M.T @ CiM, torch.tensor([1.0, 0.0], dtype=torch.float64))
        s = float(K["resid_norm"][L]); u = torch.tensor(U[L], dtype=torch.float64)
        r = -g["beta"] * s * u
        dW = torch.outer(r, k)
        pt, pp, ptk = X[T] @ k, X[P] @ k, X[PT] @ k
        q = lambda x: [round(float(np.percentile(x.numpy(), p)), 2) for p in (5, 50, 95)]
        print("%s L%d: k.a  after-tool p5/50/95 %s | after-user %s | user-think %s | |dW| %.3g" % (
            g["tag"], L, q(pt), q(pp), q(ptk), dW.norm()), flush=True)
        dws[L] = dW.float()
    torch.save({"cfg": g, "dW": dws}, "%s_dw_%s.pt" % (pre, g["tag"]))
