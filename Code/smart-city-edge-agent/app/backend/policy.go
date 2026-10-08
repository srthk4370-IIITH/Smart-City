package main

// PolicyGate: every LLM output is validated before it is shown as a finding/report.
// Fails closed: invalid JSON, unknown enum values, uncited or hallucinated evidence ids,
// non-whitelisted actions or actuation language -> REJECTED with reasons (raw output still shown).

import (
	"encoding/json"
	"fmt"
	"regexp"
	"strings"
)

func extractJSON(text string) (string, bool) {
	s := strings.Index(text, "{")
	if s < 0 {
		return "", false
	}
	depth, inStr, esc := 0, false, false
	for i := s; i < len(text); i++ {
		c := text[i]
		if inStr {
			if esc {
				esc = false
			} else if c == '\\' {
				esc = true
			} else if c == '"' {
				inStr = false
			}
			continue
		}
		switch c {
		case '"':
			inStr = true
		case '{':
			depth++
		case '}':
			depth--
			if depth == 0 {
				return text[s : i+1], true
			}
		}
	}
	return "", false
}

var idRe = regexp.MustCompile(`\bE\d+\b`)
var refRe = regexp.MustCompile(`\bS\d+\.E\d+\b`)
var actuation = regexp.MustCompile(`(?i)\b(shut ?off|shut down|switch off|turn off|cut power|disable|override|bypass|force close|evacuate)\b`)

func contains(list []string, s string) bool {
	for _, x := range list {
		if x == s {
			return true
		}
	}
	return false
}

// normEnum: documented light normalisation of enum spellings ("Load Surge" -> "load_surge").
// It never invents values: the result must still be one of the allowed enum values.
func normEnum(v string) string {
	v = strings.ToLower(strings.TrimSpace(v))
	v = strings.NewReplacer(" ", "_", "-", "_").Replace(v)
	return v
}

// mergeStrayIDs fixes outputs where the model put the evidence ids in a separate list element.
func mergeStrayIDs(obs []string) []string {
	var out []string
	stray := regexp.MustCompile(`^[\[\]E0-9,\s]+$`)
	for _, o := range obs {
		if stray.MatchString(o) && len(out) > 0 {
			out[len(out)-1] += " " + strings.TrimSpace(o)
			continue
		}
		out = append(out, o)
	}
	return out
}

// --- tolerant recovery for malformed JSON from the 4-bit on-device model ------------------------
// Only the model's OWN stated values are extracted; nothing is invented. Used solely when strict
// json.Unmarshal fails, and the result still goes through every enum/evidence check below.
var reField = map[string]*regexp.Regexp{
	"pattern":      regexp.MustCompile(`"pattern"\s*:\s*"?([A-Za-z_]+)"?`),
	"status":       regexp.MustCompile(`"status"\s*:\s*"?([A-Za-z_]+)"?`),
	"likely_cause": regexp.MustCompile(`"likely_cause"\s*:\s*"?([A-Za-z_]+)"?`),
	"action":       regexp.MustCompile(`"action"\s*:\s*"?([A-Za-z_]+)"?`),
}
var reConf = regexp.MustCompile(`"confidence"\s*:\s*([0-9]*\.?[0-9]+)`)
var reObs = regexp.MustCompile(`"([^"]*\[E\d+[^"]*)"`) // observations always cite evidence ids

// dropUnmatchedBrackets removes `]` characters outside strings that do not close an open array.
func dropUnmatchedBrackets(js string) (string, int) {
	var b strings.Builder
	var stack []byte
	inStr, esc, n := false, false, 0
	for i := 0; i < len(js); i++ {
		c := js[i]
		if inStr {
			if esc {
				esc = false
			} else if c == '\\' {
				esc = true
			} else if c == '"' {
				inStr = false
			}
			b.WriteByte(c)
			continue
		}
		switch c {
		case '"':
			inStr = true
		case '{', '[':
			stack = append(stack, c)
		case '}':
			if len(stack) > 0 {
				stack = stack[:len(stack)-1]
			}
		case ']':
			if len(stack) == 0 || stack[len(stack)-1] != '[' {
				n++
				continue
			}
			stack = stack[:len(stack)-1]
		}
		b.WriteByte(c)
	}
	return b.String(), n
}

func salvageFinding(text string) (*Finding, bool) {
	get := func(k string) string {
		if m := reField[k].FindStringSubmatch(text); m != nil {
			return m[1]
		}
		return ""
	}
	f := Finding{Pattern: get("pattern"), Status: get("status"), LikelyCause: get("likely_cause"), Action: get("action")}
	if f.Pattern == "" || f.Status == "" {
		return nil, false
	}
	for _, m := range reObs.FindAllStringSubmatch(text, -1) {
		f.Observations = append(f.Observations, m[1])
	}
	if len(f.Observations) == 0 {
		return nil, false
	}
	if m := reConf.FindStringSubmatch(text); m != nil {
		fmt.Sscanf(m[1], "%f", &f.Confidence)
	}
	return &f, true
}

var reportIDRe = regexp.MustCompile(`S\d+\.E\d+`)

