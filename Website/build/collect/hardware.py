"""Hardware datasets: GPU (Adreno/OpenCL) bring-up, HTP (llama.cpp Hexagon) bring-up, placement grid,
thermals and memory on the QIDK."""
from _lib import *

S = __file__
T = "hardware"
GB = PROOFS / "2026-10-16_gpu_bringup"
HB_ = PROOFS / "2026-10-16_htp_bringup"
HG = PROOFS / "2026-10-16_hw_grid"

ROW = re.compile(r"^\|\s*(\d+)\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|\s*([\d.]+)\s*\|\s*([\d.]+)\s*\|\s*([\d.]+)\s*\|\s*([\d.]+)\s*\|\s*([\d.]+)\s*\|\s*([\d.]+)\s*\|")


def parse_ladder(path):
    steps, cur = {}, None
    for line in text(path).splitlines():
        m = re.match(r"\[[\d:]+\] (\d\d_\S+)\s+\(", line)
        if m:
            cur = m.group(1)
            steps[cur] = []
            continue
        m = re.match(r"\[[\d:]+\] (\d\d_\S+): rc=(\d+)", line)
        if m:
            steps.setdefault(m.group(1), [])
            continue
        m = ROW.match(line)
        if m and cur:
            pp, tg, b, nkv, tpp, spp, ttg, stg, tt, st = m.groups()
            steps[cur].append({"pp": int(pp), "tg": int(tg), "B": int(b), "t_pp": float(tpp), "s_pp": float(spp),
                               "t_tg": float(ttg), "s_tg": float(stg), "t": float(tt), "s": float(st)})
    return steps


def gpu():
    st = {}
    for p in (GB / "run3_gpu_only/ladder.log", GB / "run4_gpu_only_mc3fix/ladder.log", GB / "run5_gpu_only_opts/ladder.log"):
        for k, v in parse_ladder(p).items():
            if v:
                st[k] = v
    real = st["06_bb_real_kvu_np123468_mc3"]
    shared = st["07_bb_shared_prefix_mc3"]
    split = st["08_bb_split_kv_mc3"]
    write(T, "hw_gpu_batched", "GPU (Adreno 750, llama.cpp OpenCL): batched decode does not scale (600-token prompt, 80 tokens)",
          "tok/s",
          [ser("decode tok/s, all streams (unified KV)", [pt(str(r["B"]), r["s_tg"]) for r in real], "alt"),
           ser("decode tok/s, shared prefix", [pt(str(r["B"]), r["s_tg"]) for r in shared], "alt"),
           ser("decode tok/s, split KV", [pt(str(r["B"]), r["s_tg"]) for r in split], "alt"),
           ser("wall s per batch (unified KV)", [pt(str(r["B"]), r["t"]) for r in real], "ref", unit="s")],
          [GB / "run4_gpu_only_mc3fix/ladder.log", GB / "run5_gpu_only_opts/ladder.log", hb_section("2.37")], S,
          chart={"type": "line", "x": "parallel streams B"},
          claim="1 stream 16.7 tok/s; 8 streams together only 12.4 tok/s",
          notes="llama-batched-bench on the device's own weights repacked to Q4_0/Q8_0. The OpenCL matmuls do not batch. "
                "Prefill on GPU ~195 tok/s vs ~970 tok/s on HTP and ~1380 tok/s in Genie.")
    ren = {"bench_baseline": "baseline", "bench_dp4a": "dp4a", "bench_ubatch": "ubatch 128", "bench_ubatch (1)": "ubatch 256",
           "bench_ubatch (2)": "ubatch 1024", "bench_fa_on": "flash attention on"}
    b = {ren.get(k, k): v for k, v in parse_bench(GB / "run5_gpu_only_opts/ladder.log").items()}
    write(T, "hw_gpu_bench_knobs", "GPU llama-bench: prefill/decode with each knob", "tok/s",
          [ser("prefill pp600", [pt(k, v["pp600"]) for k, v in b.items() if "pp600" in v], "alt"),
           ser("decode tg80", [pt(k, v["tg80"]) for k, v in b.items() if "tg80" in v], "alt")],
          [GB / "run5_gpu_only_opts/ladder.log"], S, chart={"type": "bar"},
          notes="dp4a cut prefill to 64 tok/s; flash attention on cut decode to 7.5 tok/s; ubatch made no gain. None adopted.")
    # GPU bring-up reboots (run1/run2 rc=137 = killed)
    write(T, "hw_gpu_bringup_failures", "GPU bring-up: first runs killed (OOM), then the ladder fix", "count",
          [ser("ladder steps", [pt("run1 01_bb_tiny_np1", 137, note="rc=137 killed, 5771 MB available"),
                                pt("run2 01_bb_tiny_np1", 137, note="rc=137 killed after drop_caches"),
                                pt("run3 05_bb_real_kvu_np124_mc3", 134, note="rc=134 abort: OpenCL work-group bug"),
                                pt("run4 after mc3 patch", 0, note="rc=0")], "ref", unit="exit code")],
          [GB / "ladder.log", GB / "run2/ladder.log", GB / "run3_gpu_only/ladder.log", GB / "run4_gpu_only_mc3fix/ladder.log", hb_section("2.37")],
          S, notes="GPU (kgsl) and NPU buffers are unmovable and must fit in the 7.26 GB Normal zone; Genie alone holds ~3.1 GB. "
                   "Loading a second 3B on the GPU made the OOM killer pick system processes and Android rebooted. Fix: llama.cpp at "
                   "oom_score_adj 1000, drop_caches + compact_memory before each load, one rung at a time. No reboot since. "
                   "Work-group fix: app/htpd/patches/opencl_mc3_workgroup.patch.")


