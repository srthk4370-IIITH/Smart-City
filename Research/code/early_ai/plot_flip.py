import json, matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
d = json.load(open("Research/results/early_ai_v5.json"))
fig, ax = plt.subplots(figsize=(7, 4))
for sh, v in d["shapes"].items():
    ks = sorted(int(k) for k in v["by_k"] if v["by_k"][k].get("flip") is not None and int(k) < 8)
    ax.plot(ks, [v["by_k"][str(k)]["flip"] for k in ks], marker="o", label=sh)
ax.axhline(0.15, color="k", ls="--", lw=1, label="limit 0.15")
ax.set_xlabel("readings seen before the early AI run (k; the gate is k = 8)")
ax.set_ylabel("flip rate vs the k = 8 verdict")
ax.set_ylim(0, 1); ax.set_xticks([3,4,5,6,7]); ax.legend(ncol=4, fontsize=8); ax.set_title("Early AI: no shape stays under the flip limit")
fig.tight_layout(); fig.savefig("Research/figures/fig_early_ai_flip.png", dpi=150)
print("ok")
