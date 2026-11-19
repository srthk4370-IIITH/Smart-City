package main

// Agent tool-call protocol (agt_v3 top-up v2). Spec + byte reference: proofs/2026-11-17_agt_topup_v2/PROTOCOL.md and
// gen_tools.py (render_* functions); the trained model sees exactly these bytes.
//
// htpd_profile agent_tools=1 (default OFF: the current single-turn model keeps today's behaviour) switches the agent call
// path: generation 1 starts from the prefill `{"`; the model answers with a tool call
//
//	{"tool": "get_history", "args": {"hours": 6|12}} | {"tool": "get_neighbors", "args": {}} | {"tool": "get_card", "args": {}}
//
// or directly with the answer (`pattern": ...`). A call is executed here, its result is appended to the SAME prompt string in
// the Llama 3.2 `ipython` role (the prefix stays byte-identical, so the KV cache is reused) and generation continues. At most
// maxAgentToolCalls calls; the generation after the last one is forced to the answer prefill `{"pattern": "`. Every turn must
// fit the board agent ctx (agentFits): a result that would overflow is not sent, the answer is forced instead. With
// agent_tools=1 the prompt also carries the GAPS line of the training rows (gaps_line) after WINDOW, and a prompt that does not
// fit with its full CARD is sent with the card cut to its first line + the get_card marker (token-budget mode).

import (
	"context"
	"encoding/json"
	"fmt"
	"regexp"
	"strings"
	"time"
)

const (
	// AgentToolPrefill: generation 1 (and 2 after a first result): the model decides between a call and an answer.
	AgentToolPrefill   = `{"`
	maxAgentToolCalls  = 2
	toolIPY            = "<|start_header_id|>ipython<|end_header_id|>\n\n"
	toolAssist         = "<|start_header_id|>assistant<|end_header_id|>\n\n"
	toolEOT            = "<|eot_id|>"
	cardWithheldMarker = "  details withheld (limits, noise, behaviour): call get_card"
	maxToolNeighbours  = 3
)

var idReTools = regexp.MustCompile(`\b(?:[EHN]\d+|GAPS)\b`)

// agentTools: the tool-call protocol is on (agt_v3 agents only).
func agentTools() bool { return agentV3() && profOn("agent_tools") }

func isAgentPrefill(p string) bool { return p == AgentPrefill || p == AgentToolPrefill }

// toolSensorCard is sensorCard; tests swap it.
var toolSensorCard = sensorCard

// ---------------------------------------------------------------------------------------------------- prompt pieces

// gapsLine mirrors evidence.gaps_line (missing: per reading of the n-point window, true = no reading).
func gapsLine(missing []bool, n int) string {
	k, best, cur := 0, 0, 0
	for _, m := range missing {
		if m {
			k++
			cur++
			if cur > best {
				best = cur
			}
		} else {
			cur = 0
		}
	}
	if k == 0 {
		return ""
	}
	return fmt.Sprintf("GAPS: %d of %d readings missing (filled with the last value), longest gap %d min", k, n, best*StepMin)
}

// MissingMask: per reading of the n-point window ending at end, true = the sensor sent no reading (the history holds the last value
// there). nil when nothing is missing or the sensor is unknown.
func (e *Engine) MissingMask(node, metric string, end int64, n int) []bool {
	e.mu.RLock()
	defer e.mu.RUnlock()
	s := e.series[key(node, metric)]
	if s == nil || n <= 0 {
		return nil
	}
	out := make([]bool, n)
	any := false
	for i := range out {
		if _, ok := s[end-int64(n-1-i)*bucketSec]; !ok {
			out[i], any = true, true
		}
	}
	if !any {
		return nil
	}
	return out
}

// agentGaps: the missing mask of the agent's n-point window (agent_tools=1 only; nil otherwise or when the history is short).
func (r *Reasoner) agentGaps(s SensorRef, histLen, n int) []bool {
	if r.eng == nil || !agentTools() || histLen < n {
		return nil
	}
	return r.eng.MissingMask(s.Node, s.Metric, s.End, n)
}

// shortCardPrompt cuts the CARD block of a prompt to its first line plus the get_card marker (gen_tools.short_card_prompt).
func shortCardPrompt(prompt string, c Card, place string) string {
	full := RenderCardFull(c, place)
	if !strings.Contains(prompt, full) {
		return prompt
	}
	head := strings.SplitN(full, "\n", 2)[0]
	return strings.Replace(prompt, full, head+"\n"+cardWithheldMarker, 1)
}

