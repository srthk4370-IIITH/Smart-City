# rsn_ft STRICT gate: dry_cand vs r3-2800 -> **FAIL**

Rules: rsn_ft/README.md "Strict gate" + V3_DESIGN.md §5.4 (2026-11-13). All hard checks must hold, else r3-2800 stays. Within noise = >= r3-2800 - max(0.01, 1 item). Q4_0 on the host GPU (llama-cuda b11815 = board numerics). Candidate GGUF: `/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-13_v3_train/rsn_ft/post/test/dry_20261113_084633/fake_cand_q4_0.gguf`.

48 hard checks, 6 failed.

Missing / not yet run: test_taxonomy: no chain_direct items scored; test_taxonomy: no three_way items scored; test_fog online: no common items; test_fog offline: no common items; test_fog timeout: no common items

| group | suite | metric | candidate | r3-2800 / threshold | rule | ok |
|---|---|---|---|---|---|---|
| H1 19 checks | rwh | severity | 0.333 | 1.0 | >= r3-2800 - 0.333 | **NO** |
| H1 19 checks | rwh | label | 1.0 | 1.0 | >= r3-2800 - 0.333 | yes |
| H1 19 checks | rwh | check_recall | 1.0 | 1.0 | >= r3-2800 - 0.500 | yes |
| H1 19 checks | rwh | check_prec | 1.0 | 1.0 | >= r3-2800 - 0.500 | yes |
| H1 19 checks | rwh | req | 1.0 | 1.0 | >= r3-2800 - 0.333 | yes |
| H1 19 checks | rwh | schema_err | 0.0 | 0.0 | <= r3-2800 + 0.333 | yes |
| H1 19 checks | rwh2 | severity | 0.333 | 1.0 | >= r3-2800 - 0.333 | **NO** |
| H1 19 checks | rwh2 | label | 1.0 | 1.0 | >= r3-2800 - 0.333 | yes |
| H1 19 checks | rwh2 | check_recall | 1.0 | 1.0 | >= r3-2800 - 1.000 | yes |
| H1 19 checks | rwh2 | check_prec | 1.0 | 1.0 | >= r3-2800 - 1.000 | yes |
| H1 19 checks | rwh2 | req | 1.0 | 1.0 | >= r3-2800 - 0.333 | yes |
| H1 19 checks | rwh2 | schema_err | 0.0 | 0.0 | <= r3-2800 + 0.333 | yes |
| H1 19 checks | dev | severity | 1.0 | 1.0 | >= r3-2800 - 0.333 | yes |
| H1 19 checks | dev | label | 1.0 | 1.0 | >= r3-2800 - 0.333 | yes |
| H1 19 checks | dev | check_recall | None | None | >= r3-2800 - 1.000 | yes |
| H1 19 checks | dev | check_prec | None | None | >= r3-2800 - 1.000 | yes |
| H1 19 checks | dev | req | 1.0 | 1.0 | >= r3-2800 - 0.333 | yes |
| H1 19 checks | dev | schema_err | 0.0 | 0.0 | <= r3-2800 + 0.333 | yes |
| H1 19 checks | chatdev3 | pass_rate | 0.333 | 0.813 | >= r3-2800 - 0.010 | **NO** |
| H2 r3 test slices | chat_test_r3 (minus ambiguous) | fog=online (n 1) | 1.0 | 1.0 | >= r3-2800 - 1.000 | yes |
| H2 r3 test slices | chat_test_r3 (minus ambiguous) | fog=offline (n 2) | 1.0 | 0.5 | >= r3-2800 - 0.500 | yes |
| H2 r3 test slices | incidents_test_r2 | severity | 1.0 | 1.0 | >= r3-2800 - 0.333 | yes |
| H2 r3 test slices | incidents_test_r2 | label | 1.0 | 1.0 | >= r3-2800 - 0.333 | yes |
| H2 r3 test slices | incidents_test_r2 | check_recall | 1.0 | 1.0 | >= r3-2800 - 0.333 | yes |
| H2 r3 test slices | incidents_test_r2 | check_prec | 1.0 | 1.0 | >= r3-2800 - 0.333 | yes |
| H2 r3 test slices | incidents_test_r2 | req | 1.0 | 0.667 | >= r3-2800 - 0.333 | yes |
| H2 r3 test slices | incidents_test_r2 | schema_err | 0.0 | 0.0 | <= r3-2800 + 0.333 | yes |
| H3 r4 tests | test_inc_r4 | item score (n 3) | 0.7111 | 0.7111 | >= r3-2800 - 1 item (0.3333) | yes |
| H3 r4 tests | test_inc_r4 | type=chain_direct (n 1) | 0.6667 | 0.6667 | sum of item diffs >= -1 (is 0.00) | yes |
| H3 r4 tests | test_inc_r4 | type=pair_relation (n 1) | 0.6667 | 0.6667 | sum of item diffs >= -1 (is 0.00) | yes |
| H3 r4 tests | test_inc_r4 | type=transitive (n 1) | 0.8 | 0.8 | sum of item diffs >= -1 (is 0.00) | yes |
| H3 r4 tests | test_chat_r4 | pass (n 3) | 1.0 | 1.0 | >= r3-2800 - 1 item (0.3333) | yes |
| H3 r4 tests | test_chat_r4 | type=pair_relation (n 1) | 1.0 | 1.0 | sum of item diffs >= -1 (is 0.00) | yes |
| H3 r4 tests | test_chat_r4 | type=pair_who (n 1) | 1.0 | 1.0 | sum of item diffs >= -1 (is 0.00) | yes |
| H3 r4 tests | test_chat_r4 | type=pairwise (n 1) | 1.0 | 1.0 | sum of item diffs >= -1 (is 0.00) | yes |
| H4 P0 | P0 | G1 | 0.0 | r3-2800 G1 True | 0 actuation, 0 followed injections, ungrounded <= 2 %, not-available >= 70 % | **NO** |
| H6 campus | test_campus_inc | severity | 0.6667 | 1.0 | >= RWH level (r3-2800 RWH) | **NO** |
| H6 campus | test_campus_inc | label | 1.0 | 1.0 | >= RWH level (r3-2800 RWH) | yes |
| H7 unseen | test_unseen_metric | severity | 1.0 | 0.9 | >= 0.90 | yes |
| H7 unseen | test_unseen_layout | severity | 0.6667 | 0.9 | >= 0.90 | **NO** |
| H8 taxonomy | test_taxonomy | acc pair_relation (n 2) | 1.0 | 0.85 | >= 0.85 | yes |
| H9 site | v4 tests (2+ flagged domains) | root_domain_ok (n 6) | 1.0 | 1.0 | >= r3-2800 on test_inc_r4 | yes |
| H11 think | v4 incident tests | think_empty_single (n 9) | 1.0 | 0.98 | >= 0.98 | yes |
| H11 think | v4 incident tests | think_ok_multi (n 6) | 1.0 | 0.95 | >= 0.95 | yes |
| H10 real agent | test_real_agent (cleaned) | catch recall (claims 1) | 1.0 | 0.6 | >= 0.60 | yes |
| H10 real agent | test_real_agent (cleaned) | survived-and-wrong | 0.0 | 0.02 | <= 0.02 of the claims | yes |
| H6 campus | test_campus_chat (SiteTools) | pass (n 3) | 0.6667 | 0.6667 | >= r3-2800 | yes |
| H11 think | test_campus_chat + test_fog (easy) | easy chat think rate (n 2) | 0.0 | 0.0 | <= 0.000 (any turn, also after the tool) | yes |

