// Host unit test for htpd_logic.h (no llama.cpp needed):
//   g++ -std=c++17 -O2 -o test_logic test_logic.cpp && ./test_logic [cases.jsonl]
// cases.jsonl (optional): one {"src","id","stop","sys","text"} per line - real device outputs (text after the
// agent prefill `{"pattern": "`) with the system turn of their prompt, written by make_cases.py.
#include "htpd_logic.h"

#include <cassert>
#include <fstream>
#include <iostream>
#include <random>

using namespace htpd;

// ---- the v6 stop rule, verbatim from htpd.cpp before v7, as the reference
struct OldScanner {
    int depth = 0;
    bool in_str = false, esc = false, after_colon = false, in_key = false, trim;
    std::string key, text;
    std::string stop;
    OldScanner(const std::string & prefill, bool trim_action) : trim(trim_action) { feed(prefill, false); }
    bool feed(const std::string & s, bool count = true) {
        for (char c : s) {
            if (count) text += c;
            if (in_str) {
                if (esc) { esc = false; }
                else if (c == '\\') { esc = true; }
                else if (c == '"') {
                    in_str = false;
                    if (in_key) {
                        in_key = false;
                        if (trim && depth == 1 && key == "action") {
                            size_t q = text.rfind("\"action\"");
                            size_t comma = text.rfind(',', q);
                            if (comma != std::string::npos) text = text.substr(0, comma);
                            text += "}";
                            stop = "action";
                            return true;
                        }
                    }
                } else if (in_key) {
                    key += c;
                }
                continue;
            }
            if (c == '"') {
                in_str = true;
                if (depth == 1 && !after_colon) { in_key = true; key.clear(); }
            } else if (c == '{' || c == '[') {
                ++depth; after_colon = false;
            } else if (c == '}' || c == ']') {
                if (--depth == 0) { stop = "json"; return true; }
            } else if (c == ':') {
                after_colon = true;
            } else if (c == ',') {
                after_colon = false;
            }
        }
        return false;
    }
};

static int g_fail = 0, g_checks = 0;
#define CHECK(c) do { ++g_checks; if (!(c)) { ++g_fail; std::cerr << "FAIL " << __LINE__ << ": " #c "\n"; } } while (0)

static const std::string PRE = "{\"pattern\": \"";

// split s into random pieces of 1..6 bytes (token-like)
static std::vector<std::string> chunks(const std::string & s, std::mt19937 & rng) {
    std::vector<std::string> v;
    std::uniform_int_distribution<int> d(1, 6);
    for (size_t i = 0; i < s.size();) { size_t k = std::min(s.size() - i, (size_t) d(rng)); v.push_back(s.substr(i, k)); i += k; }
    return v;
}

template <class S> static std::pair<std::string, std::string> run_scan(S & sc, const std::vector<std::string> & pcs) {
    for (auto & p : pcs) if (sc.feed(p)) break;
    return {sc.text, sc.stop};
}

static void test_json() {
    JVal v;
    CHECK(json_parse("{\"kind\":\"agents\",\"prompts\":[\"a\\nb\",\"\\u003c|x|\\u003e\"],\"labels\":[[\"stable\",\"spike\"],{\"status\":[\"normal\"]},null],\"logprobs\":true,\"id\":7}", v));
    CHECK(v.get("kind") && v.get("kind")->str == "agents");
    CHECK(v.get("prompts")->arr.size() == 2 && v.get("prompts")->arr[0].str == "a\nb" && v.get("prompts")->arr[1].str == "<|x|>");
    CHECK(v.get("logprobs")->truthy() && v.get("id")->num == 7);
    Labels a = labels_from_json(&v.get("labels")->arr[0]);
    Labels b = labels_from_json(&v.get("labels")->arr[1]);
    Labels c = labels_from_json(&v.get("labels")->arr[2]);
    CHECK(a.size() == 1 && a["pattern"].size() == 2 && b.size() == 1 && b["status"][0] == "normal" && c.empty());
    CHECK(json_parse("\"\\ud83d\\ude00\"", v) && v.str == "\xF0\x9F\x98\x80");
    CHECK(!json_parse("{\"a\":}", v));
    CHECK(!json_parse("{\"a\":1} x", v));
    CHECK(json_escape("a\"b\\\n\x01") == "a\\\"b\\\\\\n\\u0001");
}