// ---------------------------------------------------------------------------------------------------- tools

type agentToolCall struct {
	Tool  string
	Hours int
}

// canonical is json.dumps of the call, the bytes of the training rows.
func (t agentToolCall) canonical() string {
	if t.Tool == "get_history" {
		return fmt.Sprintf(`{"tool": "get_history", "args": {"hours": %d}}`, t.Hours)
	}
	return `{"tool": "` + t.Tool + `", "args": {}}`
}

// display: the timeline text of a call.
func (t agentToolCall) display() string {
	if t.Tool == "get_history" {
		return fmt.Sprintf("get_history(%d h)", t.Hours)
	}
	return t.Tool + "()"
}

// parseAgentToolCall: isCall = the output is a tool call attempt (starts with `{"tool`); ok = a valid call (known tool, valid args).
func parseAgentToolCall(text string) (tc agentToolCall, isCall, ok bool) {
	if !strings.HasPrefix(text, `{"tool`) {
		return tc, false, false
	}
	js, found := extractJSON(text)
	if !found {
		return tc, true, false
	}
	var c struct {
		Tool string                     `json:"tool"`
		Args map[string]json.RawMessage `json:"args"`
	}
	if json.Unmarshal([]byte(js), &c) != nil {
		return tc, true, false
	}
	switch c.Tool {
	case "get_history":
		raw, has := c.Args["hours"]
		var h float64
		if len(c.Args) != 1 || !has || json.Unmarshal(raw, &h) != nil || (h != 6 && h != 12) {
			return tc, true, false
		}
		return agentToolCall{c.Tool, int(h)}, true, true
	case "get_neighbors", "get_card":
		if len(c.Args) != 0 {
			return tc, true, false
		}
		return agentToolCall{Tool: c.Tool}, true, true
	}
	return tc, true, false
}

// renderToolHistory is gen_tools.render_history: the last `hours` h ending at end, 12 series means, the E2/E3/E4/E8 lines of the
// n-point window relabelled H2/H3/H4/H8, GAPS if readings are missing. ok=false: the history is shorter than the window.
func renderToolHistory(c Card, hist []float64, hours int, end int64, missing []bool) (string, bool) {
	n := hours * 12
	if c.Kind != "continuous" || len(hist) < n {
		return "", false
	}
	if len(missing) > n {
		missing = missing[len(missing)-n:]
	}
	xs := hist[len(hist)-n:]
	role, _ := cardMetricKey(c)
	m := cardMetric(c)
	dec := m.Dec // the series uses the card's decimals; the H lines the effective ones (as the first prompt's E lines)
	m.Dec = effDec(xs, m.Dec)
	st := ComputeStats(xs, m.Dec)
	ev := EvidenceItemsV2(role, st, OccStats{}, end, m.Dec, m.Unit, n)
	endT := time.Unix(end, 0).In(IST)
	startT := endT.Add(-time.Duration(StepMin*(n-1)) * time.Minute)
	lines := []string{fmt.Sprintf("HISTORY %d h: %s -> %s IST, %d x 5 min", hours, startT.Format("Mon 02 Jan 15:04"), endT.Format("15:04"), n)}
	if len(missing) == n {
		if g := gapsLine(missing, n); g != "" {
			lines = append(lines, g)
		}
	}
	kind := "30-min"
	if hours != 6 {
		kind = "hourly"
	}
	ds := downsampleK(xs, 12)
	parts := make([]string, len(ds))
	for i, v := range ds {
		parts[i] = Fmt(v, dec)
	}
	lines = append(lines, "SERIES ("+kind+" means): "+strings.Join(parts, " "))
	by := map[string]string{}
	for _, e := range ev {
		by[e.ID] = e.Text
	}
	for _, i := range []string{"2", "3", "4", "8"} {
		lines = append(lines, "H"+i+" "+by["E"+i])
	}
	return strings.Join(lines, "\n"), true
}

// toolNbr is one related sensor of a get_neighbors result.
type toolNbr struct{ Node, Short, Status, Pattern, Last string }

