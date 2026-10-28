// htpd_logic.h: the pure (llama-free) parts of htpd, so they can be unit-tested on the host
// (test_logic.cpp). Everything here works on bytes / token ids only.
//
//   JVal / json_parse   minimal JSON reader for request lines (strings, numbers, bools, null, arrays, objects)
//   json_escape         JSON string escaping for responses
//   JState              byte-level JSON lexer state shared by the stop rule, the abort guard and the trie
//   Scanner             the app's stop rule (object closed / agent "action" key) + optional JSON-abort guard
//   Labels / labels_from_prompt / piece_allowed   per-key label sets and the label-prefix (trie) constraint
//   NgramTable          static per-role draft table (n-gram -> most frequent next token)
//   top_logprobs        top-k log-softmax of one logits row
#pragma once

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <map>
#include <string>
#include <unordered_map>
#include <utility>
#include <vector>

namespace htpd {

// ------------------------------------------------------------------ JSON escape / parse

inline std::string json_escape(const std::string & s) {
    std::string o;
    o.reserve(s.size() + 16);
    for (unsigned char c : s) {
        switch (c) {
            case '"': o += "\\\""; break;
            case '\\': o += "\\\\"; break;
            case '\n': o += "\\n"; break;
            case '\r': o += "\\r"; break;
            case '\t': o += "\\t"; break;
            default:
                if (c < 0x20) { char b[8]; snprintf(b, sizeof b, "\\u%04x", c); o += b; }
                else o += (char) c;
        }
    }
    return o;
}

struct JVal {
    enum Type { NUL, BOOL, NUM, STR, ARR, OBJ } type = NUL;
    bool b = false;
    double num = 0;
    std::string str;
    std::vector<JVal> arr;
    std::vector<std::pair<std::string, JVal>> obj;