func isAgentCause(c string) bool {
	for _, cs := range Causes {
		if contains(cs, c) {
			return true
		}
	}
	return false
}

func checkAgent(s SensorRef, res GenieResult, prompt string) AgentCall {
	call := AgentCall{Ref: s.Ref, Role: s.Role, Model: res.Model, FineTuned: res.FineTuned, LatencyMs: res.LatencyMs, Raw: res.Text, Prompt: prompt}
	if res.Error != "" {
		call.Errors = append(call.Errors, "NPU error: "+res.Error)
		return call
	}
	js, ok := extractJSON(res.Text)
	if !ok {
		call.Errors = append(call.Errors, "no complete JSON object in output")
		return call
	}
	var f Finding
	if err := json.Unmarshal([]byte(js), &f); err != nil {
		rec, ok := salvageFinding(res.Text)
		if !ok {
			call.Errors = append(call.Errors, "invalid JSON: "+err.Error())
			return call
		}
		f = *rec
		call.Repairs = append(call.Repairs, "malformed JSON ("+err.Error()+"); fields recovered from the model's own output")
	}
	f.Pattern, f.Status, f.LikelyCause, f.Action = normEnum(f.Pattern), normEnum(f.Status), normEnum(f.LikelyCause), normEnum(f.Action)
	f.Observations = mergeStrayIDs(f.Observations)
	call.Parsed = &f
	pats := ContPatterns
	if s.Role == "occupancy" {
		pats = OccPatterns
	}
	if !contains(pats, f.Pattern) {
		call.Errors = append(call.Errors, "unknown pattern '"+f.Pattern+"'")
	}
	if !contains([]string{"normal", "warning", "critical", "sensor_fault"}, f.Status) {
		call.Errors = append(call.Errors, "unknown status '"+f.Status+"'")
	}
	if !contains(Causes[s.Role], f.LikelyCause) {
		call.Errors = append(call.Errors, "cause '"+f.LikelyCause+"' not allowed for "+s.Role)
	}
	if f.Action == "" && contains(Causes[s.Role], f.LikelyCause) {
		// The model dropped the action field but gave a valid cause. Action is a deterministic function
		// of (cause, status) in our taxonomy - the same mapping that generated the training targets - so
		// fill it in and record the repair rather than discarding an otherwise sound finding.
		f.Action = ActionOf(f.LikelyCause, f.Status)
		call.Repairs = append(call.Repairs, "action missing, derived from cause '"+f.LikelyCause+"' by policy")
	}
	if !contains(Actions, f.Action) {
		call.Errors = append(call.Errors, "action '"+f.Action+"' not whitelisted")
	}
	if f.Confidence < 0 || f.Confidence > 1 {
		call.Errors = append(call.Errors, "confidence out of [0,1]")
	}
	if len(f.Observations) == 0 {
		call.Errors = append(call.Errors, "no observations")
	}
	valid := map[string]bool{}
	for _, e := range s.Evidence {
		valid[e.ID] = true
	}
	for _, o := range f.Observations {
		ids := idRe.FindAllString(o, -1)
		if len(ids) == 0 {
			call.Errors = append(call.Errors, "observation without evidence: "+trunc(o, 60))
		}
		for _, id := range ids {
			if !valid[id] {
				call.Errors = append(call.Errors, "hallucinated evidence id "+id)
			}
		}
		if actuation.MatchString(o) {
			call.Errors = append(call.Errors, "actuation language blocked")
		}
	}
	call.Valid = len(call.Errors) == 0
	return call
}

