# rsn_v3 on Kaggle: owner guide (click by click)

Kaggle trains the **4B candidate** (Qwen3.5-4B, LoRA r32/α64, from the base model). The laptop trains the 2B candidate on its own
and gates both (`kaggle/local/laptop_chain.sh`). You only need to handle Kaggle and one download per result.

Files you will use:
- **Bundle A**: `C:\Users\hp\Desktop\qidk\proofs\2026-10-29_rsn_v3\kaggle\build\r2\rsn_v3_bundle.zip`
  (15,329,659 bytes, md5 `d5efe71b8e04adb98539f59ef916bb36`). It holds 20,000 verified incident rows (compact targets), the
  chat dev/train question files for the dev score, the tools/store, and the scripts. Contents and flags are listed in `UPLOAD_MANIFEST.md`.
- **Notebook**: `C:\Users\hp\Desktop\qidk\proofs\2026-10-29_rsn_v3\kaggle\rsn3_kaggle.ipynb`
- **Bundle B** (later; the laptop builds it after its chat distillation finishes):
  `C:\Users\hp\Desktop\qidk\proofs\2026-10-29_rsn_v3\kaggle\build\r1\rsn_v3_chat_bundle.zip`, with its md5 in
  `rsn_v3_chat_bundle.zip.md5`. It holds the verified distilled chat rows and ~1,000 general replay rows.

## A. One-time account check
1. Go to kaggle.com and sign in.
2. Click your profile picture (top right) -> **Settings**. Under **Phone verification**, make sure the phone is verified.
   Without it you cannot use a GPU or turn Internet on.
3. Your weekly GPU quota (about 30 h) is shown at the top of the notebook editor's right panel.

