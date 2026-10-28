"""Dataset v2 composition (aggregates only), QA checks, held-out sensors, HVAC role data, v1 dataset and source data."""
from _lib import *

S = __file__
T = "dataset_v2"
RV = PROOFS / "2026-10-17_retrain_v2"
HV = PROOFS / "2026-10-16_hvac_data"
MAN = RV / "dataset_manifest.json"
CHK = RV / "dataset_checks.json"
SPLITS = ["train", "dev", "test"]
ROLES = ["air_quality", "water", "power", "occupancy", "weather", "hvac"]


def by_split(field, title, id, unit="rows", role="ours", order=None, notes="", claim=None, chart=None):
    m = read_json(MAN)["splits"]
    keys = order or sorted({k for s in SPLITS for k in m[s][field]}, key=lambda k: -m["train"][field].get(k, 0))
    series = [ser(s, [pt(k, m[s][field].get(k, 0)) for k in keys], role if s == "train" else "alt") for s in SPLITS]
    return write(T, id, title, unit, series, [MAN, RV / "RESULTS.md", TRAIN / "RETRAIN_V2_SPEC.md"], S,
                 n=sum(m["train"][field].values()), chart=chart or {"type": "bar"}, notes=notes, claim=claim)


def composition():
    man = read_json(MAN)
    m = man["splits"]
    by_split("roles", "Rows per role and split (6 roles incl. the new HVAC agent)", "ds_roles", order=ROLES,
             claim=f"{m['train']['n']:,} train / {m['dev']['n']:,} dev / {m['test']['n']:,} test rows",
             notes=f"Duplicates dropped: train {m['train']['duplicates_dropped']}, dev {m['dev']['duplicates_dropped']}, "
                   f"test {m['test']['duplicates_dropped']}. sha256/16: train {m['train']['sha256_16']}, dev {m['dev']['sha256_16']}, test {m['test']['sha256_16']}.")
    by_split("families", "Case families (what each example teaches)", "ds_families",
             notes="event = one of the training patterns; routine/real_routine = normal routines that look like alarms (hard negatives); "
                   "old_shift/long_drift/recurring = what the 4 h v1 agent missed; fault = 7 sensor-fault kinds; compound = two shapes.")
    by_split("status", "Status labels", "ds_status", order=["normal", "warning", "critical", "sensor_fault"])
    by_split("fault_kind", "Sensor-fault kinds (status = sensor_fault)", "ds_fault_kind")
    win = sorted({int(k) for s in SPLITS for k in m[s]["window_n"]})
    write(T, "ds_window_lengths", "Window length of each example (5-min points; 48 = 4 h)", "rows",
          [ser(s, [pt(f"{w} ({w * 5 / 60:g} h)", m[s]["window_n"].get(str(w), 0)) for w in win], "ours" if s == "train" else "alt") for s in SPLITS],
          [MAN], S, n=m["train"]["n"], chart={"type": "bar"}, claim="21 window lengths from 2 h to 12 h (v1: 4 h only)")
    by_split("routine", "Routine hard negatives by kind (labelled normal)", "ds_routine")
    by_split("event_active", "event_active label", "ds_event_active", order=["True", "False"])
    by_split("confidence", "Confidence targets (calibrated from measured accuracy)", "ds_confidence",
             order=sorted({k for s in SPLITS for k in m[s]["confidence"]}, key=float), chart={"type": "bar", "x": "confidence"})
    pat = m["train"]["patterns"]
    write(T, "ds_patterns", "Train rows per role x pattern", "rows",
          [ser("train", [pt(k.split("/", 1)[1], v, role=k.split("/")[0]) for k, v in sorted(pat.items())], "ours")],
          [MAN, CHK], S, n=sum(pat.values()), chart={"type": "heatmap", "x": "pattern", "y": "role"})
    ck = read_json(CHK)["splits"]
    for key, id, title in (("age (readings since onset)", "ds_event_age", "Event age at the window end (readings since onset)"),
                           ("size (x noise)", "ds_event_size", "Event size in multiples of the sensor's noise")):
        cats = list(ck["train"]["balance"][key].keys())
        write(T, id, title, "rows", [ser(s, [pt(c, ck[s]["balance"][key].get(c, 0)) for c in cats], "ours" if s == "train" else "alt") for s in SPLITS],
              [CHK, TRAIN / "RETRAIN_V2_SPEC.md"], S, n=m["train"]["n"], chart={"type": "bar"},
              notes="Spec #6: onset uniform from 3 readings before the end to the window start, extra weight on 20-60 min. "
                    "Spec #11: size 1.5-12x noise; below ~3x the label stays normal (boundary examples).")
    tok = []
    for s in SPLITS:
        t = m[s]["tokens"]
        tok.append(ser(s, [pt("prompt mean", t["prompt"]["mean"], p95=t["prompt"]["p95"], max=t["prompt"]["max"]),
                           pt("completion mean", t["completion"]["mean"], p95=t["completion"]["p95"], max=t["completion"]["max"]),
                           pt("generated until 'action'", t["generated_until_action"]["mean"], p95=t["generated_until_action"]["p95"],
                              max=t["generated_until_action"]["max"])], "ours" if s == "train" else "alt"))
    write(T, "ds_tokens", "Token statistics (Llama 3.2 tokenizer)", "tokens", tok, [MAN], S, n=m["train"]["n"], chart={"type": "bar"},
          notes="Generation stops at the 'action' key (derived by the backend). Spec #13 target 55-60 tokens before the new fields.")
    bw = m["train"]["tokens"]["by_window"]
    write(T, "ds_tokens_by_window", "Prompt and generated tokens by window length (train)", "tokens",
          [ser("prompt mean", [pt(int(w), v["prompt"]["mean"], n=v["n"]) for w, v in sorted(bw.items(), key=lambda x: int(x[0]))], "ours"),
           ser("generated mean", [pt(int(w), v["gen"]["mean"], n=v["n"]) for w, v in sorted(bw.items(), key=lambda x: int(x[0]))], "alt")],
          [MAN], S, chart={"type": "line", "x": "window points"})
    ho = man["heldout_nodes"]
    write(T, "ds_heldout", "Held-out sensors (never seen in training) and test rows seen vs unseen", "count",
          [ser("held-out sensors per role", [pt(r, len(ho.get(r, []))) for r in ROLES], "ours"),
           ser("test rows", [pt(k, v) for k, v in m["test"]["seen"].items()], "alt", unit="rows")],
          [MAN, TRAIN / "RETRAIN_V2_SPEC.md"], S, n=sum(len(v) for v in ho.values()), chart={"type": "bar"},
          claim=f"{sum(len(v) for v in ho.values())} sensors held out entirely; {m['test']['seen'].get('unseen', 0) + m['test']['seen'].get('unseen_sepoct', 0)} test rows from them",
          notes="Spec #21: test months (Nov-Dec) plus ~15% of sensors per role never seen in training; report seen vs unseen. "
                "Weather: seen stations only (D8, stated limit). unseen_sepoct = held-out water sensors in Sep-Oct. Sensor IDs omitted here.")
    write(T, "ds_mix", "Sampling plan: family mix weights and per-role quotas", "weight",
          [ser("mix weight", [pt(k, v) for k, v in man["mix_weights"].items()], "ours"),
           ser("train quota per role", [pt(k, v) for k, v in man["quota"]["train"].items()], "alt", unit="rows")],
          [MAN], S, chart={"type": "bar"},
          notes=f"Generated in {man['generation_seconds']} s, seed {man['seed']}, config {man['config_hash']}.")


