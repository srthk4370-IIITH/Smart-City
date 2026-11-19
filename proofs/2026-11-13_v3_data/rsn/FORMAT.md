# v4 incident prompt + chat r5 format (single source: `fmt_v4.py`; the Go builders must match it byte for byte)

Python is the reference. Go twins to write: `reasoner_v4.go RenderV4User` (+ `SystemV4`), `chat_site.go` (4 tools),
`chat_header_r5.txt`. Parity tests to add: `TestSitePromptParity` (Python fixtures from `gen_inc_v4` rows), `TestChatHeaderR5MatchesTraining`
(`tools_v4.json["chat_r5"]`), `TestSiteToolsParity` (`gen_chat_v4.SiteTools` outputs on fixture sites).

## System (incident, v4) = `fmt_v4.system_v4(prompts.SYSTEM_INCIDENT_SHORT)`
r3 short system with three edits: the campus `Limits: ... negative flow or power.` sentence becomes
`Limits, units, impossible values and normal behaviour are on each sensor's card. Tank level has no physical unit (...). Outdoor CO2 is about 420 ppm.`;
the TRUST paragraph is inserted before `Reply with one JSON object:`; the key list ends with `scope` and `suspect_node`.

## User block (`render_v4(case, ctx)`) — lines in order
```
CONTEXT: <as RenderV3User>
INCIDENT <id> opened HH:MM (mode <m>), windows <h> h of 5-min samples
SITE: <campus> > <building> > <floor> > <room> (<use>, capacity N)      # path of the scope node; equipment: (<etype>)
DOMAIN AGENT FINDINGS:
S# [FLAGGED]: <device> <metric> [<unit>] at <building>, <floor>, <host> (<role>)
S# [linked: <why> (<link>)]: ...                                        # link = located-in|serves|supplies|feeds|outdoor-for|same floor|same building|no site link
  card: <cards.render_line(card)>[ | tank: high >H, overflow >O, usual fill <=F min][ | comfort band setpoint -3/+2 C]
  quality=<...>
  [NO CURRENT DATA: ...]
  agent: pattern=.. status=.. cause=.. confidence=0.00
  agent data: dq=<ok|suspect|bad> | reason: <E# text> (<tail>)          # agt_v3 agents only; absent = B50 agent line
  - <agent observation with S#.E# ids>
  S#.E1 ... S#.E10 (flagged)  /  role subset (linked), as RenderV3User
LINKS: S# located-in <room>; S# on <equipment>; <from> <type> <to>; ...   # max 14 items
SIBLINGS (<host of S1>): <device> <metric> <value> <unit> normal; ... | none   # max 3
NEARBY FLAGS (<building>, last 60 min): <device> <metric> warning since HH:MM (INC-x) | none
[SUSPECT: <node>? <why> -> confirm or reject]
[missing note] [RE-CHECK HISTORY:] [MEMORY ...] [OPERATOR NOTES ...]
<ask line>
```
LIMITS / TANK head lines of RenderV3User are replaced by the card line (same numbers). `quality=` mapping to dq: good -> ok,
uncertain -> suspect, bad / stale -> bad. The related_context tool result blocks use the same sensor lines (no LINKS block).

## Report (assistant) = r3 keys + `scope` (string, must appear in the prompt) + `suspect_node` {node, verdict
confirmed|rejected|undecided, why, src} only when a SUSPECT line is present. Think: `reasoning_content` only when the FLAGGED
sensors span 2+ roles (r4 rule).

## Chat r5
System = `fmt_v4.chat_system_r5(r3 chat system)`: inserts the SITE_RULE bullet before `- The tools are read-only:`; on a
synthetic site the campus name replaces `(IIIT Hyderabad)`. Tools = r3 21 + `get_site_tree`, `nodes_under`, `linked_equipment`,
`site_status` (`tools_v4.json["chat_r5"]`). Tool arguments take a node id or its name (case-insensitive); results always carry
`"source": "device"`; an unknown node returns `{"found": false, "node": .., "note": "no such node in the site map"}`.
