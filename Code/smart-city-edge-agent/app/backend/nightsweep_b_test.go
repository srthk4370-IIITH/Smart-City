package main

// night sweep 2026-11-27, workstream B (reasoner / report): #37 #39 #57 #58 #70 #82 #94 #95 #98

import (
	"fmt"
	"strings"
	"testing"
)

func flatXs(n int, v float64) []float64 {
	xs := make([]float64, n)
	for i := range xs {
		xs[i] = v
	}
	return xs
}

func rampXs(n int, a, b float64) []float64 {
	xs := make([]float64, n)
	for i := range xs {
		xs[i] = a + (b-a)*float64(i)/float64(n-1)
	}
	return xs
}

// #82: a reading beyond its critical limit keeps the incident critical; the AI's lower view is the note.
func TestSeverityGuardBeyondCritical(t *testing.T) {
	var logs []string
	r := &Reasoner{notify: func(string, any) {}}
	inc := &Incident{ID: "INC-T", Sensors: []SensorRef{{Ref: "S1", Role: "air_quality", Metric: "pm25", Location: "KN outdoor",
		Xs: append(flatXs(10, 40), 135), Rule: Finding{Status: "critical", Pattern: "step_increase"}}}}
	rep := Report{Severity: "warning", Title: "Outdoor dust warning, wind fell"}
	r.severityGuard(inc, &rep)
	for _, it := range inc.Timeline {
		logs = append(logs, it.Msg)
	}
	b := rep.SeverityBasis
	if rep.Severity != "critical" || b.Final != "critical" || b.Reasoner != "warning" || !strings.Contains(b.Guard, "AI read it as warning") ||
		!strings.Contains(b.Guard, "PM2.5 135 ug/m3, critical limit 120") {
		t.Fatalf("kept critical: sev %s basis %+v", rep.Severity, b)
	}
	if rep.Title != "Outdoor dust critical, wind fell" {
		t.Fatalf("title %q", rep.Title)
	}
	if !strings.Contains(strings.Join(logs, "\n"), "Severity guard: a reading is beyond its critical limit") {
		t.Fatalf("no timeline line: %q", logs)
	}
	// back under the critical limit: the AI's warning stands
	inc.Sensors[0].Xs = append(flatXs(10, 135), 90)
	rep = Report{Severity: "warning"}
	r.severityGuard(inc, &rep)
	if rep.Severity != "warning" || rep.SeverityBasis.Guard != "" {
		t.Fatalf("below critical: %+v", rep.SeverityBasis)
	}
	// the rules call it a sensor fault: not a critical event
	inc.Sensors[0].Xs = append(flatXs(10, 40), 135)
	inc.Sensors[0].Rule.Status = "sensor_fault"
	rep = Report{Severity: "warning"}
	r.severityGuard(inc, &rep)
	if rep.Severity != "warning" {
		t.Fatalf("rule sensor_fault forced critical")
	}
	// a sensor_fault diagnosis is not lowered by this guard
	inc.Sensors[0].Rule.Status = "critical"
	rep = Report{Severity: "sensor_fault"}
	r.severityGuard(inc, &rep)
	if rep.Severity != "sensor_fault" {
		t.Fatalf("sensor_fault changed to %s", rep.Severity)
	}
}

// #94: the corroborated-rise guard acts only on claims about the temperature / room sensors.
func TestCorroboratedRiseOtherSensorFault(t *testing.T) {
	inc := &Incident{Sensors: []SensorRef{
		{Ref: "S1", Node: "SR-AQ-KH03-03", Metric: "temp", Xs: rampXs(8, 25, 34.5)},
		{Ref: "S2", Node: "WM-WD-KH98-00", Metric: "ph", Role: "water", Xs: flatXs(8, 7.2)},
		{Ref: "S3", Node: "AC-KH03", Metric: "room_temp", Context: true, Xs: rampXs(8, 24, 33.5)},
	}}
	good := "Room temperature 34.5 C, AC off; pH sensor fault"
	rep := &Report{Severity: "critical", Title: good, RootCause: "Real room heating with the AC off. The pH sensor fault is separate.",
		Explanation: "The S2 sensor fault needs a recalibration."}
	contextFixReport(rep, inc)
	if rep.Title != good || !strings.Contains(rep.RootCause, "pH sensor fault") || !strings.Contains(rep.Explanation, "S2 sensor fault") {
		t.Fatalf("other-sensor fault wording touched: %q / %q / %q", rep.Title, rep.RootCause, rep.Explanation)
	}
	// a temperature claim is still overruled
	rep = &Report{Severity: "critical", Title: "Room temperature sensor fault: KH level 03", Explanation: "S1 sensor jump. The pH is fine."}
	contextFixReport(rep, inc)
	if rep.Title != "" || strings.Contains(rep.Explanation, "S1 sensor jump") || !strings.Contains(rep.Explanation, "The pH is fine.") {
		t.Fatalf("temperature claim kept: %q / %q", rep.Title, rep.Explanation)
	}
}

