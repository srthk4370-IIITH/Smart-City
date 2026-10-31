"""tools_v4.json = round-1 pipeline/tools_v3.json with the 6 chat tools of TOOLS_V3_CHAT.md appended to "chat".
"incident" and the 9 round-1 chat tools are copied unchanged.

Compact schemas (header cost, measure_header.py): the metric/domain enums and the time object are spelled out once in
the round-1 tools (count_incidents etc.), so the new tools reference them by name ("time": "as in count_incidents")
instead of repeating ~150 tokens of enums per tool; descriptions keep what the tool returns and when to use it.
  python3 make_tools_v4.py   -> ./tools_v4.json"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "..", "..", "2026-10-25_reasoner_final", "pipeline", "tools_v3.json")


def main():
    t3 = json.load(open(SRC, encoding="utf-8"))
    S, I, N, B = {"type": "string"}, {"type": "integer"}, {"type": "number"}, {"type": "boolean"}
    TIME = {"type": "object", "description": "as in count_incidents"}
    LOC = {"type": "string", "description": "building or node, e.g. KH, KH03"}

    def fn(name, desc, props, req=None):
        par = {"type": "object", "properties": props}
        if req:
            par["required"] = req
        return {"type": "function", "function": {"name": name, "description": desc, "parameters": par}}

    new = [
        fn("rank_readings", "Highest or lowest reading of a metric per sensor in a period (default today), with time, place and status.",
           {"metric": S, "time": TIME, "order": {"type": "string", "enum": ["highest", "lowest"]}, "domain": S, "location": LOC,
            "limit": I, "include_faulty": B}, ["metric"]),
        fn("current_levels", "Latest reading per sensor with live status, today's min/max/mean and alert limits.",
           {"metric": S, "domain": S, "location": LOC}),
        fn("recent_incidents", "Newest incidents of any day.", {"limit": I, "domain": S, "severity": {"type": "array", "items": S}, "metric": S}),
        fn("open_incidents", "Incidents awaiting an operator decision per domain and severity, and the top 3 to handle first.", {"domain": S}),
        fn("faulty_sensors", "Sensors faulty now and sensors the AI diagnosed as faulty in a period (default 7 days).", {"time": TIME}),
        fn("what_if", "Estimated effect of changing one metric (e.g. occupancy +50%) on other readings of the same building, fitted from recent history.",
           {"driver": S, "change_pct": N, "change_abs": N, "location": LOC, "time": TIME}, ["driver"]),
    ]
    out = {"incident": t3["incident"], "chat": t3["chat"] + new}
    assert [t["function"]["name"] for t in out["chat"][:9]] == [t["function"]["name"] for t in t3["chat"]]
    with open(os.path.join(HERE, "tools_v4.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)
    print("tools_v4.json: incident %d tools (unchanged), chat %d tools (+%d)" % (len(out["incident"]), len(out["chat"]), len(new)))


if __name__ == "__main__":
    main()
