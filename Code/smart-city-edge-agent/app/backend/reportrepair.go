package main

// Mechanical repairs of a reasoner report before the gate (owner 2026-11-27, "do all these fixes"). A rejected report
// is replaced by the agent template, which the paper measured at 25 % fully correct against 75 % for the reasoner,
// and most rejections were format slips around a sound diagnosis (proofs/2026-11-27_features/FOLLOWUP.md §2).
// Repaired here, each with a logged repair line:
//   - evidence ids written as S1-E3 / S1_E3 / S1 E3 / s1.e3 -> S1.E3; ids still unknown are dropped from a list that
//     keeps at least one known id;
//   - an agent_check with a verdict outside the list, or an unknown sensor ref, is dropped (agent_checks are
//     optional; the backend claim checker adds its own);
//   - empty evidence is filled from the observations' own ids;
//   - the checklist's first action is brought in line with the severity policy: a later policy action moves to the
//     front, else the domain's inspect action (or the sensor / monitor step) is added first.
// Still rejected: invented numbers, actuation language, bad JSON, unknown labels or actions, missing confidence,
// empty title, title/severity contradictions.

import (
	"fmt"
	"regexp"
	"strings"
)

var repairIDRe = regexp.MustCompile(`^(?i)(s\d+)\s*[-_. ]\s*(e\d+)$`)

func normV3ID(id string) string {
	id = strings.TrimSpace(id)
	if m := repairIDRe.FindStringSubmatch(id); m != nil {
		return strings.ToUpper(m[1]) + "." + strings.ToUpper(m[2])
	}
	return id
}

// fixIDs normalises ids and drops unknown ones when at least one known id remains.
func fixIDs(src []string, ids map[string]bool, where string, rep *[]string) []string {
	var out, bad []string
	changed := false
	for _, id := range src {
		n := normV3ID(id)
		if n != strings.TrimSpace(id) {
			changed = true
		}
		if ids[n] {
			out = append(out, n)
		} else {
			bad = append(bad, n)
		}
	}
	if len(out) == 0 {
		if changed {
			return append(out, bad...)
		}
		return src
	}
	if changed {
		*rep = append(*rep, where+": evidence ids normalised")
	}
	if len(bad) > 0 {
		*rep = append(*rep, fmt.Sprintf("%s: unknown id(s) %s dropped", where, strings.Join(bad, ", ")))
	}
	return out
}

var domainInspect = map[string]string{"air_quality": "inspect_ventilation", "hvac": "inspect_hvac", "water": "inspect_water_system",
	"power": "inspect_electrical", "occupancy": "review_schedule"}

func repairV3Report(r *reportV3Raw, ids map[string]bool, weatherOnly bool) []string {
	var rep []string
	r.Evidence = fixIDs(r.Evidence, ids, "evidence", &rep)
	for i := range r.Observations {
		r.Observations[i].Src = fixIDs(r.Observations[i].Src, ids, fmt.Sprintf("observation %d", i+1), &rep)
	}
	var checks []V3AgentCheck
	for i, c := range r.AgentChecks {
		ref := strings.ToUpper(strings.TrimSpace(c.Ref))
		if j := strings.IndexAny(ref, ".-_ "); j > 0 {
			ref = ref[:j]
		}
		if !contains(v3Verdicts, c.Verdict) || !ids[ref] || !strings.HasPrefix(ref, "S") {
			rep = append(rep, fmt.Sprintf("agent_check %d dropped (ref %q, verdict %q not allowed)", i+1, c.Ref, c.Verdict))
			continue
		}
		c.Ref = ref
		c.Src = fixIDs(c.Src, ids, fmt.Sprintf("agent_check %d", i+1), &rep)
		checks = append(checks, c)
	}
	r.AgentChecks = checks
	if len(r.Evidence) == 0 {
		seen := map[string]bool{}
		for _, o := range r.Observations {
			for _, id := range o.Src {
				if ids[id] && !seen[id] && len(r.Evidence) < 6 {
					seen[id] = true
					r.Evidence = append(r.Evidence, id)
				}
			}
		}
		if len(r.Evidence) > 0 {
			rep = append(rep, "empty evidence filled from the observations' ids")
		}
	}
	if contains(v3Severities, r.Severity) && v3ActionFloor(r.Severity, r.Checklist, weatherOnly) != "" || len(r.Checklist) == 0 {
		if fixChecklistFloor(r, weatherOnly) {
			rep = append(rep, "checklist first action set to the "+r.Severity+" policy ("+r.Checklist[0].Action+")")
		}
	}
	return rep
}

// fixChecklistFloor: move the first policy-conforming item to the front, else add the policy action first.
func fixChecklistFloor(r *reportV3Raw, weatherOnly bool) bool {
	if !contains(v3Severities, r.Severity) {
		return false
	}
	for i := 1; i < len(r.Checklist); i++ {
		c := append([]V3ChecklistItem{r.Checklist[i]}, append(append([]V3ChecklistItem{}, r.Checklist[:i]...), r.Checklist[i+1:]...)...)
		if v3ActionFloor(r.Severity, c, weatherOnly) == "" {
			r.Checklist = c
			return true
		}
	}
	act := "monitor"
	switch r.Severity {
	case "critical", "warning":
		act = "request_facility_review"
		for _, d := range r.AffectedDomains {
			if a, ok := domainInspect[d]; ok {
				act = a
				break
			}
		}
		if r.Severity == "critical" && act == "review_schedule" {
			act = "request_facility_review"
		}
	case "sensor_fault":
		act = "check_sensor"
	}
	target := ""
	if len(r.Evidence) > 0 {
		target = strings.SplitN(r.Evidence[0], ".", 2)[0]
	}
	item := V3ChecklistItem{Action: act, Target: target, Why: "Added by the " + r.Severity + " action policy"}
	c := append([]V3ChecklistItem{item}, r.Checklist...)
	if len(c) > 5 {
		c = c[:5]
	}
	if v3ActionFloor(r.Severity, c, weatherOnly) != "" {
		return false
	}
	r.Checklist = c
	return true
}