// renderToolNeighbors is gen_tools.render_neighbors.
func renderToolNeighbors(rows []toolNbr) string {
	if len(rows) == 0 {
		return "no related sensors"
	}
	out := make([]string, len(rows))
	for i, n := range rows {
		out[i] = fmt.Sprintf("N%d %s | %s | %s | %s | last %s", i+1, n.Node, n.Short, n.Status, n.Pattern, n.Last)
	}
	return strings.Join(out, "\n")
}

// toolNeighbours: the related sensors of s from the site graph: same room / equipment first, then same-type peers on the same floor
// (max 3); status / pattern from the incident's findings when the sensor is part of it, else "normal stable".
func (r *Reasoner) toolNeighbours(inc *Incident, s SensorRef) []toolNbr {
	cfg, ix := siteS.Get()
	if cfg == nil || ix == nil || r.eng == nil {
		return nil
	}
	self := ix.nodes[s.Node+"/"+s.Metric]
	if self == nil {
		return nil
	}
	gp := ix.Parent(self.Parent)
	var same, peers []*SiteNode
	for _, id := range ix.order {
		n := ix.nodes[id]
		if n.Kind != "sensor" || id == self.ID || n.Card == "" {
			continue
		}
		switch {
		case n.Parent == self.Parent:
			same = append(same, n)
		case n.Card == self.Card && gp != "" && ix.Parent(n.Parent) == gp:
			peers = append(peers, n)
		}
	}
	var out []toolNbr
	for _, n := range append(same, peers...) {
		if len(out) >= maxToolNeighbours {
			break
		}
		c, ok := cfg.Cards[n.Card]
		if !ok {
			c, ok = existingCards[n.Card]
		}
		if !ok || (c.Kind != "continuous" && c.Kind != "binary_state") {
			continue
		}
		node, metric, _ := strings.Cut(n.ID, "/")
		h := r.eng.HistoryAt(node, metric, s.End, 1)
		if len(h) == 0 {
			continue
		}
		status, pattern := "normal", "stable"
		for _, o := range inc.Sensors {
			if o.Node == node && o.Metric == metric && contains([]string{"normal", "warning", "critical", "sensor_fault"}, o.Rule.Status) && o.Rule.Pattern != "" {
				status, pattern = o.Rule.Status, o.Rule.Pattern
			}
		}
		short := c.Short
		if short == "" {
			short = c.Quantity
		}
		dev := n.Device
		if dev == "" {
			dev = node
		}
		out = append(out, toolNbr{dev, short, status, pattern, strings.TrimSpace(Fmt(h[len(h)-1], c.Decimals) + " " + c.Unit)})
	}
	return out
}

// toolHistory: the sensor's 12 h history ending at its window end.
func (r *Reasoner) toolHistory(s SensorRef) []float64 {
	hist := s.Hist
	if hist == nil && r.eng != nil {
		hist = r.eng.HistoryAt(s.Node, s.Metric, s.End, v2Hist)
	}
	return hist
}

// execAgentTool runs a validated call. ok=false: it cannot be answered (the answer is then forced).
func (r *Reasoner) execAgentTool(inc *Incident, s SensorRef, c Card, place string, tc agentToolCall) (string, bool) {
	switch tc.Tool {
	case "get_history":
		hist := r.toolHistory(s)
		var miss []bool
		if r.eng != nil {
			miss = r.eng.MissingMask(s.Node, s.Metric, s.End, tc.Hours*12)
		}
		return renderToolHistory(c, hist, tc.Hours, s.End, miss)
	case "get_neighbors":
		return renderToolNeighbors(r.toolNeighbours(inc, s)), true
	case "get_card":
		return RenderCardFull(c, place), true
	}
	return "", false
}

// toolPromptIDs: the evidence ids a tool-protocol prompt adds to E1-E10: H* / N* of the tool results and GAPS.
var toolIDRe = regexp.MustCompile(`(?m)^([HN]\d+) `)

func toolPromptIDs(prompt string) map[string]bool {
	var out map[string]bool
	add := func(id string) {
		if out == nil {
			out = map[string]bool{}
		}
		out[id] = true
	}
	if strings.Contains(prompt, "\nGAPS: ") {
		add("GAPS")
	}
	if i := strings.Index(prompt, toolIPY); i >= 0 {
		for _, m := range toolIDRe.FindAllStringSubmatch(prompt[i:], -1) {
			add(m[1])
		}
	}
	return out
}