def parse_bench(path):
    out, cur = {}, None
    for line in text(path).splitlines():
        m = re.match(r"\[[\d:]+\] (\d\d_bench_\S+)\s+\(", line)
        if m:
            cur = m.group(1)[3:]
            out[cur] = {}
            continue
        m = re.search(r"\|\s*(pp600|tg80)\s*\|\s*([\d.]+) ± ([\d.]+)", line)
        if m and cur:
            key = m.group(1)
            if key in out[cur]:
                cur2 = f"{cur} ({len([k for k in out if k.startswith(cur)])})"
                out[cur2] = {}
                out[cur2][key] = float(m.group(2))
            else:
                out[cur][key] = float(m.group(2))
    return out


def htp():
    st = parse_ladder(HB_ / "ladder.log")
    pts_before, seenB = [], set()
    for k in ("02_htp_real_np1", "03_htp_real_np124", "04_htp_real_np8", "05_htp_real_np13"):
        for r in st.get(k, []):
            if r["B"] in seenB:
                continue
            seenB.add(r["B"])
            pts_before.append(pt(str(r["B"]), r["s_tg"], wall_s=r["t"], prefill_tok_s=r["s_pp"]))
    def tab(path):
        rs = []
        for line in text(path).splitlines():
            m = ROW.match(line)
            if m:
                g = m.groups()
                rs.append(pt(g[2], float(g[7]), wall_s=float(g[8]), prefill_tok_s=float(g[5])))
        return rs
    write(T, "hw_htp_batching", "NPU via llama.cpp Hexagon: batched decode before/after the per-stream flash-attention patch",
          "tok/s",
          [ser("before (FA on CPU)", pts_before, "alt"),
           ser("FA on HTP, KV unified", tab(HB_ / "real_fa_kvu.txt"), "alt"),
           ser("FA_STREAMS patch (shipped in htpd)", tab(HB_ / "real_fa_streams_patch.txt"), "ours")],
          [HB_ / "ladder.log", HB_ / "real_fa_kvu.txt", HB_ / "real_fa_streams_patch.txt", hb_section("2.37")], S,
          chart={"type": "line", "x": "parallel streams B"},
          claim="13 streams: 15 tok/s total before the patch, 75 tok/s after",
          why="Batching only pays if all agents share one sweep over the weights; this patch made that true on the NPU.",
          notes="600-token prompts, 80 tokens each. Wall time for 13 agents: 91.8 s before, 38.0 s FA-on-HTP, 23.8 s with the streams patch.")
    rows = []
    for line in text(HB_ / "knob_sweep.txt").splitlines():
        m = re.match(r"(\S+)=(\S+) :: \|\s*\d+\s*\|\s*\d+\s*\|\s*\d+\s*\|\s*\d+\s*\|\s*[\d.]+\s*\|\s*([\d.]+)\s*\|\s*[\d.]+\s*\|\s*([\d.]+)\s*\|\s*([\d.]+)", line)
        if m:
            rows.append(pt(f"{m.group(1).replace('GGML_HEXAGON_', '')}={m.group(2)}", float(m.group(4)), prefill_tok_s=float(m.group(3)), wall_s=float(m.group(5))))
    write(T, "hw_htp_knob_sweep", "HTP runtime knobs (13 streams, 600-token prompts, 32 tokens)", "tok/s",
          [ser("decode tok/s (all streams)", rows, "alt")], [HB_ / "knob_sweep.txt", hb_section("2.37")], S, chart={"type": "bar"},
          notes="burst vs sustained power mode +9%; FA_SELECT=1 and MM_SELECT=1 are 5-10x slower; others within noise. Defaults kept.")