static void test_labels_prompt() {
    std::string sys = "You are... JSON keys: pattern (stable|spike|dip), status (normal|warning|critical|sensor_fault), "
                      "observations (1-2 short strings, each ending with cited ids like [E1,E4]), likely_cause (a_b|c), "
                      "confidence (0-1), event_active (true|false), onset (HH:MM), fault_kind (stuck|bias|quantised, only if sensor_fault), "
                      "action (none|monitor).<|eot_id|>user: pattern (zzz|yyy)";
    Labels L = labels_from_prompt(sys, {"pattern", "status", "likely_cause", "fault_kind", "action", "confidence", "onset"});
    CHECK(L["pattern"] == std::vector<std::string>({"stable", "spike", "dip"}));
    CHECK(L["status"].size() == 4 && L["likely_cause"].size() == 2 && L["action"].size() == 2);
    CHECK(L["fault_kind"].size() == 3 && L["fault_kind"][2] == "quantised");
    CHECK(!L.count("confidence") && !L.count("onset"));  // not label lists
    CHECK(labels_from_prompt("no keys here", {"pattern"}).empty());
}

static JState after(const std::string & s) { JState st; for (char c : s) st.step(c); return st; }

static void test_trie_synthetic() {
    Labels L = {{"pattern", {"stable", "spike", "step_increase", "step_decrease"}}, {"status", {"normal", "warning"}}};
    JState st = after(PRE);
    CHECK(in_constrained(st, L));
    CHECK(piece_allowed(st, "stable", L));
    CHECK(piece_allowed(st, "st", L));
    CHECK(piece_allowed(st, "step_", L));
    CHECK(!piece_allowed(st, " stable", L));
    CHECK(!piece_allowed(st, "stablex", L));
    CHECK(!piece_allowed(st, "strep", L));
    CHECK(!piece_allowed(st, "\"", L));          // empty value is not a label
    CHECK(!piece_allowed(st, "", L));            // empty piece inside a constrained value
    CHECK(!piece_allowed(st, "st\n", L));
    CHECK(!piece_allowed(st, "s\\u", L));
    CHECK(piece_allowed(st, "stable\",", L));
    CHECK(piece_allowed(st, "stable\", \"status\": \"norm", L));
    CHECK(!piece_allowed(st, "stable\", \"status\": \"nope", L));
    JState mid = after(PRE + "spi");
    CHECK(piece_allowed(mid, "ke\"", L));
    CHECK(!piece_allowed(mid, "kes\"", L));
    CHECK(!piece_allowed(mid, "\"", L));
    // outside constrained values anything goes
    JState obs = after(PRE + "spike\", \"observations\": [\"");
    CHECK(!in_constrained(obs, L));
    CHECK(piece_allowed(obs, "anything\n at all", L));
    CHECK(piece_allowed(obs, "", L));
    // a value opened inside the piece is checked too
    JState pre_status = after(PRE + "spike\", \"status\":");
    CHECK(piece_allowed(pre_status, " \"warn", L));
    CHECK(!piece_allowed(pre_status, " \"wrong", L));
    // empty labels = no constraint
    CHECK(piece_allowed(st, " garbage\n", Labels{}));
}

static void test_abort_synthetic() {
    Labels L = {{"pattern", {"stable", "spike"}}};
    auto run = [&](const std::string & gen, int level, const Labels * l) {
        Scanner sc(PRE, true);
        sc.abort.level = level;
        sc.labels = l;
        sc.feed(gen);
        return sc;
    };
    CHECK(run("stable\", \"status\": \"normal\", \"confidence\": 0.85, \"event_active\": true, \"onset\": null, \"action\": \"none\"}", 1, &L).stop == "action");
    CHECK(run("step 0, 0 1-1\nG 1", 1, nullptr).stop == "abort");          // newline in string
    CHECK(run("stablee", 1, &L).stop == "abort");                          // longer than any label
    CHECK(run("stablee", 1, nullptr).stop == "");                          // no labels: 48-byte default
    CHECK(run(std::string(49, 'a'), 1, nullptr).stop == "abort");
    CHECK(run("stable\", x", 1, &L).stop == "abort");                      // non-JSON byte outside strings
    CHECK(run("stable\",\n \"status\": \"normal\"}", 1, &L).stop == "json"); // legal newline: level 1 keeps it
    CHECK(run("stable\",\n \"status\": \"normal\"}", 2, &L).stop == "abort");
    CHECK(run("stable\", \"o\": [[1]]}", 2, &L).stop == "abort");
    CHECK(run("stable\", \"o\": [[1]]}", 1, &L).stop == "json");
    CHECK(run("stable\", \"Rear 0.7 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0", 2, &L).stop == "abort");
    CHECK(run("stable\", \"Rear 0.7 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0", 1, &L).stop == "");
    Scanner off(PRE, true);
    off.feed("step 0\n1 1\n");
    CHECK(off.stop.empty());                                                // level 0 = old behaviour
}

