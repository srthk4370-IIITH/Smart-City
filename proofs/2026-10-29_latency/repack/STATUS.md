# Parallel weight repack in libggml-hexagon.so (lab only, NOT deployed)

Status: built + bit-identical; lab window 1 aborted by the NPU guard (stop-list gap, fixed); A/B not yet measured. Live app lib untouched
(/data/local/tmp/llama.cpp/lib/libggml-hexagon.so md5 5587a193acca52219c6596581929dfdb).

## Build (WSL, no Docker)
- Source: C:\Users\hp\gpu_work\llama.cpp\ggml\src\ggml-hexagon\ggml-hexagon.cpp (same mtime as the board lib build) + htp-drv.cpp.
- Toolchain: NDK r26d clang (aarch64-android34), Hexagon SDK 6.7.0.1 headers (incs, incs/stddef, utils/examples).
  Flags = build-snapdragon/build.ninja ggml-hexagon flags minus -flto and -g (as for libllama_p.so).
  The prebuilt htp_iface_stub.c.o is LLVM-21 LTO bitcode (unreadable by r26d's lld), so htp_iface_stub.c (generated, in the
  build tree) is recompiled. Linked against the board-identical bin/libggml-base.so. Scripts: src/build.sh, src/build_test.sh.
- libs/libggml-hexagon.base.so  772c93842c34793484928ffdcf843412  unmodified source, this toolchain (baseline rebuild; links)
- libs/libggml-hexagon.rp.so    abee8fd610c249ed7e20d043f7fa60ad  patch rp1 (src/rp1.patch) -> board /data/local/tmp/llama.cpp/lib_rp/

## Patch rp1 (src/rp1.patch)
- Every *_tiled repack writes slice s / column tile ct (32 rows) to data + s*matrix_size + ct*n_k_tiles*tile_size and reads only
  those 32 source rows, so column tiles are independent. The unchanged serial repack runs on 2-D views of chunks of column tiles.
- Persistent worker pool (N-1 workers + caller), work handed out in small chunks through an atomic counter (static even splits
  were slower than serial: new threads land on slow/idle cores). N = min(8, hw threads); GGML_HEXAGON_REPACK_THREADS overrides,
  1 = original path. Tensors < 256 KB, unknown types or partial writes keep the original path.
- GGML_HEXAGON_REPACK_STATS=1 prints "ggml-hex: repack stats (...)" (repack wall time since the last report) when a buffer is freed.

## Bit-identity proof (test/)
rp_test (arm64, run on the board, CPU only) quantizes random tensors with ggml_quantize_chunk and compares the original serial
repack with the parallel one byte-for-byte over the whole tiled buffer; destination buffers pre-filled with different patterns
(0xA5 / 0x5A) so unwritten bytes would also show; 64-byte guard after the allocation checked.
23 cases: Q4_0 (incl. ne1=33, ne1=1000, 4-D 6 slices, 1024x32768), IQ4_NL, Q8_0 (ne0=1056, 3-D), Q6_K (1024x32768, odd ne1,
4-D), Q4_1, MXFP4, Q4_K (3-D odd), Q5_K, Q3_K, Q2_K (3-D odd).
Result: ALL BYTE-IDENTICAL for threads 1, 2, 4, 7, 8 and a second seed with the final pool version (test/out_t*.txt); also 2, 3, 7, 8 with the earlier spawn-per-tensor version.

## Micro timings (board, app running in background)
- Serial repack ~1.9 GB/s on one core (Q4_0 18 MB: 11 ms; Q6_K 26 MB: 54 ms). Model = 2.6 GB -> ~1.3 s of serial repack.
- Pinned scaling probe (test/out_scaling.txt): Q4_0 1/2/3/4/6 fast cores 11.1/8.5/5.9/4.3/3.4 ms (3.3x); 8 incl. little cores with
  a static split 10.1 ms. Q6_K 54 -> 29 ms (4 cores).
- Unpinned pool in short bursts: only ~1.05-1.2x (cores idle at 0.5-0.6 GHz, DVFS ramp). The real multi-second load is the test.

## Lab A/B
Attempt 1 (board clock 02:36-02:40, ab_attempt1/): ABORTED by the guard before any config ran: "NPU client still running".
Cause: lab_ab.sh only stopped htpd_v8x3/htpd_v8x4/htpd, but the live app now runs htpd_v8x5, so the app's htpd stayed up
(edge-agent was stopped ~4 min; the app was restarted by finish(); afterwards edge-agent + htpd_v8x5 were running). No data. No
second window was run (brief: one window only).