def grid():
    samples = read_jsonl(HG / "samples.jsonl") + read_jsonl(HG / "htp/samples.jsonl")
    genie = {}
    for f in sorted(HG.glob("workload_INC-*.json")):
        d = read_json(f)
        genie[d["id"]] = {"wall_s": d["total_ms"] / 1000, "npu_calls": d["npu_calls"],
                          "agent_tokens_per_s": [round(a["tokens_per_s"], 2) for a in d["agents"] if a.get("tokens_per_s")]}
    nag = {}
    for s in samples:
        nag[s["incident"]] = s["n_agents"]
    for iid in genie:
        genie[iid]["n_agents"] = nag.get(iid)
    order = ["INC-0407", "INC-0392", "INC-0384", "INC-0116", "INC-0401"]
    label = {i: f'{nag.get(i, "?")} agents' + (" + synth" if i != "INC-0407" else "") for i in order}
    names = {"gpu_seq": ("GPU only, sequential (ctx 4096)", "alt"), "gpu_agents_only": ("GPU only, small footprint (ctx 1024)", "alt"),
             "htp_par13": ("llama.cpp HTP, 13 parallel streams", "alt"), "htp_seq": ("llama.cpp HTP, sequential", "alt")}
    series = [ser("Genie NPU (app, genied)", [pt(label[i], round(genie[i]["wall_s"], 2), npu_calls=genie[i]["npu_calls"]) for i in order if i in genie], "ours")]
    temps = []
    for pl, (nm, role) in names.items():
        pts, tp = [], []
        for i in order:
            for s in samples:
                if s["placement"] == pl and s["incident"] == i:
                    ok = sum(1 for c in s["calls"] if c.get("ok", None) is not False)
                    js = sum(1 for c in s["calls"] if c.get("json_ok") or c.get("json"))
                    pts.append(pt(label[i], round(s["wall_s"], 2), peak_c=s["peak_c"], calls=len(s["calls"])))
                    tp.append(pt(label[i], s["peak_c"]))
        series.append(ser(nm, pts, role))
        temps.append(ser(nm, tp, role))
    write(T, "hw_grid", "Placement grid: the same incidents on Genie NPU, GPU and llama.cpp HTP (wall time)", "s", series,
          [HG / "samples.jsonl", HG / "htp/samples.jsonl", HG / "log.txt", HG / "htp/log.txt", HG / "manifest.json", HG / "htp/manifest.json"]
          + [HG / f"workload_{i}.json" for i in order], S, chart={"type": "bar", "x": "incident size"},
          claim="GPU-only is slower than the NPU at every incident size",
          why="The evaluators asked for GPU only, NPU only and hybrid; the data decides.",
          notes="1 rep per cell, board cooled between cells. Genie times are the original app incidents (workload_*.json total_ms). "
                "GPU ctx-4096 runs produced no valid JSON (json 0/n in log.txt); the ctx-1024 footprint run did (4/4, 8/8). "
                "HANDBOOK: ~8.4 s per agent on GPU, 82% agreement with Genie. Hybrid placements (agents on GPU + synth on NPU) were "
                "slower too (HANDBOOK 2.37).",
          extra={"genie_reference": genie})
    agr = []
    for pl, (nm, role) in names.items():
        f = {"pattern": [0, 0], "status": [0, 0], "likely_cause": [0, 0], "json": [0, 0]}
        for sm in samples:
            if sm["placement"] != pl:
                continue
            for c in sm["calls"]:
                if c.get("kind") != "agent":
                    continue
                a = c.get("agree_npu") or {}
                f["json"][1] += 1
                f["json"][0] += bool(a.get("json_ok"))
                for key in ("pattern", "status", "likely_cause"):
                    if key in a:
                        f[key][1] += 1
                        f[key][0] += bool(a[key])
        agr.append(ser(nm, [pt(k if k != "json" else "valid JSON", **rate(v[0], v[1])) for k, v in f.items() if v[1]], role))
    write(T, "hw_grid_agreement", "Do GPU/HTP answers agree with the Genie NPU answers? (agent calls, same prompts)", "fraction",
          agr, [HG / "samples.jsonl", HG / "htp/samples.jsonl"], S, chart={"type": "bar"},
          notes="Agreement with the Genie answer for the same agent prompt (not accuracy vs ground truth). GPU at ctx 4096 "
                "produced no valid JSON. HANDBOOK 2.37 quotes 82% GPU agreement from a wider check; the saved grid rows give the "
                "values shown here (12 GPU agent calls).")
    write(T, "hw_grid_peak_temp", "Placement grid: peak board temperature per run", "C", temps,
          [HG / "samples.jsonl", HG / "htp/samples.jsonl"], S, chart={"type": "bar"},
          notes="GPU runs peaked at 87-96 C; HTP runs 77-95 C.")