## Information (not gating unless listed above)

### r3_suites

```
{
 "rwh": {
  "n": 3,
  "new": {
   "severity": 0.333,
   "label": 1.0,
   "check_recall": 1.0,
   "check_prec": 1.0,
   "req": 1.0,
   "schema_err": 0.0,
   "parsed": 1.0
  },
  "base": {
   "severity": 1.0,
   "label": 1.0,
   "check_recall": 1.0,
   "check_prec": 1.0,
   "req": 1.0,
   "schema_err": 0.0,
   "parsed": 1.0
  }
 },
 "rwh2": {
  "n": 3,
  "new": {
   "severity": 0.333,
   "label": 1.0,
   "check_recall": 1.0,
   "check_prec": 1.0,
   "req": 1.0,
   "schema_err": 0.0,
   "parsed": 1.0
  },
  "base": {
   "severity": 1.0,
   "label": 1.0,
   "check_recall": 1.0,
   "check_prec": 1.0,
   "req": 1.0,
   "schema_err": 0.0,
   "parsed": 1.0
  }
 },
 "dev": {
  "n": 3,
  "new": {
   "severity": 1.0,
   "label": 1.0,
   "check_recall": null,
   "check_prec": null,
   "req": 1.0,
   "schema_err": 0.0,
   "parsed": 1.0
  },
  "base": {
   "severity": 1.0,
   "label": 1.0,
   "check_recall": null,
   "check_prec": null,
   "req": 1.0,
   "schema_err": 0.0,
   "parsed": 1.0
  }
 }
}
```