## B. Upload bundle A as a private dataset (once)
1. In the left bar, click **Datasets** -> **+ New Dataset**.
2. Drag in `rsn_v3_bundle.zip` from `...\kaggle\build\r2\`.
3. Set the title to `rsn-v3-bundle` and **Visibility: Private**. Click **Create**.
4. Wait until the dataset page shows the file list. Kaggle unzips the file itself: you should see `BUNDLE_OK_RSN3`,
   `proofs/` and `base/`.

## C. Import the notebook (once)
1. In the left bar, click **Code** -> **+ New Notebook**.
2. In the editor, click **File -> Import Notebook**, choose `rsn3_kaggle.ipynb`, then click **Import**.
3. In the right panel, under **Session options**:
   - **Accelerator: GPU T4 x2** (not P100, not a single T4).
   - **Internet: On** (needed to download the base model and install the pinned packages).
   - **Persistence**: leave it as it is. Resuming works through the version output (step E), not persistence.
4. In the right panel, click **Input -> + Add Input -> Your Datasets -> rsn-v3-bundle -> Add**.
5. Rename the notebook (title at the top left) to `rsn3-kaggle`.

## D. Session 1: Save & Run All
1. Click **Save Version** (top right) -> select **Save & Run All (Commit)** -> **Save**.
2. The run continues in the background, so you can close the tab. To watch it, go to **Code -> Your Work -> rsn3-kaggle ->
   Versions**, open the running version, then open the **Logs** tab.
3. What session 1 does and prints:
   - About 10 min: package install and the base-model download. The log shows `rsn_v3 bundle r2 ...` and
     `bundle B (chat rows): not attached`.
   - About 30–45 min: the setup probe. It prints one `PROBE ...` line for each candidate setup:
     - 16-bit vs 4-bit base;
     - flash-linear-attention on vs off;
     - then 2 GPUs vs 1.

     Each line shows `tok_s`, `peak_vram_gib` and `loss`. Then it prints
     `PROJECTION: setup ... on N GPU(s), X tok/s -> epoch 1 A h, epoch 2 B h (~C sessions)`. **Send this line to the agent.**
   - The rest of the session: training on the incident rows of epoch 1. Each session stops itself at about 11.3 h.
4. At the end, the log shows `train rc 3 session time used up...`, or `train rc 4 incident part of epoch 1 done: attach bundle B...`.

## E. Every next session (resume)
0. **Before session 2 only:** the notebook was updated on 2026-10-30 (faster `causal_conv1d` kernel, checked against the reference;
   removed again if it does not match). In the editor click **File -> Import Notebook**, choose the new `rsn3_kaggle.ipynb`, and
   confirm replacing the cells. The probe choice and checkpoints live in the attached output, so nothing restarts.
   Import can drop the inputs: afterwards check the right panel lists **rsn-v3-bundle** (bundle A), the chat bundle (B, once
   ready) and the previous output; re-add any missing one. Attach the output of the last version that actually trained (about
   11 h run), not a version that failed in setup: a failed version's output has no checkpoints. Sessions after this one
   install `causal_conv1d` from `wheels/` in the attached output instead of a 12 min build.
1. Open the notebook editor (**Code -> rsn3-kaggle -> Edit**).
2. In the right panel, click **Input -> + Add Input -> Notebook Output Files**, then choose **rsn3-kaggle**, its **latest version**
   -> **Add**. If an older version's output is already attached, remove it first (the **⋮** menu next to it -> **Remove**).
3. Click **Save Version -> Save & Run All (Commit)**. The run resumes from the last 25-step checkpoint and keeps the probe's
   choice.

## F. Adding bundle B (when the agent says it is ready, after session 1)
1. In the left bar, click **Datasets** -> **+ New Dataset**, drag in `rsn_v3_chat_bundle.zip`, set the title to `rsn-v3-chat` and
   **Private**, then click **Create**.
2. In the notebook editor, click **Input -> + Add Input -> Your Datasets -> rsn-v3-chat -> Add**. Keep `rsn-v3-bundle` and the
   previous version's output attached as well.
3. Click **Save Version -> Save & Run All**. The log shows `bundle B (chat rows): rsn_v3 chat bundle ...` and
   `resumed at step N (schedule mixed ...)`. The incident rows not trained yet and the chat and replay rows are now mixed for the
   rest of epoch 1.
4. Keep both datasets attached in every later session.

## G. When training ends: download
The log ends with one of these lines:
- `EPOCH 1 DONE ...` (rc 5): the normal end.
- `EARLY STOP ...` (rc 6): the dev score stopped improving.
- `plan done` (rc 0): only after an epoch-2 run.

Then:
1. Open the version page -> **Output** tab (or **Data -> Output**).
2. Download **`rsn_v3_adapter_best.zip`** (the checkpoint with the best dev score). Also download **`rsn_v3_adapter_epoch1.zip`** if
   it is there.
3. Save them **unchanged** in `C:\Users\hp\Downloads\`. The laptop chain watches this folder for `rsn_v3_adapter_best*.zip`,
   `rsn_v3_adapter_final*.zip` and `rsn_v3_adapter_epoch1*.zip`. It then imports the adapter, converts it to Q4_0, gates it
   against rsn_v1 (RWH, RWH-2, dev, chat dev v3) and compares it with the 2B. The winner is written to
   `kaggle/READY_FOR_BOARD_<id>.json`. The board steps still need your approval.
4. `rsn_v3_adapter_PARTIAL.zip` is only the latest mid-run checkpoint and is ignored by the chain.

## H. Epoch 2 (only if the agent says the epoch-1 gate failed)
1. In the notebook's first code cell, change `RUN_E2 = False` to `RUN_E2 = True`.
2. Attach the latest output as in E.2, then click **Save Version -> Save & Run All**.
3. When it ends, download `rsn_v3_adapter_final.zip` (or `_best`) into `C:\Users\hp\Downloads\`.

## Troubleshooting
- **"bundle A not attached"**: in E.2 or C.4 the dataset was not added. Add `rsn-v3-bundle`.
- **"no setup fits / numerics wrong"**: the probe failed for every setup. Send the log to the agent and don't retry.
- **GPU or Internet options are greyed out**: the phone is not verified (A.2), or the weekly GPU quota is used up (wait for the
  weekly reset).
- **"multi-GPU run failed before its first checkpoint: one GPU from now on"**: training continues at about half speed. Tell the agent.
- **The session started over from the beginning**: the previous version's output was not attached (E.2). Stop the version
  (**Versions -> ⋮ -> Cancel**), attach the output and commit again.
- **"WARNING: a different bundle B is attached"**: only the first bundle B is used. Ask the agent before changing it.
- **The log ends with `ERROR: send train.log`**: download `rsn_v3_adapter_PARTIAL.zip` (it contains the log) and send it to the agent.
