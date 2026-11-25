whisper.cpp ca19af2 (ggml-org), NDK r26d, arm64-v8a, static libs, CPU NEON +dotprod, no OpenMP; whisper-cli stripped 2147864 B md5 2dd4eee2104e10f812ede74599c9c200
model ggml-tiny.en.bin (HF ggerganov/whisper.cpp) 77704715 B sha256 921e4cf8686fdd993dcd081a5da5b6c365bfde1162e72b08d75ac75289920b1f md5 5c5223266e7bdb9b7554205e739ed174
laptop (8 core x86, host build): jfk.wav 11 s audio -> 2 threads 2.90 s wall, 4 threads 2.27 s (incl. model load). Board expected 2-3x slower: ~6-9 s for 11 s speech, a 30 s clip ~15-20 s (near the 20 s timeout; typical questions are 3-8 s -> 2-4 s).
