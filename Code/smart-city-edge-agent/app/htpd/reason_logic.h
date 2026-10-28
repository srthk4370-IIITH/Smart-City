// reason_logic.h: pure (llama-free) parts of the htpd v8 reasoner path, unit-tested on the host by test_reason.cpp.
//
//   Schema / schema_from_json   the fixed shape of the reasoner's final answer (key order per object, value types,
//                               enum lists), sent by the backend in the request ("schema", reasoner_v3.go)
//   Forcer                      byte-level state machine over that shape: which bytes may come next, and the
//                               deterministic continuation (keys, punctuation, the rest of an enum value once only
//                               one label fits) that htpd feeds as forced tokens instead of decoding them
//   answer_prefix               the part of the prompt after the last assistant header (thinking block removed)
//
// The trained answers (proofs/2026-10-25_reasoner_final/data/*.ok.jsonl, 6,046 of them) all use one layout:
// {"k": v, "k": v} with ", " and ": " separators, keys in one fixed order, arrays "[a, b]" or "[]". The Forcer
// accepts exactly that layout; anything that is not a JSON answer (a <tool_call>, text) switches it off at the
// first byte, so tool turns are never constrained. Inside free string values every byte is allowed (control
// bytes excepted, JSON forbids them raw), so the content stays the model's choice; only enum values are limited
// to their labels (what the gate would reject anyway).
#pragma once

#include "htpd_logic.h"

#include <map>
#include <string>
#include <vector>

namespace htpd {

struct Schema {
    std::vector<std::string> keys;                              // top-level key order
    std::map<std::string, std::vector<std::string>> items;      // array-of-object key -> item key order
    std::map<std::string, std::string> types;                   // key -> str | num | bool | arr_str | arr_obj
    std::map<std::string, std::vector<std::string>> enums;      // key (or array-of-string key) -> labels
    bool empty() const { return keys.empty(); }
};

// {"keys":[...], "items":{"k":[...]}, "types":{"k":"str"}, "enums":{"k":[...]}}; false if malformed
inline bool schema_from_json(const JVal * v, Schema & s) {
    s = Schema();
    if (!v || v->type != JVal::OBJ) return false;
    auto strs = [](const JVal * a, std::vector<std::string> & out) {
        if (!a || a->type != JVal::ARR) return false;
        for (auto & e : a->arr) { if (e.type != JVal::STR) return false; out.push_back(e.str); }
        return true;
    };
    if (!strs(v->get("keys"), s.keys) || s.keys.empty()) return false;
    if (const JVal * it = v->get("items"); it && it->type == JVal::OBJ)
        for (auto & kv : it->obj) { std::vector<std::string> ks; if (!strs(&kv.second, ks) || ks.empty()) return false; s.items[kv.first] = ks; }
    if (const JVal * ty = v->get("types"); ty && ty->type == JVal::OBJ)
        for (auto & kv : ty->obj) { if (kv.second.type != JVal::STR) return false; s.types[kv.first] = kv.second.str; }
    if (const JVal * en = v->get("enums"); en && en->type == JVal::OBJ)
        for (auto & kv : en->obj) { std::vector<std::string> ls; if (!strs(&kv.second, ls) || ls.empty()) return false; s.enums[kv.first] = ls; }
    for (auto & kv : s.items) if (s.types[kv.first] != "arr_obj") return false;
    for (auto & k : s.keys) if (!s.types.count(k)) return false;
    for (auto & kv : s.items) for (auto & k : kv.second) if (!s.types.count(k)) return false;
    return true;
}

// The text the model continues: after the last "<|im_start|>assistant\n", without a leading <think>...</think>
// block and the whitespace after it (Qwen3.5 template, thinking off).
inline std::string answer_prefix(const std::string & prompt) {
    const std::string h = "<|im_start|>assistant\n";
    size_t i = prompt.rfind(h);
    if (i == std::string::npos) return std::string();
    std::string s = prompt.substr(i + h.size());
    if (s.compare(0, 7, "<think>") == 0) {
        size_t e = s.find("</think>");
        if (e == std::string::npos) return std::string();
        s = s.substr(e + 8);
        size_t k = 0;
        while (k < s.size() && (s[k] == '\n' || s[k] == ' ' || s[k] == '\r' || s[k] == '\t')) ++k;
        s = s.substr(k);
    }
    return s;
}

struct Forcer {
    enum Mode { ROOT, FORCED, STR, NUM, BOOL, ARR_FIRST, ARR_NEXT, DONE, OFF };
    struct Frame { bool obj; std::string key; int idx; };  // obj: key = "" (root) or the array key; idx = next key
    const Schema * S = nullptr;
    Mode mode = ROOT;
    std::vector<Frame> st;
    std::string need;          // FORCED: bytes still required
    std::string then_key;      // FORCED: the value that starts once `need` is consumed ("" = none)
    std::string then_push;     // FORCED: push an item-object frame for this array key first ("" = none)
    bool then_close = false;   // FORCED: the `need` was "}" closing the top object frame
    std::string key;           // STR/NUM/BOOL: key of the current value (enum lookup)
    std::string val;           // STR (enum keys) / BOOL: bytes so far
    bool esc = false;
    int ndig = 0;              // NUM: digits seen