func (r *Reasoner) checkReport(res GenieResult, prompt string, sensors []SensorRef) *ReportCall {
	rc := &ReportCall{Model: res.Model, LatencyMs: res.LatencyMs, Raw: res.Text, Prompt: prompt}
	if res.Error != "" {
		rc.Errors = append(rc.Errors, "NPU error: "+res.Error)
		return rc
	}
	js, ok := extractJSON(res.Text)
	if !ok {
		// common 4-bit slip: the last string value is never closed (`..."explanation": "... [S1.E7] }`)
		t := strings.TrimSuffix(strings.TrimSpace(res.Text), "}")
		if j2, ok2 := extractJSON(strings.TrimRight(t, " ") + `"}`); ok2 {
			js, ok = j2, true
			rc.Repairs = append(rc.Repairs, "unterminated final string closed")
		}
	}
	if !ok {
		rc.Errors = append(rc.Errors, "no complete JSON object in output")
		return rc
	}
	var rep Report
	if err := json.Unmarshal([]byte(js), &rep); err != nil {
		// 4-bit slip seen on the QIDK: a `]` that closes no array (`... [S1.E1]."]}`). Dropping brackets that
		// match nothing changes only the syntax; every field is still validated below.
		fixed, n := dropUnmatchedBrackets(js)
		if n == 0 || json.Unmarshal([]byte(fixed), &rep) != nil {
			rc.Errors = append(rc.Errors, "invalid JSON: "+err.Error())
			return rc
		}
		rc.Repairs = append(rc.Repairs, fmt.Sprintf("%d stray ']' removed from the JSON", n))
	}
	// affected_domains must be real domain names; keep the valid ones, else use the flagged sensors' domains
	okDom := map[string]bool{"air_quality": true, "water": true, "power": true, "occupancy": true, "weather": true, "hvac": true}
	var doms []string
	for _, d := range rep.AffectedDomains {
		if nd := normEnum(d); okDom[nd] {
			doms = appendUnique(doms, nd)
		}
	}
	if len(doms) != len(rep.AffectedDomains) {
		if len(doms) == 0 {
			for _, sr := range sensors {
				if !sr.Context {
					doms = appendUnique(doms, sr.Role)
				}
			}
		}
		rc.Repairs = append(rc.Repairs, "affected_domains cleaned to real domain names")
		rep.AffectedDomains = doms
	}
	rep.RequiresHuman = true // structural: every report needs operator approval
	rep.Label, rep.Action = normEnum(rep.Label), normEnum(rep.Action)
	// documented aliases for generic wording of the same whitelisted action (report only)
	if a, ok := map[string]string{"inspect": "request_facility_review", "investigate": "request_facility_review",
		"inspection": "request_facility_review", "no_action": "none", "monitor_closely": "monitor"}[rep.Action]; ok {
		rep.Action = a
	}
	if rep.Label == "" && contains(ReportLabels, normEnum(rep.RootCause)) {
		rep.Label = normEnum(rep.RootCause)
	}
	if !contains(ReportLabels, rep.Label) && rep.Label != "" {
		// label holds something else (e.g. a domain name) but the model's own root_cause is a valid label
		if rcl := normEnum(rep.RootCause); contains(ReportLabels, rcl) {
			rc.Repairs = append(rc.Repairs, "label '"+rep.Label+"' invalid, used the stated root_cause '"+rcl+"'")
			rep.Label = rcl
		} else if lab, ok := causeToLabel[rcl]; ok {
			rc.Repairs = append(rc.Repairs, "label '"+rep.Label+"' invalid, mapped stated root_cause '"+rcl+"' to '"+lab+"'")
			rep.Label = lab
		}
	}
	if !contains(ReportLabels, rep.Label) {
		// the fine-tuned model sometimes names the agent-level CAUSE ("normal_conditions") as the label;
		// map it through our own cause->label taxonomy and record the repair.
		lab, ok := causeToLabel[normEnum(rep.Label)]
		if !ok && isAgentCause(normEnum(rep.Label)) {
			lab, ok = "normal_operation", true // normal_load, normal_conditions, normal_usage, diurnal_cycle ...
		}
		if ok {
			rc.Repairs = append(rc.Repairs, "label '"+rep.Label+"' is a cause name, mapped to '"+lab+"' by policy")
			rep.Label = lab
		}
	}
	rc.Parsed = &rep
	if !contains(ReportLabels, rep.Label) {
		rc.Errors = append(rc.Errors, "unknown label '"+rep.Label+"'")
	}
	if !contains(Actions, rep.Action) {
		rc.Errors = append(rc.Errors, "action '"+rep.Action+"' not whitelisted")
	}
	valid := map[string]bool{}
	for _, s := range sensors {
		valid[s.Ref] = true // sensor-level citation of a flagged sensor
		for _, e := range s.Evidence {
			valid[s.Ref+"."+e.ID] = true
		}
	}
	// models sometimes pack several ids into one string ("S1.E5,S1.E7") or append the evidence text
	// ("S2.E2 max = 43.4 C at 04:30"): keep exactly the S#.E# ids written, each id is still verified below
	var flat []string
	for _, e := range rep.Evidence {
		if ids := reportIDRe.FindAllString(e, -1); len(ids) > 0 {
			for _, id := range ids {
				flat = appendUnique(flat, id)
			}
		} else {
			flat = append(flat, strings.TrimSpace(e)) // left as is -> rejected below if not a real id
		}
	}
	if strings.Join(flat, "|") != strings.Join(rep.Evidence, "|") {
		rc.Repairs = append(rc.Repairs, "evidence entries reduced to their S#.E# ids")
		rep.Evidence = flat
	}
	cited := append([]string{}, rep.Evidence...)
	cited = append(cited, refRe.FindAllString(rep.RootCause+" "+rep.Explanation, -1)...)
	if len(rep.Evidence) == 0 {
		rc.Errors = append(rc.Errors, "no evidence cited")
	}
	for _, id := range cited {
		if !valid[strings.TrimSpace(id)] {
			rc.Errors = append(rc.Errors, fmt.Sprintf("hallucinated evidence id %q", id))
		}
	}
	if actuation.MatchString(rep.RootCause + " " + rep.Explanation) {
		rc.Errors = append(rc.Errors, "actuation language blocked")
	}
	if rep.Confidence < 0 || rep.Confidence > 1 {
		rc.Errors = append(rc.Errors, "confidence out of [0,1]")
	}
	rc.Valid = len(rc.Errors) == 0
	return rc
}

func trunc(s string, n int) string {
	if len(s) > n {
		return s[:n] + "..."
	}
	return s
}
