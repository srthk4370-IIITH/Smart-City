# Reasoner round 2 on Kaggle: owner steps

The notebook continues training from **our round-1 adapter (ckpt_step0612)**. Base Qwen3.5-4B (downloaded from the HF hub and
SHA256-checked against the laptop copy) is used only as the frozen NF4 backbone and as the paraphrase/replay generator.

Files: `rsn_r2_bundle.zip` (125.3 MB, md5 in `rsn_r2_bundle.zip.md5`) and `round2_kaggle.ipynb` (same code as `round2_kaggle.py`).

## 1. Create the private dataset (once)
1. kaggle.com -> **Datasets** (left bar) -> **+ New Dataset**.
2. Drag in `rsn_r2_bundle.zip`. Title: `rsn-r2-bundle`. Visibility: **Private**. Click **Create**.
   Kaggle extracts the zip automatically; wait until the dataset page says it's ready.

## 2. Create the notebook
1. **Code** (left bar) -> **+ New Notebook**.
2. **File -> Import Notebook** -> upload `round2_kaggle.ipynb` -> Import.
3. Right panel, **Session options**: Accelerator **GPU T4 x2** (not P100). Internet **On** (needs a phone-verified account).
   Persistence: leave as is.
4. Right panel **Input -> + Add Input -> Your Datasets -> rsn-r2-bundle -> Add**.

## 3. Run
- Click **Save Version** (top right) -> **Save & Run All (Commit)** -> Save. It runs in the background, so you can close the tab.
- Expected time: about 10 min for setup and the base download, 1–1.5 h of generation (chat ~5k + replay 515), then about 6–9 h of
  training (around 3,400 examples, ~140 steps at accumulation 16). Training saves and exits at 11.3 h, before Kaggle's 12 h limit.
- The pre-flight check stops the run early with a clear message if the 612 adapter's loss under fp16 is not finite or is above 1.5.
  If that happens, send the log; don't retry.

## 4. If it says PARTIAL (the 12 h limit was hit)
Open the notebook -> **Edit** -> **+ Add Input -> Notebook Output Files** -> choose this same notebook's latest version -> Add.
Then **Save Version -> Save & Run All** again. It skips generation and resumes from the last 25-step checkpoint.

## 5. Download
Notebook page -> latest version -> **Output** tab -> download **`rsn_r2_adapter.zip`** (about 120 MB; the partial version is
`rsn_r2_adapter_PARTIAL.zip`). Save it to `C:\Users\hp\Downloads\`. Then tell the agent, or run the local import:
`wsl bash /mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-28_kaggle_round2/import_round2.sh /mnt/c/Users/hp/Downloads/rsn_r2_adapter.zip`
(this does the low-RAM merge to `Code/models_stage/rsn_v2_q4_0.gguf` with its md5, then waits for a free GPU before running RWH, P0 and severity agreement).