static void test_ngram() {
    NgramTable t;
    t.build({{1, 2, 3, 4}, {1, 2, 3, 5}, {1, 2, 3, 5}, {9, 3, 7}});
    int32_t h[] = {0, 1, 2, 3};
    CHECK(t.lookup(h, 4, 3) == 5);   // [1,2,3] -> 5 (2x) over 4 (1x)
    CHECK(t.lookup(h, 4, 1) == 5);   // [3] -> 5 (2x), 4 (1x), 7 (1x)
    int32_t g[] = {7, 8};
    CHECK(t.lookup(g, 2, 1) == -1);
    NgramTable tie;
    tie.build({{1, 4}, {1, 3}});
    int32_t o[] = {1};
    CHECK(tie.lookup(o, 1, 1) == 4); // tie -> first seen
}

static void test_logprobs() {
    std::vector<float> lg = {0.f, 2.f, 1.f, 2.f, -1.f};
    auto top = top_logprobs(lg.data(), (int) lg.size(), 3);
    CHECK(top.size() == 3 && top[0].first == 1 && top[1].first == 3 && top[2].first == 2);
    double z = 0;
    for (float x : lg) z += std::exp(x);
    CHECK(std::fabs(top[0].second - (2.0 - std::log(z))) < 1e-5);
}

// real device outputs: v7 scanner == v6 scanner; abort never fires on valid outputs; trie allows them
static void test_cases(const char * path) {
    std::ifstream f(path);
    if (!f) { std::cerr << "no cases file " << path << ", skipping corpus tests\n"; return; }
    std::mt19937 rng(42);
    std::string line;
    int n = 0, same = 0, same_act = 0, n_act = 0;
    int valid = 0, valid_abort1 = 0, valid_abort2 = 0, valid_trie_block = 0;
    int invalid = 0, inv_abort = 0, inv_trie_block_in_pattern = 0, runaway = 0, runaway_abort = 0, runaway_abort2 = 0;
    long runaway_chars = 0, runaway_abort_chars = 0;
    std::map<std::string, int> why;
    while (std::getline(f, line)) {
        JVal c;
        if (!json_parse(line, c)) continue;
        const std::string text = c.get("text")->str, stop = c.get("stop") && c.get("stop")->type == JVal::STR ? c.get("stop")->str : "";
        const std::string sys = c.get("sys")->str;
        ++n;
        // 1) stop rule equivalence on random token splits
        auto pcs = chunks(text, rng);
        OldScanner o(PRE, true);
        Scanner s(PRE, true);
        auto ro = run_scan(o, pcs), rs = run_scan(s, pcs);
        same += ro == rs;
        // 2) the "action" trim: rebuild the untrimmed text when the device trimmed it
        if (stop == "action" && !text.empty() && text.back() == '}') {
            ++n_act;
            std::string full = text.substr(0, text.size() - 1) + ", \"action\": \"monitor\"}";
            auto p2 = chunks(full, rng);
            OldScanner o2(PRE, true);
            Scanner s2(PRE, true);
            auto a = run_scan(o2, p2), b = run_scan(s2, p2);
            same_act += a == b && b.first == text && b.second == "action";
        }
        if (sys.empty()) continue;
        Labels L = labels_from_prompt(sys, {"pattern", "status", "likely_cause", "action"});
        JVal obj;
        bool ok = json_parse(PRE + text, obj) && obj.type == JVal::OBJ;
        if (ok) {
            for (auto k : {"pattern", "status"}) {
                const JVal * v = obj.get(k);
                if (!v || v->type != JVal::STR || !L.count(k) || !is_any(v->str, L[k])) ok = false;
            }
        }
        // 3) abort rule
        for (int lvl = 1; lvl <= 2; ++lvl) {
            Scanner a(PRE, true);
            a.abort.level = lvl;
            a.labels = &L;
            auto r = run_scan(a, pcs);
            if (ok && r.second == "abort") { (lvl == 1 ? valid_abort1 : valid_abort2)++; std::cerr << "valid output aborted (" << a.abort_why << "): " << text.substr(0, 120) << "\n"; }
            if (lvl == 1 && ok) CHECK(r == rs);  // byte-identical
            if (lvl == 1 && !ok && r.second == "abort") { inv_abort++; why[a.abort_why]++; }
            if (lvl == 2 && stop == "ctx" && r.second == "abort") runaway_abort2++;
            if (lvl == 1 && stop == "ctx") { runaway++; runaway_chars += (long) text.size(); if (r.second == "abort") { runaway_abort++; runaway_abort_chars += (long) r.first.size(); } }
        }
        // 4) trie over pattern/status: every piece of a valid output is allowed; invalid ones get blocked
        Labels T;
        T["pattern"] = L["pattern"];
        T["status"] = L["status"];
        JState st = after(PRE);
        bool blocked = false, blocked_in_pattern = false;
        for (auto & p : pcs) {
            if (!piece_allowed(st, p, T)) { blocked = true; blocked_in_pattern = st.in_val && st.key == "pattern"; break; }
            for (char ch : p) st.step(ch);
        }
        if (ok) { ++valid; valid_trie_block += blocked; if (blocked) std::cerr << "valid output blocked by trie: " << text.substr(0, 120) << "\n"; }
        else { ++invalid; inv_trie_block_in_pattern += blocked && blocked_in_pattern; }
    }
    std::cout << "corpus: " << n << " outputs; v7 scanner == v6 scanner on " << same << "/" << n
              << "; action trim identical " << same_act << "/" << n_act << "\n";
    std::cout << "valid (JSON + on-label pattern/status): " << valid << "; aborted at level1 " << valid_abort1
              << ", level2 " << valid_abort2 << "; trie-blocked " << valid_trie_block << "\n";
    std::cout << "invalid/off-label: " << invalid << "; aborted (level 1) " << inv_abort
              << "; trie blocks inside pattern " << inv_trie_block_in_pattern << "\n";
    std::cout << "runaways (stop ctx): " << runaway << ", aborted " << runaway_abort << " (level 2: " << runaway_abort2 << "); mean chars "
              << (runaway ? runaway_chars / runaway : 0) << " -> " << (runaway_abort ? runaway_abort_chars / runaway_abort : 0) << "\n";
    for (auto & w : why) std::cout << "  abort reason: " << w.first << " x" << w.second << "\n";
    CHECK(same == n);
    CHECK(same_act == n_act);
    CHECK(valid_abort1 == 0 && valid_abort2 == 0 && valid_trie_block == 0);
}

