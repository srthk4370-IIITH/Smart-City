#!/usr/bin/env python3
# htpd v9c -> v9d: live corpus growth (HTPD_REASON_CORPUS_LIVE) + long drafts behind long matches (HTPD_REASON_SPEC_KLONG).
# usage: python3 patch_v9d.py htpd.cpp   (applies to the v9c source, md5 36433cfa...)
import sys
p = sys.argv[1]
s = open(p, encoding='utf-8').read()


def rep(a, b, cnt=1):
    global s
    assert s.count(a) == cnt, (a[:80], s.count(a))
    s = s.replace(a, b)


rep('#include <unordered_map>\n', '#include <unordered_map>\n#include <unordered_set>\n')
rep('''static bool g_sspec_ctx = false;     // the loaded reasoner context has the 2 x streams sequences''',
'''static bool g_sspec_ctx = false;     // the loaded reasoner context has the 2 x streams sequences
// v9d (default off): HTPD_REASON_CORPUS_LIVE=<file>: loaded like the corpus and, after every complete split report,
// each stream's emitted tokens (head + its group) are added to the in-memory corpus and appended to the file (exact
// duplicates skipped; at most HTPD_REASON_CORPUS_LIVE_MAX docs, default 3000). Drafts stay verified, so only the
// number of kept drafts changes. HTPD_REASON_SPEC_KLONG=K2 (0 = off): a stream whose draft match is at least
// HTPD_REASON_SPEC_LONGM (16) tokens long may draft up to K2 tokens (the rows cap still applies).
static std::string g_corpus_live;
static int g_corpus_live_max = 3000, g_corpus_live_n = 0;
static int g_sspec_klong = 0, g_sspec_longm = 16;''')
rep('''    int docs = 0;
    static uint64_t key(llama_token a, llama_token b) { return ((uint64_t) (uint32_t) a << 32) | (uint32_t) b; }
    bool load(const char * path, bool with_uni) {
        FILE * fp = fopen(path, "rb");
        if (!fp) return false;
        std::vector<llama_token> doc;
        long v = 0;
        bool in = false;
        int c;
        auto end_doc = [&] { if (!doc.empty()) { t.insert(t.end(), doc.begin(), doc.end()); t.push_back(-1); docs++; doc.clear(); } };
        while ((c = fgetc(fp)) != EOF) {
            if (c >= '0' && c <= '9') { v = v * 10 + (c - '0'); in = true; continue; }
            if (in) { doc.push_back((llama_token) v); v = 0; in = false; }
            if (c == '\\n') end_doc();
        }
        if (in) doc.push_back((llama_token) v);
        end_doc();
        fclose(fp);
        for (size_t i = 1; i < t.size(); ++i) if (t[i] >= 0 && t[i - 1] >= 0) bi[key(t[i - 1], t[i])].push_back((int) i);
        if (with_uni) for (size_t i = 0; i < t.size(); ++i) if (t[i] >= 0) uni[t[i]].push_back((int) i);
        return docs > 0;
    }''',
'''    int docs = 0;
    bool with_uni = false;
    std::unordered_set<uint64_t> seen;                          // v9d: hashes of the docs (exact duplicates skipped)
    static uint64_t key(llama_token a, llama_token b) { return ((uint64_t) (uint32_t) a << 32) | (uint32_t) b; }
    static uint64_t hash(const llama_token * p, size_t n) {
        uint64_t h = 1469598103934665603ull;
        for (size_t i = 0; i < n; ++i) { h ^= (uint32_t) p[i]; h *= 1099511628211ull; }
        return h ^ n;
    }
    // index t[i0..] (positions only grow, so the candidate lists stay in corpus order)
    void index_from(size_t i0) {
        for (size_t i = std::max<size_t>(i0, 1); i < t.size(); ++i) if (t[i] >= 0 && t[i - 1] >= 0) bi[key(t[i - 1], t[i])].push_back((int) i);
        if (with_uni) for (size_t i = i0; i < t.size(); ++i) if (t[i] >= 0) uni[t[i]].push_back((int) i);
    }
    // append one doc (not indexed); false = empty or duplicate
    bool push_doc(const llama_token * p, size_t n) {
        if (n == 0 || !seen.insert(hash(p, n)).second) return false;
        t.insert(t.end(), p, p + n); t.push_back(-1); docs++;
        return true;
    }
    bool add(const std::vector<llama_token> & d) { const size_t i0 = t.size(); if (!push_doc(d.data(), d.size())) return false; index_from(i0); return true; }
    // keep_last > 0: only the last keep_last lines of the file. Returns the docs added (-1: no file).
    int load(const char * path, bool uni_idx, int keep_last = 0) {
        with_uni = uni_idx;
        FILE * fp = fopen(path, "rb");
        if (!fp) return -1;
        std::vector<std::vector<llama_token>> ds;
        std::vector<llama_token> doc;
        long v = 0;
        bool in = false;
        int c;
        auto end_doc = [&] { if (!doc.empty()) { ds.push_back(std::move(doc)); doc.clear(); } };
        while ((c = fgetc(fp)) != EOF) {
            if (c >= '0' && c <= '9') { v = v * 10 + (c - '0'); in = true; continue; }
            if (in) { doc.push_back((llama_token) v); v = 0; in = false; }
            if (c == '\\n') end_doc();
        }
        if (in) doc.push_back((llama_token) v);
        end_doc();
        fclose(fp);
        const size_t first = keep_last > 0 && ds.size() > (size_t) keep_last ? ds.size() - keep_last : 0;
        const size_t i0 = t.size();
        int added = 0;
        for (size_t k = first; k < ds.size(); ++k) added += push_doc(ds[k].data(), ds[k].size());
        index_from(i0);
        return added;
    }''')