// #70: event claims about a sensor that the rule and the agent both call normal are removed.
func TestNormalEventFix(t *testing.T) {
	inc := &Incident{Sensors: []SensorRef{
		{Ref: "S1", Node: "WM-WD-KH98-00", Metric: "ph", Role: "water", Rule: Finding{Status: "critical"}},
		{Ref: "S2", Node: "WM-WD-KH98-01", Metric: "flow", Role: "water", Context: true, Rule: Finding{Status: "normal"}},
	}}
	calls := []AgentCall{{Ref: "S1", Valid: true, Parsed: &Finding{Status: "critical"}}}
	rep := &Report{Title: "Water pH 9.61 critical",
		RootCause:   "The pH moved beyond its card limit and a matching alarm; the flow event is real.",
		Explanation: "The flow stays steady. A flow surge pushed the dosing."}
	why := normalEventFix(rep, inc, calls)
	if why == "" || rep.RootCause != "The pH moved beyond its card limit and a matching alarm." || rep.Explanation != "The flow stays steady." {
		t.Fatalf("%q: %q / %q", why, rep.RootCause, rep.Explanation)
	}
	// the flow agent calls it abnormal: the claim stays
	rep = &Report{RootCause: "The pH rose; the flow event is real."}
	calls = append(calls, AgentCall{Ref: "S2", Valid: true, Parsed: &Finding{Status: "warning"}})
	if why := normalEventFix(rep, inc, calls); why != "" || rep.RootCause != "The pH rose; the flow event is real." {
		t.Fatalf("agent-flagged flow edited: %q %q", why, rep.RootCause)
	}
}

// #57: an agent's sensor_fault on a fast rise is not the second evidence when another nearby sensor agrees.
func TestFaultGuardFastRiseAgentFault(t *testing.T) {
	r := &Reasoner{notify: func(string, any) {}}
	loc := "KH building, level 03, indoor air sensor 03"
	agentFault := AgentCall{Ref: "S1", Valid: true, Parsed: &Finding{Status: "sensor_fault", Pattern: "step_increase"}}
	mk := func(otherStatus, rulePattern string) *Incident {
		return &Incident{ID: "INC-T", Sensors: []SensorRef{
			{Ref: "S1", Node: "SR-AQ-KH03-03", Role: "air_quality", Metric: "temp", Location: loc, Xs: rampXs(8, 25, 34.5),
				Rule: Finding{Status: "critical", Pattern: rulePattern}},
			{Ref: "S2", Node: "SR-AQ-KH03-04", Role: "air_quality", Metric: "co2", Location: loc, Xs: flatXs(8, 600),
				Rule: Finding{Status: otherStatus}},
		}}
	}
	// another sensor agrees, no rule fault sign: the vote does not count, the reasoner's fault is guarded
	rep := Report{Severity: "sensor_fault", Label: "sensor_fault"}
	inc := mk("warning", "step_increase")
	r.severityGuard(inc, &rep)
	r.faultGuard(inc, &rep, []AgentCall{agentFault})
	if rep.Severity != "critical" {
		t.Fatalf("agreeing sensor: got %s", rep.Severity)
	}
	// nobody else moved: the agent's vote counts
	rep = Report{Severity: "sensor_fault", Label: "sensor_fault"}
	inc = mk("normal", "step_increase")
	r.severityGuard(inc, &rep)
	r.faultGuard(inc, &rep, []AgentCall{agentFault})
	if rep.Severity != "sensor_fault" {
		t.Fatalf("lone sensor: got %s", rep.Severity)
	}
	// the rules see a fault sign: the vote counts
	rep = Report{Severity: "sensor_fault", Label: "sensor_fault"}
	inc = mk("warning", "erratic")
	r.severityGuard(inc, &rep)
	r.faultGuard(inc, &rep, []AgentCall{agentFault})
	if rep.Severity != "sensor_fault" {
		t.Fatalf("rule fault sign: got %s", rep.Severity)
	}
}

// #58: the more-data request is skipped when the longer window + related lines cannot fit agent_ctx.
func TestMoreDataDead(t *testing.T) {
	withAgentVersion(t, "v2") // agent_ctx 1280
	build := func(per int) func(SensorRef) (AgentInput, bool) {
		return func(s SensorRef) (AgentInput, bool) {
			n := s.WinN
			if n == 0 {
				n = 48
			}
			p := strings.Repeat("x ", 40*n/10) // grows with the window
			for _, e := range s.ExtraEv {
				p += strings.Repeat("y ", per) + e
			}
			return AgentInput{Prompt: p, Xs: make([]float64, n)}, true
		}
	}
	s0 := SensorRef{Ref: "S1", Role: "water", Metric: "ph"}
	rel := []string{"related flow (water, KH): stable"}
	if d := moreDataDead(build(5000), s0, 48, rel); d == "" || !strings.Contains(d, "would not fit") {
		t.Fatalf("huge related lines must not fit: %q", d)
	}
	if d := moreDataDead(build(5), s0, 48, rel); d != "" {
		t.Fatalf("small request fits: %q", d)
	}
	if d := moreDataDead(build(5000), s0, 48, nil); d != "" {
		t.Fatalf("no related lines: nothing to pre-check: %q", d)
	}
}