    explicit Forcer(const Schema * s = nullptr) : S(s) { if (!S || S->empty()) mode = OFF; }

    bool active() const { return mode != OFF; }
    bool done() const { return mode == DONE; }
    // inside the JSON answer (every byte checked)? ROOT before '{' and OFF are free
    bool constrained() const { return mode != OFF && mode != ROOT; }

    const std::string & type_of(const std::string & k) const {
        static const std::string none;
        auto it = S->types.find(k);
        return it == S->types.end() ? none : it->second;
    }
    const std::vector<std::string> * enum_of(const std::string & k) const {
        auto it = S->enums.find(k);
        return it == S->enums.end() ? nullptr : &it->second;
    }
    const std::vector<std::string> & keys_of(const Frame & f) const {
        if (f.key.empty()) return S->keys;
        return S->items.at(f.key);
    }
    static std::string opener(const std::string & ty) {
        if (ty == "str") return "\"";
        if (ty == "arr_str" || ty == "arr_obj") return "[";
        return "";
    }
    void force(const std::string & n, const std::string & k, const std::string & push, bool close) {
        mode = FORCED; need = n; then_key = k; then_push = push; then_close = close;
    }
    // the bytes of `"k": <opener>` and the value they start
    void force_key(const std::string & pre, const std::string & k, const std::string & push = std::string()) {
        force(pre + "\"" + k + "\": " + opener(type_of(k)), k, push, false);
    }
    void begin_value(const std::string & k) {
        const std::string & ty = type_of(k);
        key = k; val.clear(); esc = false; ndig = 0;
        if (ty == "str") mode = STR;
        else if (ty == "num") mode = NUM;
        else if (ty == "bool") mode = BOOL;
        else if (ty == "arr_str" || ty == "arr_obj") { st.push_back({false, k, 0}); mode = ARR_FIRST; }
        else mode = OFF;  // unknown type: stop constraining
    }
    void after_value() {
        if (st.empty()) { mode = DONE; return; }
        Frame & f = st.back();
        if (!f.obj) { mode = ARR_NEXT; return; }
        const auto & ks = keys_of(f);
        if (f.idx < (int) ks.size()) { const std::string k = ks[f.idx++]; force_key(", ", k); }
        else force("}", "", "", true);
    }
    // item opener of the array on top of the stack, after "[" (pre "") or after "," (pre " ")
    bool start_item(const std::string & pre, char c, bool * consumed) {
        const Frame & a = st.back();
        const std::string & ty = type_of(a.key);
        *consumed = false;
        if (ty == "arr_obj") {
            const auto & ks = S->items.at(a.key);
            if (pre.empty()) {
                if (c != '{') return false;
                *consumed = true;
                force_key("", ks[0], a.key);
            } else {
                force_key(" {", ks[0], a.key);
            }
            return true;
        }
        // arr_str
        if (pre.empty()) {
            if (c != '"') return false;
            *consumed = true;
            key = a.key; val.clear(); esc = false; mode = STR;
        } else {
            force(" \"", "", "", false);
            then_push = "\x01" + a.key;  // marker: a string item of this array starts
        }
        return true;
    }

