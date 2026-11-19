# Verdict: parallel repack built with NDK android-ndk-r29 (job ndk29, 2026-10-29 23:19:32)

**rp29: NOT deployable (identical text 3/6 vs base, load faster: yes)**

## Toolchain
- NDK: /home/hp_srthk4370/ndk/android-ndk-r29 (Pkg.Revision = 29.0.14206865); clang: Android (13989888, +pgo, +bolt, +lto, +mlgo, based on r563880c) clang version 21.0.0 (https://android.googlesource.com/toolchain/llvm-project 5e96669f06077099aa41290cdb4c5e6fa0f59349)
- original libggml-hexagon.so md5 5587a193acca52219c6596581929dfdb; rb29 (unmodified, this toolchain) md5 448043c8779c2bf45edbc3d8a8e2bc45; rp29 md5 c4e4598412e54469e9f387935de595bb
- per-section md5 (orig vs rb29):
```
.text 051cad31b9d3793cd693badfcdd51c66 533108	.text 051cad31b9d3793cd693badfcdd51c66 533108
.rodata b52a890ebb54987c37698b784e445967 30056	.rodata b52a890ebb54987c37698b784e445967 30056
.data.rel.ro b632d3a1b62343933de4cf06f55ce0e7 19312	.data.rel.ro b632d3a1b62343933de4cf06f55ce0e7 19312
.data 02b7e8e662bcfcfd7fc1ff6d03683781 392	.data 02b7e8e662bcfcfd7fc1ff6d03683781 392
.eh_frame aa836b606bd0f613b0be3720901bb687 78024	.eh_frame aa836b606bd0f613b0be3720901bb687 78024
.dynstr 98432d446a5334bbe1468ed423d16ddf 89138	.dynstr 98432d446a5334bbe1468ed423d16ddf 89138
```
## Lab window rp29_ab (base = live lib; rb29 = unmodified r29 rebuild; rp29 = rp1 patch, 8 threads)
```
base: n=6 parse=6 sev+label same as base=6 identical text=6 mean 29.4 s  [q10 35.8, q11 35.4, q12 26.8, q13 30.8, q14 23.5, q15 23.9]
base0: n=6 parse=6 sev+label same as base=6 identical text=2 mean 29.0 s  [q10 35.2, q11 34.9, q12 26.2, q13 30.4, q14 23.8, q15 23.4]
rb29: n=6 parse=6 sev+label same as base=6 identical text=3 mean 30.6 s  [q10 39.6, q11 38.9, q12 26.7, q13 30.6, q14 24.0, q15 23.9]
rp29: n=6 parse=6 sev+label same as base=6 identical text=3 mean 28.8 s  [q10 35.9, q11 34.9, q12 26.0, q13 30.0, q14 23.6, q15 22.6]
```
base0 = base answers from the earlier repack_ab window (run-to-run reference).

- base: reasoner load (model phase) 3699 ms mean of 7 (3849 3718 3642 3617 3799 3515 3754); agents' model back 2701 ms mean of 7
- rb29: reasoner load (model phase) 3665 ms mean of 7 (3638 3566 3848 3527 3684 3559 3835); agents' model back 2799 ms mean of 7
- rp29: reasoner load (model phase) 2800 ms mean of 7 (2731 2901 2705 2844 2704 3024 2691); agents' model back 2630 ms mean of 7
- rp29 repack stats: ggml-hex: repack stats (buffer free): 197 tensors, 1911.2 MB, 423.1 ms wall, 8 threads;ggml-hex: repack stats (buffer free): 249 tensors, 2411.9 MB, 635.8 ms wall, 8 threads;ggml-hex: repack stats (buffer free): 197 tensors, 1911.2 MB, 376.9 ms wall, 8 threads;

Rule: rp29 deployable only if identical text 6/6 vs base AND faster reasoner load. Nothing was deployed.

## Correction (2026-10-30, coordinator)
The 6/6 identical-text rule was wrong. The original lib run against itself in an earlier window (base0) matches only 2/6, so text identity
across windows is run-to-run noise on the NPU, not a lib effect. rb29 `.text`/`.rodata` are byte-identical to the original and the repack is
byte-identical (test/, 23 runs); severity+label 6/6 for every config. rp29 is lossless and loads 0.9 s faster -> deployed as deploy14
(profile env LD_LIBRARY_PATH/ADSP_LIBRARY_PATH=lib_rp29, GGML_HEXAGON_REPACK_THREADS=8). Earlier "toolchain changes numerics" (r26d) is withdrawn for the same reason.
