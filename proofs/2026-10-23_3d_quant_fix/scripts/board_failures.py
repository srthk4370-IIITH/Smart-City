"""Where the board's invalid answers sit: batch index, stream slot, thermal pacing state; across all v2/3d board runs."""
import json, pathlib
P = pathlib.Path(__file__).resolve().parents[1]; REPO = P.parents[1]
RUNS = {"v2_1020": "proofs/2026-10-20_v2_post/device/host400", "v2t_1021": "proofs/2026-10-21_v2t_device/host400",
        "v2_1021k8": "proofs/2026-10-21_v2_confirm/host400_k8", "v2_1023app": "proofs/2026-10-23_app_ab_v2_vs_3d/v2/host400",
        "3d_1023app": "proofs/2026-10-23_app_ab_v2_vs_3d/v2t3d/host400"}
host = {json.loads(l)["id"]: json.loads(l) for l in open(P / "post_diag/eval/3d_q4_0_deployed/samples.jsonl", encoding="utf-8")}
out = {}
for k, v in RUNS.items():
    rows = [json.loads(l) for l in open(REPO / v / "samples.jsonl", encoding="utf-8")]
    bs = rows[0].get("batch_size", 8)
    fails = [{"row": i, "id": r["id"], "batch": i // bs, "slot": i % bs, "stop": r.get("stop"), "board_c_before": r.get("board_c_before"),
              "text_tail": r["text"][-60:], "host_3d_q4_0_json_ok": host.get(r["id"], {}).get("json"), "host_3d_q4_0_pattern_ok": host.get(r["id"], {}).get("pattern")}
             for i, r in enumerate(rows) if not r["json"]]
    paced = [r for r in rows if r.get("board_c_before", 0) != -1]
    out[k] = {"n": len(rows), "invalid": len(fails), "batches_with_invalid": sorted({f["batch"] for f in fails}),
              "rows_thermal_unpaced(board_c=-1)": len(rows) - len(paced), "invalid_in_unpaced": sum(f["board_c_before"] == -1 for f in fails), "failures": fails}
    print(k, out[k]["invalid"], "invalid; batches", out[k]["batches_with_invalid"], "slots", [f["slot"] for f in fails], "unpaced rows", out[k]["rows_thermal_unpaced(board_c=-1)"])
(P / "board_failures.json").write_text(json.dumps(out, indent=1))