Fixed for the next window (lab_ab.diff): the stop list now includes htpd_v8x5 htpd_v8x5p; "a" in REQS = agents request (swap
sample: reasoner down + agents' model back); the "stopped" summary also greps "repack stats"; extra env may override
LD_LIBRARY_PATH/ADSP_LIBRARY_PATH (later env assignments win, checked on the board), so no other script change is needed.

Ready-to-run window (from Git Bash in proofs/2026-10-29_latency; Windows RAM was 4.1 GB free):
    REQS="10 a 10 a 11 a 12 a 13 a 14 a 15" bash lab_run.sh repack_ab \
      "base,htpd_v8x5,qwen35_reasoner_q4_0.gguf,X=0" \
      "rp,htpd_v8x5,qwen35_reasoner_q4_0.gguf,LD_LIBRARY_PATH=/data/local/tmp/llama.cpp/lib_rp ADSP_LIBRARY_PATH=/data/local/tmp/llama.cpp/lib_rp GGML_HEXAGON_REPACK_THREADS=8 GGML_HEXAGON_REPACK_STATS=1"
then: grep -E "load phases|reasoner loaded in|model back|repack stats" repack_ab/htpd_*.log ; node score.js repack_ab base rp
Board: /data/local/tmp/llama.cpp/lib_rp = full copy of lib/ with only libggml-hexagon.so replaced (lib.md5 vs lib_rp.md5 in test/).

## NDK r29 job (detached, owner-approved 2026-10-29)
Coordinator A/B (repack_ab, rebuild_ab): rp (r26d) load 3.60 -> 2.95 s, agents back 2.67 -> 2.46 s, identical text 2/6; unmodified r26d rebuild rb 3/6 -> the toolchain changes numerics, not the patch. Job: repack/ndk29_job.sh (stop: touch repack/STOP_ndk29). lab_run.sh window limit now WINDOW_MAX (default 1500 s; job uses 2700 for 3 configs).
- 10-29 22:43 ndk29: job start (pid 15346, log ~/detached/ndk29.log)
- 10-29 22:43 ndk29: waiting: Windows free RAM 1132 MB < 1536
- 10-29 22:44 ndk29: downloading android-ndk-r29-linux.zip (sha1 87e2bb7e9be5d6a1c6cdf5ec40dd4e0c6d07c30b)
- 10-29 22:46 ndk29: android-ndk-r29-linux.zip sha1 87e2bb7e9be5d6a1c6cdf5ec40dd4e0c6d07c30b ok
- 10-29 22:47 ndk29: NDK r29 (Pkg.Revision = 29.0.14206865) clang matches the original: Android (13989888, +pgo, +bolt, +lto, +mlgo, based on r563880c) clang version 21.0.0 (https://android.googlesource.com/toolchain/llvm-project 5e96669f06077099aa41290cdb4c5e6fa0f59349)
- 10-29 22:47 ndk29: waiting: Windows free RAM 1107 MB < 1536
- 10-29 22:48 ndk29: step 2: building unmodified lib with android-ndk-r29
- 10-29 22:48 ndk29: rb29 md5 448043c8779c2bf45edbc3d8a8e2bc45 != original 5587a193acca52219c6596581929dfdb (size 7412320 vs 7411424); .text same; stripped md5 0aada61d141b1647d2d57cc61db86b3b vs 98fd34773ec74b9c44364fc54688c6bb; sections: repack/ndk29/sections_*.txt
- 10-29 22:48 ndk29: step 3: building rp1 patch
- 10-29 22:48 ndk29: rp29 md5 c4e4598412e54469e9f387935de595bb
- 10-29 22:48 ndk29: waiting: Windows free RAM 517 MB < 1536
- 10-29 22:50 ndk29: step 4: lib_rb29 + lib_rp29 on the board (live lib untouched); starting lab window rp29_ab (base, rb29, rp29; ~30 min, app stopped)
- 10-29 23:19 ndk29: lab window done: 50 log lines; app: edge-agent htpd_v8x5 
- 10-29 23:19 ndk29: step 5: NOT deployable (identical text 3/6 vs base, load faster: yes) -> repack/VERDICT.md
- 10-29 23:19 ndk29: job done