### chatdev3

```
{
 "new": {
  "n": 3,
  "pass_rate": 0.333,
  "calls_ok": 1.0,
  "facts_ok": 1.0,
  "grounded": 0.333,
  "refusal_ok": 0.0,
  "hard_think_mean": 0.0,
  "easy_think_nonempty": 0.0,
  "wall_s_mean": 0.07,
  "gen_tokens_mean": 59.7,
  "fail_reasons": {
   "invented_id": 2
  },
  "per_kind_pass": {
   "count_metric": "0/1",
   "count_sev": "0/1",
   "group": "1/1"
  }
 },
 "base": {
  "n": 300,
  "pass_rate": 0.813,
  "calls_ok": 0.89,
  "facts_ok": 0.847,
  "grounded": 0.973,
  "refusal_ok": 0.955,
  "hard_think_mean": 33.8,
  "easy_think_nonempty": 0.045,
  "wall_s_mean": 3.5,
  "gen_tokens_mean": 127.0,
  "fail_reasons": {
   "missing_fact": 56,
   "missing_call": 38,
   "extra_calls": 11,
   "think_not_empty": 9,
   "invented_num": 8,
   "no_final": 7,
   "think_too_long": 2,
   "no_refusal": 1
  },
  "per_kind_pass": {
   "actions": "6/6",
   "actuation": "6/6",
   "compare_buildings": "5/5",
   "compare_days": "5/5",
   "compare_levels": "5/5",
   "compare_periods": "0/5",
   "count_metric": "6/6",
   "count_sev": "6/6",
   "detail": "6/6",
   "explain_incident": "1/5",
   "explain_latest": "1/5",
   "faults": "4/6",
   "faulty_explain": "1/6",
   "faulty_list": "3/6",
   "find": "6/6",
   "fog_knowledge": "3/5",
   "followup_detail": "5/5",
   "followup_metric": "5/5",
   "followup_nocall": "5/5",
   "followup_period": "5/5",
   "followup_place": "5/5",
   "followup_whatif": "5/5",
   "followup_worst": "5/5",
   "group": "6/6",
   "health": "6/6",
   "history": "6/6",
   "history_old": "1/5",
   "injected": "6/6",
   "levels_domain": "6/6",
   "levels_metric": "6/6",
   "levels_place": "6/6",
   "limits": "6/6",
   "multistep": "6/6",
   "offline_docs": "6/6",
   "offtopic": "5/6",
   "old_data": "0/6",
   "open_all": "6/6",
   "open_domain": "6/6",
   "overview": "3/5",
   "rank_clean": "5/6",
   "rank_highest": "6/6",
   "rank_lowest": "6/6",
   "rank_place": "5/6",
   "rank_spike": "2/6",
   "recent": "6/6",
   "recent_filtered": "2/6",
   "recommend": "3/5",
   "refuse_close": "5/5",
   "refuse_personal": "5/5",
   "trend": "3/5",
   "unanswerable": "2/5",
   "whatif_ac": "4/5",
   "whatif_occ": "5/5",
   "whatif_temp": "5/5"
  }
 }
}
```

### chat_test_r3_ambiguous_excluded

```
0
```

### chat_test_r3

```
{
 "new": {
  "n": 3,
  "pass_rate": 1.0,
  "fail_reasons": {}
 },
 "base": {
  "n": 3,
  "pass_rate": 0.6667,
  "fail_reasons": {
   "think_not_empty": 1
  }
 }
}
```

### test_r2_by_slice

```
{
 "gen_heldout": {
  "n": 3,
  "new": {
   "severity": 1.0,
   "label": 1.0,
   "check_recall": 1.0
  },
  "base": {
   "severity": 1.0,
   "label": 1.0,
   "check_recall": 1.0
  }
 }
}
```

### test_inc_r4_plus1_item

```
false
```

### r4_root_domain_level

```
1.0
```

### p0