def thermal_mem():
    write(T, "hw_board_thermal", "QIDK board temperatures (measured)", "C",
          [ser("measured", [pt("idle, any dashboard tab", 50), pt("rest after 3 incidents (CPU)", 39), pt("right after inference", 66),
                            pt("idle, DeerFlow UI (before power fix)", 75), pt("idle, after UI power fix", 43),
                            pt("genied poll busy-wait (before fix)", 94), pt("13-agent chaos, before pacing", 94),
                            pt("chaos with thermal pacing (Genie)", 90), pt("htpd chaos peaks", 96)], "ref")],
          [hb_section("2.30"), hb_section("2.35"), hb_section("2.37"), PROOFS / "2026-10-16_htpd_v6_app_stress_tail.log"], S,
          chart={"type": "bar"},
          notes="'right after inference' is the midpoint of 63-69 C. Guard: pause above 88 C NPU / 60 C skin; before each NPU call "
                "at >= 88 C the runner waits up to 15 s for 82 C. Use a heatsink/fan for the demo and the field.")
    write(T, "hw_memory", "Memory on the QIDK", "MB",
          [ser("resident", [pt("Genie session (one 3B)", 3700), pt("Genie unmovable share of Normal zone", 3100),
                            pt("edge-agent backend (24 min stress)", 15), pt("genied daemon (24 min stress)", 81),
                            pt("genied with the ctx-4096 window", 237)], "ref")],
          [hb_section("5"), hb_section("2.35"), hb_section("2.37"), ROOT / "ppt.md"], S, chart={"type": "bar"},
          notes="Normal zone 7.26 GB. Two full models cannot be resident: loading the base 3B beside genied rebooted the board "
                "with 5.8 GB free (2.27). Soak: backend 24-27 MB, daemon 77 MB, no growth.")
    write(T, "hw_ui_cpu", "The dashboard was the heater: app + WebView CPU", "% of one core",
          [ser("before", [pt("idle (DeerFlow redesign)", 220), pt("incident sheet open", 185)], "alt"),
           ser("after", [pt("idle (DeerFlow redesign)", 8), pt("incident sheet open", 10)], "ours")],
          [hb_section("2.35"), ROOT / "ppt.md"], S, chart={"type": "bar"}, claim="220% -> 5-11% CPU; board 75 C -> 43 C idle",
          notes="'after' idle is the midpoint of 5-11%. Cause: 22 px backdrop blurs re-rasterised under 60 fps infinite animations.")


def main():
    gpu(); htp(); grid(); thermal_mem()


if __name__ == "__main__":
    main()