static void test_stream() {
    CHECK(utf8_complete_prefix("abc") == 3);
    CHECK(utf8_complete_prefix("a\xC2") == 1);              // lead of a 2-byte char, held back
    CHECK(utf8_complete_prefix("a\xC2\xB0") == 3);          // degree sign complete
    CHECK(utf8_complete_prefix("\xE2\x82") == 0);           // 3-byte char, 2 bytes so far
    CHECK(utf8_complete_prefix("x\xF0\x9F\x98") == 1);
    CHECK(utf8_complete_prefix("x\xF0\x9F\x98\x80") == 5);
    CHECK(utf8_complete_prefix("\x80\x80") == 2);           // malformed: passed through
    StepStream ss;
    ss.reset(3);
    std::string l;
    CHECK(!ss.line(l));                                     // nothing new: no line
    ss.add(0, "28.9 \xC2"); ss.add(2, "ok\"");
    CHECK(ss.line(l) && l == "{\"kind\":\"toks\",\"t\":[\"28.9 \",\"\",\"ok\\\"\"]}\n");
    ss.add(0, "\xB0" "C");
    CHECK(ss.line(l) && l == "{\"kind\":\"toks\",\"t\":[\"\xC2\xB0" "C\",\"\",\"\"]}\n");
    // concatenating every streamed piece reproduces the fed text (up to a held-back partial tail)
    std::mt19937 rng(1);
    std::string src = "{\"pattern\": \"stable\", \"t\": \"28.9 \xC2\xB0" "C, 12 \xC2\xB5g/m\xC2\xB3 \xF0\x9F\x98\x80\"}";
    for (int rep = 0; rep < 200; ++rep) {
        StepStream s1;
        s1.reset(1);
        std::string got;
        for (auto & p : chunks(src, rng)) {
            s1.add(0, p);
            if (s1.line(l)) {
                JVal v;
                CHECK(json_parse(l.substr(0, l.size() - 1), v));
                got += v.get("t")->arr[0].str;
            }
        }
        CHECK(got == src);
    }
}

int main(int argc, char ** argv) {
    test_stream();
    test_json();
    test_labels_prompt();
    test_trie_synthetic();
    test_abort_synthetic();
    test_ngram();
    test_logprobs();
    if (argc > 1) test_cases(argv[1]);
    std::cout << (g_fail ? "FAILED " : "OK ") << g_checks - g_fail << "/" << g_checks << " checks\n";
    return g_fail ? 1 : 0;
}
