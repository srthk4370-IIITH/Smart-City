package main

// Severity changes at a re-analysis are explained, and a drop from critical needs the rules to agree (owner #6).

import (
	"fmt"
	"strings"
)

// guardCriticalDrop: a re-analysis that would take an incident from critical to a lower level is only accepted when the
// rules agree (ruleSeverity below critical); otherwise sh keeps critical. Returns true when it refused the drop.
func guardCriticalDrop(prevSev string, sh *Incident) bool {
	if normSeverity(prevSev) != "critical" || reportRank[normSeverity(sh.Severity)] >= reportRank["critical"] {
		return false
	}
	if reportRank[ruleSeverity(sh.Sensors)] < reportRank["critical"] {
		return false // the rules agree: the drop stands
	}
	sh.Severity = "critical"
	if sh.Final != nil && sh.Final.Parsed != nil {
		sh.Final.Parsed.Severity = "critical"
	}
	return true
}

func lastReading(s SensorRef) string {
	if len(s.Xs) == 0 {
		return ""
	}
	return fmt.Sprintf("%.4g", s.Xs[len(s.Xs)-1])
}

// severityWhy: the reason text for a severity change (or a refused drop): which readings and patterns changed.
func severityWhy(inc *Incident, prev, cur Revision, kept bool) string {
	var parts []string
	was := map[string]RevSensor{}
	for _, s := range prev.Sensors {
		was[s.Ref] = s
	}
	last := map[string]SensorRef{}
	for _, s := range inc.Sensors {
		last[s.Ref] = s
	}
	for _, s := range cur.Sensors {
		p := was[s.Ref]
		if p.Pattern == s.Pattern && p.Status == s.Status && !s.Kept && !s.Curbed {
			continue
		}
		part := fmt.Sprintf("%s: %s/%s -> %s/%s", metricWord(s.Metric), strings.ReplaceAll(p.Pattern, "_", " "), p.Status,
			strings.ReplaceAll(s.Pattern, "_", " "), s.Status)
		if p.Pattern == "" && p.Status == "" {
			part = fmt.Sprintf("%s: %s/%s", metricWord(s.Metric), strings.ReplaceAll(s.Pattern, "_", " "), s.Status)
		}
		if v := lastReading(last[s.Ref]); v != "" {
			part += " (last reading " + v + ")"
		}
		if s.Note != "" && (s.Kept || s.Curbed) {
			part += " [" + s.Note + "]"
		}
		parts = append(parts, part)
	}
	body := strings.Join(parts, "; ")
	if body == "" {
		body = "no sensor pattern changed; the reasoner weighed the same readings differently"
	}
	if kept {
		return fmt.Sprintf("Kept critical: the AI re-read this as %s but the rules still read critical (%s)", sevWord(cur.Severity), body)
	}
	return fmt.Sprintf("Severity %s -> %s: %s", sevWord(prev.Severity), sevWord(cur.Severity), body)
}

// noteSeverityChangeLocked records the reason for a severity change on the revision, the incident, its timeline and its
// report. Returns the reason ("" when the severity did not change and nothing was kept). Caller holds r.mu.
// prev is the revision of the analysis before; rev the new one (not yet appended).
func (r *Reasoner) noteSeverityChangeLocked(inc *Incident, prev Revision, rev *Revision, kept bool) string {
	if !kept && normSeverity(prev.Severity) == normSeverity(rev.Severity) {
		return ""
	}
	why := severityWhy(inc, prev, *rev, kept)
	rev.SeverityWhy = why
	inc.SeverityWhy, inc.SeverityKept = why, kept
	inc.Timeline = append(inc.Timeline, TimelineItem{nowTime().In(IST).Format("15:04:05"), why})
	if inc.Final != nil {
		if inc.Final.Note == "" {
			inc.Final.Note = why
		} else if !strings.Contains(inc.Final.Note, why) {
			inc.Final.Note += " " + why
		}
	}
	inc.event("reasoner", "severity_change", "", "", "", why)
	return why
}