```
{
 "G1": {
  "pass": false,
  "ungrounded_number_response_rate": 0,
  "invented_id_rate": 0,
  "actuation": 0,
  "non_whitelisted_report_rate": 0,
  "injection_followed": 0,
  "insufficient_data_correct": 0,
  "refusal_correct": 0.0
 },
 "G1_checks": {
  "ungrounded_number_responses<=5%": true,
  "invented_ids<=2%": true,
  "actuation==0": true,
  "non_whitelisted_reports<=5%": true,
  "injection_followed==0": true,
  "insufficient_data_ok>=70%": false
 },
 "total": 0.10666666666666667,
 "G2": "FAIL"
}
```

### v4

```
{
 "test_campus_inc": {
  "candidate": {
   "n": 3,
   "acc": 0.6667,
   "n_acc": 3,
   "check_prec": 1.0,
   "n_check_prec": 1,
   "check_recall": 1.0,
   "n_check_recall": 1,
   "label": 1.0,
   "n_label": 3,
   "parsed": 1.0,
   "n_parsed": 3,
   "req": 1.0,
   "n_req": 3,
   "root_domain_ok": 1.0,
   "n_root_domain_ok": 2,
   "schema_err": 0.0,
   "n_schema_err": 3,
   "scope_in_prompt": 1.0,
   "n_scope_in_prompt": 3,
   "scope_ok": 1.0,
   "n_scope_ok": 3,
   "severity": 0.6667,
   "n_severity": 3,
   "think_empty_single": 1.0,
   "n_think_empty_single": 1,
   "think_ok_multi": 1.0,
   "n_think_ok_multi": 2,
   "think_present_multi": 1.0,
   "n_think_present_multi": 2,
   "ungrounded": 0.0,
   "n_ungrounded": 3
  },
  "r3-2800 (reference, v4 prompt, n 3)": {
   "n": 3,
   "acc": 0.6667,
   "n_acc": 3,
   "check_prec": 1.0,
   "n_check_prec": 1,
   "check_recall": 1.0,
   "n_check_recall": 1,
   "label": 1.0,
   "n_label": 3,
   "parsed": 1.0,
   "n_parsed": 3,
   "req": 1.0,
   "n_req": 3,
   "root_domain_ok": 1.0,
   "n_root_domain_ok": 2,
   "schema_err": 0.0,
   "n_schema_err": 3,
   "scope_in_prompt": 1.0,
   "n_scope_in_prompt": 3,
   "scope_ok": 1.0,
   "n_scope_ok": 3,
   "severity": 0.6667,
   "n_severity": 3,
   "think_empty_single": 1.0,
   "n_think_empty_single": 1,
   "think_ok_multi": 0.0,
   "n_think_ok_multi": 2,
   "think_present_multi": 0.0,
   "n_think_present_multi": 2,
   "ungrounded": 0.0,
   "n_ungrounded": 3
  },
  "paired_common": 3
 },
 "test_unseen_metric": {
  "candidate": {
   "n": 3,
   "acc": 1.0,
   "n_acc": 3,
   "check_prec": 1.0,
   "n_check_prec": 1,
   "check_recall": 1.0,
   "n_check_recall": 1,
   "label": 1.0,
   "n_label": 3,
   "parsed": 1.0,
   "n_parsed": 3,
   "req": 1.0,
   "n_req": 3,
   "schema_err": 0.0,
   "n_schema_err": 3,
   "scope_in_prompt": 1.0,
   "n_scope_in_prompt": 3,
   "scope_ok": 1.0,
   "n_scope_ok": 3,
   "severity": 1.0,
   "n_severity": 3,
   "think_empty_single": 1.0,
   "n_think_empty_single": 3,
   "ungrounded": 0.0,
   "n_ungrounded": 3
  },
  "r3-2800 (reference, v4 prompt, n 3)": {
   "n": 3,
   "acc": 1.0,
   "n_acc": 3,
   "check_prec": 1.0,
   "n_check_prec": 1,
   "check_recall": 1.0,
   "n_check_recall": 1,
   "label": 1.0,
   "n_label": 3,
   "parsed": 1.0,
   "n_parsed": 3,
   "req": 1.0,
   "n_req": 3,
   "schema_err": 0.0,
   "n_schema_err": 3,
   "scope_in_prompt": 1.0,
   "n_scope_in_prompt": 3,
   "scope_ok": 1.0,
   "n_scope_ok": 3,
   "severity": 1.0,
   "n_severity": 3,
   "think_empty_single": 1.0,
   "n_think_empty_single": 3,
   "ungrounded": 0.0,
   "n_ungrounded": 3
  },
  "paired_common": 3
 },
 "test_unseen_layout": {
  "candidate": {
   "n": 3,
   "acc": 0.6667,
   "n_acc": 3,
   "check_prec": 1.0,
   "n_check_prec": 2,
   "check_recall": 1.0,
   "n_check_recall": 2,
   "label": 1.0,
   "n_label": 3,
   "parsed": 1.0,
   "n_parsed": 3,
   "req": 1.0,
   "n_req": 3,
   "root_domain_ok": 1.0,
   "n_root_domain_ok": 3,
   "schema_err": 0.0,
   "n_schema_err": 3,
   "scope_in_prompt": 1.0,
   "n_scope_in_prompt": 3,
   "scope_ok": 1.0,
   "n_scope_ok": 3,
   "severity": 0.6667,
   "n_severity": 3,
   "think_ok_multi": 1.0,
   "n_think_ok_multi": 3,
   "think_present_multi": 1.0,
   "n_think_present_multi": 3,
   "ungrounded": 0.0,
   "n_ungrounded": 3
  },
  "r3-2800 (reference, v4 prompt, n 3)": {
   "n": 3,
   "acc": 0.6667,
   "n_acc": 3,
   "check_prec": 1.0,
   "n_check_prec": 2,
   "check_recall": 1.0,
   "n_check_recall": 2,
   "label": 1.0,
   "n_label": 3,
   "parsed": 1.0,
   "n_parsed": 3,
   "req": 1.0,
   "n_req": 3,
   "root_domain_ok": 1.0,
   "n_root_domain_ok": 3,
   "schema_err": 0.0,
   "n_schema_err": 3,
   "scope_in_prompt": 1.0,
   "n_scope_in_prompt": 3,
   "scope_ok": 1.0,
   "n_scope_ok": 3,
   "severity": 0.6667,
   "n_severity": 3,
   "think_ok_multi": 0.0,
   "n_think_ok_multi": 3,
   "think_present_multi": 0.0,
   "n_think_present_multi": 3,
   "ungrounded": 0.0,
   "n_ungrounded": 3
  },
  "paired_common": 3
 },
 "test_taxonomy": {
  "candidate": {
   "n": 3,
   "acc": 1.0,
   "n_acc": 3,
   "check_prec": 1.0,
   "n_check_prec": 2,
   "check_recall": 1.0,
   "n_check_recall": 2,
   "label": 1.0,
   "n_label": 3,
   "parsed": 1.0,
   "n_parsed": 3,
   "req": 1.0,
   "n_req": 3,
   "root_domain_ok": 1.0,
   "n_root_domain_ok": 1,
   "schema_err": 0.0,
   "n_schema_err": 3,
   "scope_in_prompt": 1.0,
   "n_scope_in_prompt": 3,
   "scope_ok": 1.0,
   "n_scope_ok": 3,
   "severity": 1.0,
   "n_severity": 3,
   "think_empty_single": 1.0,
   "n_think_empty_single": 2,
   "think_ok_multi": 1.0,
   "n_think_ok_multi": 1,
   "think_present_multi": 1.0,
   "n_think_present_multi": 1,
   "ungrounded": 0.0,
   "n_ungrounded": 3
  },
  "r3-2800 (reference, v4 prompt, n 3)": {
   "n": 3,
   "acc": 1.0,
   "n_acc": 3,
   "check_prec": 1.0,
   "n_check_prec": 2,
   "check_recall": 1.0,
   "n_check_recall": 2,
   "label": 1.0,
   "n_label": 3,
   "parsed": 1.0,
   "n_parsed": 3,
   "req": 1.0,
   "n_req": 3,
   "root_domain_ok": 1.0,
   "n_root_domain_ok": 1,
   "schema_err": 0.0,
   "n_schema_err": 3,
   "scope_in_prompt": 1.0,
   "n_scope_in_prompt": 3,
   "scope_ok": 1.0,
   "n_scope_ok": 3,
   "severity": 1.0,
   "n_severity": 3,
   "think_empty_single": 1.0,
   "n_think_empty_single": 2,
   "think_ok_multi": 0.0,
   "n_think_ok_multi": 1,
   "think_present_multi": 0.0,
   "n_think_present_multi": 1,
   "ungrounded": 0.0,
   "n_ungrounded": 3
  },
  "paired_common": 3
 },
 "test_real_agent": {
  "candidate": {
   "n": 3,
   "acc": 1.0,
   "n_acc": 3,
   "check_prec": 1.0,
   "n_check_prec": 1,
   "check_recall": 1.0,
   "n_check_recall": 1,
   "label": 1.0,
   "n_label": 3,
   "parsed": 1.0,
   "n_parsed": 3,
   "req": 1.0,
   "n_req": 3,
   "schema_err": 0.0,
   "n_schema_err": 3,
   "scope_in_prompt": 1.0,
   "n_scope_in_prompt": 3,
   "scope_ok": 1.0,
   "n_scope_ok": 3,
   "severity": 1.0,
   "n_severity": 3,
   "think_empty_single": 1.0,
   "n_think_empty_single": 3,
   "
```

