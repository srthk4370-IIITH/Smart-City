package main

// agt_v3 domain-agent prompt (V3_DESIGN §2.2): one generic system text per card + the CARD block, then the v2 window
// lines (WINDOW, SERIES/STATES/ROOM TEMP, EVIDENCE E1-E10). Python twins: core/evidence.py agent_system / agent_user and
// agt_v3/build_gate.py v3_from_real (real windows: the v2 prompt from WINDOW on). Byte parity: features_v3_test.go
// (every v2 Go fixture converted, + synthetic / campus / unseen-metric rows incl. hvac_unit, binary_state, count, tank).
//
// Profile key agents=agt_v3 (needs the v2 agent ladder, agentversion v2) switches the agent prompts and output checks;
// unset / agents=b50 = the B50 v2 path, untouched (rollback = delete the key + the agt_v3 model key).

import (
	"fmt"
	"strconv"
	"strings"
	"time"
)

func agentV3() bool { return agentV2() && strings.EqualFold(profStr("agents"), "agt_v3") }

// AgentSystemV3 mirrors evidence.agent_system.
func AgentSystemV3(c Card, n int) string {
	dn := cardDomainNames[c.Domain]
	return "You are the " + dn + " agent of a smart-campus edge monitor. You receive one " +
		"sensor's CARD (what it measures, its limits and normal behaviour) and a " + hoursStr(n) + "-hour window " +
		"(5-minute samples) with precomputed evidence E1..E10. Judge the data first: values the CARD calls " +
		"impossible, stuck, biased or missing are a data-quality problem, not an event. Then name the pattern, set " +
		"status from the CARD limits or rate rules, and give the reason with evidence ids. Use only the given numbers. " +
		"Never order physical actuation. Reply with one JSON object only. JSON keys: pattern (" + strings.Join(CardPatterns(c), "|") + "), status " +
		"(normal|warning|critical|sensor_fault), data_quality {verdict (ok|suspect|fault|insufficient), why, src}, " +
		"severity_reason, evidence (ids), observations (1-2 short strings ending with ids like [E1,E4]), likely_cause (" +
		strings.Join(c.Causes, "|") + "), confidence (0-1), event_active (true|false), onset (HH:MM), fault_kind (" +
		strings.Join(c.Faults, "|") + ", only if sensor_fault), action (" + strings.Join(c.Actions, "|") + ")."
}

// cardMetricKey mirrors cards.metric_key: the legacy (role, metric) of an existing card, else ("card", id).
func cardMetricKey(c Card) (string, string) {
	if lk, ok := c.Rules["legacy_key"].([]any); ok && len(lk) == 2 {
		a, _ := lk[0].(string)
		b, _ := lk[1].(string)
		return a, b
	}
	return "card", c.CardID
}

// cardMetric: the Metric the E-line code uses for a card (evidence.register for synthetic cards).
func cardMetric(c Card) Metric {
	role, metric := cardMetricKey(c)
	if role == "hvac" && metric == "room_temp" {
		return HVACRoomTemp
	}
	if m, ok := Metrics[role+"/"+metric]; ok {
		return overlayCard(m, c) // the card's own limits, the same ones the rules use (rules_config.go)
	}
	lo, hi := -1e18, 1e18
	if c.Impossible != nil {
		if c.Impossible.Below != nil {
			lo = *c.Impossible.Below
		}
		if c.Impossible.Above != nil {
			hi = *c.Impossible.Above
		}
	}
	fl := 0.0
	if c.Floor != nil {
		fl = *c.Floor
	}
	return Metric{Unit: c.Unit, Dec: c.Decimals, Dir: "high", Floor: fl, Lo: lo, Hi: hi}
}

// BuildAgentPromptV3 mirrors evidence.agent_user (no GAPS line: the app interpolates gaps as the gate rows did).
// hist: <= 144 values ending at the window end (oldest first); the window is hist[-n:]. hc: the hvac ctx of the window
// (kind hvac_unit only). place "" = none.
func BuildAgentPromptV3(c Card, node, location, place string, hist []float64, n int, end int64, hc *HVACCtx) AgentInputV2 {
	return BuildAgentPromptV3Gaps(c, node, location, place, hist, n, end, hc, nil)
}

