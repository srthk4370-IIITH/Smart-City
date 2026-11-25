# Cutoff
Campus replay data range ends 2026-01-01 00:00 IST (epoch 1767205800). Paper held-out test = last 3 weeks.
**CUTOFF = epoch 1765391400 = 2025-12-11 00:00 IST.** Every row built here has all windows ending strictly before it (real windows: end_epoch < cutoff, checked per row; injected scenes dated 2025-01..2025-12-10; sft_v2 train/dev pool ends 2025-08).
Board incidents (old_inc.jsonl): sim clock is shifted +1 year to campus data, only 428 non-injected incidents exist, and their reports are the old board schema with no verified gold -> not used.