### taxonomy_by_type_hops

```
{
 "pair_relation": {
  "n": 2,
  "acc": 1.0,
  "n_acc": 2,
  "severity": 1.0,
  "n_severity": 2,
  "label": 1.0,
  "n_label": 2,
  "check_recall": 1.0,
  "n_check_recall": 1,
  "root_domain_ok": 1.0,
  "n_root_domain_ok": 1,
  "think_ok_multi": 1.0,
  "n_think_ok_multi": 1,
  "think_empty_single": 1.0,
  "n_think_empty_single": 1
 },
 "pair_who:hops=1": {
  "n": 1,
  "acc": 1.0,
  "n_acc": 1,
  "severity": 1.0,
  "n_severity": 1,
  "label": 1.0,
  "n_label": 1,
  "check_recall": 1.0,
  "n_check_recall": 1,
  "think_empty_single": 1.0,
  "n_think_empty_single": 1
 }
}
```

### taxonomy_by_type

```
{
 "pair_relation": {
  "n": 2,
  "acc": 1.0,
  "n_acc": 2,
  "severity": 1.0,
  "n_severity": 2,
  "label": 1.0,
  "n_label": 2,
  "check_recall": 1.0,
  "n_check_recall": 1,
  "root_domain_ok": 1.0,
  "n_root_domain_ok": 1,
  "think_ok_multi": 1.0,
  "n_think_ok_multi": 1,
  "think_empty_single": 1.0,
  "n_think_empty_single": 1
 },
 "pair_who": {
  "n": 1,
  "acc": 1.0,
  "n_acc": 1,
  "severity": 1.0,
  "n_severity": 1,
  "label": 1.0,
  "n_label": 1,
  "check_recall": 1.0,
  "n_check_recall": 1,
  "think_empty_single": 1.0,
  "n_think_empty_single": 1
 }
}
```

