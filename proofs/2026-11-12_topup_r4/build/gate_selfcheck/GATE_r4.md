# r4 top-up STRICT gate: rsn_v3_4b_r3 vs rsn_v3_4b_r3 (r3 step 2800) -> **INCOMPLETE**

Rule (TOPUP.md): (a) r4 held-out cross-domain test better than r3-2800 by >= 1 item, no part worse beyond noise; (b) all 19 existing gate checks >= r3-2800 within 1 item; (c) chat_test_r3 fog slices not lower beyond noise. Q4_0 on the host GPU (host = board numerics). On FAIL r3-2800 (rsn_v3_4b_r3_q4_0.gguf) stays the model.

Missing: r4 test results

| suite | metric | r4 | r3-2800 | rule | ok |
|---|---|---|---|---|---|
| rwh | severity | 0.947 | 0.947 | >= r3-2800 within 1 item (0.007) | yes |
| rwh | label | 0.96 | 0.96 | >= r3-2800 within 1 item (0.007) | yes |
| rwh | check_recall | 0.937 | 0.937 | >= r3-2800 within 1 item (0.013) | yes |
| rwh | check_prec | 0.974 | 0.974 | >= r3-2800 within 1 item (0.013) | yes |
| rwh | req | 0.88 | 0.88 | >= r3-2800 within 1 item (0.007) | yes |
| rwh | schema_err | 0.0 | 0.0 | <= r3-2800 within 1 item (0.007) | yes |
| rwh2 | severity | 0.993 | 0.993 | >= r3-2800 within 1 item (0.007) | yes |
| rwh2 | label | 1.0 | 1.0 | >= r3-2800 within 1 item (0.007) | yes |
| rwh2 | check_recall | 0.883 | 0.883 | >= r3-2800 within 1 item (0.017) | yes |
| rwh2 | check_prec | 0.982 | 0.982 | >= r3-2800 within 1 item (0.018) | yes |
| rwh2 | req | 0.927 | 0.927 | >= r3-2800 within 1 item (0.007) | yes |
| rwh2 | schema_err | 0.02 | 0.02 | <= r3-2800 within 1 item (0.007) | yes |
| dev | severity | 0.942 | 0.942 | >= r3-2800 within 1 item (0.008) | yes |
| dev | label | 0.942 | 0.942 | >= r3-2800 within 1 item (0.008) | yes |
| dev | check_recall | 0.86 | 0.86 | >= r3-2800 within 1 item (0.023) | yes |
| dev | check_prec | 0.927 | 0.927 | >= r3-2800 within 1 item (0.024) | yes |
| dev | req | 0.925 | 0.925 | >= r3-2800 within 1 item (0.008) | yes |
| dev | schema_err | 0.008 | 0.008 | <= r3-2800 within 1 item (0.008) | yes |
| chatdev3 | pass_rate | 0.813 | 0.813 | >= r3-2800 within 1 item (0.0033) | yes |
| chat_test_r3 (minus ambiguous) | fog=online | 0.876 | 0.876 | not lower beyond noise (paired z < -1.96 and >= 1 item) | yes |
| chat_test_r3 (minus ambiguous) | fog=offline | 0.739 | 0.739 | not lower beyond noise (paired z < -1.96 and >= 1 item) | yes |
| chat_test_r3 (minus ambiguous) | fog=timeout | 0.522 | 0.522 | not lower beyond noise (paired z < -1.96 and >= 1 item) | yes |

## (c) chat_test_r3 by fog, GATING: minus 50 ambiguous items (data/chat_test_r3_ambiguous.jsonl, owner 2026-11-12)

| fog | n | r4 | r3-2800 | reported r3-2800 | paired diff | z | ok |
|---|---|---|---|---|---|---|---|
| online | 404 | 0.876 | 0.876 | 0.876 | 0.0 | 0.0 | True |
| offline | 460 | 0.739 | 0.739 | 0.739 | 0.0 | 0.0 | True |
| timeout | 69 | 0.522 | 0.522 | 0.522 | 0.0 | 0.0 | True |

## chat_test_r3 by fog, full set (info, not gating)

| fog | n | r4 | r3-2800 | reported r3-2800 | paired diff | z | ok |
|---|---|---|---|---|---|---|---|
| online | 421 | 0.841 | 0.841 | 0.841 | 0.0 | 0.0 | True |
| offline | 493 | 0.692 | 0.692 | 0.692 | 0.0 | 0.0 | True |
| timeout | 69 | 0.522 | 0.522 | 0.522 | 0.0 | 0.0 | True |

Baseline note: r3-2800 filtered (gating) fog baselines from its cached gate_r3 outputs: online 354/404 = 0.876, offline 340/460 = 0.739, timeout 36/69 = 0.522 (full: 0.841 / 0.692 / 0.522; the 50 excluded items: 1 pass).
