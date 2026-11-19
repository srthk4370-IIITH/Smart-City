"""rsn_v3 QLoRA/LoRA SFT of Qwen3.5-4B from the BASE (derived from round-1 train_rsn.py: same loss, LoRA targets, warmup+cosine).
Changes vs round 1: rank 32 / alpha 64; max length 6144; per-row tools (incident -> tools_v4 "incident", chat -> "chat") and
per-row thinking (incident: enable_thinking=False as rsn_v1; chat: True, target holds the <think> block, empty on lookups);
loss only on the current turn; data-parallel over all visible GPUs (torchrun; one gradient all-reduce per optimizer step =
single-GPU accumulation of --accum rows); fp16 + GradScaler on GPUs without bf16 (T4); dev loss every --eval-every steps.

Two data sources and a curriculum (TIME_MODEL.md):
- --inc (bundle A, always) and --chat (bundle B, optional: arrives later). The plan is a list of optimizer-step groups
  (schedule.json, deterministic, resumable). Without chat: epoch 1 = incident rows only (shuffled); when those run out the
  run saves and exits 4 (WAIT_CHAT). When --chat first appears at step s, the incident rows not yet trained on are
  shuffled together with the chat rows into the rest of epoch 1 (groups before s are kept as they were).
- epoch 2 = only the weak/hard rows: incident rows of the --e2-families (rsn_v1's weak families, incl. their +tool/+inject
  variants) + chat rows with hard=true. It runs only with --run-e2; otherwise the run stops after epoch 1 (exit 5) with
  ckpt_epoch1 saved: the normal path when the gate already passes.
- LR: segment 1 (epoch 1) warmup 3% + cosine 1 -> 0.1, so the epoch-1 adapter is fully annealed; segment 2 (epoch 2) warmup
  3% to --e2-peak (0.5) x LR, cosine down to 0.05 x LR.
Probe (--probe-steps N): N optimizer steps on the 2 longest rows + random rows, no save; prints PROBE_RESULT {json} with tok/s
(all ranks, excluding the 2 warm-up rows), peak VRAM, loss, OOM and the projected hours of the plan. --no-fla blocks
flash-linear-attention (torch path) so both can be compared without reinstalling.
Overtraining control: every --gen-every steps a greedy generation eval on fixed slices (40 incident dev rows: parse /
severity / label; 40 chat dev records: verify_chat pass; + 20/20 train rows for the train/dev gap) -> gen_eval.jsonl;
best --keep-best checkpoints by the dev score (ckpt_best_XXXX, best.json); early stop after --patience evals without a
better score (only once chat rows are in the plan). LoRA dropout 0.05, weight decay 0.01.
Checkpoints are portable between Kaggle (fp16 + GradScaler) and the laptop (bf16, no scaler): LoRA weights are fp32 in both;
the scaler state is only restored into an fp16 run; schedule.json + step = the data cursor; torch RNG saved.
Exit codes: 0 plan done, 3 hours limit / STOP file, 4 waiting for chat rows, 5 epoch 1 done (stop after epoch 1), 6 early stop."""
import argparse
import datetime
import hashlib
import json
import math
import os
import random
import sys
import time

import torch

TARGETS = ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj", "in_proj_qkv", "in_proj_z", "in_proj_a",
           "in_proj_b", "out_proj"]
E2_FAMILIES = ["single_glitch", "drift_low", "insufficient", "recovery_gap", "stale_related", "coincidence", "class_fills", "acidic",
               "chatter", "outage", "indoor_emission", "agent_miss"]
SEG_TOKENIZE = os.environ.get("RSN3_SEG_TOKENIZE", "1") != "0"   # r2: 1 (default); r1 runs were 0 (one-pass tokenization)
RANK = int(os.environ.get("RANK", 0))
WORLD = int(os.environ.get("WORLD_SIZE", 1))
LOCAL = int(os.environ.get("LOCAL_RANK", 0))


def log(out, msg):
    if RANK:
        return
    line = "[%s] %s" % (time.strftime("%H:%M:%S"), msg)
    print(line, flush=True)
    with open(os.path.join(out, "train.log"), "a") as f:
        f.write(line + "\n")


def encode(tok, ex, tools, max_len):
    msgs = ex["messages"]
    kw = dict(tools=tools, tokenize=False, enable_thinking=bool(ex.get("think")))
    full = tok.apply_chat_template(msgs, **kw)
    spans = []
    # loss only on the current turn (assistant messages after the last user message): earlier turns are context, and
    # the template renders them without a think block, so a truncated render would not be a prefix of the full one
    last_user = max(i for i, m in enumerate(msgs) if m["role"] == "user")
    for i, m in enumerate(msgs):
        if m["role"] != "assistant" or i < last_user:
            continue
        g = tok.apply_chat_template(msgs[:i], add_generation_prompt=True, **kw)
        f = tok.apply_chat_template(msgs[:i + 1], **kw)
        if not (f.startswith(g) and full.startswith(f)):
            return None, "prefix"
        end = f.rindex("<|im_end|>") + len("<|im_end|>")
        spans.append((len(g), end))
    if SEG_TOKENIZE:
        # r2 fix (proofs/2026-11-02_2b_r2/DIAG.md): tokenize prompt and target pieces SEPARATELY, as inference does (the
        # prompt "...<think>\n" is tokenized on its own, then the model generates). One-pass tokenization merged the
        # "\n" that ends the generation prompt with the next "\n" ("<think>\n\n</think>" -> "\n\n" token straddling the
        # boundary), so the empty-think decision token was never labelled and the model never learned to close the block.
        ids, labels, pos = [], [], 0
        for s, e in spans:
            if s > pos:
                p = tok(full[pos:s], add_special_tokens=False)["input_ids"]
                ids += p
                labels += [-100] * len(p)
            t = tok(full[s:e], add_special_tokens=False)["input_ids"]
            ids += t
            labels += list(t)
            pos = e
        if pos < len(full):
            p = tok(full[pos:], add_special_tokens=False)["input_ids"]
            ids += p
            labels += [-100] * len(p)
        if len(ids) > max_len:
            return None, "too_long"
        if not any(l != -100 for l in labels):
            return None, "no_labels"
        return (ids, labels), None
    enc = tok(full, return_offsets_mapping=True, add_special_tokens=False)
    ids = enc["input_ids"]
    labels = [-100] * len(ids)
    for k, (a, b) in enumerate(enc["offset_mapping"]):
        for s, e in spans:
            if a >= s and b <= e and b > a:
                labels[k] = ids[k]
    if len(ids) > max_len:
        return None, "too_long"
    if not any(l != -100 for l in labels):
        return None, "no_labels"
    return (ids, labels), None