    const JVal * get(const char * k) const {
        if (type != OBJ) return nullptr;
        for (auto & kv : obj) if (kv.first == k) return &kv.second;
        return nullptr;
    }
    bool truthy() const { return (type == BOOL && b) || (type == NUM && num != 0); }
};

namespace detail {
inline void skip_ws(const std::string & s, size_t & i) { while (i < s.size() && (s[i] == ' ' || s[i] == '\t' || s[i] == '\n' || s[i] == '\r')) ++i; }

inline void put_utf8(std::string & out, unsigned cp) {
    if (cp < 0x80) out += (char) cp;
    else if (cp < 0x800) { out += (char) (0xC0 | (cp >> 6)); out += (char) (0x80 | (cp & 0x3F)); }
    else if (cp < 0x10000) { out += (char) (0xE0 | (cp >> 12)); out += (char) (0x80 | ((cp >> 6) & 0x3F)); out += (char) (0x80 | (cp & 0x3F)); }
    else { out += (char) (0xF0 | (cp >> 18)); out += (char) (0x80 | ((cp >> 12) & 0x3F)); out += (char) (0x80 | ((cp >> 6) & 0x3F)); out += (char) (0x80 | (cp & 0x3F)); }
}

inline unsigned hex4(const std::string & s, size_t i, bool & ok) {
    if (i + 4 > s.size()) { ok = false; return 0; }
    unsigned v = 0;
    for (size_t k = i; k < i + 4; ++k) {
        char c = s[k];
        v <<= 4;
        if (c >= '0' && c <= '9') v |= (unsigned) (c - '0');
        else if (c >= 'a' && c <= 'f') v |= (unsigned) (c - 'a' + 10);
        else if (c >= 'A' && c <= 'F') v |= (unsigned) (c - 'A' + 10);
        else { ok = false; return 0; }
    }
    return v;
}

// s[i] == '"'; on success i is just past the closing quote
inline bool parse_str(const std::string & s, size_t & i, std::string & out) {
    out.clear();
    ++i;
    while (i < s.size() && s[i] != '"') {
        if (s[i] == '\\') {
            if (i + 1 >= s.size()) return false;
            char e = s[++i];
            switch (e) {
                case 'n': out += '\n'; break;
                case 't': out += '\t'; break;
                case 'r': out += '\r'; break;
                case 'b': out += '\b'; break;
                case 'f': out += '\f'; break;
                case 'u': {
                    bool ok = true;
                    unsigned cp = hex4(s, i + 1, ok);
                    if (!ok) return false;
                    i += 4;
                    if (cp >= 0xD800 && cp <= 0xDBFF && i + 6 < s.size() && s[i + 1] == '\\' && s[i + 2] == 'u') {
                        unsigned lo = hex4(s, i + 3, ok);
                        if (ok && lo >= 0xDC00 && lo <= 0xDFFF) { cp = 0x10000 + ((cp - 0xD800) << 10) + (lo - 0xDC00); i += 6; }
                    }
                    put_utf8(out, cp);
                    break;
                }
                default: out += e;  // \" \\ \/
            }
        } else {
            out += s[i];
        }
        ++i;
    }
    if (i >= s.size()) return false;
    ++i;
    return true;
}

inline bool parse_val(const std::string & s, size_t & i, JVal & v, int depth) {
    if (depth > 64) return false;
    skip_ws(s, i);
    if (i >= s.size()) return false;
    char c = s[i];
    if (c == '"') { v.type = JVal::STR; return parse_str(s, i, v.str); }
    if (c == '{') {
        v.type = JVal::OBJ; ++i; skip_ws(s, i);
        if (i < s.size() && s[i] == '}') { ++i; return true; }
        for (;;) {
            skip_ws(s, i);
            if (i >= s.size() || s[i] != '"') return false;
            std::string k;
            if (!parse_str(s, i, k)) return false;
            skip_ws(s, i);
            if (i >= s.size() || s[i] != ':') return false;
            ++i;
            JVal e;
            if (!parse_val(s, i, e, depth + 1)) return false;
            v.obj.emplace_back(std::move(k), std::move(e));
            skip_ws(s, i);
            if (i < s.size() && s[i] == ',') { ++i; continue; }
            if (i < s.size() && s[i] == '}') { ++i; return true; }
            return false;
        }
    }
    if (c == '[') {
        v.type = JVal::ARR; ++i; skip_ws(s, i);
        if (i < s.size() && s[i] == ']') { ++i; return true; }
        for (;;) {
            JVal e;
            if (!parse_val(s, i, e, depth + 1)) return false;
            v.arr.push_back(std::move(e));
            skip_ws(s, i);
            if (i < s.size() && s[i] == ',') { ++i; continue; }
            if (i < s.size() && s[i] == ']') { ++i; return true; }
            return false;
        }
    }
    if (s.compare(i, 4, "true") == 0) { v.type = JVal::BOOL; v.b = true; i += 4; return true; }
    if (s.compare(i, 5, "false") == 0) { v.type = JVal::BOOL; v.b = false; i += 5; return true; }
    if (s.compare(i, 4, "null") == 0) { v.type = JVal::NUL; i += 4; return true; }
    if (c == '-' || (c >= '0' && c <= '9')) {
        const char * b = s.c_str() + i;
        char * e = nullptr;
        v.type = JVal::NUM;
        v.num = strtod(b, &e);
        if (e == b) return false;
        i += (size_t) (e - b);
        return true;
    }
    return false;
}
}  // namespace detail

// parse one JSON document (a request line); false on syntax error
inline bool json_parse(const std::string & s, JVal & out) {
    size_t i = 0;
    out = JVal();
    if (!detail::parse_val(s, i, out, 0)) return false;
    detail::skip_ws(s, i);
    return i == s.size();
}

// ------------------------------------------------------------------ JSON lexer state

// Byte-level state of the generated JSON, enough for the app's stop rule and for the label constraint.
// "value" = a string that is the value of a top-level (depth 1) key; `key` then names that key.
struct JState {
    int depth = 0;
    bool in_str = false, esc = false, after_colon = false, in_key = false, in_val = false;
    std::string key;  // last top-level key (complete once in_key is false)
    std::string val;  // raw bytes of the current top-level string value so far (escapes kept as written)

