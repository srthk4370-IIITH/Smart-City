package main

import (
	"encoding/json"
	"fmt"
	"regexp"
	"sort"
	"strings"
)

// deploy25: checks on the model's chat turn (blind sweep: the model passed an invented node "INC-0123" to
// get_sensor_history, asked for an unknown preset "last_14d" and then answered for 30 days, and widened "since Monday
// 8 am" to the whole week).
//   - the period and sensors the question names are given to the model as a hint after the question;
//   - Validate: a call's time is held to the question's period; an incident id must exist and come from the question,
//     the conversation or an earlier tool result; a node must exist; a sensor-history metric must be one the question
//     asks for on that node (a temperature question never reads ac_on);
//   - Check: incident ids in the answer must come from the evidence, a failed tool is reported instead of hidden, and a
//     period the router could not read is named in the answer.

type chatGuard struct {
	Span     chatSpan
	Compare  bool
	Hint     string
	metrics  []string
	evidence strings.Builder
	errs     map[string]string
	times    []string
	nodes    map[string]NodeInfo
}

// 2026-11-03: rank_readings, faulty_sensors and what_if take the same "time" object and are held to the question's period too.
var chatTimeTools = map[string]bool{"count_incidents": true, "find_incidents": true, "sensor_faults": true, "get_sensor_history": true, "get_action_history": true,
	"rank_readings": true, "faulty_sensors": true, "what_if": true}

func (t chatTools) chatGuardOf(q string, history []ChatMsg) *chatGuard {
	g := &chatGuard{Span: chatSpanOf(q, t.now), Compare: chatCompareRe.MatchString(q), metrics: chatMetricsOf(q), errs: map[string]string{}, nodes: map[string]NodeInfo{}}
	if t.r != nil && t.r.eng != nil {
		g.nodes = t.r.eng.Meta.Nodes
	}
	var hints []string
	switch {
	case g.Span.Found() && !g.Compare:
		hints = append(hints, fmt.Sprintf(`period: {"from": "%s", "to": "%s"}`, g.Span.Args()["from"], g.Span.Args()["to"]))
	case g.Span.Future:
		hints = append(hints, "this asks about the future; the device has no forecast")
	}
	place := chatPlaceOf(q, t.chatBuildings())
	if picks, _ := chatPickSensors(place, g.metrics, "", g.nodes); len(picks) > 0 && len(picks) <= 3 {
		var ps []string
		for _, p := range picks {
			ps = append(ps, p.Node+" "+p.Metric)
		}
		hints = append(hints, "sensors: "+strings.Join(ps, ", "))
	}
	if len(hints) > 0 {
		g.Hint = " [" + strings.Join(hints, "; ") + "]"
	}
	g.evidence.WriteString(strings.ToUpper(q) + "\n")
	for _, m := range history {
		g.evidence.WriteString(strings.ToUpper(m.Text) + "\n")
		for _, tl := range m.Tools {
			g.evidence.WriteString(strings.ToUpper(tl.Result) + "\n")
		}
	}
	return g
}

func chatErrJSON(e string) string {
	b, _ := json.Marshal(map[string]any{"error": e})
	return string(b)
}

// Validate checks (and may correct) one model call; a non-empty return is the call's result (an error).
func (g *chatGuard) Validate(t chatTools, name string, args map[string]any) string {
	if g.Span.Found() && !g.Compare && chatTimeTools[name] {
		args["time"] = g.Span.Args()
	}
	if tv, ok := args["time"]; ok {
		b, _ := json.Marshal(tv)
		g.times = append(g.times, string(b))
	}
	if name == "get_incident" {
		ids := chatIDs(strArg(args, "id"))
		if len(ids) != 1 {
			return chatErrJSON(fmt.Sprintf("%q is not an incident id (ids look like INC-0123); use find_incidents to find one", strArg(args, "id")))
		}
		if n := chatIncSeq(ids[0]); n > 0 {
			ids[0] = fmt.Sprintf("INC-%04d", n) // "inc-300" is INC-0300
		}
		args["id"] = ids[0]
		if !strings.Contains(g.evidence.String(), ids[0]) {
			return chatErrJSON(ids[0] + " was not named in the question or found by a tool; use find_incidents to find the incident first")
		}
	}
	// site tools take site-tree nodes (campus, buildings, floors, equipment) and answer "not found" themselves; the
	// sensor-node check blocked "campus" (sweep 2026-11-27: "status of the campus" -> "there is no campus")
	if node := strArg(args, "node"); node != "" && len(g.nodes) > 0 && !contains(siteToolNames, name) {
		if chatIDRe.MatchString(node) {
			return chatErrJSON(fmt.Sprintf("%q is an incident id, not a sensor node; nodes on this device: %s", node, g.nodeList()))
		}
		known := false
		for id := range g.nodes {
			known = known || id == node || (name != "get_sensor_history" && strings.Contains(id, node))
		}
		if !known {
			return chatErrJSON(fmt.Sprintf("unknown node %q; nodes on this device: %s", node, g.nodeList()))
		}
		if name == "get_sensor_history" && len(g.metrics) > 0 {
			var want []string
			for _, w := range g.metrics {
				want = append(want, chatResolveMetric(w, g.nodes[node].Metrics)...)
			}
			if m := strArg(args, "metric"); len(want) > 0 && !contains(want, m) {
				args["metric"] = want[0]
			}
		}
	}
	return ""
}

func (g *chatGuard) nodeList() string {
	var ids []string
	for id := range g.nodes {
		ids = append(ids, id)
	}
	sort.Strings(ids)
	return strings.Join(ids, ", ")
}

// Saw records a tool result as evidence and its error, if any.
func (g *chatGuard) Saw(name, res string) {
	g.evidence.WriteString(strings.ToUpper(res) + "\n")
	var m map[string]any
	if json.Unmarshal([]byte(res), &m) == nil {
		if e, ok := m["error"]; ok {
			g.errs[name] = fmt.Sprint(e)
			return
		}
	}
	delete(g.errs, name)
}

var chatSaysFailRe = regexp.MustCompile(`(?i)\b(could\s*n[o']t|can\s*n[o']t|can't|cannot|unable|not\s+available|no\s+data|error|failed|unknown|not\s+found|no\s+such|does\s+not\s+exist|isn't\s+on)\b`)

// Check: the answer against the evidence (ids), failed tools and an unread period.
func (g *chatGuard) Check(text string, tools []ChatTool) string {
	ev := g.evidence.String()
	var bad []string
	for _, id := range chatIDs(text) {
		if !strings.Contains(ev, id) {
			bad = append(bad, id)
		}
	}
	for _, id := range bad {
		text = strings.ReplaceAll(text, "["+id+"]", "[unverified id removed]")
		text = strings.ReplaceAll(text, id, "[unverified id removed]")
	}
	if len(bad) > 0 {
		text += fmt.Sprintf(" (Note: %s that did not appear in the device data %s removed.)", plural(len(bad), "an incident id", "incident ids"),
			map[bool]string{true: "was", false: "were"}[len(bad) == 1])
	}
	if len(g.errs) > 0 && !chatSaysFailRe.MatchString(text) {
		var ks []string
		for k := range g.errs {
			ks = append(ks, k)
		}
		sort.Strings(ks)
		text += fmt.Sprintf(" (Note: the device could not run %s: %s.)", ks[0], g.errs[ks[0]])
	}
	if g.Span.Unparsed != "" && len(g.times) > 0 {
		text += fmt.Sprintf(" (Note: I could not read the period \"%s\" exactly; the tool was asked for %s.)", g.Span.Unparsed, g.times[0])
	}
	return strings.TrimSpace(text)
}
