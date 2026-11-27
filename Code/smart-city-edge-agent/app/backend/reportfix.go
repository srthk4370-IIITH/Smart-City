package main

// Report wording guards from live facts (sweep 2026-11-27; owner: "try a local fix, no new top-up unless the errors
// vary"). Each guard only rewrites the reasoner's free text when the incident's own readings contradict it, and
// records a repair line, so the report stays the model's report.
//   1. AC off: an AC-units sensor in the incident reads 0, but the text says "stop/turn off the AC" or "AC running".
//   2. Outdoor dust: every flagged sensor is an outdoor PM sensor, but the text says "ventilate"/"open windows"/
//      "increase fresh air" (outdoor dust: keep windows closed, cut fresh-air intake).
//   3. Corroborated rise: the report calls a temperature rise a sensor jump / sensor fault while a second temperature
//      sensor in the incident rose by >= 1 C over the same 30 min: treated as a real change.

import (
	"regexp"
	"strings"
)

var (
	acStopRe     = regexp.MustCompile(`(?i)\b(stop|turn off|switch off|shut (?:down|off))\s+(the\s+)?(ac|a/c|air[- ]?conditioning|ac units?)\b`)
	acRunningRe  = regexp.MustCompile(`(?i)\b(ac|a/c|ac units?)\s+(is |are |still )*running\b`)
	ventilateRe  = regexp.MustCompile(`(?i)\b(ventilate( the (room|area|space))?|open (the )?windows|increase (the )?(fresh[- ]air|ventilation)( intake)?)\b`)
	jumpClaimRe  = regexp.MustCompile(`(?i)\b(sensor (jump|glitch|spike|error|fault|malfunction|problem|issue)|not (a )?real (heat|rise|event|change)|not a hot room|faulty sensor|suspect(ed)? (\w+ ){0,2}(readings?|sensors?|values?)|sensor (is )?heating itself)\b`)
	tempMetricRe = regexp.MustCompile(`(?i)^(temp|temperature|room_temp|air_temp)$`)
)

func lastVal(s SensorRef) (float64, bool) {
	if len(s.Xs) == 0 {
		return 0, false
	}
	return s.Xs[len(s.Xs)-1], true
}

// rise over the last n readings (0 when the window is shorter)
func riseOver(s SensorRef, n int) float64 {
	if len(s.Xs) <= n {
		return 0
	}
	return s.Xs[len(s.Xs)-1] - s.Xs[len(s.Xs)-1-n]
}

func acOff(inc *Incident) bool {
	for _, s := range inc.Sensors {
		if s.Metric == "ac_units_on" || s.Metric == "ac_on" {
			if v, ok := lastVal(s); ok && v == 0 {
				return true
			}
		}
	}
	return false
}

func outdoorPMOnly(inc *Incident) bool {
	n := 0
	for _, s := range inc.Sensors {
		if s.Context {
			continue
		}
		n++
		m := strings.ToLower(s.Metric)
		loc := strings.ToLower(s.Location)
		if !strings.HasPrefix(m, "pm") || !(s.Role == "weather" || strings.Contains(loc, "outdoor") || strings.Contains(loc, "weather")) {
			return false
		}
	}
	return n > 0
}

// corroboratedRise: two different temperature sensors both rose >= 1 C over the last 6 readings (30 min).
func corroboratedRise(inc *Incident) (a, b string, ok bool) {
	var up []SensorRef
	for _, s := range inc.Sensors {
		if tempMetricRe.MatchString(s.Metric) && riseOver(s, 6) >= 1.0 {
			up = append(up, s)
		}
	}
	for i := range up {
		for j := i + 1; j < len(up); j++ {
			if up[i].Node != up[j].Node || up[i].Metric != up[j].Metric {
				return up[i].Node + " " + up[i].Metric, up[j].Node + " " + up[j].Metric, true
			}
		}
	}
	return "", "", false
}