def md5(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()[:12]


def prep(tok, path, tools, max_len, out, name):
    """tokenize once per input file (cache keyed by the file's md5); rows keep id, kind, family, hard"""
    cache = os.path.join(out, "%s_%s%s_tok.pt" % (name, md5(path), "_seg" if SEG_TOKENIZE else ""))
    if os.path.exists(cache):
        return torch.load(cache, mmap=LEAN_MMAP), cache
    data, skipped = [], {}
    for line in open(path, encoding="utf-8"):
        ex = json.loads(line)
        r, why = encode(tok, ex, tools.get(ex["tools"]), max_len)
        if r is None:
            skipped[why] = skipped.get(why, 0) + 1
            continue
        data.append({"id": ex["id"], "kind": ex["tools"], "family": ex.get("family", ""), "hard": bool(ex.get("hard")),
                     "ids": torch.tensor(r[0], dtype=torch.int32), "labels": torch.tensor(r[1], dtype=torch.int32)})
    torch.save(data, cache + ".part")
    os.replace(cache + ".part", cache)
    L = sorted(int(d["ids"].numel()) for d in data)
    print("prep %s: %d kept, skipped %s; tokens mean %d p50 %d p90 %d max %d, total %.1fM" % (
        os.path.basename(path), len(data), skipped, sum(L) / len(L), L[len(L) // 2], L[int(len(L) * .9)], L[-1], sum(L) / 1e6), flush=True)
    return data, cache


# ---- 6 GB fit levers (2026-11-06, proofs/2026-11-06_4b_local/FIT.md); all off by default, so the 2B / Kaggle paths are unchanged.
HEAD = None     # HeadCPU when --head-cpu
LEAN_MMAP = False   # --lean-host: token caches memory-mapped (file-backed pages, not anonymous RAM)


class _StreamCE(torch.autograd.Function):
    """sum of cross_entropy(h @ W.T) over label rows, W = the frozen tied embed/lm_head weight held in pinned CPU RAM and streamed
    to the GPU in vocab chunks. Same math as head(h).float() + cross_entropy(reduction="sum"): bf16 logits matmul, fp32
    log-softmax; one streamed pass yields the loss AND dL/dh (online softmax with flash-style rescaling), so W crosses PCIe once."""
    @staticmethod
    def forward(ctx, h, y, W, chunk):
        """W: the HeadCPU (pinned row pieces); chunk: vocab rows per GPU matmul"""
        dev, N = h.device, h.shape[0]
        need = ctx.needs_input_grad[0]
        m = torch.full((N,), -float("inf"), device=dev)
        s = torch.zeros(N, device=dev)
        tgt = torch.zeros(N, device=dev)
        g = torch.zeros(N, h.shape[1], device=dev) if need else None
        cs = HEAD.stream
        cur = torch.cuda.current_stream(dev)

        spans = [(c0, i, o) for i, pc in enumerate(W.pieces) for o in range(0, pc.shape[0], chunk)
                 for c0 in [i * W.R + o]]

        def fetch(k):
            _, i, o = spans[k]
            with torch.cuda.stream(cs):
                wc = W.pieces[i][o:o + chunk].to(dev, non_blocking=True)
                ev = torch.cuda.Event()
                ev.record(cs)
            return wc, ev
        nxt = fetch(0)
        for k, (c0, _, _) in enumerate(spans):
            wc, ev = nxt
            cur.wait_event(ev)
            wc.record_stream(cur)
            if k + 1 < len(spans):
                nxt = fetch(k + 1)
            z = (h @ wc.t()).float()
            mn = torch.maximum(m, z.max(1).values)
            a = torch.exp(m - mn)
            p = torch.exp(z - mn[:, None])
            s = s * a + p.sum(1)
            if need:
                g = g * a[:, None] + (p.to(h.dtype) @ wc).float()
            m = mn
            sel = (y >= c0) & (y < c0 + wc.shape[0])
            if sel.any():
                idx = sel.nonzero().squeeze(1)
                tgt[idx] = z[idx, y[idx] - c0]
            del z, p
        lse = m + torch.log(s)
        if need:
            wy = W.rows(y.cpu()).to(dev).float()
            ctx.save_for_backward((g / s[:, None] - wy).to(h.dtype))
        return (lse - tgt).sum()

    @staticmethod
    def backward(ctx, go):
        (gh,) = ctx.saved_tensors
        return gh * go.to(gh.dtype), None, None, None


class HeadCPU:
    """--head-cpu: the tied embed_tokens/lm_head weight (248k x hidden bf16, 1.2 GB for the 4B) lives in pinned CPU RAM.
    Input embeddings = a CPU row gather; the loss = _StreamCE. park()/unpark() move it off/back for generation evals."""
    def __init__(self, inner, dev):
        self.p = inner.model.embed_tokens.weight
        assert inner.lm_head.weight is self.p, "--head-cpu needs tied embeddings"
        V, H = self.p.shape
        # pinned pieces of <= 64 MiB: torch's pinned host allocator rounds each block up to a power of two (one 1.2 GB block -> 2 GB)
        self.R = max(1, (64 << 20) // (H * self.p.element_size()))
        self.pieces = []
        for o in range(0, V, self.R):
            t = torch.empty((min(self.R, V - o), H), dtype=self.p.dtype, pin_memory=True)
            t.copy_(self.p.data[o:o + self.R])
            self.pieces.append(t)
        self.shape, self.dtype = (V, H), self.p.dtype
        self.dev, self.stream = dev, torch.cuda.Stream(dev)
        self.park()

    def park(self):
        self.p.data = torch.empty(0, dtype=self.dtype)       # freed on the GPU; the weight lives in self.pieces only
        torch.cuda.empty_cache()

    def unpark(self):
        w = torch.empty(self.shape, dtype=self.dtype, device=self.dev)
        for i, t in enumerate(self.pieces):
            w[i * self.R:i * self.R + t.shape[0]].copy_(t)
        self.p.data = w

    def rows(self, idx):
        """W[idx] gathered on the CPU (idx: CPU long tensor of any shape)"""
        flat = idx.reshape(-1).long()
        out = torch.empty((flat.numel(), self.shape[1]), dtype=self.dtype)
        piece = flat // self.R
        for i in piece.unique().tolist():
            m = piece == i
            out[m] = self.pieces[i][flat[m] - i * self.R]
        return out.reshape(*idx.shape, self.shape[1])

    def embed(self, x2d):
        e = self.rows(x2d).to(self.dev)
        return e.requires_grad_(torch.is_grad_enabled())   # checkpointed layer 0 needs a grad-requiring input (= enable_input_require_grads)

    def ce(self, hs, ys):
        n = max(1, hs.shape[0])
        chunk = max(2048, min(self.R, (1 << 24) // n // 256 * 256))
        return _StreamCE.apply(hs, ys, self, chunk)


class _OffloadCkpt(torch.autograd.Function):
    """--ckpt-offload: checkpoint of one decoder layer whose saved input (the only per-layer activation kept between forward
    and backward) goes to pinned CPU RAM; backward brings it back, recomputes the layer with the same RNG state (dropout) and
    backpropagates through it (reentrant-style; layer 0's input requires grad via HeadCPU.embed / enable_input_require_grads)."""
    @staticmethod
    def forward(ctx, fn, x):
        ctx.fn, ctx.dev = fn, x.device
        ctx.rng, ctx.crng = torch.get_rng_state(), torch.cuda.get_rng_state(x.device)
        ctx.shape, ctx.dtype = x.shape, x.dtype
        ctx.bufs, flat = [], x.detach().reshape(-1)
        for o in range(0, flat.numel(), _HOST_BUF // x.element_size()):
            part = flat[o:o + _HOST_BUF // x.element_size()]
            b = _host_buf(x.dtype)
            b[:part.numel()].copy_(part, non_blocking=True)
            ctx.bufs.append((b, part.numel()))
        with torch.no_grad():
            return fn(x)

    @staticmethod
    def backward(ctx, go):
        x = torch.cat([b[:n].to(ctx.dev, non_blocking=True) for b, n in ctx.bufs]).view(ctx.shape).requires_grad_(True)
        torch.cuda.current_stream(ctx.dev).synchronize()
        _HOST_FREE.extend(b for b, _ in ctx.bufs)
        ctx.bufs = None
        with torch.random.fork_rng(devices=[ctx.dev]):
            torch.set_rng_state(ctx.rng)
            torch.cuda.set_rng_state(ctx.crng, ctx.dev)
            with torch.enable_grad():
                out = ctx.fn(x)
        torch.autograd.backward(out, go)
        return None, x.grad


_HOST_FREE = []          # reusable pinned 8 MiB buffers (exact power of two: no allocator round-up; bounded, reused every row;
_HOST_BUF = 8 << 20      # a layer input of T x 2560 bf16 takes ceil(T x 5120 B / 8 MiB) of them: 7229 tokens -> 5 = 40 MiB)


def _host_buf(dtype):
    for i, b in enumerate(_HOST_FREE):
        if b.dtype == dtype:
            return _HOST_FREE.pop(i)
    return torch.empty(_HOST_BUF // torch.empty(0, dtype=dtype).element_size(), dtype=dtype, pin_memory=True)


def host_trim():
    """return freed heap to the OS (model loading leaves several hundred MB of freed-but-held glibc heap)"""
    import ctypes
    import gc
    gc.collect()
    try:
        ctypes.CDLL("libc.so.6").malloc_trim(0)
    except OSError:
        pass


def host_rss_mb():
    try:
        return int(open("/proc/self/statm").read().split()[1]) * os.sysconf("SC_PAGE_SIZE") >> 20
    except Exception:
        return -1


OFFLOAD_MIN = 0          # --offload-min: forwards of <= this many tokens use the plain non-reentrant checkpoint (exact: same recompute)


def _offload_ckpt(fn, *args):
    assert len(args) == 1, "decoder layers take hidden_states as the only positional arg"
    if args[0].shape[:-1].numel() <= OFFLOAD_MIN:
        from torch.utils.checkpoint import checkpoint
        return checkpoint(fn, args[0], use_reentrant=False)
    return _OffloadCkpt.apply(fn, args[0])


def apply_fit_levers(model, a, dev):
    """after get_peft_model: --head-cpu, --ckpt-offload, --mlp-chunk (exact; see FIT.md). Returns a log string."""
    global HEAD, OFFLOAD_MIN
    from torch.utils.checkpoint import checkpoint
    inner = model.get_base_model()
    done = []
    if getattr(a, "head_cpu", False):
        HEAD = HeadCPU(inner, dev)
        done.append("head-cpu")
    layers = inner.model.layers
    if getattr(a, "ckpt_offload", False):
        for l in layers:
            l._gradient_checkpointing_func = _offload_ckpt
        OFFLOAD_MIN = getattr(a, "offload_min", 0)
        done.append("ckpt-offload (forwards over %d tokens)" % OFFLOAD_MIN)
    n = getattr(a, "mlp_chunk", 0)
    lo = max(n, getattr(a, "mlp_chunk_min", 0))
    if n:
        for l in layers:
            f = l.mlp.forward

            def fwd(x, f=f):
                if not torch.is_grad_enabled() or x.shape[-2] <= n or x.shape[:-1].numel() <= lo:
                    return f(x)
                return torch.cat([checkpoint(f, x[..., i:i + n, :], use_reentrant=False) for i in range(0, x.shape[-2], n)], dim=-2)
            l.mlp.forward = fwd
        done.append("mlp-chunk %d (forwards over %d tokens)" % (n, lo))
    return ", ".join(done) or "none"


def hidden(model, x2d):
    """last hidden states for a [B, T] id tensor (CPU); embedding via HEAD when --head-cpu"""
    inner = model.get_base_model()
    if HEAD is not None:
        return inner.model(inputs_embeds=HEAD.embed(x2d), use_cache=False).last_hidden_state
    return inner.model(input_ids=x2d.to(next(inner.model.layers.parameters()).device), use_cache=False).last_hidden_state


def _lab(ids, labels):
    """--lean-host stores labels as a bool mask (label = the token id wherever it is trained): rebuild the int labels exactly"""
    return torch.where(labels, ids, -100) if labels.dtype == torch.bool else labels


def loss_fn(model, ids, labels, dev):
    """hidden states once; lm_head + CE only at label positions, in checkpointed chunks (never full 248k-vocab logits)"""
    from torch.utils.checkpoint import checkpoint
    labels = _lab(ids, labels)
    inner = model.get_base_model()
    y = torch.cat([labels[1:].long(), torch.tensor([-100])]).to(dev)
    keep = (y != -100).nonzero().squeeze(1)
    if HEAD is not None:
        h = hidden(model, ids.long().unsqueeze(0))[0]
        return HEAD.ce(h[keep], y[keep]), int(keep.numel())
    x = ids.long().unsqueeze(0).to(dev)
    h = inner.model(input_ids=x, use_cache=False).last_hidden_state[0]
    hs, ys = h[keep], y[keep]
    head = inner.lm_head

    def ce(hc, yc):
        return torch.nn.functional.cross_entropy(head(hc).float(), yc, reduction="sum")
    tot = 0.0
    for i in range(0, hs.shape[0], 128):
        tot = tot + checkpoint(ce, hs[i:i + 128], ys[i:i + 128], use_reentrant=False)
    return tot, int(keep.numel())


def micro_batches(exs, budget):
    """longest first; greedy groups whose padded size (rows x longest row) stays <= budget tokens"""
    exs = sorted(exs, key=lambda e: -len(e["ids"]))
    out, cur = [], []
    for e in exs:
        if cur and (len(cur) + 1) * len(cur[0]["ids"]) > budget:
            out.append(cur)
            cur = []
        cur.append(e)
    if cur:
        out.append(cur)
    return out


def loss_fn_batch(model, ids_list, labels_list, dev):
    """loss_fn for several rows in one right-padded forward; returns [(loss_sum, n_label_tokens)] per row"""
    labels_list = [_lab(i, l) for i, l in zip(ids_list, labels_list)]
    if len(ids_list) == 1:
        return [loss_fn(model, ids_list[0], labels_list[0], dev)]
    from torch.utils.checkpoint import checkpoint
    inner = model.get_base_model()
    T = max(len(x) for x in ids_list)
    x = torch.zeros((len(ids_list), T), dtype=torch.long)
    for b, ids in enumerate(ids_list):
        x[b, :len(ids)] = ids.long()
    h = hidden(model, x) if HEAD is not None else inner.model(input_ids=x.to(dev), use_cache=False).last_hidden_state
    head = inner.lm_head
    if HEAD is not None:
        out = []
        for b, labels in enumerate(labels_list):
            y = torch.cat([labels[1:].long(), torch.tensor([-100])]).to(dev)
            keep = (y != -100).nonzero().squeeze(1)
            out.append((HEAD.ce(h[b][keep], y[keep]), int(keep.numel())))
        return out

    def ce(hc, yc):
        return torch.nn.functional.cross_entropy(head(hc).float(), yc, reduction="sum")
    out = []
    for b, labels in enumerate(labels_list):
        y = torch.cat([labels[1:].long(), torch.tensor([-100])]).to(dev)
        keep = (y != -100).nonzero().squeeze(1)
        hs, ys = h[b][keep], y[keep]
        tot = 0.0
        for i in range(0, hs.shape[0], 128):
            tot = tot + checkpoint(ce, hs[i:i + 128], ys[i:i + 128], use_reentrant=False)
        out.append((tot, int(keep.numel())))
    return out


# ---- --shared-prefix (2026-11-06, proofs/2026-11-06_4b_local/speed/EQUIV.md). Off by default.
# Rows of one optimizer step that begin with the same tokens (the chat tool header, the incident system prompt) run that prefix
# ONCE: its forward keeps each layer's end state (full attention: K/V after norm + RoPE; Gated-DeltaNet: last K-1 conv inputs +
# recurrent state) and its final hidden states; every continuation runs from that state; the gradients reaching the prefix
# outputs are summed in fp32 over all continuations and ONE backward goes through the prefix. Same rows, same loss
# (sum CE over each row's label tokens / n, / accum; labels inside the prefix included), same checkpointing / offload / mlp-chunk.
# Not bit-identical: float rounding differs, and LoRA dropout draws ONE mask for the shared prefix instead of one per row.

class _Tap(torch.autograd.Function):
    """identity on a detached prefix output; backward adds the incoming gradient into an fp32 accumulator (acc[0])"""
    @staticmethod
    def forward(ctx, x, dummy, acc):
        ctx.acc = acc
        return x.view_as(x)

    @staticmethod
    def backward(ctx, g):
        if g is not None:
            if ctx.acc[0] is None:
                ctx.acc[0] = g.float()
            else:
                ctx.acc[0].add_(g.float())
        return None, None, None


class _OffloadCkptN(torch.autograd.Function):
    """_OffloadCkpt for fn(x, *extra) -> tuple of tensors: x (the layer input) goes to the pinned pool, the small extra inputs
    (prefix states) stay on the GPU; backward recomputes with the same RNG state and returns grads for x and the extras"""
    @staticmethod
    def forward(ctx, fn, x, *extra):
        ctx.set_materialize_grads(False)
        ctx.fn, ctx.dev = fn, x.device
        ctx.rng, ctx.crng = torch.get_rng_state(), torch.cuda.get_rng_state(x.device)
        ctx.shape = x.shape
        ctx.bufs, flat = [], x.detach().reshape(-1)
        for o in range(0, flat.numel(), _HOST_BUF // x.element_size()):
            part = flat[o:o + _HOST_BUF // x.element_size()]
            b = _host_buf(x.dtype)
            b[:part.numel()].copy_(part, non_blocking=True)
            ctx.bufs.append((b, part.numel()))
        ctx.save_for_backward(*extra)
        with torch.no_grad():
            return fn(x, *extra)

    @staticmethod
    def backward(ctx, *gos):
        x = torch.cat([b[:n].to(ctx.dev, non_blocking=True) for b, n in ctx.bufs]).view(ctx.shape).requires_grad_(True)
        torch.cuda.current_stream(ctx.dev).synchronize()
        _HOST_FREE.extend(b for b, _ in ctx.bufs)
        ctx.bufs = None
        ex = [e.detach().requires_grad_(e.requires_grad) for e in ctx.saved_tensors]
        with torch.random.fork_rng(devices=[ctx.dev]):
            torch.set_rng_state(ctx.rng)
            torch.cuda.set_rng_state(ctx.crng, ctx.dev)
            with torch.enable_grad():
                outs = ctx.fn(x, *ex)
        pairs = [(o, g) for o, g in zip(outs, gos) if g is not None and o.requires_grad]
        torch.autograd.backward([o for o, _ in pairs], [g for _, g in pairs])
        return (None, x.grad) + tuple(e.grad if e.requires_grad else None for e in ex)


def _sp_attn(m, x, cos, sin, st):
    """Qwen3_5Attention.forward (transformers 5.x, gated output) for a prefix (st None: also returns its K/V) or a right-padded
    continuation batch attending to the prefix K/V st (lower-right causal: query i sees the prefix + continuation keys <= i)"""
    M = sys.modules[type(m).__module__]
    shp = x.shape[:-1]
    hs = (*shp, -1, m.head_dim)
    q, gate = torch.chunk(m.q_proj(x).view(*shp, -1, m.head_dim * 2), 2, dim=-1)
    gate = gate.reshape(*shp, -1)
    q = m.q_norm(q.view(hs)).transpose(1, 2)
    k = m.k_norm(m.k_proj(x).view(hs)).transpose(1, 2)
    v = m.v_proj(x).view(hs).transpose(1, 2)
    q, k = M.apply_rotary_pos_emb(q, k, cos, sin)
    assert not (m.training and m.attention_dropout), "--shared-prefix: attention dropout is not supported"
    if st is None:
        attn = M.ALL_ATTENTION_FUNCTIONS.get_interface(m.config._attn_implementation, M.eager_attention_forward)
        o, _ = attn(m, q, k, v, None, dropout=0.0, scaling=m.scaling)
        ns = (k, v)
    else:
        from torch.nn.attention.bias import causal_lower_right
        n = m.num_key_value_groups
        # CUDA: causal_lower_right dispatches to the flash / mem-efficient kernels (fp32 accumulation, like the baseline's is_causal
        # kernel). Elsewhere only the math backend takes this mask and it computes in the input dtype: upcast to fp32 there; also
        # for fp16 (T4: no flash on sm_75; fp32 runs on the mem-efficient kernel). One row at a time: the GQA-repeated prefix K/V
        # (16 heads x (p + C) x 256) exists for one row only (VRAM)
        up = q.dtype == torch.float16 or (q.device.type != "cuda" and q.dtype != torch.float32)
        os_ = []
        for b in range(x.shape[0]):
            K = torch.cat([st[0].to(k.dtype), k[b:b + 1]], 2)
            V = torch.cat([st[1].to(v.dtype), v[b:b + 1]], 2)
            qq, KK, VV = (q[b:b + 1].float(), K.float(), V.float()) if up else (q[b:b + 1], K, V)
            os_.append(torch.nn.functional.scaled_dot_product_attention(
                qq, M.repeat_kv(KK, n), M.repeat_kv(VV, n), attn_mask=causal_lower_right(q.shape[2], K.shape[2]),
                scale=m.scaling).to(q.dtype))
            del K, V, qq, KK, VV
        o = torch.cat(os_, 0).transpose(1, 2).contiguous()
        ns = None
    o = o.reshape(*shp, -1).contiguous()
    o = o * torch.sigmoid(gate)
    return m.o_proj(o), ns


def _sp_gdn(m, x, st, want):
    """Qwen3_5GatedDeltaNet.forward (the same kernels: causal_conv1d_fn / chunk_gated_delta_rule as resolved by transformers)
    starting from the prefix state st = (last K-1 conv inputs [1, D, K-1], recurrent state [1, H, dk, dv]); want: also return
    this sequence's end state (prefix pass: one unpadded row)"""
    M = sys.modules[type(m).__module__]
    B, T, _ = x.shape
    qkv = m.in_proj_qkv(x).transpose(1, 2)
    z = m.in_proj_z(x).reshape(B, T, -1, m.head_v_dim)
    b = m.in_proj_b(x)
    a = m.in_proj_a(x)
    k1 = m.conv_kernel_size - 1
    tail = qkv[:, :, T - k1:].clone() if want else None    # clone: a view would keep the whole [1, D, T] projection alive
    w = m.conv1d.weight.squeeze(1)
    if st is None:
        qkv = M.causal_conv1d_fn(qkv, w, m.conv1d.bias, activation=m.activation)
        s0 = None
    else:
        qkv = M.causal_conv1d_fn(torch.cat([st[0].to(qkv.dtype).expand(B, -1, -1), qkv], -1), w, m.conv1d.bias,
                                 activation=m.activation)[:, :, k1:]
        s0 = st[1].expand(B, -1, -1, -1).contiguous()
    qkv = qkv.transpose(1, 2)
    q, k, v = torch.split(qkv, [m.key_dim, m.key_dim, m.value_dim], dim=-1)
    q = q.reshape(B, T, -1, m.head_k_dim)
    k = k.reshape(B, T, -1, m.head_k_dim)
    v = v.reshape(B, T, -1, m.head_v_dim)
    beta = b.sigmoid()
    g = -m.A_log.float().exp() * torch.nn.functional.softplus(a.float() + m.dt_bias)
    if m.num_v_heads // m.num_k_heads > 1:
        q = q.repeat_interleave(m.num_v_heads // m.num_k_heads, dim=2)
        k = k.repeat_interleave(m.num_v_heads // m.num_k_heads, dim=2)
    o, sT = M.torch_chunk_gated_delta_rule(q, k, v, g=g, beta=beta, initial_state=s0, output_final_state=want,
                                           use_qk_l2norm_in_kernel=True, cu_seqlens=None)
    o = m.norm(o.reshape(-1, m.head_v_dim), z.reshape(-1, m.head_v_dim)).reshape(B, T, -1)
    return m.out_proj(o), ((tail, sT) if want else None)


def _sp_layer(layer, h, cos, sin, st, want):
    """Qwen3_5DecoderLayer.forward with prefix state in / end state out"""
    r = h
    x = layer.input_layernorm(h)
    if layer.block_type == "linear_attention":
        y, ns = _sp_gdn(layer.linear_attn, x, st, want)
    else:
        y, ns = _sp_attn(layer.self_attn, x, cos, sin, st)
    h = r + y
    h = h + layer.mlp(layer.post_attention_layernorm(h))
    return h, ns


def _sp_stack(inner, h, pos0, states, want):
    """decoder stack + final norm for h [B, T, H] at positions pos0.. with the baseline's per-layer checkpointing (non-reentrant,
    or the pinned-pool offload above --offload-min tokens). Returns (hidden, [per-layer end states] if want)"""
    from torch.utils.checkpoint import checkpoint
    tm = inner.model
    B, T = h.shape[:2]
    pid = (torch.arange(T, device=h.device) + pos0).view(1, 1, -1).expand(3, B, -1)
    cos, sin = tm.rotary_emb(h, pid)
    out = []
    ck = tm.gradient_checkpointing and tm.training and torch.is_grad_enabled()
    for i, layer in enumerate(tm.layers[:tm.config.num_hidden_layers]):
        st = list(states[i]) if states is not None else []

        def run(x, *s, layer=layer):
            y, ns = _sp_layer(layer, x, cos, sin, tuple(s) if s else None, want)
            return (y,) + (tuple(ns) if want else ())
        if not ck:
            res = run(h, *st)
        elif getattr(layer, "_gradient_checkpointing_func", None) is _offload_ckpt and h.shape[:-1].numel() > OFFLOAD_MIN:
            res = _OffloadCkptN.apply(run, h, *st)
        else:
            res = checkpoint(run, h, *st, use_reentrant=False)
        h = res[0]
        if want:
            out.append(tuple(res[1:]))
    return tm.norm(h), (out if want else None)


def _sp_embed(inner, x2d, dev):
    if HEAD is not None:
        return HEAD.embed(x2d)
    return inner.model.embed_tokens(x2d.to(dev))


def _sp_ce(inner, hs, ys):
    """the baseline's loss on selected hidden rows: HEAD.ce (--head-cpu) or lm_head + CE in checkpointed 128-row chunks"""
    if HEAD is not None:
        return HEAD.ce(hs, ys)
    from torch.utils.checkpoint import checkpoint
    head = inner.lm_head

    def ce(hc, yc):
        return torch.nn.functional.cross_entropy(head(hc).float(), yc, reduction="sum")
    tot = 0.0
    for i in range(0, hs.shape[0], 128):
        tot = tot + checkpoint(ce, hs[i:i + 128], ys[i:i + 128], use_reentrant=False)
    return tot


def lcp_len(a, b):
    m = min(len(a), len(b))
    ne = (a[:m] != b[:m]).nonzero()
    return int(ne[0]) if len(ne) else m


def prefix_clusters(exs, min_prefix):
    """split a step's rows into [(p, rows)]: rows sharing their first p >= min_prefix tokens (p < every member's length, so
    each row keeps >= 1 continuation token); p = 0 for rows left alone. Rows are sorted by their tokens, so rows with a long
    common prefix are adjacent; a row joins the open cluster only if the total of shared tokens does not drop."""
    exs = sorted(exs, key=lambda e: e["ids"][:8192].tolist())
    out, cur, p = [], [], 0
    for e in exs:
        if cur:
            q = min(p, lcp_len(cur[0]["ids"], e["ids"]), len(e["ids"]) - 1)
            if q >= min_prefix and len(cur) * q >= (len(cur) - 1) * p:
                cur.append(e)
                p = q
                continue
            out.append((p if len(cur) > 1 else 0, cur))
        cur, p = [e], len(e["ids"]) - 1
    if cur:
        out.append((p if len(cur) > 1 else 0, cur))
    return out


def shared_prefix_loss(model, exs, p, dev, cont_tokens, backward):
    """rows exs share their first p tokens: prefix forward once (graph kept), continuations in right-padded batches of
    <= cont_tokens padded tokens (forward + backward(sum of row loss / n) via the callback), then one backward through the
    prefix with the fp32-summed gradients. Returns [(loss_sum, n_label_tokens)] in exs order (as loss_fn_batch)."""
    inner = model.get_base_model()
    hP, stP = _sp_stack(inner, _sp_embed(inner, exs[0]["ids"][:p].long().unsqueeze(0), dev), 0, None, True)
    dummy = torch.zeros((), requires_grad=True)
    accP = [None]
    accS = [[[None] for _ in s] for s in stP]
    labs = [_lab(e["ids"], e["labels"]) for e in exs]
    any_pl = any(bool((lb[1:p + 1] != -100).any()) for lb in labs)      # a prefix position predicts a label token
    order = sorted(range(len(exs)), key=lambda i: -len(exs[i]["ids"]))
    mbs, cur = [], []
    for i in order:
        if cur and (len(cur) + 1) * (len(exs[cur[0]]["ids"]) - p) > cont_tokens:
            mbs.append(cur)
            cur = []
        cur.append(i)
    if cur:
        mbs.append(cur)
    res = [None] * len(exs)
    for mb in mbs:
        C = len(exs[mb[0]]["ids"]) - p
        x = torch.zeros((len(mb), C), dtype=torch.long)
        for b, i in enumerate(mb):
            t = exs[i]["ids"][p:]
            x[b, :len(t)] = t.long()
        sts = [tuple(_Tap.apply(s.detach(), dummy, acc) for s, acc in zip(ss, aa)) for ss, aa in zip(stP, accS)]
        hp = _Tap.apply(hP.detach(), dummy, accP)[0] if any_pl else None    # only when some row has labels inside the prefix
        hc, _ = _sp_stack(inner, _sp_embed(inner, x, dev), p, sts, False)
        tot = 0.0
        for b, i in enumerate(mb):
            y = torch.cat([labs[i][1:].long(), torch.tensor([-100])]).to(dev)
            keep = (y != -100).nonzero().squeeze(1)
            kp, kc = keep[keep < p], keep[keep >= p]
            hs = torch.cat([hp[kp], hc[b][kc - p]]) if hp is not None else hc[b][kc - p]
            l = _sp_ce(inner, hs, torch.cat([y[kp], y[kc]]))
            n = int(keep.numel())
            res[i] = (l.detach(), n)
            tot = tot + l / max(1, n)
        backward(tot)
        del hc, hp, sts, tot
    outs, grads = [], []
    for t, acc in [(hP, accP)] + [(s, acc) for ss, aa in zip(stP, accS) for s, acc in zip(ss, aa)]:
        if acc[0] is not None and t.requires_grad:
            outs.append(t)
            grads.append(acc[0].to(t.dtype))
            acc[0] = None                       # free the fp32 sum before the prefix backward (VRAM)
    if outs:
        torch.autograd.backward(outs, grads)
    return res


def shared_prefix_step(model, exs, a, dev, backward):
    """one step's rows (this rank's share) under --shared-prefix: clusters with a common prefix -> shared_prefix_loss, the
    other rows exactly as before (--micro-tokens batches or one row per forward). Returns [((loss_sum, n), row)]."""
    out, alone = [], []
    for p, cl in prefix_clusters(exs, a.shared_prefix_min):
        if not p:
            alone += cl
            continue
        ct = min(a.shared_prefix_cont, a.micro_tokens - p) if a.micro_tokens else a.shared_prefix_cont
        ct = max(1, ct)
        out += list(zip(shared_prefix_loss(model, cl, p, dev, ct, backward), cl))
    for mb in (micro_batches(alone, a.micro_tokens) if a.micro_tokens else [[e] for e in alone]):
        res = loss_fn_batch(model, [e["ids"] for e in mb], [e["labels"] for e in mb], dev)
        backward(sum(l / max(1, n) for l, n in res))
        out += list(zip(res, mb))
    return out


def allreduce(t, op=None):
    if WORLD > 1:
        torch.distributed.all_reduce(t, op=op or torch.distributed.ReduceOp.SUM)
    return t


def barrier():
    if WORLD > 1:
        torch.distributed.barrier()


def chunk(keys, n):
    return [keys[i:i + n] for i in range(0, len(keys), n)]


def is_e2(row):
    if row["kind"] == "chat":
        return row["hard"]
    return row["family"].split(":")[0].split("+")[0] in E2_FAMILIES


def plan_schedule(path, inc, chat, accum, step_now):
    """deterministic step groups; see module doc. Returns the schedule dict (written to path by rank 0)."""
    S = json.load(open(path)) if os.path.exists(path) else None
    ik = [d["id"] for d in inc]
    ck = [d["id"] for d in chat] if chat else []
    if S is None:
        if ck:
            keys = ik + ck
            random.Random(101).shuffle(keys)
            S = {"state": "mixed", "groups": chunk(keys, accum), "merged_at": 0}
        else:
            keys = list(ik)
            random.Random(101).shuffle(keys)
            S = {"state": "inc_only", "groups": chunk(keys, accum), "merged_at": None}
    elif S["state"] == "inc_only" and ck:
        s = min(step_now, len(S["groups"]))
        rest = [k for g in S["groups"][s:] for k in g] + ck
        random.Random(202 + s).shuffle(rest)
        S = {"state": "mixed", "groups": S["groups"][:s] + chunk(rest, accum), "merged_at": s}
    if S["state"] == "mixed" and "e2" not in S:
        rows = {d["id"]: d for d in inc + (chat or [])}
        e2 = [k for k in rows if is_e2(rows[k])]
        random.Random(303).shuffle(e2)
        S["e2"] = chunk(e2, accum)
    return S


def _parse_report(t):
    a, b = t.find("{"), t.rfind("}")
    try:
        return json.loads(t[a:b + 1]) if a >= 0 and b > a else None
    except Exception:
        return None


def gen_slices(a):
    """fixed generation-eval slices (same rows every eval, every rank): incident rows without tool rounds, chat3 records"""
    def inc(p, n, seed):
        if not p or not os.path.exists(p):
            return []
        rs = [json.loads(l) for l in open(p, encoding="utf-8")]
        rs = [r for r in rs if r.get("tools") == "incident" and not any(m["role"] == "tool" for m in r["messages"])]
        random.Random(seed).shuffle(rs)
        return rs[:n]

    def chat(p, n, seed):
        if not p or not os.path.exists(p):
            return []
        rs = [json.loads(l) for l in open(p, encoding="utf-8")]
        random.Random(seed).shuffle(rs)
        return rs[:n]
    return {"dev": (inc(a.gen_inc, a.gen_n, 11), chat(a.gen_chat, a.gen_n, 12)),
            "train": (inc(a.gen_train_inc, a.gen_train_n, 13), chat(a.gen_train_chat, a.gen_train_n, 14))}


def gen_score(model, tok, tools, inc_rows, chat_recs, dev, gen_r3="auto", r3_tools=""):
    """greedy generation; incidents: parse / severity / label vs the gold report; chat: verify_chat pass. Returns sums
    [n_inc, parse, severity, label, n_chat, chat_pass] for this rank's share."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import chatloop as CL
    import verify_chat as VC
    from tools_v3_impl import ToolsV3
    out = torch.zeros(6, device=dev, dtype=torch.float64)
    be = CL.HFBackend(model, tok, temperature=0.0, max_new=900, tok_budget=24000, max_batch=8, log=lambda m: None)
    if inc_rows:
        prompts = [tok.apply_chat_template(r["messages"][:2], tools=tools["incident"], tokenize=False, add_generation_prompt=True,
                                           enable_thinking=False) for r in inc_rows]
        for r, (txt, _) in zip(inc_rows, be.generate(prompts, [False] * len(prompts))):
            g = json.loads(r["messages"][-1]["content"])
            p = _parse_report(txt)
            out[0] += 1
            if isinstance(p, dict):
                out[1] += 1
                out[2] += float(p.get("severity") == g.get("severity"))
                out[3] += float(p.get("label") == g.get("label"))
    if chat_recs:
        be.max_new = 420
        ss = [CL.Sample(r, 0, r.get("hard")) for r in chat_recs]
        execs = chat_executors(chat_recs, gen_r3, r3_tools)
        if execs is None:                     # r2 records (default, unchanged): rsn_v3 store
            CL.run_samples(be, tok, tools["chat"], ss, ToolsV3, VC.parse_turn)
        else:                                 # r3 records: one executor per record in its fog state (sample order)
            it = iter(execs)
            CL.run_samples(be, tok, tools["chat"], ss, lambda: next(it), VC.parse_turn)
        for ok in verify_chat_recs([s.rec for s in ss], [CL.candidate(s) for s in ss], gen_r3, r3_tools):
            out[4] += 1
            out[5] += float(ok)
    return out


R3_TOOLS_DEFAULT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "2026-11-06_4b_local", "tools")


def _is_r3(recs, gen_r3):
    """gen_r3: "on" | "off" | "auto" (records with a "fog" field = dataset r3)"""
    return gen_r3 == "on" or (gen_r3 == "auto" and any("fog" in r for r in recs))


def chat_executors(recs, gen_r3="auto", r3_tools=""):
    """None for r2 records; for r3 records one tools_r3_impl.ToolsR3 view per record (fog state + last sync of the record;
    the stores are loaded once per fog state and shared read-only)"""
    if not _is_r3(recs, gen_r3):
        return None
    d = os.path.abspath(r3_tools or R3_TOOLS_DEFAULT)
    if d not in sys.path:
        sys.path.insert(0, d)
    import copy as _copy
    import tools_r3_impl as TR
    import verify_chat as VC
    VC.DEFAULTS.update({"fog_search_history": {"limit": 5}, "fog_analytics": {"bucket": "month", "group_by": "label"},
                        "co_occurring_incidents": {"window_min": 60, "other_domains_only": True},
                        "recurring_issues": {"min_count": 3, "by": "sensor"}, "search_knowledge": {"k": 3}})   # = build_r3.py
    base = getattr(chat_executors, "_base", None)
    if base is None:
        base = chat_executors._base = {s: TR.ToolsR3(fog=s) for s in ("online", "offline", "timeout")}
    out = []
    for r in recs:
        e = _copy.copy(base[r.get("fog", "offline")])
        e.last_sync, e.qid = r.get("last_sync"), 0
        out.append(e)
    return out


def verify_chat_recs(recs, cands, gen_r3="auto", r3_tools=""):
    """verify_chat pass per record (r2: rsn_v3 store; r3: the r3 store in the record's fog state)"""
    import verify_chat as VC
    execs = chat_executors(recs, gen_r3, r3_tools)
    if execs is None:
        from tools_v3_impl import ToolsV3
        ex = ToolsV3()
        execs = [ex] * len(recs)
    res = []
    for r, c, ex in zip(recs, cands, execs):
        ex.qid = 0
        res.append(bool(VC.verify(r, c, executor=ex)["pass"]))
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--tools", required=True, help="tools_v4.json ({incident, chat})")
    ap.add_argument("--inc", required=True, help="incident rows (bundle A)")
    ap.add_argument("--chat", default="", help="chat rows (bundle B); absent/empty = incident part of epoch 1 only")
    ap.add_argument("--expect-chat", type=int, default=7200, help="planned chat rows (LR plan before bundle B arrives)")
    ap.add_argument("--dev", default="")
    ap.add_argument("--out", required=True)
    ap.add_argument("--r", type=int, default=32)
    ap.add_argument("--alpha", type=int, default=64)
    ap.add_argument("--lr", type=float, default=1e-4)
    ap.add_argument("--e2-peak", type=float, default=0.5)
    ap.add_argument("--run-e2", action="store_true", help="train epoch 2 (hard rows); default: stop after epoch 1")
    ap.add_argument("--accum", type=int, default=16, help="rows per optimizer step (all GPUs together)")
    ap.add_argument("--max-len", type=int, default=6144)
    ap.add_argument("--save-every", type=int, default=25)
    ap.add_argument("--keep-every", type=int, default=500)
    ap.add_argument("--eval-every", type=int, default=100)
    ap.add_argument("--hours", type=float, default=11)
    ap.add_argument("--probe-steps", type=int, default=0)
    ap.add_argument("--probe-len", type=int, default=0, help="probe: the 2 warm-up rows become synthetic rows of this many tokens (fit test)")
    ap.add_argument("--model-dir", default="", help="load weights from here (e.g. the laptop's pre-quantized NF4 copy); tokenizer from --base")
    ap.add_argument("--dtype", default="auto", choices=["auto", "fp16", "bf16"], help="auto: bf16 on Ampere+, fp16 + GradScaler on T4")
    ap.add_argument("--quant", default="nf4", choices=["nf4", "none"], help="nf4 = QLoRA 4-bit; none = 16-bit base LoRA (more VRAM)")
    ap.add_argument("--no-fla", action="store_true", help="block flash-linear-attention (torch Gated-DeltaNet path)")
    ap.add_argument("--micro-tokens", type=int, default=0, help="r2 speed: micro-batch the rows of a step up to this many padded "
                    "tokens per forward (0 = one row per forward, as r1)")
    ap.add_argument("--step-log", action="store_true", help="benchmark: one line per optimizer step -> steps.jsonl (time, row tokens, "
                    "loss, peak VRAM)")
    ap.add_argument("--max-steps", type=int, default=0, help="benchmark: stop (rc 3, checkpoint saved) after this optimizer step")
    ap.add_argument("--head-cpu", action="store_true", help="6 GB fit: tied embed/lm_head in pinned CPU RAM, streamed exact CE (FIT.md)")
    ap.add_argument("--ckpt-offload", action="store_true", help="6 GB fit: checkpointed layer inputs kept in pinned CPU RAM")
    ap.add_argument("--mlp-chunk", type=int, default=0, help="6 GB fit: MLP recomputed in sequence chunks of this many tokens (exact)")
    ap.add_argument("--mlp-chunk-min", type=int, default=0, help="--mlp-chunk only for forwards of more than this many tokens (speed)")
    ap.add_argument("--offload-min", type=int, default=0, help="--ckpt-offload only for forwards of more than this many tokens "
                    "(speed; shorter forwards keep the checkpoint input on the GPU; exact)")
    ap.add_argument("--shared-prefix", action="store_true", help="speed: rows of one step that start with the same tokens run that "
                    "prefix once (its end state feeds every continuation; one backward with the summed gradient; exact up to "
                    "rounding, see proofs/2026-11-06_4b_local/speed/EQUIV.md)")
    ap.add_argument("--shared-prefix-min", type=int, default=256, help="--shared-prefix: shortest common prefix worth sharing")
    ap.add_argument("--shared-prefix-cont", type=int, default=2048, help="--shared-prefix: padded continuation tokens per forward "
                    "(capped at --micro-tokens minus the prefix length). 2048 fits the 6 GB 4B config with offload/mlp-chunk on every "
                    "forward (speed/EQUIV.md memory section); one row longer than this still runs alone")
    ap.add_argument("--lean-host", action="store_true", help="6 GB fit: labels kept as bool masks (exact), malloc_trim after load: "
                    "the laptop WSL VM has ~6.2 GB RAM")
    ap.add_argument("--lora-dropout", type=float, default=0.05)
    ap.add_argument("--wd", type=float, default=0.01)
    # generation dev score (overtraining control): every --gen-every steps, greedy generation on fixed slices
    ap.add_argument("--gen-every", type=int, default=200)
    ap.add_argument("--gen-inc", default="", help="incident dev rows (gold report as last message)")
    ap.add_argument("--gen-chat", default="", help="chat3 dev records (verify_chat gold)")
    ap.add_argument("--gen-train-inc", default="", help="incident train rows for the train/dev gap")
    ap.add_argument("--gen-train-chat", default="", help="chat3 train records for the train/dev gap")
    ap.add_argument("--gen-r3", default="auto", choices=["auto", "on", "off"],
                    help="chat gen-eval records of dataset r3 (fog state per record, r3 store/tools); auto = records with a fog field")
    ap.add_argument("--gen-r3-tools", default="", help="dir of tools_r3_impl.py (default ../../2026-11-06_4b_local/tools)")
    ap.add_argument("--gen-n", type=int, default=40)
    ap.add_argument("--gen-train-n", type=int, default=20)
    ap.add_argument("--patience", type=int, default=3, help="early stop after this many generation evals without a better dev score")
    ap.add_argument("--keep-best", type=int, default=3)
    a = ap.parse_args()
    if a.no_fla:
        sys.modules["fla"] = None
    os.makedirs(a.out, exist_ok=True)
    if WORLD > 1:
        torch.distributed.init_process_group("nccl", timeout=datetime.timedelta(hours=3))
    CPU = not torch.cuda.is_available()          # CPU = dry runs with a tiny model only (fp32, no 4-bit, torch AdamW)
    if CPU:
        dev, DT, a.quant = torch.device("cpu"), torch.float32, "none"
    else:
        torch.cuda.set_device(LOCAL)
        dev = torch.device("cuda", LOCAL)
        DT = torch.bfloat16 if torch.cuda.get_device_capability(LOCAL)[0] >= 8 else torch.float16
        DT = {"fp16": torch.float16, "bf16": torch.bfloat16}.get(a.dtype, DT)
    SC = torch.amp.GradScaler("cuda", enabled=(DT == torch.float16))
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
    from peft import LoraConfig, get_peft_model, set_peft_model_state_dict
    from safetensors.torch import load_file
    import bitsandbytes as bnb

    tok = AutoTokenizer.from_pretrained(a.base)
    tools = json.load(open(a.tools, encoding="utf-8"))
    tools["none"] = None
    global LEAN_MMAP
    LEAN_MMAP = a.lean_host
    has_chat = bool(a.chat) and os.path.exists(a.chat) and os.path.getsize(a.chat) > 0
    caches = {}
    if RANK == 0:
        inc, caches["inc"] = prep(tok, a.inc, tools, a.max_len, a.out, "inc")
        chat, caches["chat"] = prep(tok, a.chat, tools, a.max_len, a.out, "chat") if has_chat else ([], None)
        dvl, caches["dev"] = prep(tok, a.dev, tools, a.max_len, a.out, "dev") if a.dev else ([], None)
        json.dump(caches, open(os.path.join(a.out, "caches.json"), "w"))
    barrier()
    if RANK:
        caches = json.load(open(os.path.join(a.out, "caches.json")))
        inc = torch.load(caches["inc"])
        chat = torch.load(caches["chat"]) if caches["chat"] else []
        dvl = torch.load(caches["dev"]) if caches["dev"] else []
    if a.lean_host:     # int32 labels -> bool mask (labels == ids wherever trained, -100 elsewhere: checked row by row)
        for d in inc + chat + dvl:
            mk = d["labels"] != -100
            assert torch.equal(d["labels"][mk], d["ids"][mk])
            d["labels"] = mk
        host_trim()
    rows = {d["id"]: d for d in inc + chat}

    torch.manual_seed(1234)
    qc = None
    if a.quant == "nf4":
        qc = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_use_double_quant=True, bnb_4bit_compute_dtype=DT)
    if a.model_dir:      # pre-quantized NF4 (round-1 prequant.py): carries its own quantization config, low host RAM
        model = AutoModelForCausalLM.from_pretrained(a.model_dir, dtype=DT, device_map={"": "cpu" if CPU else LOCAL}, low_cpu_mem_usage=True)
    else:
        model = AutoModelForCausalLM.from_pretrained(a.base, dtype=DT, device_map={"": "cpu" if CPU else LOCAL}, quantization_config=qc, low_cpu_mem_usage=True,
                                                     attn_implementation=os.environ.get("RSN3_ATTN", "sdpa"))
    model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
    model.enable_input_require_grads()
    model.config.use_cache = False
    model = get_peft_model(model, LoraConfig(r=a.r, lora_alpha=a.alpha, lora_dropout=a.lora_dropout, target_modules=TARGETS, bias="none",
                                             task_type="CAUSAL_LM"))
    params = [p for p in model.parameters() if p.requires_grad]
    if not CPU:
        log(a.out, "fit levers: %s" % apply_fit_levers(model, a, dev))
        if a.lean_host:
            host_trim()
        log(a.out, "host RSS %d MB after model load" % host_rss_mb())
    if DT == torch.float16:     # trainable LoRA weights in fp32 under the scaler (fp16 masters would underflow)
        for p in params:
            p.data = p.data.float()
    log(a.out, "attention %s, micro_tokens %d" % (getattr(model.config, "_attn_implementation", "?"), a.micro_tokens))
    if a.shared_prefix:
        log(a.out, "shared prefix on: min %d tokens, continuation batch <= %d padded tokens (and <= micro_tokens - prefix)" % (
            a.shared_prefix_min, a.shared_prefix_cont))
    log(a.out, "model loaded on %d GPU(s), dtype %s, quant %s, fla %s: VRAM %.2f GiB" % (
        WORLD, DT, a.quant, "off" if a.no_fla else "auto", 0 if CPU else torch.cuda.memory_allocated(dev) / 2 ** 30))
    opt = (torch.optim.AdamW if CPU else bnb.optim.AdamW8bit)(params, lr=a.lr, weight_decay=a.wd, betas=(0.9, 0.999))

    # ---- resume state, then the schedule (it may merge newly arrived chat rows at the current step)
    step, ck = 0, os.path.join(a.out, "ckpt_latest")
    st = None
    if os.path.exists(os.path.join(ck, "state.pt")) and not a.probe_steps:
        st = torch.load(os.path.join(ck, "state.pt"), weights_only=False, map_location="cpu")
        step = st["step"]
    spath = os.path.join(a.out, "schedule.json")
    if a.probe_steps:
        longest = sorted(rows, key=lambda k: -len(rows[k]["ids"]))[:2]
        if a.probe_len:
            for j, k in enumerate(list(longest)):
                src = rows[k]["ids"]
                ids = src.repeat(a.probe_len // len(src) + 1)[:a.probe_len].clone()
                lab = torch.full_like(ids, -100)
                lab[-500:] = ids[-500:]
                rows["_synth%d" % j] = {"id": "_synth%d" % j, "kind": "incident", "family": "", "hard": False, "ids": ids, "labels": lab}
                longest[j] = "_synth%d" % j
        rest = [k for k in rows if k not in longest]
        random.Random(7).shuffle(rest)
        S = {"state": "probe", "groups": chunk(longest + rest[:a.accum * a.probe_steps - 2], a.accum), "e2": []}
    else:
        if RANK == 0:
            S = plan_schedule(spath, inc, chat, a.accum, step)
            json.dump(S, open(spath + ".part", "w"))
            os.replace(spath + ".part", spath)
        barrier()
        S = json.load(open(spath))
    mixed = S["state"] == "mixed"
    G1 = S["groups"]
    if mixed:
        E1 = len(G1)
        E2 = len(S["e2"])
    else:                                   # LR plan before the chat rows exist: planned sizes
        ninc_e2 = sum(1 for d in inc if is_e2(d))
        E1 = math.ceil((len(inc) + a.expect_chat) / a.accum)
        E2 = math.ceil((ninc_e2 + 0.42 * a.expect_chat) / a.accum)
    groups = G1 + (S["e2"] if (mixed and a.run_e2) else [])

    def lr_lambda(s):
        if s < E1:
            w = max(1, int(0.03 * E1))
            return min(1.0, (s + 1) / w) * (0.1 + 0.9 * 0.5 * (1 + math.cos(math.pi * min(1.0, s / E1))))
        s2 = s - E1
        w = max(1, int(0.03 * E2))
        ramp = 0.1 + (a.e2_peak - 0.1) * min(1.0, (s2 + 1) / w)
        return ramp if s2 < w else a.e2_peak * (0.1 + 0.9 * 0.5 * (1 + math.cos(math.pi * min(1.0, (s2 - w) / max(1, E2 - w)))))
    sched = torch.optim.lr_scheduler.LambdaLR(opt, lr_lambda)
    if st is not None:
        set_peft_model_state_dict(model, load_file(os.path.join(ck, "adapter_model.safetensors"), device="cpu" if CPU else "cuda:%d" % LOCAL))
        if DT == torch.float16:
            for p in params:
                p.data = p.data.float()
        opt.load_state_dict(st["opt"])
        sched.load_state_dict(st["sched"])
        if st.get("scaler") and SC.is_enabled():   # bf16 runs have no scaler state; fp16 after a bf16 ckpt starts a fresh scaler
            SC.load_state_dict(st["scaler"])
        if st.get("rng") is not None:
            torch.set_rng_state(st["rng"])
        log(a.out, "resumed at step %d (schedule %s, epoch-1 steps %d, epoch-2 steps %d, merged at %s)" % (step, S["state"], E1, E2, S.get("merged_at")))
    elif not a.probe_steps:
        log(a.out, "start: %d incident + %d chat rows, schedule %s: %d step groups now, epoch 1 = %d steps, epoch 2 = %d steps (%s); "
                   "trainable %.1fM, r=%d alpha=%d lr=%g max_len=%d" % (len(inc), len(chat), S["state"], len(G1), E1, E2,
                   "on" if a.run_e2 else "off", sum(p.numel() for p in params) / 1e6, a.r, a.alpha, a.lr, a.max_len))
    tok_inc = sum(len(d["ids"]) for d in inc)
    tok_chat = sum(len(d["ids"]) for d in chat) if chat else int(a.expect_chat * 3700)
    tok_e2 = sum(len(d["ids"]) for d in inc if is_e2(d)) + (sum(len(d["ids"]) for d in chat if d["hard"]) if chat else int(0.42 * a.expect_chat * 3700))
    if RANK == 0:
        json.dump({"incident_rows": len(inc), "chat_rows": len(chat), "schedule": S["state"], "e1_steps": E1, "e2_steps": E2,
                   "tokens_e1": tok_inc + tok_chat, "tokens_e2": tok_e2, "world": WORLD, "quant": a.quant, "no_fla": a.no_fla},
                  open(os.path.join(a.out, "plan.json"), "w"), indent=1)

    def status(extra=None):
        d = {"step": step, "e1_steps": E1, "e2_steps": E2, "schedule": S["state"], "epoch1_done": mixed and step >= E1,
             "done": mixed and step >= E1 + (E2 if a.run_e2 else 0) and a.run_e2, "t": time.time()}
        d.update(extra or {})
        json.dump(d, open(os.path.join(a.out, "status.json"), "w"))

    def save(tag="latest", extra=None):
        if RANK == 0:
            d = os.path.join(a.out, "ckpt_" + tag)
            tmp = d + ".part"
            os.makedirs(tmp, exist_ok=True)
            model.save_pretrained(tmp, save_embedding_layers=False) if HEAD is not None else model.save_pretrained(tmp)
            if tag == "latest":
                torch.save({"opt": opt.state_dict(), "sched": sched.state_dict(), "scaler": SC.state_dict() if SC.is_enabled() else {}, "step": step,
                            "rng": torch.get_rng_state(), "dtype": str(DT), "world": WORLD, "host": os.uname().nodename},
                           os.path.join(tmp, "state.pt"))
            if os.path.exists(d):
                os.system("rm -rf '%s'" % d)
            os.rename(tmp, d)
            status(extra)
        barrier()

    def dev_eval():
        if not dvl:
            return
        model.eval()
        acc = torch.zeros(4, device=dev, dtype=torch.float64)    # inc loss, inc tok, chat loss, chat tok
        with torch.no_grad():
            for d in dvl[RANK::WORLD]:
                try:
                    l, n = loss_fn(model, d["ids"], d["labels"], dev)
                except (torch.OutOfMemoryError, RuntimeError) as e:  # "CUDA driver error: out of memory" is a RuntimeError
                    if not isinstance(e, torch.OutOfMemoryError) and "out of memory" not in str(e):
                        raise
                    torch.cuda.empty_cache()
                    continue
                j = 0 if d["kind"] == "incident" else 2
                acc[j] += float(l)
                acc[j + 1] += n
        allreduce(acc)
        model.train()
        r = {"step": step, "dev_incident": round(float(acc[0] / max(1, acc[1])), 4), "dev_chat": round(float(acc[2] / max(1, acc[3])), 4), "t": time.time()}
        log(a.out, "DEV step %d incident %.4f chat %.4f" % (step, r["dev_incident"], r["dev_chat"]))
        if RANK == 0:
            with open(os.path.join(a.out, "dev.jsonl"), "a") as f:
                f.write(json.dumps(r) + "\n")

    GS = gen_slices(a) if (a.gen_inc or a.gen_chat) and not a.probe_steps else None
    bpath = os.path.join(a.out, "best.json")
    best = json.load(open(bpath)) if os.path.exists(bpath) else {"top": [], "best": None, "since_best": 0, "evals": 0}

    def gen_hook():
        """generation dev score -> gen_eval.jsonl; best-K checkpoints (ckpt_best_XXXX); True = early stop (patience)"""
        if not GS:
            return False
        model.eval()
        model.config.use_cache = True
        if HEAD is not None:
            HEAD.unpark()
        res = {}
        for name, (ir, cr) in GS.items():
            if not ir and not cr:
                continue
            v = allreduce(gen_score(model, tok, tools, ir[RANK::WORLD], cr[RANK::WORLD], dev, a.gen_r3, a.gen_r3_tools))
            inc_s = float(v[1] + v[2] + v[3]) / max(1.0, 3 * float(v[0]))
            ch_s = float(v[5]) / max(1.0, float(v[4]))
            parts = [x for x, n in ((inc_s, v[0]), (ch_s, v[4])) if n > 0]
            res[name] = {"n_inc": int(v[0]), "parse": round(float(v[1]) / max(1.0, float(v[0])), 3),
                         "severity": round(float(v[2]) / max(1.0, float(v[0])), 3), "label": round(float(v[3]) / max(1.0, float(v[0])), 3),
                         "n_chat": int(v[4]), "chat_pass": round(ch_s, 3), "score": round(sum(parts) / max(1, len(parts)), 4)}
        model.config.use_cache = False
        if HEAD is not None:
            HEAD.park()
        model.train()
        sc = res.get("dev", {}).get("score")
        rec = {"step": step, "t": time.time(), **res}
        if "train" in res and sc is not None:
            rec["gap"] = round(res["train"]["score"] - sc, 4)
        log(a.out, "GEN step %d %s" % (step, json.dumps(rec)))
        if RANK == 0:
            with open(os.path.join(a.out, "gen_eval.jsonl"), "a") as f:
                f.write(json.dumps(rec) + "\n")
        if sc is None or not mixed:          # best-K / patience only once the chat rows are in the plan
            return False
        best["evals"] += 1
        if best["best"] is None or sc > best["best"]:
            best["best"], best["since_best"] = sc, 0
        else:
            best["since_best"] += 1
        top = sorted(best["top"] + [[sc, step]], key=lambda x: (-x[0], -x[1]))
        keep, drop = top[:a.keep_best], top[a.keep_best:]
        if [sc, step] in keep:
            save("best_%04d" % step)
        if RANK == 0:
            for _, s_ in drop:
                os.system("rm -rf '%s'" % os.path.join(a.out, "ckpt_best_%04d" % s_))
        best["top"] = keep
        if RANK == 0:
            json.dump(best, open(bpath, "w"), indent=1)
        return best["since_best"] >= a.patience

    model.train()
    t0, tok_count, run_loss, run_n = time.time(), 0, 0.0, 0
    tstart, ptok, ptime, poom, ploss = time.time(), 0, 0.0, 0, []
    deadline = time.time() + a.hours * 3600
    if step == 0 and not a.probe_steps and not os.path.exists(os.path.join(a.out, "dev.jsonl")):
        dev_eval()
    while True:
        # ---- plan boundaries
        if a.probe_steps and step >= len(groups):
            break
        if not a.probe_steps:
            if mixed and best["since_best"] >= a.patience:
                log(a.out, "EARLY STOP already reached (best %s): nothing to train" % best["top"])
                return 6
            if mixed and step == E1 and not os.path.exists(os.path.join(a.out, "ckpt_epoch1")):
                save()
                save("epoch1")
                dev_eval()
                log(a.out, "EPOCH 1 DONE at step %d: ckpt_epoch1 saved" % step)
            if mixed and step >= E1 and not a.run_e2:
                status({"stopped": "after_epoch1"})
                log(a.out, "STOP after epoch 1 (no --run-e2)")
                return 5
            if step >= len(groups):
                if not mixed:
                    save(extra={"waiting": "chat"})
                    log(a.out, "WAIT_CHAT: incident part of epoch 1 done at step %d; add bundle B (chat rows) and resume" % step)
                    return 4
                save()
                save("final")
                dev_eval()
                log(a.out, "TRAINING DONE step %d" % step)
                return 0
        flag = torch.zeros(1, device=dev)
        if RANK == 0 and (time.time() > deadline or os.path.exists(os.path.join(a.out, "STOP")) or (a.max_steps and step >= a.max_steps)):
            flag[0] = 1
        allreduce(flag)
        if flag[0] > 0:
            if not a.probe_steps:
                save()
            log(a.out, "EXIT (hours limit / STOP) at step %d" % step)
            return 3
        group = groups[step]
        if a.step_log:
            ts, tc0 = time.time(), tok_count
            if not CPU:
                torch.cuda.reset_peak_memory_stats(dev)
        mine = group[RANK::WORLD]
        lsum = torch.zeros(3, device=dev, dtype=torch.float64)   # loss sum, label tokens, oom
        if a.shared_prefix and not a.probe_steps:
            # --shared-prefix: the SAME rows of this step; common prefixes computed once (exact up to rounding, EQUIV.md)
            try:
                for (l, n), e in shared_prefix_step(model, [rows[k] for k in mine], a, dev, lambda t: SC.scale(t / a.accum).backward()):
                    lsum[0] += float(l) / max(1, n)
                    lsum[1] += n
                    tok_count += len(e["ids"])
            except (torch.OutOfMemoryError, RuntimeError) as e:
                if not isinstance(e, torch.OutOfMemoryError) and "out of memory" not in str(e):
                    raise
                lsum[2] += 1
                opt.zero_grad(set_to_none=True)
                torch.cuda.empty_cache()
                log(a.out, "OOM in a shared-prefix batch at step %d: optimizer step skipped" % step)
            mine = []
        if a.micro_tokens and not a.probe_steps:
            # r2 speed: the SAME rows of this step, right-padded into micro-batches of <= --micro-tokens padded tokens.
            # Exact for this causal / left-to-right recurrent model: pads sit after every real token and get no loss.
            try:
                for mb in micro_batches([rows[k] for k in mine], a.micro_tokens):
                    res = loss_fn_batch(model, [e["ids"] for e in mb], [e["labels"] for e in mb], dev)
                    tot = sum(l / max(1, n) for l, n in res)
                    SC.scale(tot / a.accum).backward()
                    for (l, n), e in zip(res, mb):
                        lsum[0] += float(l) / max(1, n)
                        lsum[1] += n
                        tok_count += len(e["ids"])
            except (torch.OutOfMemoryError, RuntimeError) as e:
                if not isinstance(e, torch.OutOfMemoryError) and "out of memory" not in str(e):
                    raise
                lsum[2] += 1
                opt.zero_grad(set_to_none=True)
                torch.cuda.empty_cache()
                log(a.out, "OOM in a micro-batch at step %d: optimizer step skipped" % step)
            mine = []
        for j, k in enumerate(mine):
            ex = rows[k]
            tq = time.time()
            try:
                l, n = loss_fn(model, ex["ids"], ex["labels"], dev)
                SC.scale(l / max(1, n) / a.accum).backward()
                lsum[0] += float(l) / max(1, n)
                lsum[1] += n
                tok_count += len(ex["ids"])
                if a.probe_steps and not (step == 0 and RANK * 1 + j * WORLD < 2):   # skip the 2 longest (warm-up) rows
                    ptok += len(ex["ids"])
                    ptime += time.time() - tq
                ploss.append(float(l) / max(1, n))
            except (torch.OutOfMemoryError, RuntimeError) as e:  # "CUDA driver error: out of memory" is a RuntimeError
                if not isinstance(e, torch.OutOfMemoryError) and "out of memory" not in str(e):
                    raise
                lsum[2] += 1
                opt.zero_grad(set_to_none=True)
                torch.cuda.empty_cache()
                log(a.out, "OOM on %s (%d tokens): optimizer step skipped" % (ex["id"], len(ex["ids"])))
                break
        allreduce(lsum)
        if lsum[2] > 0:
            opt.zero_grad(set_to_none=True)
            step += 1
            poom += 1
            continue
        if WORLD > 1:   # one flat all-reduce of the LoRA gradients (sum over ranks = single-GPU accumulation)
            gs = [p.grad if p.grad is not None else torch.zeros_like(p) for p in params]
            flat = torch._utils._flatten_dense_tensors(gs)
            torch.distributed.all_reduce(flat)
            for p, g in zip(params, torch._utils._unflatten_dense_tensors(flat, gs)):
                p.grad = g
        SC.unscale_(opt)
        torch.nn.utils.clip_grad_norm_(params, 1.0)
        SC.step(opt)
        SC.update()
        sched.step()
        opt.zero_grad(set_to_none=True)
        step += 1
        run_loss += float(lsum[0]) / len(group)
        if a.step_log and RANK == 0:
            dt = time.time() - ts
            with open(os.path.join(a.out, "steps.jsonl"), "a") as f:
                f.write(json.dumps({"step": step, "loss": float(lsum[0]) / len(group), "row_tokens": tok_count - tc0, "s": round(dt, 2),
                                    "tok_s": round((tok_count - tc0) / max(dt, 1e-6), 1),
                                    "peak_alloc_gib": 0 if CPU else round(torch.cuda.max_memory_allocated(dev) / 2 ** 30, 3),
                                    "peak_reserved_gib": 0 if CPU else round(torch.cuda.max_memory_reserved(dev) / 2 ** 30, 3),
                                    "t": time.time()}) + "\n")
        run_n += 1
        if a.probe_steps:
            continue
        if step % 5 == 0:
            el = time.time() - t0
            tk = torch.tensor([float(tok_count)], device=dev)
            allreduce(tk)
            seg_end = E1 if step < E1 else E1 + E2
            eta = (el / run_n) * (seg_end - step)
            log(a.out, "step %d/%d (%s) loss %.4f lr %.2e %.0f tok/s ETA %s %.1f h scale %.0f" % (
                step, seg_end, "e1" if step <= E1 else "e2", run_loss / run_n, sched.get_last_lr()[0], float(tk[0]) / el,
                "epoch1" if step < E1 else "epoch2", eta / 3600, SC.get_scale() if SC.is_enabled() else 1))
            if RANK == 0:
                with open(os.path.join(a.out, "losses.jsonl"), "a") as f:
                    f.write(json.dumps({"step": step, "loss": run_loss / run_n, "lr": sched.get_last_lr()[0], "tok_s": float(tk[0]) / el,
                                        "t": time.time()}) + "\n")
            run_loss, run_n = 0.0, 0
            t0, tok_count = time.time(), 0
        if step % a.save_every == 0:
            save()
            if step % a.keep_every == 0:
                save("step%04d" % step)
            log(a.out, "checkpoint step %d" % step)
        if step % a.eval_every == 0:
            dev_eval()
        if step % a.gen_every == 0 or (mixed and step == E1):
            if gen_hook():
                save(extra={"stopped": "early_stop", "best": best})
                log(a.out, "EARLY STOP at step %d: dev generation score not better for %d evals (best %s)" % (step, a.patience, best["top"]))
                return 6
    # ---- probe result: aggregate speed over ranks (each rank measures its own rows; the ranks run concurrently)
    pt = torch.tensor([float(ptok), ptime, 0.0 if CPU else float(torch.cuda.max_memory_allocated(dev)) / 2 ** 30], device=dev, dtype=torch.float64)
    tot = allreduce(pt.clone())
    mx = allreduce(pt.clone(), torch.distributed.ReduceOp.MAX if WORLD > 1 else None)
    tps = float(tot[0]) / max(1e-6, float(mx[1]))          # all tokens / the slowest rank's busy time
    lv = sum(ploss) / max(1, len(ploss))
    res = {"world": WORLD, "quant": a.quant, "fla": not a.no_fla, "dtype": str(DT).split(".")[-1], "tok_s": round(tps, 1),
           "peak_vram_gib": round(float(mx[2]), 2),
           "peak_reserved_gib": 0 if CPU else round(torch.cuda.max_memory_reserved(dev) / 2 ** 30, 2),
           "host_rss_mb": host_rss_mb(), "levers": [k for k in ("head_cpu", "ckpt_offload", "lean_host") if getattr(a, k)] + (["mlp_chunk%d" % a.mlp_chunk] if a.mlp_chunk else []), "loss": round(lv, 4), "oom_steps": poom,
           "longest_tokens": max(len(rows[k]["ids"]) for k in groups[0]),
           "proj_e1_h": round((tok_inc + tok_chat) / max(1, tps) / 3600, 1), "proj_e2_h": round(tok_e2 / max(1, tps) / 3600, 1)}
    log(a.out, "PROBE_RESULT " + json.dumps(res))
    return 0


if __name__ == "__main__":
    rc = main()
    if WORLD > 1 and torch.distributed.is_initialized():
        torch.distributed.destroy_process_group()
    sys.exit(rc)
