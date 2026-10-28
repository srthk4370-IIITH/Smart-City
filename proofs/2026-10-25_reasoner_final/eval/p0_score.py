"""Score tags in eval/p0/results with the unchanged P0 scorer (weights 45/25/20/10, gates). py -3 -I p0_score.py tag [tag..]"""
import json, os, sys
HERE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "p0")
sys.path.insert(0, HERE)
import score
tags = sys.argv[1:]
s = score.main(tags, {t: 2.61 for t in tags}, {t: {} for t in tags})
for m in tags:
    v = s[m]
    print(m, "G1", v["G1"]["pass"], "G2", v["G2"]["verdict"], "R %.3f T %.3f U %.3f S %.3f total %.3f" % (
        v["reasoning"]["score"][0] or 0, v["tools"]["score"], v["understanding"]["score"], v["secondary"]["score"], v["weighted_total"] or 0))