    // advance by one byte; false = the byte is not allowed here (state unchanged only on false at the first check)
    bool step(char c) {
        switch (mode) {
            case OFF: return true;
            case DONE: return false;
            case ROOT:
                if (c == ' ' || c == '\n' || c == '\r' || c == '\t') return true;
                if (c != '{') { mode = OFF; return true; }
                st.push_back({true, "", 1});
                force_key("", S->keys[0]);
                return true;
            case FORCED: {
                if (need.empty() || c != need[0]) return false;
                need.erase(0, 1);
                if (!need.empty()) return true;
                if (then_close) { st.pop_back(); after_value(); return true; }
                if (!then_push.empty() && then_push[0] == '\x01') {
                    key = then_push.substr(1); val.clear(); esc = false; mode = STR; then_push.clear(); return true;
                }
                if (!then_push.empty()) st.push_back({true, then_push, 1});
                begin_value(then_key);
                return true;
            }
            case STR: {
                const auto * en = enum_of(key);
                if ((unsigned char) c < 0x20) return false;
                if (esc) { if (en) return false; esc = false; return true; }
                if (c == '\\') { if (en) return false; esc = true; return true; }
                if (c == '"') {
                    if (en && !is_any(val, *en)) return false;
                    after_value();
                    return true;
                }
                if (en) { if (!is_prefix_of_any(val + c, *en)) return false; val += c; }
                return true;
            }
            case NUM: {
                if ((c >= '0' && c <= '9')) { ndig++; return true; }
                if (c == '-' || c == '+' || c == '.' || c == 'e' || c == 'E') return true;
                if (ndig == 0) return false;
                after_value();
                return step(c);
            }
            case BOOL: {
                static const std::vector<std::string> tf = {"true", "false"};
                if (!is_prefix_of_any(val + c, tf)) return false;
                val += c;
                if (is_any(val, tf)) after_value();
                return true;
            }
            case ARR_FIRST: {
                if (c == ']') { st.pop_back(); after_value(); return true; }
                bool consumed = false;
                if (!start_item("", c, &consumed) || !consumed) return false;
                return true;
            }
            case ARR_NEXT: {
                if (c == ']') { st.pop_back(); after_value(); return true; }
                if (c != ',') return false;
                bool consumed = false;
                return start_item(" ", c, &consumed);
            }
        }
        return false;
    }
    bool feed(const std::string & s) {
        for (char c : s) if (!step(c)) return false;
        return true;
    }
    // would `piece` be allowed from here (state untouched)? An empty piece is not, inside the answer.
    bool allows(const std::string & piece) const {
        if (!constrained()) return true;
        if (piece.empty()) return false;
        Forcer f = *this;
        return f.feed(piece);
    }
    // the deterministic continuation from here (keys, punctuation, a unique enum rest), at most `cap` bytes
    std::string forced_text(size_t cap = 256) const {
        if (!constrained()) return std::string();
        Forcer f = *this;
        std::string out;
        while (out.size() < cap) {
            if (f.mode == FORCED) {
                std::string n = f.need;
                out += n;
                for (char c : n) f.step(c);
                continue;
            }
            if (f.mode == STR) {
                const auto * en = f.enum_of(f.key);
                if (!en) break;
                const std::string * only = nullptr;
                int cnt = 0;
                for (auto & l : *en) if (l.compare(0, f.val.size(), f.val) == 0) { only = &l; cnt++; }
                if (cnt != 1) break;
                std::string rest = only->substr(f.val.size()) + "\"";
                out += rest;
                for (char c : rest) f.step(c);
                continue;
            }
            break;
        }
        return out;
    }
};

}  // namespace htpd
