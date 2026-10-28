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

// recommendOff is a RECOMMENDATION to switch something off ("recommend switching the AC off"), allowed
// since v2's switch_off_ac action (HVAC running in an empty room): the operator still approves it. Commands
// ("switch off the pump", "turn off the AC now") stay blocked.
var recommendOff = regexp.MustCompile(`(?i)\b(recommend|suggest|consider|advise)\w*\b[^.\[]{0,30}?\b(switch|turn)(ing)?\b[^.\[]{0,20}?\boff\b`)

// blocksActuation reports actuation language once recommendation phrases are set aside.
func blocksActuation(text string) bool {
	return actuation.MatchString(recommendOff.ReplaceAllString(text, " "))
}

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
	"onset":        regexp.MustCompile(`"onset"\s*:\s*"(\d{1,2}:\d{2})"`),
	"fault_kind":   regexp.MustCompile(`"fault_kind"\s*:\s*"?([A-Za-z_]+)"?`),
}
var reActive = regexp.MustCompile(`"event_active"\s*:\s*(true|false)`)
var reOnset = regexp.MustCompile(`^([01]?\d|2[0-3]):[0-5]\d$`)
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
	f.Onset, f.FaultKind = get("onset"), get("fault_kind")
	if m := reActive.FindStringSubmatch(text); m != nil {
		v := m[1] == "true"
		f.EventActive = &v
	}
	return &f, true
}

var reportIDRe = regexp.MustCompile(`S\d+\.E\d+`)

func isAgentCause(c string) bool {
	causes := Causes
	if agentV2() {
		causes = CausesV2
	}
	for _, cs := range causes {
		if contains(cs, c) {
			return true
		}
	}
	return false
}

func checkAgent(s SensorRef, res GenieResult, prompt string) AgentCall { return checkAgentWin(s, res, prompt, nil) }