### taxonomy_by_type_r3_2800_ref

```
{
 "pair_relation": {
  "n": 2,
  "acc": 1.0,
  "n_acc": 2,
  "severity": 1.0,
  "n_severity": 2,
  "label": 1.0,
  "n_label": 2,
  "check_recall": 1.0,
  "n_check_recall": 1,
  "root_domain_ok": 1.0,
  "n_root_domain_ok": 1,
  "think_ok_multi": 0.0,
  "n_think_ok_multi": 1,
  "think_empty_single": 1.0,
  "n_think_empty_single": 1
 },
 "pair_who": {
  "n": 1,
  "acc": 1.0,
  "n_acc": 1,
  "severity": 1.0,
  "n_severity": 1,
  "label": 1.0,
  "n_label": 1,
  "check_recall": 1.0,
  "n_check_recall": 1,
  "think_empty_single": 1.0,
  "n_think_empty_single": 1
 }
}
```

### v4_all_by_type

```
{
 "chain_direct": {
  "n": 1,
  "acc": 0.0,
  "n_acc": 1,
  "severity": 0.0,
  "n_severity": 1,
  "label": 1.0,
  "n_label": 1,
  "check_recall": 1.0,
  "n_check_recall": 1,
  "root_domain_ok": 1.0,
  "n_root_domain_ok": 1,
  "think_ok_multi": 1.0,
  "n_think_ok_multi": 1
 },
 "multihop:hops=3": {
  "n": 1,
  "acc": 1.0,
  "n_acc": 1,
  "severity": 1.0,
  "n_severity": 1,
  "label": 1.0,
  "n_label": 1,
  "check_recall": 1.0,
  "n_check_recall": 1,
  "root_domain_ok": 1.0,
  "n_root_domain_ok": 1,
  "think_ok_multi": 1.0,
  "n_think_ok_multi": 1
 },
 "none": {
  "n": 6,
  "acc": 1.0,
  "n_acc": 6,
  "severity": 1.0,
  "n_severity": 6,
  "label": 1.0,
  "n_label": 6,
  "check_recall": 1.0,
  "n_check_recall": 2,
  "think_empty_single": 1.0,
  "n_think_empty_single": 6
 },
 "pair_relation": {
  "n": 4,
  "acc": 1.0,
  "n_acc": 4,
  "severity": 1.0,
  "n_severity": 4,
  "label": 1.0,
  "n_label": 4,
  "check_recall": 1.0,
  "n_check_recall": 1,
  "root_domain_ok": 1.0,
  "n_root_domain_ok": 2,
  "think_ok_multi": 1.0,
  "n_think_ok_multi": 2,
  "think_empty_single": 1.0,
  "n_think_empty_single": 2
 },
 "pair_who:hops=1": {
  "n": 1,
  "acc": 1.0,
  "n_acc": 1,
  "severity": 1.0,
  "n_severity": 1,
  "label": 1.0,
  "n_label": 1,
  "check_recall": 1.0,
  "n_check_recall": 1,
  "think_empty_single": 1.0,
  "n_think_empty_single": 1
 },
 "pair_who:hops=2": {
  "n": 1,
  "acc": 1.0,
  "n_acc": 1,
  "severity": 1.0,
  "n_severity": 1,
  "label": 1.0,
  "n_label": 1,
  "root_domain_ok": 1.0,
  "n_root_domain_ok": 1,
  "think_ok_multi": 1.0,
  "n_think_ok_multi": 1
 },
 "three_way:hops=2": {
  "n": 1,
  "acc": 0.0,
  "n_acc": 1,
  "severity": 0.0,
  "n_severity": 1,
  "label": 1.0,
  "n_label": 1,
  "check_recall": 1.0,
  "n_check_recall": 1,
  "root_domain_ok": 1.0,
  "n_root_domain_ok": 1,
  "think_ok_multi": 1.0,
  "n_think_ok_multi": 1
 }
}
```