// BuildAgentPromptV3Gaps is BuildAgentPromptV3 with the per-reading missing mask of the window (true = no reading, the
// value was held): the GAPS line of the training rows (evidence.gaps_line) follows the WINDOW line. nil / no gap = no line,
// byte-identical to BuildAgentPromptV3. Only used with htpd_profile agent_tools=1 (agent_tools.go).
func BuildAgentPromptV3Gaps(c Card, node, location, place string, hist []float64, n int, end int64, hc *HVACCtx, missing []bool) AgentInputV2 {
	if len(hist) > v2Hist {
		hist = hist[len(hist)-v2Hist:]
	}
	if n > len(hist) {
		n = len(hist)
	}
	xs := hist[len(hist)-n:]
	endT := time.Unix(end, 0).In(IST)
	startT := endT.Add(-time.Duration(StepMin*(n-1)) * time.Minute)
	lines := []string{RenderCardFull(c, place), "NODE: " + node + " (" + location + ")",
		fmt.Sprintf("WINDOW: %s -> %s IST, %d x 5 min", startT.Format("Mon 02 Jan 15:04"), endT.Format("15:04"), n)}
	if len(missing) >= n {
		if g := gapsLine(missing[len(missing)-n:], n); g != "" {
			lines = append(lines, g)
		}
	}
	var ev []Evidence
	var info HistInfo
	var st Stats
	var os OccStats
	switch {
	case c.Kind == "hvac_unit" && hc != nil:
		cc := *hc
		cc.End = end
		hs := hvacStats(xs, cc)
		k := n / 2
		ds := make([]string, k)
		var state strings.Builder
		for i := 0; i < k; i++ {
			ds[i] = fmt1(hvMean(xs[i*2 : (i+1)*2]))
			if hvMeanI(cc.On[i*2:(i+1)*2]) >= 0.5 {
				state.WriteByte('1')
			} else {
				state.WriteByte('0')
			}
		}
		lines = append(lines, "ROOM TEMP (10-min means): "+strings.Join(ds, " "), "AC STATE (10-min, 1=on): "+state.String())
		ev = hvacEvidence(xs, cc, hs)
		var hv []Evidence
		hv, info = HistoryItemsV2("hvac", "room_temp", HVACRoomTemp, hist, end)
		ev = append(ev, hv...)
	case c.Kind == "binary_state":
		os = ComputeOccStats(xs)
		var sb strings.Builder
		for _, v := range xs {
			sb.WriteString(strconv.Itoa(int(v)))
		}
		lines = append(lines, "STATES (1=occupied): "+sb.String())
		ev = EvidenceItemsV2("occupancy", st, os, end, 0, "0/1", n)
		var hv []Evidence
		hv, info = HistoryItemsV2("occupancy", "occ", Metrics["occupancy/occ"], hist, end)
		ev = append(ev, hv...)
	default:
		role, metric := cardMetricKey(c)
		m := cardMetric(c)
		m.Dec = effDec(xs, m.Dec) // 3 W on a kW card: shown as 0.0029, not 0.00
		st = ComputeStats(xs, m.Dec)
		ds := downsampleK(xs, n/2)
		parts := make([]string, len(ds))
		for i, v := range ds {
			parts[i] = Fmt(v, m.Dec)
		}
		lines = append(lines, "SERIES (10-min means): "+strings.Join(parts, " "))
		ev = EvidenceItemsV2(role, st, os, end, m.Dec, m.Unit, n)
		var hv []Evidence
		hv, info = HistoryItemsV2(role, metric, m, hist, end)
		ev = append(ev, hv...)
	}
	lines = append(lines, "EVIDENCE:")
	for _, e := range ev {
		lines = append(lines, e.ID+" "+e.Text)
	}
	return AgentInputV2{AgentInput: AgentInput{Prompt: Llama3Prompt(AgentSystemV3(c, n), strings.Join(lines, "\n")), Stats: st, Occ: os,
		Evidence: ev, Xs: xs}, N: n, Hist: info}
}