// #39: the rules title of a limit crossing says the value and the limit.
func TestLimitTitle(t *testing.T) {
	got, ok := limitTitle(SensorRef{Role: "water", Metric: "ph", Xs: []float64{7.2, 9.61}})
	if !ok || got != "Water pH 9.61, above the 9.0 limit" {
		t.Fatalf("%q %v", got, ok)
	}
	got, _ = limitTitle(SensorRef{Role: "air_quality", Metric: "temp", Xs: []float64{25, 31.2}})
	if got != "Temperature 31.2 C, above the 30 C limit" {
		t.Fatalf("%q", got)
	}
	got, _ = limitTitle(SensorRef{Role: "power", Metric: "pf", Xs: []float64{0.9, 0.81}})
	if got != "Power factor 0.81, below the 0.85 limit" {
		t.Fatalf("%q", got)
	}
	if _, ok := limitTitle(SensorRef{Role: "water", Metric: "ph", Xs: []float64{7.2}}); ok {
		t.Fatal("inside the limits")
	}
	if _, ok := limitTitle(SensorRef{Role: "water", Metric: "level", Xs: []float64{3}}); ok {
		t.Fatal("no limits")
	}
}

// #95: "returned to normal at HH:MM after N abnormal readings" fact line, rendered in the v4 prompt.
func TestRecoveredLines(t *testing.T) {
	xs := append(append(flatXs(30, 7.2), flatXs(8, 9.6)...), 7.3, 7.2)
	end := int64(1795800900) // 23:05 IST
	got := recoveredLines([]SensorRef{{Ref: "S2", Role: "water", Metric: "ph", End: end, Xs: xs}})
	want := "RECOVERED: S2 ph returned to normal at 23:00 after 8 abnormal readings; now 7.20 pH, inside the card limits."
	if len(got) != 1 || got[0] != want {
		t.Fatalf("%q", got)
	}
	if l := recoveredLines([]SensorRef{{Ref: "S2", Role: "water", Metric: "ph", End: end, Xs: append(flatXs(30, 7.2), 9.6)}}); len(l) != 0 {
		t.Fatalf("still abnormal: %q", l)
	}
	if l := recoveredLines([]SensorRef{{Ref: "S2", Role: "water", Metric: "ph", End: end, Xs: flatXs(30, 7.2)}}); len(l) != 0 {
		t.Fatalf("never abnormal: %q", l)
	}
	in := V3Input{End: end, IncID: "INC-T", Recovered: got}
	if p := RenderV4User(in, V4Ctx{}); !strings.Contains(p, want) {
		t.Fatalf("v4 prompt lacks the line")
	}
	if p := RenderV3User(in); strings.Contains(p, "RECOVERED") {
		t.Fatalf("v3 prompt changed")
	}
}

// #98: up/down from the sign.
func TestStepSignFix(t *testing.T) {
	for in, want := range map[string]string{
		"pH stepped up -2.40 pH at 23:05 and stayed [E5,E1]":  "pH stepped down 2.40 pH at 23:05 and stayed [E5,E1]",
		"PH stepped up +1.89 pH at 22:25 and stayed":          "PH stepped up +1.89 pH at 22:25 and stayed",
		"CO2 shifted down abruptly by +120 ppm at 10:05":      "CO2 shifted up abruptly by 120 ppm at 10:05",
		"Load STEPPED UP -3 kW":                               "Load STEPPED DOWN 3 kW",
		"Humidity stepped up [E5,E1]":                         "Humidity stepped up [E5,E1]",
	} {
		if got := stepSignFix(in); got != want {
			t.Errorf("%q -> %q, want %q", in, got, want)
		}
	}
	rep := &Report{Observations: []V3Observation{{Text: "pH stepped up -2.40 pH [S1.E5]"}}}
	if rs := contextFixReport(rep, &Incident{}); len(rs) != 1 || rep.Observations[0].Text != "pH stepped down 2.40 pH [S1.E5]" {
		t.Fatalf("%v %q", rs, rep.Observations[0].Text)
	}
}

// #37: the timeline says the reasoner is writing only where the reasoner call follows.
func TestPreliminaryTimelineWording(t *testing.T) {
	r := &Reasoner{notify: func(string, any) {}}
	inc := &Incident{ID: "INC-T"}
	rc := &ReportCall{Parsed: &Report{Severity: "critical"}}
	r.preliminary(inc, rc)
	r.preliminaryNext(inc, &ReportCall{Parsed: &Report{Severity: "critical"}}, "the reasoner is writing the full report")
	var msgs []string
	for _, it := range inc.Timeline {
		msgs = append(msgs, it.Msg)
	}
	all := strings.Join(msgs, "\n")
	if len(msgs) != 2 || strings.Contains(msgs[0], "writing") || !strings.Contains(msgs[1], "the reasoner is writing the full report") {
		t.Fatalf("%s", all)
	}
	_ = fmt.Sprint
}
