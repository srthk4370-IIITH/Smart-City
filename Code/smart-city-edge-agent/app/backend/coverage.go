package main

// Cohesive coverage check (coordinator, 2026-11-17): one incident, one report. Every alerting (non-context) sensor whose
// agent or rule status is warning, critical or sensor_fault must appear in the reasoner's report: by its S-ref in the
// observations, evidence or causal chain (also agent checks, checklist, root cause, explanation), or by node name.
// A report that leaves one out gets one retry with the missing sensors listed; if it still misses one the
// deterministic report is used and a line per missing sensor (with its agent or rule verdict) is added.

import (
	"fmt"
	"regexp"
	"strings"
)

type covItem struct {
	Ref, Node, Metric, Status, Pattern, Cause string
}

func covAbnormal(st string) bool {
	st = normSeverity(st)
	return st == "warning" || st == "critical" || st == "sensor_fault"
}

// coverageRequired: the alerting sensors of the incident with their verdict (agent finding if valid, else the rule).
func coverageRequired(inc *Incident, findings []AgentCall) []covItem {
	var out []covItem
	for i, s := range inc.Sensors {
		if s.Context {
			continue
		}
		f := s.Rule
		if i < len(findings) && findings[i].Parsed != nil && findings[i].Valid {
			f = *findings[i].Parsed
		}
		if !covAbnormal(f.Status) && !covAbnormal(s.Rule.Status) {
			continue
		}
		st := f.Status
		if !covAbnormal(st) {
			st = s.Rule.Status
		}
		out = append(out, covItem{s.Ref, s.Node, s.Metric, normSeverity(st), f.Pattern, f.LikelyCause})
	}
	return out
}

func reportText(rep *Report) string {
	var b strings.Builder
	w := func(s ...string) { b.WriteString(strings.Join(s, " ")); b.WriteByte('\n') }
	w(rep.Title, rep.RootCause, rep.CausalChain, rep.Explanation, rep.MonitorNext)
	for _, o := range rep.Observations {
		w(o.Text, strings.Join(o.Src, " "))
	}
	w(strings.Join(rep.Evidence, " "), strings.Join(rep.SuspectSensors, " "))
	for _, a := range rep.AgentChecks {
		w(a.Ref, a.Claim, a.Fact, strings.Join(a.Src, " "))
	}
	for _, c := range rep.Checklist {
		w(c.Target, c.Why)
	}
	return b.String()
}

// coverageMissing: the alerting sensors the report does not mention.
func coverageMissing(inc *Incident, findings []AgentCall, rep *Report) []covItem {
	if rep == nil {
		return nil
	}
	hay := reportText(rep)
	var miss []covItem
	for _, c := range coverageRequired(inc, findings) {
		re := regexp.MustCompile(`\b` + regexp.QuoteMeta(c.Ref) + `\b`)
		if !re.MatchString(hay) && !strings.Contains(hay, c.Node) {
			miss = append(miss, c)
		}
	}
	return miss
}

func covLine(c covItem) string {
	return fmt.Sprintf("%s %s (%s, %s)", c.Ref, c.Metric, c.Status, strings.ReplaceAll(c.Pattern, "_", " "))
}

func coverageRefs(miss []covItem) string {
	var p []string
	for _, c := range miss {
		p = append(p, c.Ref)
	}
	return strings.Join(p, ", ")
}

// coverageInstruction: the short instruction appended to the reasoner input for the retry.
func coverageInstruction(miss []covItem) string {
	var p []string
	for _, c := range miss {
		p = append(p, covLine(c))
	}
	return "\n\nYour report must also cover: " + strings.Join(p, ", ") + ". Mention each one by its S-ref in the observations, the evidence or the causal chain."
}

// coverageAddLines adds, for every alerting sensor the (deterministic) report still does not mention, one observation
// with its agent or rule verdict.
func coverageAddLines(inc *Incident, findings []AgentCall, rep *Report) {
	for _, c := range coverageMissing(inc, findings, rep) {
		txt := covLine(c)
		if c.Cause != "" {
			txt += ": " + strings.ReplaceAll(c.Cause, "_", " ")
		}
		rep.Observations = append(rep.Observations, V3Observation{Text: txt, Src: []string{}})
		if rep.CausalChain != "" {
			rep.CausalChain += "; also " + c.Ref
		}
	}
}
