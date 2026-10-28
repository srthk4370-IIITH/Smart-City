"""htpd v8x: split decoding of the reasoner answer (request "split"). One prompt; the head of the answer (keys up to and
including "split_after", default causal_chain) is decoded once; then the state is copied to k sequences and each
decodes its own group of the remaining keys in parallel (one batched step for all), with a forcer whose schema is
head keys + its group. The answer is assembled in the schema's key order. Without "split" nothing changes."""
import sys
p = sys.argv[1]
s = open(p, encoding="utf-8").read()


def rep(old, new, cnt=1):
    global s
    assert s.count(old) == cnt, (s.count(old), old[:90])
    s = s.replace(old, new)


# request-scoped split groups (set by the handler around run_reason)
rep("""static int g_reason_rs = 0;                   // n_rs_seq of the reasoner context
""", """static int g_reason_rs = 0;                   // n_rs_seq of the reasoner context
// v8x split decoding: request "split": [[keys...], ...] (+ "split_after": key); empty = off
static std::vector<std::vector<std::string>> g_req_split;
static std::string g_req_split_after = "causal_chain";
""")

# vectors sized for the split streams; trace/forcer per stream
rep("""    // ---- decode: each step feeds every active stream's pending token plus its forced tokens, logits on the last row
    const int per_seq = (int) (llama_n_ctx(ctx) / std::max<uint32_t>(1, llama_n_seq_max(ctx)));
    std::vector<bool> done(n, false);
    std::vector<std::vector<llama_token>> inj(n);""", """    // ---- decode: each step feeds every active stream's pending token plus its forced tokens, logits on the last row
    const int per_seq = (int) (llama_n_ctx(ctx) / std::max<uint32_t>(1, llama_n_seq_max(ctx)));
    // v8x split: k parallel continuation streams after the head (streams 1..k-1 start inactive)
    const int K_split = (int) g_req_split.size();
    const bool split = n == 1 && schema && !schema->empty() && K_split >= 2 && K_split <= (int) llama_n_seq_max(ctx) &&
                       out[0].stop != "error" && g_reason_spec == 0;
    std::vector<htpd::Schema> subs;
    std::string split_key0;
    if (split) {
        std::vector<std::string> head;
        for (auto & k : schema->keys) { head.push_back(k); if (k == g_req_split_after) break; }
        for (auto & grp : g_req_split) {
            htpd::Schema sc = *schema;
            sc.keys = head;
            for (auto & k : grp) sc.keys.push_back(k);
            subs.push_back(sc);
        }
        split_key0 = "\\"" + g_req_split[0][0] + "\\"";
    }
    const int NS = split ? K_split : n;
    out.resize(NS); pos.resize(NS, 0); pending.resize(NS, 0); changed.resize(NS, 0); fz.resize(NS);
    bool forked = false;
    int fork_tokens = 0, fork_forced = 0;
    size_t fork_len = 0;
    std::string fork_pick;
    std::vector<bool> done(NS, false);
    for (int s = n; s < NS; ++s) done[s] = true;
    std::vector<std::vector<llama_token>> inj(NS);""")

rep("""        out[s].text += p;
        if (lw) ss.add(gmap ? gmap[s] : s, p);""", """        out[s].text += p;
        if (lw && s < n) ss.add(gmap ? gmap[s] : s, p);""")

# main loop over NS streams, fork at the head end
rep("""    while (active > 0) {
        batch.n_tokens = 0;
        std::vector<int> last(n, -1);
        for (int s = 0; s < n; ++s) {
            if (done[s]) continue;""", """    while (active > 0) {
        batch.n_tokens = 0;
        std::vector<int> last(NS, -1);
        for (int s = 0; s < NS; ++s) {
            if (done[s]) continue;""")