rep('''            if (!g_corpus.load(cf, g_sspec_min <= 1)) fprintf(stderr, "htpd: reason corpus %s: cannot load (prompt lookup only)\\n", cf);''',
'''            if (g_corpus.load(cf, g_sspec_min <= 1) <= 0) fprintf(stderr, "htpd: reason corpus %s: cannot load (prompt lookup only)\\n", cf);''')
rep('''        fprintf(stderr, "htpd: v9 split-spec: K %d, min match %d, rows cap %d, kv %s, align %d, corpus %d docs\\n", g_sspec_k, g_sspec_min,
                g_sspec_rows, g_sspec_kvu ? "unified" : "streams", (int) g_sspec_align, g_corpus.docs);''',
'''        g_sspec_klong = std::max(0, std::min(32, env_int("HTPD_REASON_SPEC_KLONG", 0)));
        g_sspec_longm = std::max(2, env_int("HTPD_REASON_SPEC_LONGM", 16));
        if (const char * lf = getenv("HTPD_REASON_CORPUS_LIVE"); lf && *lf) {
            g_corpus_live = lf;
            g_corpus_live_max = std::max(1, env_int("HTPD_REASON_CORPUS_LIVE_MAX", 3000));
            auto tcl = clk::now();
            const int a = g_corpus.load(lf, g_sspec_min <= 1, g_corpus_live_max);
            g_corpus_live_n = std::max(0, a);
            fprintf(stderr, "htpd: v9d live corpus %s: %d docs added (%s), corpus now %d docs, %zu tokens, %.0f ms\\n", lf, g_corpus_live_n,
                    a < 0 ? "new file" : "loaded", g_corpus.docs, g_corpus.t.size(), ms_since(tcl));
        }
        fprintf(stderr, "htpd: v9 split-spec: K %d, min match %d, rows cap %d, kv %s, align %d, corpus %d docs, klong %d (match >= %d), live %s\\n",
                g_sspec_k, g_sspec_min, g_sspec_rows, g_sspec_kvu ? "unified" : "streams", (int) g_sspec_align, g_corpus.docs,
                g_sspec_klong, g_sspec_longm, g_corpus_live.empty() ? "off" : "on");''')
rep('''static void sspec_draft(const std::vector<llama_token> & h, int K, std::vector<llama_token> & d, int & src) {
    static thread_local std::vector<llama_token> dc;
    src = 0;''',
'''static void sspec_draft(const std::vector<llama_token> & h, int K, std::vector<llama_token> & d, int & src, int Klong = 0) {
    static thread_local std::vector<llama_token> dc;
    src = 0;
    if (Klong > K) {  // v9d: long drafts only behind a long match
        sspec_draft(h, Klong, d, src);
        const int m = src == 1 ? sspec_prompt_match(h, 1, g_sspec_maxm, dc) : src == 2 ? g_corpus.match(h, 1, g_sspec_maxm, g_sspec_min, dc) : 0;
        if (m < g_sspec_longm && (int) d.size() > K) d.resize(K);
        return;
    }''')
rep('''                    sspec_draft(hist[s], std::min(g_sspec_k, budget), drf[s], src);''',
'''                    sspec_draft(hist[s], std::min(g_sspec_k, budget), drf[s], src, std::min(g_sspec_klong, budget));''')
rep('''        if (failed) active = 0;
        if (steps > 0)
            fprintf(stderr, "htpd: reason step profile''',
'''        if (failed) active = 0;
        if (!g_corpus_live.empty() && !failed && forked) {  // v9d: grow the corpus with this report's streams
            bool ok = true;
            for (int s = 0; s < NS; ++s) ok = ok && out[s].stop == "json";
            const size_t P = toks[0].size();
            int added = 0;
            if (ok && g_corpus_live_n < g_corpus_live_max) {
                FILE * lf = fopen(g_corpus_live.c_str(), "a");
                for (int s = 0; s < NS && g_corpus_live_n < g_corpus_live_max; ++s) {
                    if (hist[s].size() < P + 8) continue;
                    std::vector<llama_token> d(hist[s].begin() + P, hist[s].end());
                    if (!g_corpus.add(d)) continue;
                    added++; g_corpus_live_n++;
                    if (lf) {
                        fputc('[', lf);
                        for (size_t k = 0; k < d.size(); ++k) fprintf(lf, k ? ",%d" : "%d", (int) d[k]);
                        fputs("]\\n", lf);
                    }
                }
                if (lf) fclose(lf);
            }
            fprintf(stderr, "htpd: v9d live corpus: %s, %d docs added (live %d, corpus %d docs)\\n", ok ? "report complete" : "report incomplete",
                    added, g_corpus_live_n, g_corpus.docs);
        }
        if (steps > 0)
            fprintf(stderr, "htpd: reason step profile''')
open(p, 'w', encoding='utf-8', newline='').write(s)
print("ok")
