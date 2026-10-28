# Evidence website: specification (agreed with the user 2026-10-19 via AskUserQuestion)

**Audience.** The professor/evaluators of "Agentic Edge AI for Smart Cities" (QIDK, SM8650). They asked:
*"Against what did you measure accuracy, why does it matter, why is it better than the status quo? Show data,
plots, comparisons."* and *"Give us the data and test cases you measured against."* (HANDBOOK 2.36.)
**The site must answer every such question with a chart, and the text only supports the chart.**

## Hard requirements
1. **Static site.**
   - Deploy folder: `Website/dist/`, on Cloudflare Pages.
   - No server code, no CDN at runtime: every library is vendored into `dist/vendor/`.
2. **Password-only access.**
   - The password is verified with a **bcrypt** hash stored in the site (`bcryptjs`, cost 12).
   - **Every content file is AES-256-GCM encrypted** with a key from PBKDF2-SHA256 (600,000 iterations, random salt) over the same password. That covers page bodies, data JSON and images.
   - Build: `SITE_PASSWORD=... python Website/build/build.py`. The password is never written in plain text anywhere. Agents test with the throwaway password `test-only-pw`.
   - After unlock, the derived key is kept in `sessionStorage` only, cleared when the tab closes. There is a "lock" button.
3. **Data policy (updated 2026-10-19, user):** the raw cleaned SCRC sensor data IS included, encrypted, in a Raw data explorer (`#/rawdata`, linked from Proofs).
   - Occupancy rooms appear as codes (Room A, B…), never real room IDs.
   - Year view at hourly resolution, any day at full 5-min detail.
   - Overlays: thresholds, breaches with reasons, train/dev/test months, held-out sensors, and the windows used as training bases.
   - Training/eval prompts may be shown as examples.
   The policy below applies to everything outside `data/raw/`.
