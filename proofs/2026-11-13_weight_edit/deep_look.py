"""Deeper neuron analysis from n1_profile.npz (CPU): specificity + harm/help candidates for dial / boost / rewire."""
import numpy as np, sys
Z = np.load(sys.argv[1]); mT, mU, llT = Z["mT"], Z["mU"], Z["ll_think"]; dW, mR, llR = Z["d_wrong"], Z["m_right"], Z["ll_trust"]
eps = 0.05
def show(title, idx, cols):
    print("##", title); print("L\ti\t" + "\t".join(c for c, _ in cols))
    for q in idx:
        L, i = divmod(int(q), mT.shape[1]); print("%d\t%d\t" % (L, i) + "\t".join("%.3f" % f[L, i] for _, f in cols))
# THINK. spec = |act after tool| relative to |act on hard user turns|
specT = np.abs(mT) / (np.abs(mU) + eps)
cT, cU = mT * llT, mU * llT                      # + = pushes </think> (good after tool)
harm = np.where(specT > 3, cT, 0).ravel()      # specific + pushes think after tool
show("THINK harm (specific, pushes think after tool): dial/flip", np.argsort(harm)[:20], [("act_T", mT), ("act_U", mU), ("ll", llT), ("contrib_T", cT), ("spec", specT)])
helpv = np.where(specT > 3, cT, 0).ravel()
show("THINK help (specific, already pushes close after tool): boost", np.argsort(-helpv)[:15], [("act_T", mT), ("act_U", mU), ("ll", llT), ("contrib_T", cT), ("spec", specT)])
rew = np.where((specT > 5) & (np.abs(mT) > 1.0), np.abs(mT), 0).ravel()   # strongly + specifically active after tool: rewire carriers
show("THINK rewire carriers (fire strongly + only after tool)", np.argsort(-rew)[:15], [("act_T", mT), ("act_U", mU), ("ll", llT), ("spec", specT)])
# TRUST. delta = change when the agent wrongly says normal; harm = delta * ll < 0 (pushes normal)
specR = np.abs(dW) / (np.abs(mR) + eps)
cD = dW * llR
show("TRUST harm (wrong claim shifts it toward 'normal')", np.argsort(cD.ravel())[:20], [("act_right", mR), ("delta", dW), ("ll", llR), ("contrib", cD), ("spec", specR)])
rewR = np.where(specR > 2, np.abs(dW), 0).ravel()
show("TRUST rewire carriers ('agent says normal' detectors: big delta, low base act)", np.argsort(-rewR)[:15], [("act_right", mR), ("delta", dW), ("ll", llR), ("spec", specR)])
print("total think push after tool from all neurons: %.2f | from specific (spec>3): %.2f" % (cT.sum(), np.where(specT > 3, cT, 0).sum()))