def qa():
    c = read_json(CHK)
    res = c["results"]
    write(T, "ds_qa_checks", "Automatic dataset checks: every hard check passes", "rows",
          [ser("pass", [pt(k, v["pass"]) for k, v in res.items()], "ours"), ser("fail", [pt(k, v["fail"]) for k, v in res.items()], "alt")],
          [CHK, RV / "dataset_checks.md"], S, n=max(v["pass"] for v in res.values()), chart={"type": "stackedBar"},
          claim=f"{len(res)} hard checks x 40,858 rows: 0 failures",
          notes="json, enums, observation count, evidence ids, numbers match the evidence, rebuild from the generator, v1 prompt "
                "equality at 48 points, leakage (no test windows in train), duplicates, amplitude, shape. A 60-sample private review "
                "page was also checked by hand (data/sft_v2/review.html, not published).",
          extra={"all_hard_pass": c["all_hard_pass"], "soft_flags": c["soft_flags"], "false_alarm_definition": c["false_alarm_definition"]})
    fa = c["false_alarm_label_rate"]["train"]
    write(T, "ds_label_alarm_rate", "How often a 'normal-looking' family is labelled not-normal (train)", "fraction",
          [ser("status != normal", [pt(k, **rate(v["not_normal"], v["n"])) for k, v in fa.items()], "ours")],
          [CHK], S, chart={"type": "bar"},
          notes="Routine families are labelled normal 100% of the time; boundary (small) events are mostly normal by design (D3: an "
                "alarm = status != normal).")


