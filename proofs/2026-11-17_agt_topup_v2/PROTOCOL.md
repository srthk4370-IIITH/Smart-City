# Agent tool protocol (agt_v3 top-up v2)

Status: DEFINED and TRAINED by the top-up v2 data (not yet in the app). The app side implements exactly this; `gen_tools.py` (render_* functions) is
the byte reference, `checks_v2.py` the validator. Do not deploy a v2 model to the board without this app support: the model may answer a prompt
with a tool call, and an app that treats that as a final answer would discard it.

## 1. Chat template (Llama 3.2, the template the agent is already trained and served with)

The conversation is ONE prompt string, extended turn by turn (no re-render, the prefix stays byte-identical so the KV cache is reused):

```
<|begin_of_text|><|start_header_id|>system<|end_header_id|>\n\n{system}<|eot_id|>
<|start_header_id|>user<|end_header_id|>\n\n{user}<|eot_id|>
<|start_header_id|>assistant<|end_header_id|>\n\n                    <- generation 1
{"tool": "get_history", "args": {"hours": 12}}<|eot_id|>              <- model output 1 (a tool call)
<|start_header_id|>ipython<|end_header_id|>\n\n{tool result}<|eot_id|>  <- the app appends this
<|start_header_id|>assistant<|end_header_id|>\n\n                    <- generation 2
{"pattern": "gradual_decrease", ... "action": "none"}<|eot_id|>      <- final answer (or a second call)
```

Choice: role **`ipython`** (the Llama 3.1/3.2 tool-result role, a header the base tokenizer and chat template already know; the system prompt is NOT
changed, so every existing prompt and the Go builder stay byte-identical). Rejected: a `user` turn "TOOL RESULT:" (indistinguishable from a real user
turn, no stop-rule benefit) and any change of the system text (would re-shift every replay row and the app builder).
`system` and `user` are exactly what `BuildAgentPromptV3` produces today. No tool list is in the system prompt: the model learned the three tools
and WHEN to call them from the data.

Training rows: the trainer only knows prompt -> completion, so every assistant turn is one row (loss on that completion only): turn `call`
(prompt = turn-1 prompt), turn `final` (prompt = turn-1 prompt + call + `<|eot_id|>` + ipython header + result + `<|eot_id|>` + assistant header).
A chain of two calls has a middle `call` row whose prompt already contains the first call and result.

## 2. Generation settings

* Generation 1 (and generation 2 after a first tool result): prefill **`{"`** (not `{"pattern": "`). The model continues with `tool": ...` (a call)
  or `pattern": "...` (an answer). Stop rules: `<|eot_id|>`; `"action"` for answers (the existing app stop rule/trim at `"action"` stays).
* Detection: the generated text parses as JSON (after the trim rule) and has the key `tool` -> tool call; otherwise it is the answer (existing path).
* After the SECOND call result (and after any first result when you want to forbid a second call) generate with the old prefill `{"pattern": "`: the
  answer is forced. **Max 2 tool calls per agent run**; a third call is never executed (force the answer prefill).
* Budget (board agent_ctx 1280 hard limit): every prompt, including the tool results, must be <= 904 tokens (904 + 240 new + 136 headroom = 1280).
  All training rows satisfy this. If the app's prompt for a sensor is already > 904 tokens it must not enable the protocol for it (replay data
  shows ~45 % of the old 12 h real windows exceed it: they never fit the board anyway).

## 3. Tools (JSON exactly as `json.dumps(obj)` prints: `, ` and `: ` separators, no trailing text)

| call | args | result (assistant never sees anything else) |
|---|---|---|
| `{"tool": "get_history", "args": {"hours": 6}}` or `12` | hours 6 or 12 only | below |
| `{"tool": "get_neighbors", "args": {}}` | none | below |
| `{"tool": "get_card", "args": {}}` | none | `RenderCardFull(card, place)` text, the same bytes the CARD block of a normal prompt has |

