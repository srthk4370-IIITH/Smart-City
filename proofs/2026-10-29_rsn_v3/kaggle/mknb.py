"""rsn3_kaggle.py -> rsn3_kaggle.ipynb (cells split at '# %%'; '# %% [markdown]' cells become markdown), same notebook
metadata as round 2 (T4, Internet on). python3 mknb.py [src.py] [out.ipynb]; also checks that the .py compiles."""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
src = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "rsn3_kaggle.py")
out = sys.argv[2] if len(sys.argv) > 2 else os.path.join(HERE, "rsn3_kaggle.ipynb")
text = open(src, encoding="utf-8").read()
compile(text, src, "exec")
cells, cur, kind = [], [], None


def flush():
    if kind is None:
        return
    lines = cur[:]
    while lines and not lines[-1].strip():
        lines.pop()
    if kind == "markdown":
        lines = [l[2:] if l.startswith("# ") else l.lstrip("#") for l in lines]
        cells.append({"cell_type": "markdown", "metadata": {}, "source": [l + "\n" for l in lines[:-1]] + lines[-1:]})
    else:
        cells.append({"cell_type": "code", "metadata": {}, "execution_count": None, "outputs": [],
                      "source": [l + "\n" for l in lines[:-1]] + lines[-1:]})


for line in text.split("\n"):
    if line.startswith("# %%"):
        flush()
        kind = "markdown" if "[markdown]" in line else "code"
        rest = line[4:].replace("[markdown]", "").strip()
        cur = ["# " + rest] if (rest and kind == "code") else []
        continue
    cur.append(line)
flush()
nb = {"cells": cells, "metadata": {"kernelspec": {"name": "python3", "display_name": "Python 3", "language": "python"},
                                   "language_info": {"name": "python"},
                                   "kaggle": {"accelerator": "nvidiaTeslaT4", "isInternetEnabled": True, "isGpuEnabled": True}},
      "nbformat": 4, "nbformat_minor": 4}
json.dump(nb, open(out, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
# round trip: the code cells joined must compile and equal the .py code (minus markers)
code = "\n".join("".join(c["source"]) for c in cells if c["cell_type"] == "code")
compile(code, out, "exec")
print("notebook: %d cells (%d code) -> %s" % (len(cells), sum(c["cell_type"] == "code" for c in cells), out))
