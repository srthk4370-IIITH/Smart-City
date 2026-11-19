"""check_data_topup.py TRAIN GENDEV CALIB_STATS GEN_N OUT_DIR : check_data.py (what may leave the laptop) with ONE explicit exception.
EXCEPTION (logged, this dataset only): the owner approved real windows on Kaggle as a PRIVATE dataset for the agt_v3 top-up.
Real rows (source real_sft_v2 / real_topup2 / real_rw5, synthetic=false) are accepted ONLY IF all hold:
  - REAL_APPROVED.json (env REAL_APPROVED, default next to this file) names dataset agt3-topup-data, private=true, and pins the md5 of
    TRAIN and GENDEV: any change of the data invalidates the approval;
  - the number of real rows equals the approved count; sources are in the approved list; heldout / campus sources stay refused;
  - no real row id or (node, end_epoch) is in the local REAL VAL selection set (approval['local_val_sel']);
  - synthetic rows still pass the original provenance check (rows.provenance_problem).
Every use is appended to REAL_EXCEPTION.log (next to this file) and written into data_report.json. All other checks as check_data.py.
exit 0 ok | 1 refused."""
import collections
import datetime
import hashlib
import json
import os
import re
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.environ.get("AGT_DIR", "/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-13_v3_train/agt"), "kaggle"))
import rows as RW  # noqa: E402

train, gendev, calib, gen_n, out = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4]), sys.argv[5]
APPR = os.environ.get("REAL_APPROVED", os.path.join(HERE, "REAL_APPROVED.json"))
BAD_NAME = re.compile(r"real|heldout|held_out|campus", re.I)
BAD_KEY = re.compile(r"^(samples?|windows?|series|rows?|values|readings|raw)$", re.I)


def refuse(m):
    print("REFUSED: " + m)
    sys.exit(1)


def md5(p):
    return hashlib.md5(open(p, "rb").read()).hexdigest()


for p in (train, gendev, calib, APPR):
    if not os.path.exists(p):
        refuse("missing " + p)
    if BAD_NAME.search(os.path.basename(p)) and p != APPR:
        refuse("file name suggests real data: " + p)
ap = json.load(open(APPR))
if ap.get("dataset_slug") != os.environ.get("DATA_SLUG", "agt3-topup-data") or ap.get("private") is not True:
    refuse("approval is not for this dataset / not private")
if gen_n != ap["n_real_gendev"]:
    refuse("GEN_N %d != approved real gen-dev rows %d" % (gen_n, ap["n_real_gendev"]))
if md5(train) != ap["train_md5"] or md5(gendev) != ap["gendev_md5"]:
    refuse("train/gendev md5 differs from the approved ones: the exception does not apply")
vsel = {}
if os.path.exists(ap["local_val_sel"]):
    for r in RW.read_jsonl(ap["local_val_sel"]):
        vsel[r["id"]] = (r.get("node"), r.get("end_epoch"))
else:
    refuse("local REAL VAL selection set missing: cannot prove it stays local (" + ap["local_val_sel"] + ")")
vkeys = set(vsel.values())
rep, ids, n_real_seen = {}, {}, 0
for name, p, lim in (("train", train, None), ("gendev", gendev, gen_n)):
    raw = RW.read_jsonl(p)[:lim] if lim else RW.read_jsonl(p)
    seen, fam, role, st = set(), collections.Counter(), collections.Counter(), collections.Counter()
    nreal = 0
    for r in raw:
        src = str(r.get("source", "synthetic")).lower()
        if r.get("synthetic") is False and src in ap["allowed_sources"]:
            nreal += 1
            if r["id"] in vsel or (r.get("node"), r.get("end_epoch")) in vkeys:
                refuse("%s real row %s is in the local REAL VAL selection set" % (name, r["id"]))
        else:
            bad = RW.provenance_problem(r, name)
            if bad:
                refuse(bad)
        try:
            n = RW.norm(r)
        except Exception as e:  # noqa: BLE001
            refuse("%s: %s" % (name, e))
        if n["id"] in seen:
            refuse("%s: duplicate id %s" % (name, n["id"]))
        seen.add(n["id"])
        fam[n["family"]] += 1
        role[n["role"]] += 1
        st[RW.fields(n["gold"])["status"]] += 1
    n_real_seen += nreal
    ids[name] = seen
    rep[name] = {"n": len(raw), "real": nreal, "family": dict(fam), "role": dict(role), "status": dict(st)}
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, name + ".jsonl"), "w", encoding="utf-8", newline="\n") as f:
        for r in raw:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
if rep["train"]["real"] != ap["n_real_train"] or rep["gendev"]["real"] != ap["n_real_gendev"]:
    refuse("real row counts %d/%d != approved %d/%d" % (rep["train"]["real"], rep["gendev"]["real"], ap["n_real_train"], ap["n_real_gendev"]))
ov = ids["train"] & ids["gendev"]
if ov:
    refuse("%d ids in both train and gen-dev (e.g. %s)" % (len(ov), sorted(ov)[:3]))
c = json.load(open(calib))


def walk(x, path):
    if isinstance(x, dict):
        for k, v in x.items():
            if BAD_KEY.match(str(k)) and isinstance(v, (list, dict)) and len(v) > 50:
                refuse("calib_stats key %s/%s looks like per-sample data" % (path, k))
            walk(v, path + "/" + str(k))
    elif isinstance(x, list):
        if len(x) > 400:
            refuse("calib_stats list %s has %d entries (> 400: not an aggregate)" % (path, len(x)))
        for i, v in enumerate(x):
            walk(v, "%s[%d]" % (path, i))


walk(c, "")
shutil.copy(calib, os.path.join(out, "calib_stats.json"))
rep["real_exception"] = {"dataset": ap["dataset_slug"], "approval": ap["approval"], "real_train": rep["train"]["real"],
                         "real_gendev": rep["gendev"]["real"], "train_md5": ap["train_md5"]}
json.dump(rep, open(os.path.join(out, "data_report.json"), "w", newline="\n"), indent=1)
with open(os.environ.get("REAL_EXCEPTION_LOG", os.path.join(HERE, "REAL_EXCEPTION.log")), "a", newline="\n") as f:
    f.write("%s real-rows exception USED for %s: %d train + %d gen-dev real rows, train md5 %s; %s\n" % (
        datetime.datetime.now().isoformat(timespec="seconds"), ap["dataset_slug"], rep["train"]["real"], rep["gendev"]["real"],
        ap["train_md5"], ap["approval"]))
print(json.dumps({k: v["n"] for k, v in rep.items() if k in ("train", "gendev")}), "REAL EXCEPTION applied (logged)")
