#!/bin/bash
# corpus-source sensitivity runs (same sim, corpus restricted)
D=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-30_spec_split
PY=/home/hp_srthk4370/venvs/rsn/bin/python
cd /tmp
CORPUS_SRC=gen_rsn_v1 TAG=_genonly $PY $D/sim.py | tail -2
CORPUS_SRC=board_live TAG=_boardonly $PY $D/sim.py | tail -2
CORPUS_SRC=gen_rsn_v1,board_live TAG=_norwh $PY $D/sim.py | tail -2
for t in _genonly _boardonly _norwh; do echo "== $t"; $PY $D/analyze.py $t | tail -12 | head -6; done
