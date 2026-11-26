"""env_setup.py: import path + app-data setup shared by the paper scripts (runs under ~/venvs/rsn/bin/python in WSL)."""
import os, sys, pathlib
Q = "/mnt/c/Users/hp/Desktop/qidk"
PAPER = Q + "/proofs/2026-11-26_paper"
for p in (Q + "/proofs/2026-11-12_topup_r4/tools", Q + "/proofs/2026-11-13_v3_data/rsn", Q + "/proofs/2026-11-13_v3_data/core",
          Q + "/proofs/2026-11-13_v3_data/agt_v3", Q + "/proofs/2026-10-29_rsn_v3/pipeline"):
    if p not in sys.path:
        sys.path.insert(0, p)
import sitegraph as SG  # noqa: E402
# app/device/data was removed from the working tree in the 2026-11-19 snapshot; the files are restored from git into _appdata
SG.APPDATA = pathlib.Path(PAPER + "/_appdata")
import gen_inc_v4 as G  # noqa: E402
import fmt_v4 as FM  # noqa: E402
import cards as CD  # noqa: E402
import evidence as EV  # noqa: E402
M, L, G2 = G.M, G.L, G.G2