// llamaUser: the user turn of a Llama-3 prompt.
func llamaUser(p string) string {
	const h = "<|start_header_id|>user<|end_header_id|>\n\n"
	i := strings.Index(p, h)
	if i < 0 {
		return ""
	}
	u := p[i+len(h):]
	if j := strings.Index(u, "<|eot_id|>"); j >= 0 {
		u = u[:j]
	}
	return u
}

// AgentPromptV3FromV2 mirrors build_gate.v3_from_real: the CARD block + NODE line + the v2 prompt from WINDOW on.
func AgentPromptV3FromV2(c Card, node, location, place string, v2 AgentInputV2) AgentInputV2 {
	u := llamaUser(v2.Prompt)
	lines := strings.Split(u, "\n")
	wi := 0
	for i, l := range lines {
		if strings.HasPrefix(l, "WINDOW: ") {
			wi = i
			break
		}
	}
	user := strings.Join(append([]string{RenderCardFull(c, place), "NODE: " + node + " (" + location + ")"}, lines[wi:]...), "\n")
	out := v2
	out.Prompt = Llama3Prompt(AgentSystemV3(c, v2.N), user)
	return out
}

// existingCardFor mirrors build_gate.card_for: today's card of a sensor, the tank line from node_limits_v2.json.
func existingCardFor(role, metric, node, location string) (Card, bool) {
	c, ok := existingCards[MetricToCard(role, metric, node, location)]
	if !ok {
		return Card{}, false
	}
	if c.CardID == "tank_level" {
		c.Tank = nil
		if tl, ok := NodeLimitsV2[node]; ok {
			c.Tank = &CardTank{High: tl.High, Overflow: tl.Overflow, FillMin: tl.FillMin}
		}
	}
	return c, true
}

// sensorCard: the card the agents use for a sensor: the site config's card (editor) when set, else today's card.
// place is the room text from the site config ("" unless the owner set the room's use).
func sensorCard(role, metric, node, location string) (Card, string, bool) {
	if c, place, ok := siteCardFor(node, metric); ok {
		return c, place, true
	}
	c, ok := existingCardFor(role, metric, node, location)
	return c, "", ok
}

// ---------------------------------------------------------------- output (§2.2 schema)

// FindingDQ is the agt_v3 data_quality object.
type FindingDQ struct {
	Verdict string   `json:"verdict"`
	Why     string   `json:"why,omitempty"`
	Src     []string `json:"src,omitempty"`
}

var dqVerdicts = []string{"ok", "suspect", "fault", "insufficient"}

// checkAgentV3Fields validates the agt_v3-only fields (never fails a finding: bad values are dropped with a repair note)
// and the §2.2 consistency rules. valid = the evidence ids the prompt showed.
func checkAgentV3Fields(f *Finding, valid map[string]bool) []string {
	var rep []string
	if f.DataQuality != nil {
		f.DataQuality.Verdict = normEnum(f.DataQuality.Verdict)
		if !contains(dqVerdicts, f.DataQuality.Verdict) {
			rep = append(rep, "data_quality verdict '"+f.DataQuality.Verdict+"' dropped")
			f.DataQuality = nil
		} else {
			keep := f.DataQuality.Src[:0]
			for _, id := range f.DataQuality.Src {
				if valid[id] {
					keep = append(keep, id)
				}
			}
			f.DataQuality.Src = keep
		}
	}
	keep := []string{}
	for _, id := range f.EvidenceIDs {
		if valid[id] {
			keep = append(keep, id)
		} else {
			rep = append(rep, "evidence id "+id+" dropped (not in the prompt)")
		}
	}
	f.EvidenceIDs = keep
	if len([]rune(f.SeverityReason)) > 200 {
		f.SeverityReason = string([]rune(f.SeverityReason)[:200])
	}
	if f.DataQuality != nil {
		v := f.DataQuality.Verdict
		if (f.Status == "sensor_fault") != (v == "fault") {
			rep = append(rep, "consistency: status "+f.Status+" with data_quality "+v)
		}
		if v == "insufficient" && f.Status == "critical" {
			f.Status = "warning"
			rep = append(rep, "insufficient data caps critical to warning (card rule)")
		}
	}
	return rep
}