def hvac():
    rl = text(HV / "real_label_check.txt")
    m = re.search(r"real 4h labels \(non-faulty, non-ambiguous\) (\d+) (\{.*?\})", rl)
    labels = eval(m.group(2), {"__builtins__": {}})
    st = eval(re.search(r"real 4h status rates (\{.*?\})", rl).group(1), {"__builtins__": {}})
    inj = eval(re.search(r"injected ok (\{.*?\}) \{", rl).group(1), {"__builtins__": {}})
    write(T, "ds_hvac_real_labels", "HVAC role: what the rules call real 4 h windows of 87 indoor units (2025)", "windows",
          [ser("real windows", [pt(k, v) for k, v in labels.items()], "ours"),
           ser("status share", [pt(k, float(v.strip("%")) / 100) for k, v in st.items()], "alt", unit="fraction")],
          [HV / "real_label_check.txt", HV / "MANIFEST.md", HV / "realcheck.py", TRAIN / "v2/HVAC_DATA.md"], S, n=int(m.group(1)),
          chart={"type": "bar"}, claim="98.45% of real HVAC windows are normal: alarms must be taught by injection",
          notes="311,567 windows scanned, 29,393 ambiguous skipped. Faulty units (D11) become real fault examples.")
    write(T, "ds_hvac_injection", "HVAC: injected examples that passed the labeller, per pattern", "examples",
          [ser("injected ok", [pt(k, v) for k, v in inj.items()], "ours")], [HV / "real_label_check.txt", HV / "test_output.txt"], S,
          chart={"type": "bar"}, notes="All 8 HVAC unit tests pass (test_output.txt). Observation words: max 15, mean 10.6; check failures 0.")
    up = read_json(HV / "unit_profile_aggregates.json")["summary"]
    write(T, "ds_hvac_profile", "HVAC duty cycle: share of units running by hour of day (87 units, 2025)", "fraction",
          [ser("units on", [pt(h, v) for h, v in enumerate(up["hour_on"])], "ours")],
          [HV / "unit_profile_aggregates.json", HV / "prof_units.py"], S, n=up["units"], chart={"type": "line", "x": "hour"},
          notes=f"Weekday on-share {up['weekday_on']}, weekend {up['weekend_on']}; {up['n_runs']} compressor runs, median run "
                f"{up['runs_q']['0.5']} buckets. Aggregates only; no per-room series.")


def v1_and_source():
    write(T, "ds_v1_dataset", "v1 training data (2026-10-07): 5 roles x 1,296 examples", "rows",
          [ser("v1 train examples", [pt(r, 1296) for r in ROLES[:5]], "alt"),
           ser("v2 train rows", [pt(r, read_json(MAN)["splits"]["train"]["roles"].get(r, 0)) for r in ROLES], "ours")],
          [TRAIN / "results/agents_20261006_2101/plan.json", hb_section("2.7"), hb_section("2.36")], S, n=6480, chart={"type": "bar"},
          notes="v1 split is temporal only: train Jan-Aug, dev Sep-Oct, test Nov-Dec 2025, same sensors in every split; test is "
                "class-balanced (not natural prevalence); water test used only 31 calm base windows. v2 adds ~15% held-out sensors.")
    rows = [["SR-AC.csv", "HVAC (room AC units)", 11.5, 87], ["air_qulaity.csv", "outdoor air", 9.5, 10], ["SR-AQ.csv", "indoor air", 7.0, 12],
            ["SL.csv", "solar / LT panel power", 1.8, 9], ["WM-WF.csv", "water flow", 1.7, 25], ["EM.csv", "main energy meters", 1.2, 3],
            ["WN.csv", "wireless network", 0.9, 79], ["SR-EM.csv", "room energy", 0.7, 3], ["WM-WL.csv / WL.csv", "water tank level", 0.37, 9],
            ["SR-OC.csv", "occupancy", 0.3, 2], ["we.csv", "weather", 0.1, 2], ["WM_WD.csv", "water quality", 0.03, 9]]
    write(T, "ds_source_data", "Source data: IIIT-H campus sensors, 2025 (14 CSVs, 4.6 GB, ~37 M rows)", "million rows",
          [ser("rows (M)", [pt(r[1], r[2], file=r[0], nodes=r[3]) for r in rows], "ours")],
          [ROOT / "plan.md", hb_section("2.36")], S, chart={"type": "bar"},
          notes="Row counts per file only (no readings). Data stays private on the laptop. SR-OC occupancy/temp/RH columns are empty "
                "in the CSV; occupancy was extracted separately (extract_occupancy.py). Timestamps mix +00:00 and +05:30.")


def main():
    composition(); qa(); hvac(); v1_and_source()


if __name__ == "__main__":
    main()