// reportTexts: every free-text field a guard may rewrite.
func reportTexts(rep *Report) []*string {
	out := []*string{&rep.Title, &rep.RootCause, &rep.Explanation, &rep.Action, &rep.CausalChain, &rep.MonitorNext}
	for i := range rep.Checklist {
		out = append(out, &rep.Checklist[i].Target, &rep.Checklist[i].Why)
	}
	return out
}

func rewriteAll(rep *Report, re *regexp.Regexp, repl string) bool {
	hit := false
	for _, p := range reportTexts(rep) {
		if re.MatchString(*p) {
			*p = re.ReplaceAllString(*p, repl)
			hit = true
		}
	}
	return hit
}

// contextFixReport applies the guards; returns the repair lines.
func contextFixReport(rep *Report, inc *Incident) []string {
	var rs []string
	if acOff(inc) {
		a := rewriteAll(rep, acStopRe, "check why the AC is off (power, breaker, controller) and restore cooling")
		b := rewriteAll(rep, acRunningRe, "AC is off")
		if a || b {
			rs = append(rs, "AC wording set to the readings: the AC units read 0 (off)")
		}
	}
	if outdoorPMOnly(inc) && rewriteAll(rep, ventilateRe, "keep windows closed and reduce fresh-air intake") {
		rs = append(rs, "outdoor dust: 'ventilate' replaced by 'keep windows closed, reduce fresh-air intake'")
	}
	if a, b, ok := corroboratedRise(inc); ok {
		claim := rep.Severity == "sensor_fault" || rep.Label == "sensor_fault"
		for _, p := range []*string{&rep.Title, &rep.RootCause, &rep.Explanation} {
			claim = claim || jumpClaimRe.MatchString(*p)
		}
		if claim {
			if rep.Severity == "sensor_fault" {
				rep.Severity = ruleSeverity(inc.Sensors)
				if reportRank[rep.Severity] < reportRank["warning"] || rep.Severity == "sensor_fault" {
					rep.Severity = "warning"
				}
			}
			if rep.Label == "sensor_fault" {
				rep.Label = "unknown"
			}
			if jumpClaimRe.MatchString(rep.Title) {
				rep.Title = "" // the findings title is used instead
			}
			note := "Two sensors (" + a + ", " + b + ") rose together, so this is a real temperature rise, not a sensor jump."
			rep.Explanation = dropClaimSentences(rep.Explanation)
			rep.RootCause = dropClaimSentences(rep.RootCause)
			if !strings.Contains(rep.Explanation, note) {
				rep.Explanation = strings.TrimSpace(note + " " + rep.Explanation)
			}
			rs = append(rs, "corroborated rise: "+a+" and "+b+" rose together; sensor-jump wording overruled")
		}
	}
	return rs
}

// dropClaimSentences removes the sentences that make the sensor-fault claim (and a following "Check the sensor.").
func dropClaimSentences(t string) string {
	var keep []string
	drop := false
	for _, sen := range splitSentences(t) {
		if jumpClaimRe.MatchString(sen) {
			drop = true
			continue
		}
		if drop && checkSensorRe.MatchString(sen) {
			continue
		}
		drop = false
		keep = append(keep, sen)
	}
	return strings.Join(keep, " ")
}

var checkSensorRe = regexp.MustCompile(`(?i)^\s*(please )?(check|inspect|recalibrate) the sensor\b`)

func splitSentences(t string) []string {
	var out []string
	start := 0
	for i := 0; i < len(t); i++ {
		if (t[i] == '.' || t[i] == '!' || t[i] == '?') && (i+1 == len(t) || t[i+1] == ' ') {
			if s := strings.TrimSpace(t[start : i+1]); s != "" {
				out = append(out, s)
			}
			start = i + 1
		}
	}
	if s := strings.TrimSpace(t[start:]); s != "" {
		out = append(out, s)
	}
	return out
}
