package main

import (
	"fmt"
	"math"
	"sort"
	"strconv"
	"strings"
)

// Incident titles follow the AI, like severity (severity.go).
//
// The title used to be written once from the rule findings that opened the incident ("11 sensors
// alarming: ..., CO2 sensor fault, ...") and stayed even when the CO2 agent then judged the window
// normal. Once the analysis completes the title is rebuilt from what the domain agents confirmed and
// the reasoner's root cause; the rules' title is kept in RuleTitle so the trigger stays visible.

// finalFindings gives each flagged sensor's finding after the analysis: its agent's finding where that passed
// the policy gate, else the rule finding the report fell back to (same rule as reasonerSeverity).
func finalFindings(inc *Incident) map[string]Finding {
	agent := map[string]Finding{}
	for i := range inc.Agents {
		if a := &inc.Agents[i]; a.Parsed != nil && a.Valid {
			agent[a.Ref] = *a.Parsed
		}
	}
	out := map[string]Finding{}
	for _, s := range inc.Sensors {
		if s.Context {
			continue
		}
		f, ok := agent[s.Ref]
		if !ok {
			f = s.Rule
		}
		out[s.Ref] = longRangeRaise(f, s)
	}
	return out
}

// longRangeRaise: a sensor its agent judged normal is a warning when a 12 h check fired on it.
// The window study counted "4 h agent OR 12 h check" as detected (old steps 73% -> 93%, drifts
// 83% -> 95%, no new false alarms; proofs/2026-10-16_longrange); without this an isolated incident,
// which skips the synthesizer, would never act on the 12 h evidence. Part of the reasoner stub: the
// real reasoner reads the same E9/E10 lines and decides itself.
func longRangeRaise(f Finding, s SensorRef) Finding {
	if s.Context || len(s.LongRange) == 0 || normSeverity(f.Status) != "normal" {
		return f
	}
	f.Status = "warning"
	f.Pattern = s.LongRange[0].Kind + " (12 h view)"
	return f
}

// what names a finding: its pattern, or its status when the shape is steady but the value is not.
func what(f Finding) string {
	if steadyPatterns[f.Pattern] && normSeverity(f.Status) != "normal" && f.Status != "" {
		return strings.ReplaceAll(f.Status, "_", " ")
	}
	return strings.ReplaceAll(f.Pattern, "_", " ")
}

// reasonerTitle builds the headline for a finished incident. A title written by the reasoner itself
// (Report.Title, when it passed the policy gate) wins.
func reasonerTitle(inc *Incident) string {
	if inc.Final != nil && inc.Final.Valid && inc.Final.Parsed != nil && strings.TrimSpace(inc.Final.Parsed.Title) != "" {
		t := strings.Join(strings.Fields(inc.Final.Parsed.Title), " ")
		if r := []rune(t); len(r) > 120 { // a model-written headline, kept to one list row
			t = string(r[:117]) + "..."
		}
		return t
	}
	ff := finalFindings(inc)
	type conf struct {
		s SensorRef
		f Finding
	}
	var confirmed []conf
	var checked []SensorRef
	for _, s := range inc.Sensors {
		f, ok := ff[s.Ref]
		if !ok {
			continue
		}
		checked = append(checked, s)
		if normSeverity(f.Status) != "normal" {
			confirmed = append(confirmed, conf{s, f})
		}
	}
	if len(checked) == 0 {
		return inc.Title
	}
	sort.SliceStable(confirmed, func(i, j int) bool {
		return reportRank[normSeverity(confirmed[i].f.Status)] > reportRank[normSeverity(confirmed[j].f.Status)]
	})
	if len(confirmed) == 0 {
		if len(checked) == 1 {
			s := checked[0]
			if steadyPatterns[ff[s.Ref].Pattern] {
				return fmt.Sprintf("%s judged normal: %s", nice[s.Metric], s.Location)
			}
			return fmt.Sprintf("%s %s judged normal: %s", nice[s.Metric], what(ff[s.Ref]), s.Location)
		}
		var names []string
		for _, s := range checked {
			names = append(names, nice[s.Metric])
		}
		return fmt.Sprintf("All clear: %d sensors checked (%s)", len(checked), listUpTo(names, 3))
	}
	if len(confirmed) == 1 {
		c := confirmed[0]
		return fmt.Sprintf("%s %s: %s", nice[c.s.Metric], what(c.f), c.s.Location)
	}
	var parts []string
	for _, c := range confirmed {
		parts = append(parts, nice[c.s.Metric]+" "+strings.ReplaceAll(normSeverity(c.f.Status), "_", " "))
	}
	head := fmt.Sprintf("%d sensors confirmed", len(confirmed))
	if inc.Final != nil && inc.Final.Valid && inc.Final.Parsed != nil && inc.Final.Parsed.Label != "" {
		l := strings.ReplaceAll(inc.Final.Parsed.Label, "_", " ")
		head = strings.ToUpper(l[:1]) + l[1:]
	}
	return head + ": " + listUpTo(parts, 3)
}

