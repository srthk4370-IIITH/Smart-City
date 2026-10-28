// Host unit test for reason_logic.h (no llama.cpp needed):
//   g++ -std=c++17 -O2 -o test_reason test_reason.cpp && ./test_reason <schema.json> [gold.ok.jsonl ...]
// schema.json = app/backend/testdata/reasoner_v3_force_schema.json (the request "schema" the backend sends).
// For every gold answer (last message of each line) it checks that the forcer allows every byte, ends in DONE
// exactly at the closing brace, and that each forced continuation is what the gold answer says next - i.e.
// forcing never changes a trained answer. Prints the share of bytes that are forced.
#include "reason_logic.h"

#include <cassert>
#include <fstream>
#include <iostream>
#include <sstream>

using namespace htpd;

static std::string slurp(const char * p) {
    std::ifstream f(p, std::ios::binary);
    std::stringstream ss;
    ss << f.rdbuf();
    return ss.str();
}

static void unit(const Schema & S) {
    // tool turns and plain text are never constrained
    Forcer t(&S);
    assert(t.feed("<tool_call>\n<function=x>"));
    assert(!t.active() && !t.constrained() && t.forced_text().empty());
    // the answer prefix the backend forces: '{"title": "' -> inside the title
    Forcer f(&S);
    assert(f.feed("{") && f.forced_text() == "\"title\": \"");
    assert(f.feed("\"title\": \"Low load"));
    assert(f.allows("\", \"sev") && !f.allows("\"}") && !f.allows("\n"));
    assert(f.feed("\""));
    assert(f.forced_text() == ", \"severity\": \"");
    assert(f.feed(", \"severity\": \"") && f.allows("w") && !f.allows("x") && !f.allows("\""));
    assert(f.feed("w") && f.forced_text() == "arning\", \"label\": \"");
    assert(f.feed("arning\", \"label\": \"normal_operation\", \"root_cause\": \"a\\\"b\", \"causal_chain\": \"c\""));
    assert(f.forced_text() == ", \"observations\": [");
    assert(f.feed(", \"observations\": [") && f.allows("{") && f.allows("]") && !f.allows("\""));
    assert(f.feed("{") && f.forced_text() == "\"text\": \"");
    assert(f.feed("\"text\": \"x\", \"src\": [\"S1.E1\", \"S2\"]}"));
    assert(f.allows("]") && f.allows(", {") && !f.allows(",{"));
    assert(f.feed(", ") && f.forced_text() == "{\"text\": \"");
    // a bool takes " true"/" false" after the forced ": "
    Forcer b = f;
    assert(b.feed("{\"text\": \"y\", \"src\": []}], \"agent_checks\": [], \"affected_domains\": [\"power\"], "
                  "\"suspect_sensors\": [], \"evidence\": [\"S1\"], \"confidence\": 0.87, \"checklist\": [], "
                  "\"monitor_next\": \"m\", \"needs_more_data\": "));
    assert(b.allows("false") && b.allows("t") && !b.allows("no"));
    assert(b.feed("false") && b.forced_text() == ", \"needs_deeper\": ");
    assert(b.feed(", \"needs_deeper\": true, \"explanation\": \"e\"") && b.forced_text() == "}");
    assert(b.feed("}") && b.done() && !b.allows("\n") && b.forced_text().empty());
    // enum array items
    Forcer d(&S);
    assert(d.feed("{\"title\": \"t\", \"severity\": \"normal\", \"label\": \"unknown\", \"root_cause\": \"r\", "
                  "\"causal_chain\": \"c\", \"observations\": [], \"agent_checks\": [], \"affected_domains\": ["));
    assert(d.allows("\"po") && !d.allows("\"pz"));
    // answer_prefix
    assert(answer_prefix("x<|im_start|>assistant\n<think>\n\n</think>\n\n{\"title\": \"") == "{\"title\": \"");
    assert(answer_prefix("x<|im_start|>assistant\n") == "");
    std::cout << "unit ok\n";
}

int main(int argc, char ** argv) {
    if (argc < 2) { std::cerr << "usage: test_reason schema.json [gold.jsonl ...]\n"; return 2; }
    JVal sv;
    if (!json_parse(slurp(argv[1]), sv)) { std::cerr << "schema: bad JSON\n"; return 1; }
    Schema S;
    if (!schema_from_json(&sv, S)) { std::cerr << "schema: rejected\n"; return 1; }
    unit(S);
    for (int a = 2; a < argc; ++a) {
        std::ifstream f(argv[a], std::ios::binary);
        std::string line;
        long n = 0, bad = 0, bytes = 0, forced = 0;
        while (std::getline(f, line)) {
            if (line.empty()) continue;
            JVal ex;
            if (!json_parse(line, ex)) { std::cerr << "bad line\n"; return 1; }
            const JVal * msgs = ex.get("messages");
            if (!msgs || msgs->type != JVal::ARR || msgs->arr.empty()) continue;
            const JVal * c = msgs->arr.back().get("content");
            if (!c || c->type != JVal::STR || c->str.empty() || c->str[0] != '{') continue;
            const std::string & ans = c->str;
            n++;
            Forcer fz(&S);
            size_t i = 0;
            std::string why;
            while (i < ans.size()) {
                std::string ft = fz.forced_text();
                if (!ft.empty()) {
                    if (ans.compare(i, ft.size(), ft) != 0) { why = "forced text differs: " + ft; break; }
                    if (!fz.feed(ft)) { why = "forced text rejected"; break; }
                    i += ft.size(); forced += (long) ft.size();
                    continue;
                }
                if (!fz.allows(std::string(1, ans[i]))) { why = "byte rejected"; break; }
                fz.step(ans[i++]);
            }
            if (why.empty() && !fz.done()) why = "not done at end";
            bytes += (long) ans.size();
            if (!why.empty()) {
                if (++bad <= 5) std::cerr << argv[a] << " #" << n << " at " << i << ": " << why << "\n  ..."
                                          << ans.substr(i > 60 ? i - 60 : 0, 100) << "\n";
            }
        }
        printf("%s: %ld answers, %ld rejected, forced %.1f%% of %ld bytes\n", argv[a], n, bad,
               bytes ? 100.0 * forced / bytes : 0.0, bytes);
        if (bad) return 1;
    }
    return 0;
}
