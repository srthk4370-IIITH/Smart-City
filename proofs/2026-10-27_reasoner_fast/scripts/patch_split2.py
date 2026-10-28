"""v8x fix: split groups end on a sentinel (the next group's first key) so the last value of a group terminates as in
training (", " + next key) instead of on a "}" the model never saw there (a number then ran to max_new)."""
import sys
p = sys.argv[1]
s = open(p, encoding="utf-8").read()


def rep(a, b):
    global s
    assert s.count(a) == 1, a[:70]
    s = s.replace(a, b)


rep("""        for (auto & grp : g_req_split) {
            htpd::Schema sc = *schema;
            sc.keys = head;
            for (auto & k : grp) sc.keys.push_back(k);
            subs.push_back(sc);
        }""", """        for (size_t gi = 0; gi < g_req_split.size(); ++gi) {
            htpd::Schema sc = *schema;
            sc.keys = head;
            for (auto & k : g_req_split[gi]) sc.keys.push_back(k);
            // the next group's first key is kept as a sentinel: the group's last value then ends exactly as trained
            // (", " + next key), and the stream stops when the forcer would write that key
            if (gi + 1 < g_req_split.size()) {
                sc.keys.push_back(g_req_split[gi + 1][0]);
                sentinel.push_back("\\"" + g_req_split[gi + 1][0] + "\\"");
            } else sentinel.push_back("");
            subs.push_back(sc);
        }""")
rep("""    std::vector<htpd::Schema> subs;
    std::string split_key0;""", """    std::vector<htpd::Schema> subs;
    std::vector<std::string> sentinel;  // per split stream: stop when the forced text names this key ("" = run to the end)
    std::string split_key0;""")
rep("""        if (fz[s].done()) { out[s].stop = "json"; return true; }
        const std::string ft = fz[s].forced_text();
        if (!ft.empty()) {
            htpd::Forcer g = fz[s];""", """        if (fz[s].done()) { out[s].stop = "json"; return true; }
        const std::string ft = fz[s].forced_text();
        if (forked && s < (int) sentinel.size() && !sentinel[s].empty() && ft.find(sentinel[s]) != std::string::npos) {
            out[s].stop = "json"; return true;  // group complete: the next group's key comes next
        }
        if (!ft.empty()) {
            htpd::Forcer g = fz[s];""")
old = """            if (i + 1 < NS) { size_t e = seg.find_last_not_of(" \\n"); if (e != std::string::npos && seg[e] == '}') seg = seg.substr(0, e); }"""
new = """            if (i + 1 < NS) { size_t e = seg.find_last_not_of(" \\n,"); seg = e == std::string::npos ? "" : seg.substr(0, e + 1); }"""
rep(old, new)
open(p, "w", encoding="utf-8", newline="\n").write(s)
print("split2 patched")