**get_history result** (continuous cards; the window is the last `hours` h ending at the same `end` as the first prompt, `n = hours * 12` points):
```
HISTORY {hours} h: {Mon 02 Jan 15:04} -> {15:04} IST, {n} x 5 min
[GAPS: ...]                       only if readings are missing in that window (same text as the normal GAPS line)
SERIES (30-min means): v1 ... v12          hours = 6   (12 equal-width means of the n points, `Fmt(v, dec)` of the card)
SERIES (hourly means): v1 ... v12          hours = 12
H2 {E2 text of the n-point window}         max = ... at HH:MM
H3 {E3 text}                               min = ...
H4 {E4 text}                               trend = ... (r2 ...)
H8 {E8 text}                               noise ..., longest flat run ..., plateau at max ...
```
The H lines are the E2/E3/E4/E8 lines of `EvidenceItemsV2` computed on the `n`-point window and re-labelled (`E2 ` -> `H2 `). E1 (last value) and
E9/E10 (the fixed 12 h view lines) are identical to the first prompt and are not repeated. (The full 12 h SERIES of 72 values plus ten E lines does not
fit the 1280 context behind a 700-token first prompt: this compact form is the board-budget version of "the same SERIES/EVIDENCE lines for the longer window".)

**get_neighbors result** (related sensors from the site graph: same room/equipment first, then same-type peers on the same floor; max 3; their latest
finding or "normal stable" when nothing is known; `last` = latest value with its unit):
```
N1 {node} | {metric short name} | {status} | {pattern} | last {value} {unit}
N2 ...
```
or the single line `no related sensors`. (`status`/`pattern` are the vocabulary of the agent JSON.)

**get_card**: used when the first prompt carries the withheld-card marker. In that mode (token budget) the app sends the CARD block cut to its
first line plus one marker line:
```
CARD: {quantity} [{unit}], {kind}, {context} ({place})
  details withheld (limits, noise, behaviour): call get_card
```
and the model answers `{"tool": "get_card", "args": {}}`; the result is the full CARD text (its first line equals the first line shown).

## 4. When the model calls (what the data teaches; gold = simulator truth)

| situation (first prompt) | call | final answer uses |
|---|---|---|
| event onset before the window start (E9 12 h view names a shift/excursion earlier than WINDOW start; a short window shows only the tail) | get_history 6 or 12 | the longer series and the H lines (cited as H2/H3/H4/H8) |
| slow ramp ambiguous in a short window (trend tiny in 1.5 h, a drift only visible over hours) | get_history | same |
| data gap / uncertain data quality (GAPS in the short window) | get_history 12 | same, incl. the GAPS line of the long window |
| lone instant step inside the card max_step (real event or sensor bias?) | get_neighbors | a neighbour sees the same step -> event, status from the card limits; all neighbours calm -> sensor_fault/bias citing N1 (the second evidence kind) |
| CARD marker present | get_card (first, deterministic) | the card limits; may be followed by get_neighbors (2 calls) |
| everything else (onset inside the window, clear fault signature, ordinary event, 12 h real windows) | none: answer directly | existing behaviour |

Rule used by the labels: `sensor_fault` needs a second evidence kind beyond a plateau or an instant step: an impossible value, a rate above the card max_step,
a flat-run/erratic signature, a DQ flag, or neighbour disagreement.

## 5. What the app must do

1. Build the first prompt as today (`BuildAgentPromptV3`), generate with prefill `{"`.
2. If the output is a tool call: validate (tool name, args), execute with the renderers above (same bytes as `gen_tools.py` / this file), append
   `call + <|eot_id|> + ipython header + result + <|eot_id|> + assistant header` to the prompt, generate again (<= 2 calls; last generation with the
   `{"pattern": "` prefill). Unknown tool or malformed call: ignore the call and re-run the old path (prefill `{"pattern": "`) on the first prompt.
3. Check the context: first prompt + calls + results <= 904 tokens, otherwise skip the call and answer directly with the old path.
4. Evidence ids a final answer may cite: E1-E10 of the first prompt, H2/H3/H4/H8 of a history result, N1-N3 of a neighbours result, GAPS; the existing id
   validator must accept `H*` and `N*`.
5. Host-side equivalent of this loop for evaluation: `hosteval_tool.py` (turn 1 free, `tool_t1.jsonl`) + `hosteval.py` on `tool_t2.jsonl` (turn 2 with the
   gold call and result forced).
