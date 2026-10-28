"""GBNF grammar for the v2 domain-agent answer, per role, for the CONTINUATION after the prefill '{"pattern": "'.

Enforces: the frozen key order and spacing of the training targets (json.dumps), every enum (pattern, status, cause,
fault_kind, action) from the role's v2 label set, fault_kind present iff status == sensor_fault, cause = sensor_fault
iff status == sensor_fault (true for all 696 gold sensor_fault rows), 1-2 observations each ending with an evidence
citation [E1..E10], confidence 0.xx, event_active bool, onset HH:MM.
  python gbnf_v2.py OUTDIR       -> OUTDIR/agent_v2_<role>.gbnf
"""
from __future__ import annotations

import sys
from pathlib import Path

import trackb_lib as L  # noqa: F401  (sys.path for common_v2)
import common_v2 as C


def alt(vals):
    return " | ".join('"%s"' % v for v in sorted(vals))


def grammar(role, E=None):
    E = E or C.enums()
    pats = E["patterns"][role]
    causes = sorted(c for c in E["causes"][role] if c != "sensor_fault")
    acts = E["actions"][role]
    fks = E["fault_kinds"]
    tail = ('"\\", \\"confidence\\": " conf ", \\"event_active\\": " bool ", \\"onset\\": \\"" hhmm "\\""')
    return "\n".join([
        f"# v2 {role} agent answer, continuation after the prefill {{\"pattern\": \"",
        'root ::= pat "\\", \\"status\\": \\"" ( fault | event )',
        'fault ::= "sensor_fault\\", " obsarr ", \\"likely_cause\\": \\"sensor_fault" ' + tail
        + ' ", \\"fault_kind\\": \\"" fk "\\"" act-tail',
        'event ::= ns "\\", " obsarr ", \\"likely_cause\\": \\"" cause ' + tail + ' act-tail',
        'act-tail ::= ", \\"action\\": \\"" act "\\"}"',
        f"pat ::= {alt(pats)}",
        'ns ::= "normal" | "warning" | "critical"',
        f"cause ::= {alt(causes)}",
        f"fk ::= {alt(fks)}",
        f"act ::= {alt(acts)}",
        'obsarr ::= "\\"observations\\": [" obs ( ", " obs )? "]"',
        'obs ::= "\\"" [^"\\\\\\[\\]]+ "[" eid ( "," eid )* "]\\""',
        'eid ::= "E" ( "10" | [1-9] )',
        'conf ::= "0." [0-9] [0-9]? | "1.0"',
        'bool ::= "true" | "false"',
        'hhmm ::= ( [01] [0-9] | "2" [0-3] ) ":" [0-5] [0-9]',
        "",
    ])


def all_grammars():
    E = C.enums()
    return {r: grammar(r, E) for r in sorted(E["patterns"])}


if __name__ == "__main__":
    out = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
    out.mkdir(parents=True, exist_ok=True)
    for r, g in all_grammars().items():
        (out / f"agent_v2_{r}.gbnf").write_text(g)
        print(r, len(g), "bytes")