func listUpTo(xs []string, n int) string {
	if len(xs) <= n {
		return strings.Join(xs, ", ")
	}
	return strings.Join(xs[:n], ", ") + fmt.Sprintf(" (+%d more)", len(xs)-n)
}

// consistentTitle (2026-11-20 INC-0004): a calm AI/findings title ("All clear", "... judged normal", "no fault")
// never stays on a warning or critical incident; the rules' title is used instead. Caller holds r.mu.
func consistentTitle(inc *Incident) {
	calm := strings.HasPrefix(inc.Title, "All clear") || strings.Contains(inc.Title, "judged normal") || v3CalmTitleRe.MatchString(inc.Title)
	if !calm || (inc.Severity != "warning" && inc.Severity != "critical") {
		return
	}
	if inc.RuleTitle != "" && !strings.HasPrefix(inc.RuleTitle, "All clear") {
		inc.Title = cleanTitleRefs(inc.RuleTitle)
	}
}

// retitle swaps the provisional rule title for the AI's, keeping the rules' title as RuleTitle.
// Idempotent: back-filled incidents keep their original RuleTitle. Caller holds r.mu.
func retitle(inc *Incident) {
	if inc.RuleTitle == "" {
		inc.RuleTitle = inc.Title
	}
	inc.Title = cleanTitleRefs(reasonerTitle(inc))
	consistentTitle(inc)
}

// ---------------------------------------------------------------- limit titles (night sweep 2026-11-27 #39)

// crossedLimit: the card limit the reading is beyond (critical first, then warning), as printed on the card, and
// the side ("above" / "below"). ok=false inside the limits or without limits.
func crossedLimit(m Metric, x float64) (lim, side string, ok bool) {
	if !m.HasLimits || math.IsNaN(x) {
		return "", "", false
	}
	hi := m.Dir == "high" || m.Dir == "both"
	str := func(s string, v float64) string {
		if s != "" {
			return s
		}
		return numStr(v)
	}
	switch {
	case m.HasLoSide && x < m.CritLo:
		return numStr(m.CritLo), "below", true
	case hi && x >= m.Crit:
		return str(m.CritS, m.Crit), "above", true
	case m.Dir == "low" && x < m.Crit:
		return str(m.CritS, m.Crit), "below", true
	case m.HasLoSide && x < m.WarnLo:
		return numStr(m.WarnLo), "below", true
	case hi && x >= m.Warn:
		return str(m.WarnS, m.Warn), "above", true
	case m.Dir == "low" && x < m.Warn:
		return str(m.WarnS, m.Warn), "below", true
	}
	return "", "", false
}

// valStr: a reading at the card's decimals, trailing zeros trimmed (9.61, 134.7, 0.81).
func valStr(m Metric, x float64) string {
	s := strconv.FormatFloat(x, 'f', m.Dec, 64)
	if strings.Contains(s, ".") {
		s = strings.TrimRight(strings.TrimRight(s, "0"), ".")
	}
	return s
}

// unitSfx: " C", " ppm", "" for pH (the value already says pH).
func unitSfx(m Metric) string {
	if m.Unit == "" || strings.EqualFold(m.Unit, "ph") {
		return ""
	}
	return " " + m.Unit
}

// limitTitle: "Water pH 9.61, above the 9.0 limit" for a sensor whose latest reading is beyond a card limit; the
// rules' pattern name ("pH exponential increase") is not what the operator needs (night sweep 2026-11-27 #39).
func limitTitle(s SensorRef) (string, bool) {
	if len(s.Xs) == 0 {
		return "", false
	}
	m, ok := effectiveMetricOK(s.Role, s.Metric, s.Node)
	if !ok {
		return "", false
	}
	last := s.Xs[len(s.Xs)-1]
	lim, side, ok := crossedLimit(m, last)
	if !ok {
		return "", false
	}
	name := nice[s.Metric]
	if name == "" {
		name = metricWord(s.Metric)
	}
	if s.Metric == "ph" && s.Role == "water" {
		name = "Water pH"
	}
	u := unitSfx(m)
	return fmt.Sprintf("%s %s%s, %s the %s%s limit", name, valStr(m, last), u, side, lim, u), true
}