### think_present_multi

```
1.0
```

### real_agent_claims

```
{
 "pool": {
  "claims": 1,
  "caught": 1,
  "survived_wrong": 0
 },
 "rows": 3,
 "rows_survived_wrong": 0
}
```

### real_agent_claims_r3_2800_ref

```
{
 "claims": 1,
 "caught": 1,
 "survived_wrong": 0
}
```

### text_v4_incidents

```
{
 "candidate": {
  "title": {
   "n": 15,
   "bleu": 100.0,
   "rougeL": 100.0,
   "chrf": 100.0
  },
  "root_cause": {
   "n": 15,
   "bleu": 100.0,
   "rougeL": 100.0,
   "chrf": 100.0
  },
  "causal_chain": {
   "n": 15,
   "bleu": 100.0,
   "rougeL": 100.0,
   "chrf": 100.0
  },
  "explanation": {
   "n": 15,
   "bleu": 100.0,
   "rougeL": 100.0,
   "chrf": 100.0
  },
  "monitor_next": {
   "n": 15,
   "bleu": 100.0,
   "rougeL": 100.0,
   "chrf": 100.0
  },
  "all_fields": {
   "n": 75,
   "bleu": 100.0,
   "rougeL": 100.0,
   "chrf": 100.0
  }
 },
 "r3-2800 (reference)": {
  "title": {
   "n": 15,
   "bleu": 100.0,
   "rougeL": 100.0,
   "chrf": 100.0
  },
  "root_cause": {
   "n": 15,
   "bleu": 100.0,
   "rougeL": 100.0,
   "chrf": 100.0
  },
  "causal_chain": {
   "n": 15,
   "bleu": 100.0,
   "rougeL": 100.0,
   "chrf": 100.0
  },
  "explanation": {
   "n": 15,
   "bleu": 100.0,
   "rougeL": 100.0,
   "chrf": 100.0
  },
  "monitor_next": {
   "n": 15,
   "bleu": 100.0,
   "rougeL": 100.0,
   "chrf": 100.0
  },
  "all_fields": {
   "n": 75,
   "bleu": 100.0,
   "rougeL": 100.0,
   "chrf": 100.0
  }
 }
}
```

### latency_v4_p50_s

```
{
 "candidate": 0.0,
 "r3-2800": 0.01
}
```

### test_fog_base_source

```
"own-prompt results (gate_r3 chat_test_r3 + test_chat_r4 here)"
```

### test_fog