// checkAgentWin: checkAgent plus the Track B post-rules (postrules.go, htpd_profile post_rules=, default off) on
// win, the window the prompt was built from. They run before the whitelist checks and the action derivation, so a
// corrected cause or status is what the gate checks and what the action is derived from.
// hv (optional): the deterministic HVAC rule finding on the agent's own window (post rule hvac_rule).
func checkAgentWin(s SensorRef, res GenieResult, prompt string, win []float64, hv ...*Finding) AgentCall {
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
	if on := postRules(); on != nil && len(win) > 0 {
		for _, c := range applyPostRules(on, s.Role, s.Metric, s.Node, s.End, win, &f, prompt) {
			call.Repairs = append(call.Repairs, fmt.Sprintf("post-rule %s: %s '%s' -> '%s'", c.rule, c.field, c.from, c.to))
		}
	}
	if on := postRules(); on["hvac_rule"] && s.Role == "hvac" && len(hv) > 0 && hv[0] != nil {
		for _, c := range applyHVACRule(hv[0], &f) {
			call.Repairs = append(call.Repairs, fmt.Sprintf("post-rule %s: %s '%s' -> '%s'", c.rule, c.field, c.from, c.to))
		}
	}
	call.ClaimFlags = claimFlags(s.Role, s.End, prompt, f.Observations)
	call.Parsed = &f
	pats, causes := agentPatterns(s.Role), agentCauses(s.Role) // v1 or v2 whitelists (agentversion.go)
	if !contains(pats, f.Pattern) {
		call.Errors = append(call.Errors, "unknown pattern '"+f.Pattern+"'")
	}
	if !contains([]string{"normal", "warning", "critical", "sensor_fault"}, f.Status) {
		call.Errors = append(call.Errors, "unknown status '"+f.Status+"'")
	}
	if !contains(causes, f.LikelyCause) {
		call.Errors = append(call.Errors, "cause '"+f.LikelyCause+"' not allowed for "+s.Role)
	}
	// Action is a deterministic function of (cause, status) in our taxonomy - the very mapping that
	// generated the training targets - so we always derive it instead of trusting the generated field.
	// Measured on the 54-window device set: the model's own action was right 77.8% of the time while
	// its cause was right 81.5%, i.e. it sometimes picked the wrong action from a correct cause.
	// Deriving makes action track cause exactly. The model's raw value stays in call.Raw for audit, and
	// a disagreement is recorded because it is a useful drift signal, not an error.
	if contains(causes, f.LikelyCause) {
		derived := ActionOfRole(s.Role, f.LikelyCause, f.Status)
		if f.Action != "" && f.Action != derived {
			call.Repairs = append(call.Repairs, "action '"+f.Action+"' replaced by '"+derived+"', derived from cause '"+f.LikelyCause+"'")
		} else if f.Action == "" && !trimAction() {
			// With SCE_TRIM_ACTION=1 the field is absent on purpose - generation is stopped before
			// it, because this line is about to overwrite it anyway - so its absence is not a repair.
			call.Repairs = append(call.Repairs, "action missing, derived from cause '"+f.LikelyCause+"' by policy")
		}
		f.Action = derived
	}
	if !actionAllowed(f.Action) {
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
	for id := range promptEvidenceIDs(prompt) { // v2 prompts also show E9/E10
		valid[id] = true
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
		if blocksActuation(o) {
			call.Errors = append(call.Errors, "actuation language blocked")
		}
	}
	// v2 fields are optional and never fail a finding: an invalid value is dropped and noted
	if f.FaultKind != "" {
		f.FaultKind = normEnum(f.FaultKind)
		if f.Status != "sensor_fault" || !contains(FaultKinds, f.FaultKind) {
			call.Repairs = append(call.Repairs, "fault_kind '"+f.FaultKind+"' dropped (only a known kind with status sensor_fault)")
			f.FaultKind = ""
		}
	}
	if f.Onset != "" && !reOnset.MatchString(f.Onset) {
		call.Repairs = append(call.Repairs, "onset '"+f.Onset+"' dropped (not HH:MM)")
		f.Onset = ""
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
		// 4-bit slip seen on the QIDK: the object is closed with `]` instead of `}`
		// (`..."explanation": "... [S1.E6,S2.E4]"]`), or the final `}` is simply missing. Both are
		// syntax only - every field is still validated below exactly as for a well-formed answer.
		t := strings.TrimSpace(res.Text)
		for _, cand := range []struct{ fixed, why string }{
			{strings.TrimSuffix(t, "]") + "}", "object closed with ']' instead of '}'"},
			{t + "}", "missing closing '}' added"},
		} {
			if cand.fixed == t {
				continue
			}
			if j2, ok2 := extractJSON(cand.fixed); ok2 {
				js, ok = j2, true
				rc.Repairs = append(rc.Repairs, cand.why)
				break
			}
		}
	}
	if !ok {
		rc.Errors = append(rc.Errors, "no complete JSON object in output")
		return rc
	}
	var rep Report
	js = dropNonStringSeverity(js, rc)
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
	// A domain whose own flagged sensor is warning/critical IS affected, whatever the model listed
	// (stress pass 3, INC-0114: label weather_driven, domains [weather] while power, water and air
	// quality sensors were all critical). Adding them is a fact from the rule view, not a
	// reinterpretation; label and root cause stay the model's own.
	var added []string
	for _, sr := range sensors {
		if !sr.Context && (sr.Rule.Status == "warning" || sr.Rule.Status == "critical") && okDom[sr.Role] &&
			!contains(rep.AffectedDomains, sr.Role) {
			rep.AffectedDomains = append(rep.AffectedDomains, sr.Role)
			added = append(added, sr.Role)
		}
	}
	if len(added) > 0 {
		rc.Repairs = append(rc.Repairs, "affected_domains completed with abnormal flagged domains: "+strings.Join(added, ", "))
	}
	rep.RequiresHuman = true // structural: every report needs operator approval
	// severity is optional (the prompt does not ask for it yet); a recognisable one is kept for
	// reasonerSeverity, anything else is dropped rather than failing an otherwise sound report
	if rep.Severity != "" {
		if s := normSeverity(rep.Severity); s != "" {
			rep.Severity = s
		} else {
			rc.Repairs = append(rc.Repairs, "unrecognised severity '"+rep.Severity+"' dropped")
			rep.Severity = ""
		}
	}
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
	if !actionAllowed(rep.Action) {
		rc.Errors = append(rc.Errors, "action '"+rep.Action+"' not whitelisted")
	}
	valid := map[string]bool{}
	for _, s := range sensors {
		valid[s.Ref] = true // sensor-level citation of a flagged sensor
		for _, e := range s.Evidence {
			valid[s.Ref+"."+e.ID] = true
		}
		for _, l := range s.LongRange {
			valid[s.Ref+"."+l.ID] = true
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
	if blocksActuation(rep.RootCause + " " + rep.Explanation) {
		rc.Errors = append(rc.Errors, "actuation language blocked")
	}
	if rep.Confidence < 0 || rep.Confidence > 1 {
		rc.Errors = append(rc.Errors, "confidence out of [0,1]")
	}
	rc.Valid = len(rc.Errors) == 0
	return rc
}

// dropNonStringSeverity removes a "severity" that is not a string (`"severity": 3`). Before the
// Report had a severity field such a key was simply ignored; it must not now fail the whole report
// with a JSON type error. Any other shape of output is returned unchanged.
func dropNonStringSeverity(js string, rc *ReportCall) string {
	var m map[string]json.RawMessage
	if json.Unmarshal([]byte(js), &m) != nil {
		return js
	}
	v, ok := m["severity"]
	if !ok || string(v) == "null" || (len(v) > 0 && v[0] == '"') {
		return js
	}
	delete(m, "severity")
	b, err := json.Marshal(m)
	if err != nil {
		return js
	}
	rc.Repairs = append(rc.Repairs, "non-text severity dropped")
	return string(b)
}

func trunc(s string, n int) string {
	if len(s) > n {
		return s[:n] + "..."
	}
	return s
}
