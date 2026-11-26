# Why there is no "ceiling model" arm (local or API)

The plan (RESEARCH_PAPER.md, section on the ceiling) asked for an upper-bound arm: a larger model reading the same cases, to show how far the 4B edge reasoner is from what a bigger model could do. It was skipped (owner decision, 2026-11-26). This note records why.

## Running a larger model locally is very hard

- **The laptop GPU has 8 GB.** A 14B model at Q4 needs about 8.5 GB for the weights alone, before the KV cache for 2–6k-token prompts. It has to spill into CPU RAM, which makes each case slow. A 9B model at Q4 (about 5.5 GB) fits, but only just, with the 8k context the reasoner prompts need.
- **The GPU is shared.** The same GPU runs the training, generation and paper jobs. A ceiling run over 468 cases (Sets A/B/D/F) would block it for many hours, and it would have to be repeated for every ablation to be a fair comparison.
- **The board cannot run it at all.** The QIDK runs one NPU client at a time. The 4B reasoner already shares memory with the 10 agent streams and is swapped in per incident (~3 s). A model 2–3× larger does not fit next to the agents.
- **An untuned larger model is not a fair ceiling.** The deployed reasoner is fine-tuned on this report schema, label set, evidence ids and tool format. An off-the-shelf 9B or 14B model would lose points on format and labels, not on reasoning. A fair ceiling would need the same fine-tuning on a model that the hardware above cannot train.
- **Evidence it would be weak:** the untuned Qwen3.5-4B used as a text judge could not separate a right report from a wrong-case decoy (RESULTS.md, root-cause text judge).

## An API model has its own problems

- **The prompts contain real campus sensor data.** Every reasoner prompt carries evidence blocks built from real per-sample readings (power, air quality, water, HVAC). Project policy is that raw readings never leave the campus / laptop; only reports go to the fog (Supabase). Sending the paper prompts to a hosted API would break that rule.
- **Anonymising breaks the comparison.** Removing or synthesising the readings changes the task, so the API model would not be reading the same cases as the edge models.
- **It cannot be reproduced.** Hosted models change versions and are not bit-deterministic, so the ceiling number could not be regenerated later. Every other arm in the paper can be rerun from frozen sets and frozen GGUFs.
- **It is outside the system being studied.** The research question is about escalation on an offline edge device. An API arm needs a network link and per-call cost that the deployed system is designed to avoid.
- **Cost and rate limits:** 468 cases × several prompt variants × 2–6k tokens adds up, and long runs hit rate limits.

## What the paper uses instead

- **Oracle trigger (RQ3):** escalate exactly when the full path is right and the cheap path is wrong. It gives 81.5 % both-correct against 70.2 % for the best real trigger, which shows the headroom routing could gain.
- **Mode 2-fair:** the same reasoner reading raw evidence without agents. It shows what the agents add (missed criticals 22/88 without agents vs 6/88 with).
- **Future work:** a fine-tuned larger model on a bigger GPU, or a campus-hosted server (data stays on campus), is the right ceiling.