rep("""        for (int s = 0; s < n; ++s) {
            if (last[s] < 0) continue;
            pending[s] = pick_forced(llama_get_logits_ith(ctx, last[s]), n_vocab, fz[s], &changed[s]);
            if (handle(s)) { done[s] = true; out[s].ms = ms_since(t0); active--; }
        }""", """        for (int s = 0; s < NS; ++s) {
            if (last[s] < 0) continue;
            pending[s] = pick_forced(llama_get_logits_ith(ctx, last[s]), n_vocab, fz[s], &changed[s]);
            if (split && !forked && s == 0) {
                // fork when the head key's value has closed: the forced text after this pick names the 1st group key
                htpd::Forcer g = fz[0];
                g.feed(piece(pending[0]));
                if (g.forced_text().find(split_key0) != std::string::npos) {
                    forked = true;
                    fork_len = out[0].text.size(); fork_tokens = out[0].tokens; fork_forced = out[0].forced;
                    fork_pick = piece(pending[0]);
                    std::vector<uint8_t> blob(llama_state_seq_get_size(ctx, 0));
                    blob.resize(llama_state_seq_get_data(ctx, blob.data(), blob.size(), 0));
                    const std::string ap = htpd::answer_prefix(prompts[0]);
                    for (int i = 0; i < NS; ++i) {
                        if (i > 0) {
                            if (llama_state_seq_set_data(ctx, blob.data(), blob.size(), i) == 0) { fprintf(stderr, "htpd: split fork %d failed\\n", i); continue; }
                            out[i] = out[0]; pos[i] = pos[0]; pending[i] = pending[0]; done[i] = false; active++;
                        }
                        fz[i] = htpd::Forcer(&subs[i]);
                        if (!fz[i].feed(ap) || !fz[i].feed(out[i].text)) fz[i] = htpd::Forcer(nullptr);
                        if (i > 0 && handle(i)) { done[i] = true; out[i].ms = ms_since(t0); active--; }
                    }
                    fprintf(stderr, "htpd: split at %d tokens into %d streams (state %zu B)\\n", fork_tokens, NS, blob.size());
                }
            }
            if (handle(s)) { done[s] = true; out[s].ms = ms_since(t0); active--; }
        }""")

rep("""    llama_batch_free(batch);
    for (int s = 0; s < n; ++s) {
        llama_memory_seq_rm(mem, s, -1, -1);""", """    llama_batch_free(batch);
    for (int s = 0; s < NS; ++s) {
        llama_memory_seq_rm(mem, s, -1, -1);""")

rep("""    fprintf(stderr, "htpd: reason %d streams, %d decode steps, prefill %.0f ms, cache %s (%d tokens, %.0f ms)\\n",
            n, steps, prefill_ms, rs.cache.c_str(), rs.cached_tokens, rs.cache_ms);
    return out;""", """    fprintf(stderr, "htpd: reason %d streams, %d decode steps, prefill %.0f ms, cache %s (%d tokens, %.0f ms)\\n",
            NS, steps, prefill_ms, rs.cache.c_str(), rs.cached_tokens, rs.cache_ms);
    if (split && forked) {
        // assemble: head + each group's continuation in group order; every group but the last loses its closing '}',
        // and a group that does not start with ',' gets one (the pick that closed the head may carry the comma)
        Out o = out[0];
        o.text = out[0].text.substr(0, fork_len);
        o.tokens = fork_tokens; o.forced = fork_forced; o.ms = 0; o.stop = "json";
        for (int i = 0; i < NS; ++i) {
            std::string seg = out[i].text.substr(std::min(fork_len, out[i].text.size()));
            if (i > 0) {  // drop the shared closing pick (already in group 0) and fix the separator
                seg = seg.substr(std::min(fork_pick.size(), seg.size()));
                size_t a = seg.find_first_not_of(" ");
                seg = a == std::string::npos ? "" : seg.substr(a);
                if (!seg.empty() && seg[0] != ',') seg = ", " + seg;
            }
            if (i + 1 < NS) { size_t e = seg.find_last_not_of(" \\n"); if (e != std::string::npos && seg[e] == '}') seg = seg.substr(0, e); }
            o.text += seg;
            o.tokens += out[i].tokens - fork_tokens; o.forced += out[i].forced - fork_forced;
            o.ms = std::max(o.ms, out[i].ms);
            if (out[i].stop != "json") o.stop = out[i].stop;
        }
        fprintf(stderr, "htpd: split answer: %zu bytes, %d tokens, stop %s\\n", o.text.size(), o.tokens, o.stop.c_str());
        out.assign(1, o);
    } else {
        out.resize(n);
    }
    return out;""")

# handler: read "split" / "split_after"
rep("""                        std::string prefix;
                        if (auto v = req.get("prefix"); v && v->type == JVal::STR) prefix = v->str;""", """                        std::string prefix;
                        if (auto v = req.get("prefix"); v && v->type == JVal::STR) prefix = v->str;
                        g_req_split.clear();
                        g_req_split_after = "causal_chain";
                        if (auto v = req.get("split"); v && v->type == JVal::ARR)
                            for (auto & grp : v->arr) {
                                if (grp.type != JVal::ARR) continue;
                                std::vector<std::string> ks;
                                for (auto & e : grp.arr) if (e.type == JVal::STR) ks.push_back(e.str);
                                if (!ks.empty()) g_req_split.push_back(ks);
                            }
                        if (auto v = req.get("split_after"); v && v->type == JVal::STR) g_req_split_after = v->str;""")
open(p, "w", encoding="utf-8", newline="\n").write(s)
print("split patched")
