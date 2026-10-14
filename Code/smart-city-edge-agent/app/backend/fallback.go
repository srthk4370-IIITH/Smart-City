package main

// Deterministic cross-domain report, used when the synthesizer's own output fails the policy gate.
//
// Why this exists
// ---------------
// Before this, a rejected synthesizer left the incident marked `done_with_errors` and still showed
// the operator the rejected text. That is the worst of both worlds: the gate knew the answer was
// unsound, and displayed it anyway. Observed on a real crowded_room incident (HANDBOOK 2.21), where
// the synthesizer degenerated into key=value prose stuffed inside root_cause:
//
//	{"root_cause": "Ventilation_insufficient cause=... label=... action=... explanation=..."}
//	errors: ["unknown label ''", "action '' not whitelisted", "no evidence cited"]
//
// Mode 3 already had this pattern for the single-domain case (isolatedReport, "rule finding (agent
// output rejected)"). This is the multi-domain equivalent: build the report from the agent findings
// that DID pass the gate, which are individually validated, enum-checked and evidence-cited.
//
// Nothing is invented. Every field comes from a validated finding or from our own cause->label
// taxonomy, and the rejected model text is preserved in Raw for audit.

import (
	"fmt"
	"sort"
	"strings"
)

// fallbackReport builds a cross-domain report from the validated agent findings of an incident.
// rejected is the report call that failed the gate; its text and errors are carried through so the
// failure stays visible rather than being quietly swallowed.
func fallbackReport(sensors []SensorRef, calls []AgentCall, rejected *ReportCall) *ReportCall {
	// index the validated findings by sensor ref
	type dom struct {
		ref, role string
		f         Finding
		sensor    SensorRef
	}
	var good []dom
	byRef := map[string]SensorRef{}
	for _, s := range sensors {
		byRef[s.Ref] = s
	}
	for _, c := range calls {
		if c.Parsed == nil || !c.Valid {
			continue
		}
		s, ok := byRef[c.Ref]
		if !ok {
			continue
		}
		good = append(good, dom{ref: c.Ref, role: s.Role, f: *c.Parsed, sensor: s})
	}
	if len(good) == 0 {
		// nothing validated: fall back to the rule findings, which are deterministic by construction
		for _, s := range sensors {
			if !s.Context {
				good = append(good, dom{ref: s.Ref, role: s.Role, f: s.Rule, sensor: s})
			}
		}
	}
	if len(good) == 0 {
		return rejected // genuinely nothing to build from; leave the gate's verdict alone
	}

	// most severe finding leads the report; ties broken by confidence so the order is deterministic
	sort.SliceStable(good, func(i, j int) bool {
		si, sj := sevRank(good[i].f.Status), sevRank(good[j].f.Status)
		if si != sj {
			return si > sj
		}
		return good[i].f.Confidence > good[j].f.Confidence
	})
	lead := good[0]

	// label must come from ReportLabels - this report goes through the same gate as the model's
	lab := causeToLabel[lead.f.LikelyCause]
	if lab == "" && isAgentCause(lead.f.LikelyCause) {
		lab = "normal_operation"
	}
	if !contains(ReportLabels, lab) {
		lab = "unknown"
	}

	var doms, ev []string
	var lines []string
	for _, d := range good {
		doms = appendUnique(doms, d.role)
		for _, o := range d.f.Observations {
			for _, id := range idRe.FindAllString(o, -1) {
				ev = appendUnique(ev, d.ref+"."+id)
			}
		}
		lines = append(lines, fmt.Sprintf("%s (%s): %s, %s - %s",
			nice[d.sensor.Metric], d.ref,
			strings.ReplaceAll(d.f.Pattern, "_", " "), d.f.Status,
			strings.ReplaceAll(d.f.LikelyCause, "_", " ")))
	}
	if len(ev) == 0 {
		ev = []string{lead.ref + ".E1"}
	}

	expl := "Cross-domain summary assembled by policy from the domain agents that passed the safety " +
		"check, because the synthesizer's own report was rejected. " + strings.Join(lines, "; ") + "."
	if len(doms) > 1 {
		expl += fmt.Sprintf(" %d domains are involved: %s.", len(doms), strings.Join(doms, ", "))
	}

	// confidence is the LOWEST of the contributing findings: a summary is only as good as its weakest part
	conf := lead.f.Confidence
	for _, d := range good {
		if d.f.Confidence < conf {
			conf = d.f.Confidence
		}
	}

	rep := &Report{
		RootCause: fmt.Sprintf("%s %s on %s (%s)", nice[lead.sensor.Metric],
			strings.ReplaceAll(lead.f.Pattern, "_", " "), lead.sensor.Location,
			strings.ReplaceAll(lead.f.LikelyCause, "_", " ")),
		Label: lab, AffectedDomains: doms, Evidence: ev, Confidence: conf,
		Action: lead.f.Action, Explanation: expl, RequiresHuman: true,
	}

	out := &ReportCall{
		Model:  "deterministic (synthesizer output rejected by policy)",
		Parsed: rep, Valid: true,
	}
	if rejected != nil {
		out.Raw, out.LatencyMs, out.Prompt, out.CallMetrics = rejected.Raw, rejected.LatencyMs, rejected.Prompt, rejected.CallMetrics
		out.Repairs = append(out.Repairs, "synthesizer output rejected ("+
			strings.Join(rejected.Errors, "; ")+"); cross-domain report rebuilt from the validated agent findings")
	}
	return out
}