    enum Ev { NONE, KEY_CLOSED, VAL_OPENED, VAL_CLOSED, CLOSED_ROOT };
    // advance by one byte; returns the structural event it caused
    Ev step(char c) {
        if (in_str) {
            if (esc) { esc = false; if (in_val) val += c; else if (in_key) key += c; return NONE; }
            if (c == '\\') { esc = true; if (in_val) val += c; else if (in_key) key += c; return NONE; }
            if (c == '"') {
                in_str = false;
                if (in_key) { in_key = false; return KEY_CLOSED; }
                if (in_val) { in_val = false; return VAL_CLOSED; }
                return NONE;
            }
            if (in_key) key += c;
            else if (in_val) val += c;
            return NONE;
        }
        if (c == '"') {
            in_str = true;
            if (depth == 1 && !after_colon) { in_key = true; key.clear(); }
            else if (depth == 1 && after_colon) { in_val = true; val.clear(); return VAL_OPENED; }
        } else if (c == '{' || c == '[') {
            ++depth; after_colon = false;
        } else if (c == '}' || c == ']') {
            if (--depth == 0) return CLOSED_ROOT;
        } else if (c == ':') {
            after_colon = true;
        } else if (c == ',') {
            after_colon = false;
        }
        return NONE;
    }
};

// ------------------------------------------------------------------ labels (trie constraint)

// key -> allowed values (exact strings). An empty map = no constraint.
using Labels = std::map<std::string, std::vector<std::string>>;

inline bool is_label_char(char c) { return (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c == '_'; }

// The agent system prompts list their enums: `JSON keys: pattern (stable|spike|...), status (normal|...), ...`
// (training/v2 prompt builder). Extract `key (a|b|c)` for the given keys; a list may end in a ", comment"
// (fault_kind: "...|quantised, only if sensor_fault"), which is cut. Lists with any other character are
// ignored, so a prompt in another format simply yields no labels.
inline Labels labels_from_prompt(const std::string & prompt, const std::vector<std::string> & keys) {
    Labels L;
    size_t from = prompt.find("JSON keys:");
    if (from == std::string::npos) return L;
    size_t eot = prompt.find("<|eot_id|>", from);
    const std::string sys = prompt.substr(from, eot == std::string::npos ? std::string::npos : eot - from);
    for (auto & k : keys) {
        const std::string pat = k + " (";
        size_t p = 0;
        for (;;) {
            p = sys.find(pat, p);
            if (p == std::string::npos) break;
            // must be a whole word: preceded by ':' / ' ' / ','
            if (p > 0 && is_label_char(sys[p - 1])) { p += pat.size(); continue; }
            break;
        }
        if (p == std::string::npos) continue;
        size_t a = p + pat.size(), b = sys.find(')', a);
        if (b == std::string::npos) continue;
        std::string body = sys.substr(a, b - a);
        size_t comma = body.find(',');
        if (comma != std::string::npos) body = body.substr(0, comma);
        std::vector<std::string> vals;
        bool ok = body.find('|') != std::string::npos;
        std::string cur;
        for (char c : body) {
            if (c == '|') { if (cur.empty()) ok = false; vals.push_back(cur); cur.clear(); }
            else if (is_label_char(c)) cur += c;
            else { ok = false; break; }
        }
        if (cur.empty()) ok = false; else vals.push_back(cur);
        if (ok) L[k] = vals;
    }
    return L;
}

// labels from a request element: ["a","b"] = pattern labels, {"key":["a",...],...} = per key, else none
inline Labels labels_from_json(const JVal * v) {
    Labels L;
    if (!v) return L;
    auto strs = [](const JVal & a, std::vector<std::string> & out) {
        if (a.type != JVal::ARR) return false;
        for (auto & e : a.arr) if (e.type == JVal::STR && !e.str.empty()) out.push_back(e.str);
        return !out.empty();
    };
    if (v->type == JVal::ARR) {
        std::vector<std::string> vs;
        if (strs(*v, vs)) L["pattern"] = vs;
    } else if (v->type == JVal::OBJ) {
        for (auto & kv : v->obj) {
            std::vector<std::string> vs;
            if (strs(kv.second, vs)) L[kv.first] = vs;
        }
    }
    return L;
}

inline bool is_prefix_of_any(const std::string & v, const std::vector<std::string> & labels) {
    for (auto & l : labels) if (l.size() >= v.size() && l.compare(0, v.size(), v) == 0) return true;
    return false;
}
inline bool is_any(const std::string & v, const std::vector<std::string> & labels) {
    for (auto & l : labels) if (l == v) return true;
    return false;
}
inline size_t longest(const std::vector<std::string> & labels) {
    size_t m = 0;
    for (auto & l : labels) m = std::max(m, l.size());
    return m;
}

// Would appending `piece` from state `st` keep every constrained top-level string value a prefix of one of
// its labels (and, when the value closes inside the piece, exactly a label)? Bytes outside constrained
// values are not restricted. An empty piece is rejected while inside a constrained value (it would emit
// nothing but cost a step); a backslash or control byte inside one is rejected (labels contain neither).
inline bool piece_allowed(const JState & st0, const std::string & piece, const Labels & L) {
    if (L.empty()) return true;
    auto lab = [&](const JState & s) -> const std::vector<std::string> * {
        if (!s.in_val) return nullptr;
        auto it = L.find(s.key);
        return it == L.end() ? nullptr : &it->second;
    };
    if (piece.empty()) return lab(st0) == nullptr;
    JState st = st0;
    for (char c : piece) {
        const std::vector<std::string> * cur = lab(st);
        if (cur && (c == '\\' || (unsigned char) c < 0x20)) return false;
        JState::Ev ev = st.step(c);
        if (ev == JState::VAL_CLOSED) {
            auto it = L.find(st.key);
            if (it != L.end() && !is_any(st.val, it->second)) return false;
        } else if (const std::vector<std::string> * now = lab(st)) {
            if (!is_prefix_of_any(st.val, *now)) return false;
        }
        if (ev == JState::CLOSED_ROOT) return true;
    }
    return true;
}

// true when the current position is inside a constrained value (so the argmax must be checked)
inline bool in_constrained(const JState & st, const Labels & L) {
    return st.in_val && L.count(st.key) != 0;
}

// ------------------------------------------------------------------ the app's stop rule + JSON abort guard

// JSON-abort levels (HTPD_JSON_ABORT): 0 off; 1 = provably not JSON of the agent schema:
//   - a raw control byte (newline, tab, ...) inside a string (JSON forbids it),
//   - outside strings, a byte that cannot occur in JSON (only whitespace, {}[]:, , digits, -+.eE and the
//     letters of true/false/null can),
//   - a top-level enum value (pattern/status/likely_cause/fault_kind/action/onset) longer than the longest
//     label for that key (labels from the request or the prompt; without labels `maxval` bytes);
// 2 = level 1 plus three rules that are legal JSON but never occur in an agent answer: a newline outside
//     strings (answers are single-line), nesting deeper than 2, a top-level key longer than 32 bytes (the
//     longest schema key is 12).
struct AbortRule {
    int level = 0;
    size_t maxval = 48;
};

inline bool json_outside_ok(char c) {
    if (c == ' ' || c == '\t' || c == '\n' || c == '\r' || c == '"') return true;
    if (strchr("{}[]:,-+.", c) && c != 0) return true;
    if (c >= '0' && c <= '9') return true;
    return strchr("truefalsnE", c) != nullptr && c != 0;
}

inline bool enum_key(const std::string & k) {
    return k == "pattern" || k == "status" || k == "likely_cause" || k == "fault_kind" || k == "action" || k == "onset";
}

struct Scanner {
    JState js;
    bool trim;
    std::string text;
    std::string stop;
    AbortRule abort;
    const Labels * labels = nullptr;  // for the abort length rule; may be null
    std::string abort_why;

    Scanner(const std::string & prefill, bool trim_action) : trim(trim_action) { feed(prefill, false); }

    // returns true when generation must stop (stop = "json" | "action" | "abort")
    bool feed(const std::string & s, bool count = true) {
        for (char c : s) {
            if (count) text += c;
            if (count && abort.level > 0 && check_abort(c)) { stop = "abort"; return true; }
            JState::Ev ev = js.step(c);
            if (ev == JState::KEY_CLOSED && trim && js.depth == 1 && js.key == "action") {
                // cut at the comma before "action" and close the object
                size_t q = text.rfind("\"action\"");
                size_t comma = text.rfind(',', q);
                if (comma != std::string::npos) text = text.substr(0, comma);
                text += "}";
                stop = "action";
                return true;
            }
            if (ev == JState::CLOSED_ROOT) { stop = "json"; return true; }
            if (count && abort.level >= 2 && js.in_key && js.key.size() > 32) { abort_why = "key longer than any schema key"; stop = "abort"; return true; }
            if (count && abort.level > 0 && js.in_val && enum_key(js.key)) {
                size_t lim = abort.maxval;
                if (labels) { auto it = labels->find(js.key); if (it != labels->end()) lim = longest(it->second); }
                if (js.val.size() > lim) { abort_why = "value longer than any label"; stop = "abort"; return true; }
            }
        }
        return false;
    }

  private:
    bool check_abort(char c) {
        if (js.in_str) {
            if ((unsigned char) c < 0x20) { abort_why = "control byte in string"; return true; }
            return false;
        }
        if (!json_outside_ok(c)) { abort_why = "non-JSON byte outside strings"; return true; }
        if (abort.level >= 2) {
            if ((c == '\n' || c == '\r') && js.depth >= 1) { abort_why = "newline outside strings"; return true; }
            if ((c == '{' || c == '[') && js.depth >= 2) { abort_why = "nesting deeper than the schema"; return true; }
        }
        return false;
    }
};

// ------------------------------------------------------------------ static per-role draft table

// n-gram (1..3 tokens) -> most frequent next token over a set of reference completions; ties go to the
// continuation seen first. Same table as proofs/2026-10-21_v2_research/latency/sim_draft.py's corpus.
struct NgramTable {
    std::unordered_map<uint64_t, int32_t> next;

    static uint64_t key(const int32_t * t, int ng) {
        uint64_t k = (uint64_t) ng << 62;
        for (int q = 0; q < ng; ++q) k |= (uint64_t) ((uint32_t) t[q] & 0x1FFFFF) << (21 * (2 - q));
        return k;
    }
    void build(const std::vector<std::vector<int32_t>> & seqs) {
        // per key: (token, count, first-seen order)
        std::unordered_map<uint64_t, std::vector<std::pair<int32_t, int>>> cnt;
        for (auto & s : seqs)
            for (int ng = 1; ng <= 3; ++ng)
                for (int i = 0; i + ng < (int) s.size(); ++i) {
                    auto & v = cnt[key(s.data() + i, ng)];
                    int32_t t = s[i + ng];
                    auto it = std::find_if(v.begin(), v.end(), [&](auto & e) { return e.first == t; });
                    if (it == v.end()) v.emplace_back(t, 1); else it->second++;
                }
        next.clear();
        next.reserve(cnt.size());
        for (auto & kv : cnt) {
            int best = 0;
            for (int j = 1; j < (int) kv.second.size(); ++j) if (kv.second[j].second > kv.second[best].second) best = j;
            next[kv.first] = kv.second[best].first;
        }
    }
    // the n-gram ending at h[L-1]; -1 if unknown
    int32_t lookup(const int32_t * h, int L, int ng) const {
        if (L < ng) return -1;
        auto it = next.find(key(h + L - ng, ng));
        return it == next.end() ? -1 : it->second;
    }
};

// ------------------------------------------------------------------ token streaming ("stream":true)

// length of the longest prefix of t that does not end inside a UTF-8 multi-byte sequence. A trailing lead
// byte whose continuation bytes have not all arrived is held back; malformed bytes are passed through (they
// can never be completed, and the final text carries them anyway).
inline size_t utf8_complete_prefix(const std::string & t) {
    const size_t n = t.size();
    for (size_t back = 1; back <= 4 && back <= n; ++back) {
        unsigned char c = (unsigned char) t[n - back];
        if ((c & 0xC0) == 0x80) continue;  // continuation byte: keep looking for the lead
        int need = (c & 0xE0) == 0xC0 ? 2 : (c & 0xF0) == 0xE0 ? 3 : (c & 0xF8) == 0xF0 ? 4 : 1;
        return (int) back < need ? n - back : n;
    }
    return n;
}

// Per-step progress lines of the streaming protocol (proofs/2026-10-21_v2_research/streaming/
// htpd_stream_protocol.md): {"kind":"toks","t":["<new text s0>","",...]} with exactly the raw bytes fed to
// each stream's stop scanner in this step (no action trim), whole UTF-8 characters only.
struct StepStream {
    std::vector<std::string> step, pend;
    void reset(int n) { step.assign(n, std::string()); pend.assign(n, std::string()); }
    void add(int s, const std::string & piece) { step[s] += piece; }
    // builds the line for this step (with '\n'); false (and no line) when no stream has new text
    bool line(std::string & out) {
        out = "{\"kind\":\"toks\",\"t\":[";
        bool any = false;
        for (size_t s = 0; s < step.size(); ++s) {
            std::string t = pend[s] + step[s];
            size_t cut = utf8_complete_prefix(t);
            pend[s] = t.substr(cut);
            t.resize(cut);
            any |= !t.empty();
            out += (s ? ",\"" : "\"") + json_escape(t) + "\"";
            step[s].clear();
        }
        out += "]}\n";
        return any;
    }
};

// ------------------------------------------------------------------ logprobs

// top-k (index, log-softmax) of one logits row, highest first, ties by lower index
inline std::vector<std::pair<int, float>> top_logprobs(const float * logits, int n_vocab, int k) {
    float mx = -INFINITY;
    for (int i = 0; i < n_vocab; ++i) mx = std::max(mx, logits[i]);
    double se = 0;
    for (int i = 0; i < n_vocab; ++i) se += std::exp((double) (logits[i] - mx));
    const float lse = mx + (float) std::log(se);
    std::vector<std::pair<int, float>> top;
    for (int i = 0; i < n_vocab; ++i) {
        if ((int) top.size() == k && logits[i] <= top.back().second) continue;
        auto pos = std::find_if(top.begin(), top.end(), [&](auto & e) { return logits[i] > e.second; });
        top.insert(pos, {i, logits[i]});
        if ((int) top.size() > k) top.pop_back();
    }
    for (auto & e : top) e.second -= lse;
    return top;
}

}  // namespace htpd