3b. **Original data policy.**
   - **No raw data:** no original sensor series, no CSV readings, and no prompts or windows containing sensor values (the training/eval prompts contain them, so they're excluded).
   - **Everything else is in:** all statistics, results, per-sample scores and labels (without input values), manifests, decision logs, training logs, timings, configs.
   - Occupancy appears only as aggregates.
   - Compressed (gzip) before encryption.
4. **Deck = home page.**
   - Upload **.pdf** (exact; rendered with pdf.js) or **.pptx** (best effort, in-browser renderer). The box says "PDF looks exactly like your deck".
   - Full-screen slideshow: arrow keys, click, swipe, slide counter.
   - Held in memory only and forgotten on reload; never uploaded anywhere.
5. **Pages** (one floating pill nav): **Deck · Route · Decisions · Proofs · Q&A**.
   - A visible **"Start here"** path takes a first-time visitor through Route → Decisions → Q&A.
6. **Charts:**
   - **Interactive**, drawn in the browser by **Apache ECharts** (vendored) from JSON in `data/`.
   - Hover shows exact values, **n** and the **95% CI** where one exists.
   - Each chart has a "source" link to the proof file it came from and the script that made it.
7. **Look** (model: jamiandcorp.com, but calmer):
   - charcoal background, one floating pill nav, monospace small-caps labels, white/silver text;
   - **one blue accent = "our choice / our result"** in every chart; grey = alternatives and baselines;
   - motion is short fades only: no 3D, no scroll-jacking, no parallax;
   - **no small unnecessary texts, no unnecessary headings.**

## Design system (all pages use it; SHELL agent owns it)
- **Tokens** (`src/css/tokens.css`):
  - colours: `--bg #141518`, `--panel #1c1d21`, `--line #2a2c31`, `--text #e9e9ea`, `--muted #9a9ca3`, `--accent #4c7dff` (ours), `--alt #6b6e76` (alternatives), `--good #3fbf7f`, `--warn #e0a33a`, `--bad #e5534b`;
  - fonts: body `Inter`/system sans, labels `JetBrains Mono` (vendored woff2, or system mono fallback);
  - **Contrast ≥ 4.5:1** for all text.
- **Type:**
  - one statement per section, as a big number or one line (≤ 12 words);
  - supporting one-liners ≤ 20 words;
  - label text in monospace small caps, letter-spaced.
- **Chart kit** (`src/js/charts.js`): wrappers over ECharts so every chart looks alike.
  - Chart types: `bar`, `stackedBar`, `line`, `waterfall` (latency route), `scatter`, `boxplot`, `heatmap`, `ciDot` (point + 95% CI), `sankey`/`funnel` (where it fits), `timeline`.
  - Ours = accent, others = `--alt`; axis labels mono; tooltips show value, n, CI and the source file.
  - Responsive, readable at 360 px.
  - Charts are drawn only when scrolled into view (IntersectionObserver), to keep the page light.
- **Card** = chart + **one-line claim above it** (the takeaway) + **one-line "why it matters" below it** + a "source" chip.
  Optional: a "what we rejected" chip that opens the alternative's chart.

## Behavioural UX principles (apply everywhere)
- **Anchor first.** Every page opens with its single most important number, e.g. "47 s → 21 s". People judge everything after against the first number.
- **Before → after.** Show the baseline next to ours (contrast effect); never "ours" alone.
- **Loss framing for rejected options.** "Without the 12 h check we miss 1 in 5 old steps."
- **Chunking / progressive disclosure.** ≤ 5 nav items, ≤ 7 cards per screen; details on click. Avoid choice overload.
- **Default path.** The "Start here" guided order and "Next →" at the end of each page; a visitor never wonders what to read next.
- **Credibility cues.** n, CI, p-values and test conditions sit right on the chart, and the source is one click away. Honest limits are stated (this builds trust).
- **Answer the doubt where it arises.** Each decision card answers "why not the alternative?" in place.
- **Peak-end.** Each page ends on a strong, concrete result plus the next step.
- **Low effort.** No jargon without a hover definition (glossary tooltips for NPU, htpd, Mode 1/2/3, etc.).

## Data contract (DATA agent owns it; pages only read it)
- Plain JSON lives in `Website/data/` (gitignored, local only). The build encrypts it into `dist/data/*.enc`.
- **`data/catalog.json`:** a list of every dataset, as
  `{id, title, topic, unit, n, source_files:[...], script, generated_at, notes}`.
- **Topics:** `latency`, `hardware`, `accuracy`, `agent_design`, `refinement`, `training_v2`, `dataset_v2`, `app_ux`, `ops` (crashes, sleep, thermals), `timeline`.
- **One file per dataset:** `data/<topic>/<id>.json` = `{meta:{...same as the catalog entry...}, series:[...], ci:[...]?}`, shaped for the chart kit.
- **`data/decisions.json`:** every decision we took **and** every one we rejected:
  `{id, date, title, chosen, rejected:[{option, why_not, evidence_id}], why, evidence_ids:[...], handbook_section, status: kept|replaced|pending}`.
  Mine HANDBOOK.md (all 2.x sections), `proofs/*/RESULTS.md`, `training/RETRAIN_V2_SPEC.md` and this session's work.
- **`data/route.json`:** the chronological journey, as
  `{date, phase, what, outcome: kept|dropped|pending, metric_before, metric_after, evidence_id}`.
  Plus a dedicated latency route: every latency step, from Genie CLI to the htpd v6 prefix cache / NEON argmax, with its measured effect, and the ideas tried and rejected.
- **`data/qa.json`:** professor questions → `{q, short_answer (one line), evidence_ids, decision_id?}`.
  At least 40 questions, covering:
  - accuracy vs what;
  - why not GPU;
  - why NPU;
  - why fine-tune;
  - why 4 h;
  - false alarms;
  - latency breakdown;
  - status quo;
  - data, test sets and leakage;
  - training data composition;
  - thermals and power;
  - safety and human approval;
  - limits;
  - what's next.
- **`data/status.json`:** current position (training step, losses, ETA as of build time, app version, what is deployed on the QIDK).
- **Data packs:** `data/packs/*.json.gz` (aggregates and per-sample scores, never raw) for "download the numbers".

## Folder layout
```
Website/
  SPEC.md
  build/build.py          collect -> validate -> gzip -> encrypt -> dist/ (+ bcrypt hash, salt)
  build/collect/*.py      one collector per topic (DATA agent)
  src/index.html          shell: gate, nav, router (hash routes #/deck #/route #/decisions #/proofs #/qa)
  src/pages/*.html|js     one per page
  src/css/, src/js/, src/vendor/ (echarts, pdf.js + worker, pptx renderer, bcryptjs, fonts)
  data/                   plain JSON (gitignored)
  dist/                   deployable (encrypted), _headers file for Cloudflare (no-cache for index.html, CSP)
```

## Quality gates (each agent, before reporting)
- **Correctness:** every number shown traces to a source file in `proofs/` or the repo (spot-check script `build/verify.py`).
- **Works:** the page works after `python build/build.py` with `SITE_PASSWORD=test-only-pw`; wrong passwords are rejected; `dist/` files are unreadable.
- **Layout and accessibility:** no horizontal scroll at 360 px; legible at 1440 px and on a 1920×1080 projector. Keyboard navigation, focus states, `prefers-reduced-motion` honoured.
- **Performance:** no console errors; first unlock under 3 s on the laptop.
- **Evidence:** screenshots saved in `Website/qa/` (headless Chrome works: `chrome.exe --headless=new --screenshot`).
