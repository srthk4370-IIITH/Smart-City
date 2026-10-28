package main

// Incident severity, decided by the cross-domain reasoner.
//
// An incident used to keep the severity of the rule finding that opened it, forever. The rules only
// open incidents; the NPU domain agents then look at each window properly, and they disagree with
// the rules often enough to matter: an incident whose "step decrease" sensors were all judged
// normal by their agents still showed as critical in the list. So the rule severity is now only
// provisional (shown while the analysis runs, Incident.SeverityFinal false), and the displayed
// severity is the reasoner's, set once the analysis completes.

// reportRank orders the severities an operator sees. A real warning outranks a sensor fault (the
// fault is a data-quality problem, the warning a facility one), as on the dashboard cards
// (server.go /api/live). This is deliberately not sevRank: that ranks sensor_fault above warning
// for the event gate's batching and re-report logic, which must not change.
var reportRank = map[string]int{"critical": 3, "warning": 2, "sensor_fault": 1, "normal": 0}

// normSeverity maps a severity written by a model (or a person) onto the four values the report
// uses, tolerating the usual wording drift like policy.go does for labels and actions.
// "" = not a severity.
func normSeverity(s string) string {
	n := normEnum(s)
	if _, ok := reportRank[n]; ok {
		return n
	}
	return map[string]string{"fine": "normal", "ok": "normal", "info": "normal", "none": "normal", "low": "normal",
		"normal_operation": "normal", "high": "critical", "severe": "critical", "alarm": "critical",
		"medium": "warning", "moderate": "warning", "warn": "warning",
		"fault": "sensor_fault", "faulty": "sensor_fault", "faulty_sensor": "sensor_fault"}[n]
}

// reasonerSeverity decides an incident's final severity: "critical", "warning", "normal" (shown as
// "fine") or "sensor_fault".
//
// STUB: the synthesizer is being replaced by the owner's own cross-domain reasoner, which will
// decide severity itself; this function is the one place that decision is read, so the real
// reasoner replaces this body and nothing else changes. Until then:
//
//  1. a valid severity in the reasoner's own report wins (the synthesizer prompt does not ask for
//     one yet, but policy.go keeps it when present);
//  2. otherwise the worst FINAL status among the flagged sensors: the domain agent's finding where
//     it passed the policy gate, else the rule finding the report fell back to for that sensor
//     (Mode 1 and Mode 2 have no agents, so this is the rule view there). Related context sensors
//     are evidence for the reasoner, not alarms of this incident, so they do not raise it.
//
// Caller holds r.mu (or owns inc exclusively).
func reasonerSeverity(inc *Incident) string {
	if inc.Final != nil && inc.Final.Valid && inc.Final.Parsed != nil {
		if s := normSeverity(inc.Final.Parsed.Severity); s != "" {
			return s
		}
	}
	agent := map[string]*Finding{}
	for i := range inc.Agents {
		if a := &inc.Agents[i]; a.Parsed != nil && a.Valid {
			agent[a.Ref] = a.Parsed
		}
	}
	worst := "normal"
	for _, s := range inc.Sensors {
		if s.Context {
			continue
		}
		f := s.Rule
		if a, ok := agent[s.Ref]; ok {
			f = *a
		}
		st := longRangeRaise(f, s).Status
		if st = normSeverity(st); reportRank[st] > reportRank[worst] {
			worst = st
		}
	}
	return worst
}

// ruleSeverity is the rule engine's view of the same flagged sensors (the Mode-1 shadow report).
func ruleSeverity(sensors []SensorRef) string {
	worst := "normal"
	for _, s := range sensors {
		if st := normSeverity(s.Rule.Status); !s.Context && reportRank[st] > reportRank[worst] {
			worst = st
		}
	}
	return worst
}

// finaliseSeverity records the reasoner's decision on the report the operator reads and makes it
// the incident's displayed severity. Called once the analysis has completed. Caller holds r.mu.
func finaliseSeverity(inc *Incident) {
	sev := reasonerSeverity(inc)
	if inc.Final != nil && inc.Final.Parsed != nil {
		inc.Final.Parsed.Severity = sev
	}
	inc.Severity, inc.SeverityFinal = sev, true
	retitle(inc)
}

// backfillSeverity gives an incident stored before severity_final existed the reasoner's severity,
// so the list is coloured by one rule for old and new incidents alike. Incidents that never
// finished ("failed": the process died mid-analysis) keep their provisional rule severity.
func backfillSeverity(inc *Incident) {
	if inc.SeverityFinal || inc.State == "running" || inc.State == "failed" {
		return
	}
	if inc.Mode1.Severity == "" {
		inc.Mode1.Severity = ruleSeverity(inc.Sensors)
	}
	finaliseSeverity(inc)
}