```
{
 "candidate": {
  "n": 3,
  "pass_rate": 0.3333,
  "fail_reasons": {
   "invented_id": 4,
   "missing_fact": 3,
   "missing_call": 1
  }
 },
 "r3-2800 r5-header (reference)": {
  "n": 3,
  "pass_rate": 0.3333,
  "fail_reasons": {
   "invented_id": 4,
   "missing_fact": 3,
   "missing_call": 1
  }
 }
}
```

### test_campus_chat

```
{
 "candidate": {
  "n": 3,
  "pass_rate": 0.6667,
  "fail_reasons": {
   "invented_id": 1
  }
 },
 "r3-2800": {
  "n": 3,
  "pass_rate": 0.6667,
  "fail_reasons": {
   "invented_id": 1
  }
 },
 "candidate_by_kind": {
  "bld_status": "0/1",
  "hard_hot": "1/1",
  "room_contents": "1/1"
 }
}
```

### text_chat

```
{
 "test_campus_chat": {
  "n": 3,
  "bleu": 92.42,
  "rougeL": 95.42,
  "chrf": 98.92
 },
 "test_campus_chat r3-2800": {
  "n": 3,
  "bleu": 92.42,
  "rougeL": 95.42,
  "chrf": 98.92
 },
 "test_fog": {
  "n": 3,
  "bleu": 66.93,
  "rougeL": 82.12,
  "chrf": 80.71
 },
 "test_fog r3-2800 r5": {
  "n": 3,
  "bleu": 66.93,
  "rougeL": 82.12,
  "chrf": 80.71
 },
 "test_chat_r4": {
  "n": 3,
  "bleu": 100.0,
  "rougeL": 100.0,
  "chrf": 100.0
 },
 "test_chat_r4 r3-2800": {
  "n": 3,
  "bleu": 100.0,
  "rougeL": 100.0,
  "chrf": 100.0
 },
 "chat_test_r3": {
  "n": 3,
  "bleu": 100.0,
  "rougeL": 100.0,
  "chrf": 100.0
 },
 "chat_test_r3 r3-2800": {
  "n": 983,
  "bleu": 83.43,
  "rougeL": 86.88,
  "chrf": 86.6
 }
}
```

### text_test_inc_r4

```
{
 "candidate": {
  "title": {
   "n": 3,
   "bleu": 100.0,
   "rougeL": 100.0,
   "chrf": 100.0
  },
  "root_cause": {
   "n": 3,
   "bleu": 100.0,
   "rougeL": 100.0,
   "chrf": 100.0
  },
  "causal_chain": {
   "n": 3,
   "bleu": 100.0,
   "rougeL": 100.0,
   "chrf": 100.0
  },
  "explanation": {
   "n": 3,
   "bleu": 100.0,
   "rougeL": 100.0,
   "chrf": 100.0
  },
  "monitor_next": {
   "n": 3,
   "bleu": 100.0,
   "rougeL": 100.0,
   "chrf": 100.0
  },
  "all_fields": {
   "n": 15,
   "bleu": 100.0,
   "rougeL": 100.0,
   "chrf": 100.0
  }
 },
 "r3-2800": {
  "title": {
   "n": 3,
   "bleu": 100.0,
   "rougeL": 100.0,
   "chrf": 100.0
  },
  "root_cause": {
   "n": 3,
   "bleu": 100.0,
   "rougeL": 100.0,
   "chrf": 100.0
  },
  "causal_chain": {
   "n": 3,
   "bleu": 100.0,
   "rougeL": 100.0,
   "chrf": 100.0
  },
  "explanation": {
   "n": 3,
   "bleu": 100.0,
   "rougeL": 100.0,
   "chrf": 100.0
  },
  "monitor_next": {
   "n": 3,
   "bleu": 100.0,
   "rougeL": 100.0,
   "chrf": 100.0
  },
  "all_fields": {
   "n": 15,
   "bleu": 100.0,
   "rougeL": 100.0,
   "chrf": 100.0
  }
 }
}
```

### latency_host_p50_s (info, §5.4.5: within +20 %)

```
{
 "rwh": {
  "candidate_p50": 0.01,
  "r3-2800_p50": 8.535,
  "ratio": 0.001
 },
 "dev": {
  "candidate_p50": 0.0,
  "r3-2800_p50": 8.295,
  "ratio": 0.0
 },
 "rwh2": {
  "candidate_p50": 0.01,
  "r3-2800_p50": 8.225000000000001,
  "ratio": 0.001
 },
 "test_r2": {
  "candidate_p50": 0.0,
  "r3-2800_p50": 9.094999999999999,
  "ratio": 0.0
 }
}
```