// toolTurnSink streams a tool-protocol turn to the dashboard: a call (`tool...`) is dropped, an answer loses the `pattern": "` that the
// normal agent prefill would have carried, so the live text looks like today's.
func toolTurnSink(out func(string)) func(string) {
	const ans = `pattern": "`
	buf, mode := "", 0 // 0 undecided, 1 tool call (dropped), 2 pass through
	return func(t string) {
		switch mode {
		case 1:
			return
		case 2:
			out(t)
			return
		}
		buf += t
		switch {
		case strings.HasPrefix(buf, "tool"):
			mode = 1
		case strings.HasPrefix(buf, ans):
			mode = 2
			out(buf[len(ans):])
		case strings.HasPrefix("tool", buf) || strings.HasPrefix(ans, buf):
		default:
			mode = 2
			out(buf)
		}
	}
}

// ---------------------------------------------------------------------------------------------------- the loop

// runAgentTools is the agent call with the tool protocol. It returns the final generation (Text = prefill + generated, like the
// single-turn path; latency and tokens summed over all turns) and the prompt of the last turn (what checkAgentWin checks ids against).
// fresh: forget cached answers of the prompts first (re-runs). allowCalls=false: answer directly (more-data rounds).
func (r *Reasoner) runAgentTools(ctx context.Context, inc *Incident, s SensorRef, am ModelBundle, ai AgentInput, fresh, allowCalls bool) (GenieResult, string) {
	sink := r.tokenSink(inc, s.Ref)
	var total GenieResult
	started := false
	merge := func(res GenieResult) GenieResult {
		lat, tok := total.LatencyMs+res.LatencyMs, total.GenTokens+res.GenTokens
		ttft := total.TTFTMs
		if !started {
			ttft, started = res.TTFTMs, true
		}
		res.LatencyMs, res.GenTokens, res.TTFTMs = lat, tok, ttft
		total = res
		return res
	}
	run := func(cur, prefill string, sk func(string)) GenieResult {
		if fresh {
			r.genie.Forget(am, cur+prefill)
		}
		res := r.genie.Run(ctx, am, cur+prefill, prefill, 90*time.Second, sk)
		res.Text = prefill + res.Text
		return res
	}
	direct := func(cur string) (GenieResult, string) {
		res := run(cur, AgentPrefill, sink)
		return merge(res), cur + AgentPrefill
	}
	cur := ai.Prompt
	c, place, ok := toolSensorCard(s.Role, s.Metric, s.Node, s.Location)
	if !allowCalls || !ok || !agentV3() {
		return direct(cur)
	}
	if !agentFits(cur + AgentPrefill) { // token-budget mode: the CARD cut to its first line, the model calls get_card for the rest
		short := shortCardPrompt(cur, c, place)
		if short == cur || !agentFits(short+AgentPrefill) {
			return direct(cur)
		}
		cur = short
	}
	var done []agentToolCall
	for {
		if len(done) >= maxAgentToolCalls {
			return direct(cur)
		}
		res := run(cur, AgentToolPrefill, toolTurnSink(sink))
		if res.Error != "" {
			return merge(res), cur + AgentToolPrefill
		}
		tc, isCall, valid := parseAgentToolCall(res.Text)
		if !isCall { // an answer: the existing path
			return merge(res), cur + AgentToolPrefill
		}
		if !res.Cached {
			inc.NPUCalls++
		}
		merge(res)
		dup := false
		for _, d := range done {
			dup = dup || d == tc
		}
		if !valid || dup {
			r.log(inc, fmt.Sprintf("%s agent: unusable tool call ignored, answering directly", title(s.Role)))
			return direct(cur)
		}
		result, ok := r.execAgentTool(inc, s, c, place, tc)
		if !ok {
			r.log(inc, fmt.Sprintf("%s agent called %s: no data, answering directly", title(s.Role), tc.display()))
			return direct(cur)
		}
		next := cur + tc.canonical() + toolEOT + toolIPY + result + toolEOT + toolAssist
		if !agentFits(next + AgentPrefill) {
			r.log(inc, fmt.Sprintf("%s agent called %s: the result would not fit the NPU agent context, answering directly", title(s.Role), tc.display()))
			return direct(cur)
		}
		r.log(inc, fmt.Sprintf("%s agent called %s", title(s.Role), tc.display()))
		done = append(done, tc)
		cur = next
	}
}
