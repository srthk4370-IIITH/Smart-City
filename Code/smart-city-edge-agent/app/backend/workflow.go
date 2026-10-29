package main

// Approval lifecycle and action memory (UX v34).
//
// Spec: proofs/2026-10-23_reasoner_research/APPROVAL_AND_MEMORY.md §3 and DECISIONS.md "Approval and
// action memory", approved by the owner. One field, workflow, kept apart from severity and status:
//
//	analysing -> needs_decision -> in_progress -> resolved -> closed
//	                  |  ^              |
//	                  |  +-- got worse at a re-check (re-acknowledge) --+
//	                  +-- dismiss + note -> closed (false alarm / no action needed)
//	analysis failed -> interrupted (rerun, or dismiss with a note)
//
//   - Acknowledge ("I'm on it") records who and when and makes that person the owner. It never changes
//     severity or status: only the readings and the AI do (ISA-18.2: acknowledging is not fixing).
//   - Each recommended step is marked done or not needed (optional note); operators may add up to 5
//     steps of their own. Ticking a step acknowledges automatically.
//   - Close needs an outcome. Dismiss stays: a note is required and it closes as false alarm or
//     no action needed. The old approve endpoint = acknowledge + every step accepted ("approve all").
//   - Re-checks: worse on an acknowledged incident -> back to needs_decision and re-alert; readings back
//     to normal -> resolved with a pre-filled outcome; resolved for 24 h -> auto-closed as "resolved on
//     its own (auto)" unless the owner still has an open step; an unacknowledged critical incident
//     re-alerts once after 15 min.
//   - Every click and automatic transition appends a row to the incident's append-only event log,
//     persisted with the incident (state/incidents.jsonl).
//   - Memory: if a sensor fault comes back within 30 days of a repair, "Replace the sensor" is added.
//
// Clocks: the people-facing timers (the 15 min reminder, the 24 h auto-close, list grouping, event
// times) use the device wall clock. Sensor time runs ~150x faster in the demo (one 5-minute reading
// per 2 s poll), which would fire a 15 min reminder 6 s after an alert. The re-checks themselves stay
// in sensor time (refine.go). On a real deployment polling every 5 minutes both clocks agree.
//
// Model prompts, the policy gate and the refinement thresholds are not touched.

import (
	"bufio"
	"encoding/json"
	"fmt"
	"net/http"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
	"sync"
	"time"
)

const (
	wfAnalysing   = "analysing"
	wfNeeds       = "needs_decision"
	wfInProgress  = "in_progress"
	wfResolved    = "resolved"
	wfClosed      = "closed"
	wfInterrupted = "interrupted"

	remindAfter      = 15 * time.Minute
	autoCloseAfter   = 24 * time.Hour
	repairHoldWindow = 30 * 24 * time.Hour
	recurWindow      = 7 * 24 * time.Hour
	groupWindow      = 30 * time.Minute
	maxSuggested     = 5    // recommended steps per incident (EEMUA 191: few steps)
	maxOwnSteps      = 5    // operator-added steps per incident
	maxEvents        = 1000 // per incident; beyond this the log stops growing (a runaway client)
	maxNote          = 500
	maxStepText      = 200
	maxOperator      = 40
	liveNormalRun    = 6 // live readings back to normal in a row before an incident counts as resolved
)

// outcomes a close records (§3.3)
var outcomeText = map[string]string{
	"fixed_by_action":     "Fixed by action",
	"sensor_replaced":     "Sensor replaced",
	"sensor_repaired":     "Sensor repaired or recalibrated",
	"resolved_on_its_own": "Resolved on its own",
	"false_alarm":         "False alarm",
	"no_action_needed":    "No action needed",
}

// sensor steps: done + readings back to normal = the sensor was repaired (owner's rule)
var sensorStepActions = map[string]bool{"check_sensor": true, "recalibrate_sensor": true, "restart_or_reconnect_sensor": true}

// Step is one checklist item. The current state lives here; its history is in the event log.
type Step struct {
	ID       string `json:"id"`     // s1, s2 ...
	Source   string `json:"source"` // report | agent | rules | playbook | rule | operator
	Action   string `json:"action,omitempty"`
	Target   string `json:"target,omitempty"`
	Text     string `json:"text"`
	Why      string `json:"why,omitempty"`
	Stage    string `json:"added_at_stage,omitempty"` // early | 1.5h | 3h
	State    string `json:"state"`                    // open | done | not_needed | withdrawn
	Accepted bool   `json:"accepted,omitempty"`       // accepted with "approve all" (the legacy approve)
	New      bool   `json:"new,omitempty"`            // added by a re-check after someone acknowledged
	By       string `json:"by,omitempty"`
	At       int64  `json:"at,omitempty"`
	Note     string `json:"note,omitempty"`
}

// IncEvent is one row of an incident's append-only log (NIST AU-3: who, when, what, outcome).
type IncEvent struct {
	Seq   int    `json:"seq"`
	At    int64  `json:"at"`    // device wall clock, unix s
	Actor string `json:"actor"` // operator name | system | reasoner
	Event string `json:"event"` // created, analysed, interrupted, ack, approve_all, step_done, step_not_needed,
	//                                 step_reopened, step_added, step_withdrawn, recheck_elevated|curbed|same|resolved,
	//                                 resolved, abnormal_again, reminder, closed, dismissed, auto_closed
	StepID  string `json:"step_id,omitempty"`
	Outcome string `json:"outcome,omitempty"`
	Note    string `json:"note,omitempty"`
	Detail  string `json:"detail,omitempty"`
}

// WorkflowState is embedded in Incident (its fields are serialised inline).
type WorkflowState struct {
	Workflow       string     `json:"workflow,omitempty"`
	Owner          string     `json:"owner,omitempty"`
	AckedAt        int64      `json:"acked_at,omitempty"`    // wall unix
	NeedsSince     int64      `json:"needs_since,omitempty"` // entered needs_decision (reminder clock)
	Reminded       bool       `json:"reminded,omitempty"`
	ResolvedAt     int64      `json:"resolved_at,omitempty"`
	ResolvedSim    int64      `json:"resolved_sim,omitempty"` // sensor time the readings were back to normal
	ClosedAt       int64      `json:"closed_at,omitempty"`
	ClosedBy       string     `json:"closed_by,omitempty"`
	Outcome        string     `json:"outcome,omitempty"`
	OutcomeNote    string     `json:"outcome_note,omitempty"`
	SuggestOutcome string     `json:"suggest_outcome,omitempty"` // pre-filled close outcome
	WorseAt        int64      `json:"worse_at,omitempty"`        // last re-check that raised the severity
	LiveEpoch      int64      `json:"live_epoch,omitempty"`      // engine history the live resolve may read
	Legacy         bool       `json:"legacy_decision,omitempty"` // decided before the lifecycle existed
	Steps          []Step     `json:"steps,omitempty"`
	Events         []IncEvent `json:"events,omitempty"`
}

// wfNow is the people clock (tests replace it).
var wfNow = func() time.Time { return nowTime() }

// WfError carries the HTTP status of a refused workflow action.
type WfError struct {
	Code int
	Msg  string
}

func (e *WfError) Error() string { return e.Msg }

func wfErr(code int, f string, a ...any) error { return &WfError{code, fmt.Sprintf(f, a...)} }

// wfOf is the incident's workflow, derived for incidents stored before the field existed.
func wfOf(inc *Incident) string {
	if inc.Workflow != "" {
		return inc.Workflow
	}
	switch {
	case inc.State == "running":
		return wfAnalysing
	case inc.State == "failed" && inc.Approval != "dismissed":
		return wfInterrupted
	case inc.Approval == "approved":
		return wfInProgress
	case inc.Approval == "dismissed":
		return wfClosed
	}
	return wfNeeds
}

// migrateWorkflow fills the lifecycle of an incident stored before it existed (store load):
// approved -> in progress, dismissed -> closed (no action needed), both marked legacy.
func migrateWorkflow(inc *Incident) {
	if inc.Workflow == wfAnalysing && inc.State == "failed" {
		inc.Workflow = wfInterrupted // the process died mid-analysis (store.go turns running into failed)
	}
	if inc.Workflow != "" {
		return
	}
	inc.Workflow = wfOf(inc)
	switch inc.Workflow {
	case wfInProgress:
		inc.Legacy = true
	case wfClosed:
		inc.Legacy, inc.Outcome, inc.OutcomeNote = true, "no_action_needed", inc.ApprovalNote
	}
	if len(inc.Steps) == 0 && inc.State != "running" && inc.State != "failed" {
		for _, s := range suggestedSteps(inc) {
			s.Accepted = inc.Approval == "approved"
			addStep(inc, s)
		}
	}
}

// event appends one log row. Caller holds r.mu (or owns inc exclusively).
func (inc *Incident) event(actor, ev, step, outcome, note, detail string) {
	if len(inc.Events) >= maxEvents {
		return
	}
	inc.Events = append(inc.Events, IncEvent{Seq: len(inc.Events) + 1, At: wfNow().Unix(), Actor: actor, Event: ev,
		StepID: step, Outcome: outcome, Note: note, Detail: detail})
}

func addStep(inc *Incident, s Step) *Step {
	s.ID = fmt.Sprintf("s%d", len(inc.Steps)+1)
	if s.State == "" {
		s.State = "open"
	}
	inc.Steps = append(inc.Steps, s)
	return &inc.Steps[len(inc.Steps)-1]
}

var wfRefRe = regexp.MustCompile(`\s*\[[^\]]*\]|\s*\((?:S\d+(?:\.E\d+)?(?:,\s*)?)+\)`)

// oneLine: model text without evidence ids, first sentence, at most ~140 characters.
func oneLine(s string) string {
	s = strings.TrimSpace(wfRefRe.ReplaceAllString(s, ""))
	if i := strings.Index(s, ". "); i > 0 {
		s = s[:i+1]
	}
	if r := []rune(s); len(r) > 140 {
		s = string(r[:137]) + "..."
	}
	return s
}

func metricWord(m string) string {
	if n := nice[m]; n != "" {
		return n
	}
	return strings.ReplaceAll(m, "_", " ")
}

// suggestedSteps: the recommended checklist for the incident as analysed now: the report's action,
// then the flagged sensors' agent actions (whitelisted, de-duplicated), the rules' action when there
// is no valid AI report, and the domain playbook when the AI says only "monitor" (at most 5).
func suggestedSteps(inc *Incident) []Step {
	var out []Step
	seen := map[string]bool{}
	add := func(action, src, target, why string) {
		a := normEnum(action)
		if a == "" || a == "none" || seen[a] || !actionAllowed(a) || actionStep[a] == "" || len(out) >= maxSuggested {
			return
		}
		seen[a] = true
		out = append(out, Step{Source: src, Action: a, Target: target, Text: actionStep[a], Why: why, State: "open"})
	}
	ai := inc.Final != nil && inc.Final.Valid && inc.Final.Parsed != nil
	if ai && normSeverity(inc.Final.Parsed.Severity) != "normal" {
		add(inc.Final.Parsed.Action, "report", "", oneLine(inc.Final.Parsed.RootCause))
	}
	ff := finalFindings(inc)
	for _, s := range inc.Sensors {
		if s.Context {
			continue
		}
		for _, a := range inc.Agents {
			if a.Ref != s.Ref || !a.Valid || a.Parsed == nil || normSeverity(a.Parsed.Status) == "normal" {
				continue
			}
			add(a.Parsed.Action, "agent", s.Node, fmt.Sprintf("%s at %s: %s (%s)", metricWord(s.Metric), s.Location,
				strings.ReplaceAll(ff[s.Ref].Pattern, "_", " "), strings.ReplaceAll(ff[s.Ref].Status, "_", " ")))
		}
	}
	if !ai && normSeverity(inc.Severity) != "normal" {
		// the rules' root cause lists node ids; the operator gets the worst flagged sensor in words
		why := ""
		for _, s := range inc.Sensors {
			if !s.Context && why == "" {
				why = fmt.Sprintf("%s at %s: %s (%s)", metricWord(s.Metric), s.Location,
					strings.ReplaceAll(ff[s.Ref].Pattern, "_", " "), strings.ReplaceAll(ff[s.Ref].Status, "_", " "))
			}
		}
		add(inc.Mode1.Action, "rules", "", why)
	}
	if len(out) == 1 && out[0].Action == "monitor" {
		out = nil // "monitor" alone is no guidance for an abnormal incident: the playbook speaks instead
	}
	level := normSeverity(inc.Severity)
	if len(out) == 0 && (level == "warning" || level == "critical" || level == "sensor_fault") && len(inc.Roles) > 0 {
		list, why := faultPlaybook, "Standard steps for a faulty sensor (no specific AI recommendation)"
		if level != "sensor_fault" {
			list = healthPlaybook[inc.Roles[0]][level]
			why = fmt.Sprintf("Standard steps for a %s %s alarm (no specific AI recommendation)", level, strings.ReplaceAll(inc.Roles[0], "_", " "))
		}
		for _, t := range list {
			if len(out) < maxSuggested {
				out = append(out, Step{Source: "playbook", Text: t, Why: why, State: "open"})
			}
		}
	}
	return out
}

func stepKey(s Step) string {
	if s.Action != "" {
		return "a:" + s.Action
	}
	return "t:" + s.Text
}

// mergeSteps brings the checklist up to date with a (re-)analysis. Ticked steps are kept; open steps
// that are no longer suggested are withdrawn ("no longer suggested"); new ones are added, marked new
// when someone had already acknowledged. Operator and rule steps are never withdrawn. Caller holds r.mu.
// Stage "preliminary" builds the checklist from the preliminary report (quietly: it is replaced within a minute);
// the AI report's "early" merge after it is logged like a re-check, so ticked steps stay and dropped ones are withdrawn.
func mergeSteps(inc *Incident, stage string) {
	cands := suggestedSteps(inc)
	prelim := false
	for _, s := range inc.Steps {
		prelim = prelim || s.Stage == "preliminary"
	}
	quiet := stage == "preliminary" || (stage == "early" && !prelim)
	what := "the " + stageText(stage) + " re-check"
	if stage == "early" {
		what = "the AI report"
	}
	want := map[string]bool{}
	cand := map[string]Step{}
	for _, c := range cands {
		want[stepKey(c)] = true
		cand[stepKey(c)] = c
	}
	have := map[string]bool{}
	for i := range inc.Steps {
		s := &inc.Steps[i]
		have[stepKey(*s)] = true
		if s.Source == "operator" || s.Source == "rule" {
			continue
		}
		switch {
		case !want[stepKey(*s)] && s.State == "open":
			s.State = "withdrawn"
			if stage != "preliminary" {
				inc.event("system", "step_withdrawn", s.ID, "", "", "no longer suggested after "+what)
			}
		case want[stepKey(*s)] && s.State == "withdrawn":
			s.State = "open"
		}
		if c, ok := cand[stepKey(*s)]; ok && s.Stage == "preliminary" && stage != "preliminary" {
			s.Stage, s.Source, s.Why, s.Target = stage, c.Source, c.Why, c.Target // confirmed by the AI report
		}
	}
	for _, c := range cands {
		if have[stepKey(c)] {
			continue
		}
		c.Stage, c.New = stage, inc.Owner != "" && !quiet
		s := addStep(inc, c)
		if !quiet {
			inc.event("system", "step_added", s.ID, "", "", "suggested by "+what)
		}
	}
}

// openSteps counts steps still to do (withdrawn ones are not).
func openSteps(inc *Incident) int {
	n := 0
	for _, s := range inc.Steps {
		if s.State == "open" {
			n++
		}
	}
	return n
}

// suggestOutcome pre-fills the close outcome from what happened (§3.3).
func suggestOutcome(inc *Incident) string {
	normal := wfOf(inc) == wfResolved
	replaced, sensor, other := false, false, false
	for _, s := range inc.Steps {
		if s.State != "done" {
			continue
		}
		switch {
		case s.Action == "replace_sensor":
			replaced = true
		case sensorStepActions[s.Action]:
			sensor = true
		default:
			other = true
		}
	}
	switch {
	case replaced:
		return "sensor_replaced"
	case normal && sensor:
		return "sensor_repaired"
	case normal && other:
		return "fixed_by_action"
	case normal:
		return "resolved_on_its_own"
	case normSeverity(inc.Severity) == "normal":
		return "no_action_needed"
	}
	return ""
}

// ---- transitions driven by the analysis --------------------------------------------------------

// wfCreated: a new incident is being analysed. Caller holds r.mu.
func wfCreated(inc *Incident) {
	inc.Workflow = wfAnalysing
	inc.event("system", "created", "", "", "", fmt.Sprintf("%d sensor(s) flagged", len(inc.Sensors)))
}

// wfAnalysedLocked: the first analysis finished; the incident waits for a person. Caller holds r.mu.
func (r *Reasoner) wfAnalysedLocked(inc *Incident, epoch int64) {
	if inc.LiveEpoch == 0 {
		inc.LiveEpoch = epoch
	}
	if inc.State == "failed" {
		inc.Workflow = wfInterrupted
		inc.event("system", "interrupted", "", "", "", "the analysis did not finish")
		return
	}
	mergeSteps(inc, "early")
	r.repairRuleLocked(inc)
	if inc.Workflow == wfAnalysing || inc.Workflow == "" {
		inc.Workflow, inc.NeedsSince = wfNeeds, wfNow().Unix()
	}
	inc.SuggestOutcome = suggestOutcome(inc)
	inc.event("reasoner", "analysed", "", "", "", "severity "+sevWord(inc.Severity))
}

// wfAfterRecheckLocked applies a 1.5 h / 3 h re-check (§3.4) and returns extra fields for the SSE
// "incident" event. A closed incident is history: the re-check is logged, nothing reopens it.
// Caller holds r.mu.
func (r *Reasoner) wfAfterRecheckLocked(inc *Incident, prevSev string, rev Revision) map[string]any {
	ev := map[string]any{}
	a, b := reportRank[normSeverity(prevSev)], reportRank[normSeverity(inc.Severity)]
	normal := len(rev.Sensors) > 0
	for _, s := range rev.Sensors {
		if normSeverity(s.Status) != "normal" {
			normal = false
		}
	}
	wf := wfOf(inc)
	detail := fmt.Sprintf("%s -> %s", sevWord(prevSev), sevWord(inc.Severity))
	if wf == wfClosed {
		inc.event("reasoner", "recheck_after_close", "", "", "", stageText(rev.Stage)+" re-check: "+detail)
		return ev
	}
	switch { // the re-check is logged first, then the checklist follows it
	case b > a:
		inc.event("reasoner", "recheck_elevated", "", "", "", stageText(rev.Stage)+" re-check: "+detail)
		inc.WorseAt = wfNow().Unix()
		if inc.Owner != "" && (wf == wfInProgress || wf == wfResolved) {
			ev["reack"] = true // "Got worse since you acknowledged: please re-acknowledge"
		}
		if wf == wfInProgress || wf == wfResolved {
			inc.Workflow, inc.NeedsSince, inc.Reminded, inc.ResolvedAt, inc.ResolvedSim = wfNeeds, wfNow().Unix(), false, 0, 0
		}
	case normal && wf != wfResolved:
		inc.event("reasoner", "recheck_resolved", "", "", "", stageText(rev.Stage)+" re-check: readings back to normal")
		r.resolveLocked(inc, rev.SimEnd, "back to normal at the "+stageText(rev.Stage)+" re-check")
		ev["workflow_change"] = "resolved"
	case b < a:
		inc.event("reasoner", "recheck_curbed", "", "", "", stageText(rev.Stage)+" re-check: "+detail)
	default:
		inc.event("reasoner", "recheck_same", "", "", "", stageText(rev.Stage)+" re-check: no change")
	}
	mergeSteps(inc, rev.Stage)
	r.repairRuleLocked(inc)
	inc.SuggestOutcome = suggestOutcome(inc)
	ev["workflow"] = inc.Workflow
	return ev
}

func (r *Reasoner) resolveLocked(inc *Incident, sim int64, why string) {
	inc.Workflow, inc.ResolvedAt, inc.ResolvedSim = wfResolved, wfNow().Unix(), sim
	inc.SuggestOutcome = suggestOutcome(inc)
	inc.event("system", "resolved", "", inc.SuggestOutcome, "", why)
}

// repairRuleLocked: a sensor fault within 30 days of a repair of the same sensor gets the step
// "Replace the sensor" (deterministic safety net; DECISIONS.md "Memory"). Caller holds r.mu.
func (r *Reasoner) repairRuleLocked(inc *Incident) {
	for _, s := range inc.Steps {
		if s.Action == "replace_sensor" {
			return
		}
	}
	ff := finalFindings(inc)
	now := wfNow()
	for _, s := range inc.Sensors {
		if s.Context {
			continue
		}
		if normSeverity(ff[s.Ref].Status) != "sensor_fault" && normSeverity(s.Rule.Status) != "sensor_fault" && normSeverity(inc.Severity) != "sensor_fault" {
			continue
		}
		if at, id := r.lastRepairLocked(s.Node, s.Metric, inc.ID); at > 0 && now.Sub(time.Unix(at, 0)) <= repairHoldWindow {
			st := addStep(inc, Step{Source: "rule", Action: "replace_sensor", Target: s.Node,
				Text:  "Replace the " + metricWord(s.Metric) + " sensor at " + s.Location + " (the earlier repair did not hold)",
				Why:   fmt.Sprintf("Repaired on %s (%s); the fault came back within 30 days", time.Unix(at, 0).In(IST).Format("02 Jan"), id),
				Stage: inc.RefineStage, New: inc.Owner != ""})
			inc.event("system", "step_added", st.ID, "", "", "30-day repair rule: "+st.Why)
			return
		}
	}
}

// lastRepairLocked: the newest repair of a sensor in another incident: closed as repaired, or a
// sensor step done on an incident whose readings then returned to normal. Caller holds r.mu.
func (r *Reasoner) lastRepairLocked(node, metric, skip string) (int64, string) {
	var at int64
	id := ""
	for _, o := range r.incidents {
		if o.ID == skip || !flags(o, node, metric) {
			continue
		}
		if o.Outcome == "sensor_repaired" && o.ClosedAt > at {
			at, id = o.ClosedAt, o.ID
		}
		if w := wfOf(o); w == wfResolved || (w == wfClosed && o.Outcome != "false_alarm" && o.Outcome != "sensor_replaced") {
			for _, s := range o.Steps {
				if s.State == "done" && sensorStepActions[s.Action] && s.At > at {
					at, id = s.At, o.ID
				}
			}
		}
	}
	return at, id
}

// flags: the incident flagged this sensor (not only checked it for context).
func flags(inc *Incident, node, metric string) bool {
	for _, s := range inc.Sensors {
		if !s.Context && s.Node == node && s.Metric == metric {
			return true
		}
	}
	return false
}

// ---- operator actions ---------------------------------------------------------------------------

// cleanOperator validates the name picked on the device (no password: accountability, not security).
func cleanOperator(op string) (string, error) {
	op = strings.Join(strings.Fields(op), " ")
	if op == "" {
		return "", wfErr(400, "choose who you are first (operator name)")
	}
	if len([]rune(op)) > maxOperator {
		return "", wfErr(400, "operator name too long (max %d characters)", maxOperator)
	}
	return op, nil
}

// mutate runs f on one incident under the lock, then persists it and tells the dashboard.
func (r *Reasoner) mutate(id string, f func(inc *Incident) error) (*Incident, error) {
	r.mu.Lock()
	var inc *Incident
	for _, i := range r.incidents {
		if i.ID == id {
			inc = i
		}
	}
	if inc == nil {
		r.mu.Unlock()
		return nil, wfErr(404, "not found")
	}
	if err := f(inc); err != nil {
		r.mu.Unlock()
		return nil, err
	}
	ev := map[string]any{"id": inc.ID, "state": inc.State, "approval": inc.Approval, "workflow": inc.Workflow}
	r.mu.Unlock()
	r.persist(inc)
	r.notify("incident", ev)
	return inc, nil
}

// decidableEarly: acknowledge, tick and add steps are allowed while the reasoner writes, once the preliminary report
// is shown (owner 2026-10-29: act on the preliminary checklist; the AI report then merges into it). Close, dismiss and
// approve-all still wait for the AI report.
func decidableEarly(inc *Incident) error {
	if inc.State == "running" && inc.Final != nil && inc.Final.Preliminary && inc.Final.Parsed != nil && wfOf(inc) != wfClosed {
		return nil
	}
	return decidable(inc, false)
}

// decidable: the shared refusals of every decision (the report must exist and the record be open).
func decidable(inc *Incident, allowFailed bool) error {
	switch {
	case inc.State == "running":
		return wfErr(409, "analysis still running - decide once the report is ready")
	case inc.State == "failed" && !allowFailed:
		return wfErr(409, "this analysis was interrupted and has no report - rerun it first (dismiss is allowed)")
	case wfOf(inc) == wfClosed:
		return wfErr(409, "this incident is closed; a recurrence opens a new incident")
	}
	return nil
}

func ackLocked(inc *Incident, op, how string) {
	inc.Workflow = wfOf(inc)
	if inc.Workflow == wfNeeds || inc.Workflow == wfAnalysing || inc.Workflow == "" {
		inc.Workflow = wfInProgress
	}
	inc.Owner, inc.AckedAt = op, wfNow().Unix()
	inc.event(op, "ack", "", "", "", how)
}

// Ack: "I'm on it". Severity and status are left alone.
func (r *Reasoner) Ack(id, op string) (*Incident, error) {
	op, err := cleanOperator(op)
	if err != nil {
		return nil, err
	}
	return r.mutate(id, func(inc *Incident) error {
		if err := decidableEarly(inc); err != nil {
			return err
		}
		ackLocked(inc, op, "")
		return nil
	})
}

// ApproveAll is the legacy approve: acknowledge and accept every open step (logged as approve_all).
func (r *Reasoner) ApproveAll(id, op, note string) (*Incident, error) {
	if strings.TrimSpace(op) == "" {
		op = "operator"
	}
	op, err := cleanOperator(op)
	if err != nil {
		return nil, err
	}
	return r.mutate(id, func(inc *Incident) error {
		if err := decidable(inc, false); err != nil {
			return err
		}
		inc.Approval, inc.ApprovalNote = "approved", note
		if inc.Owner != op || wfOf(inc) == wfNeeds {
			ackLocked(inc, op, "approve")
		}
		n := 0
		for i := range inc.Steps {
			if inc.Steps[i].State == "open" && !inc.Steps[i].Accepted {
				inc.Steps[i].Accepted = true
				n++
			}
		}
		inc.event(op, "approve_all", "", "", note, fmt.Sprintf("%d step(s) accepted", n))
		return nil
	})
}

// SetStep marks one step done, not needed, or open again. Ticking acknowledges automatically.
func (r *Reasoner) SetStep(id, sid, op, state, note string) (*Incident, error) {
	op, err := cleanOperator(op)
	if err != nil {
		return nil, err
	}
	if state != "done" && state != "not_needed" && state != "open" {
		return nil, wfErr(400, "state must be done, not_needed or open")
	}
	if len(note) > maxNote {
		return nil, wfErr(400, "note too long (max %d characters)", maxNote)
	}
	return r.mutate(id, func(inc *Incident) error {
		if err := decidableEarly(inc); err != nil {
			return err
		}
		var s *Step
		for i := range inc.Steps {
			if inc.Steps[i].ID == sid {
				s = &inc.Steps[i]
			}
		}
		if s == nil {
			return wfErr(404, "no step %s", sid)
		}
		if wfOf(inc) == wfNeeds && state != "open" {
			ackLocked(inc, op, "by ticking a step")
		}
		s.State, s.By, s.At, s.Note = state, op, wfNow().Unix(), strings.TrimSpace(note)
		ev := map[string]string{"done": "step_done", "not_needed": "step_not_needed", "open": "step_reopened"}[state]
		inc.event(op, ev, s.ID, "", s.Note, s.Text)
		inc.SuggestOutcome = suggestOutcome(inc)
		return nil
	})
}

// AddStep: the operator's own step ("approve with changes": mark the AI's step not needed, add yours).
func (r *Reasoner) AddStep(id, op, text string) (*Incident, error) {
	op, err := cleanOperator(op)
	if err != nil {
		return nil, err
	}
	text = strings.Join(strings.Fields(text), " ")
	if text == "" {
		return nil, wfErr(400, "describe the step")
	}
	if len([]rune(text)) > maxStepText {
		return nil, wfErr(400, "step too long (max %d characters)", maxStepText)
	}
	return r.mutate(id, func(inc *Incident) error {
		if err := decidableEarly(inc); err != nil {
			return err
		}
		own := 0
		for _, s := range inc.Steps {
			if s.Source == "operator" {
				own++
			}
		}
		if own >= maxOwnSteps {
			return wfErr(409, "at most %d steps of your own per incident", maxOwnSteps)
		}
		if wfOf(inc) == wfNeeds {
			ackLocked(inc, op, "by adding a step")
		}
		s := addStep(inc, Step{Source: "operator", Text: text, Stage: inc.RefineStage, By: op, At: wfNow().Unix()})
		inc.event(op, "step_added", s.ID, "", "", text)
		return nil
	})
}

// Close records the outcome; the record is final from here (a recurrence opens a new incident).
// dismiss = the old Dismiss: a note is required and the outcome is false_alarm or no_action_needed.
func (r *Reasoner) Close(id, op, outcome, note string, dismiss bool) (*Incident, error) {
	if dismiss && strings.TrimSpace(op) == "" {
		op = "operator"
	}
	op, err := cleanOperator(op)
	if err != nil {
		return nil, err
	}
	note = strings.TrimSpace(note)
	if len(note) > maxNote {
		return nil, wfErr(400, "note too long (max %d characters)", maxNote)
	}
	if dismiss && outcome == "" {
		outcome = "no_action_needed"
	}
	if outcomeText[outcome] == "" {
		return nil, wfErr(400, "outcome must be one of fixed_by_action, sensor_replaced, sensor_repaired, resolved_on_its_own, false_alarm, no_action_needed")
	}
	if dismiss && outcome != "false_alarm" && outcome != "no_action_needed" {
		return nil, wfErr(400, "dismiss closes as false_alarm or no_action_needed")
	}
	if (outcome == "false_alarm" || outcome == "no_action_needed") && note == "" {
		if dismiss {
			return nil, wfErr(400, "dismiss needs a note")
		}
		return nil, wfErr(400, "a note is required for %s", strings.ToLower(outcomeText[outcome]))
	}
	return r.mutate(id, func(inc *Incident) error {
		if err := decidable(inc, dismiss || outcome == "false_alarm" || outcome == "no_action_needed"); err != nil {
			return err
		}
		inc.Workflow, inc.Outcome, inc.OutcomeNote, inc.ClosedAt, inc.ClosedBy = wfClosed, outcome, note, wfNow().Unix(), op
		if outcome == "false_alarm" || outcome == "no_action_needed" {
			inc.Approval, inc.ApprovalNote = "dismissed", note
		} else if inc.Approval == "" || inc.Approval == "pending" {
			inc.Approval = "approved"
		}
		ev := "closed"
		if dismiss {
			ev = "dismissed"
		}
		inc.event(op, ev, "", outcome, note, outcomeText[outcome])
		return nil
	})
}

// ---- the periodic pass (main.go onTick) ---------------------------------------------------------

// WorkflowTick runs the people timers and the live return-to-normal check once per engine poll.
func (r *Reasoner) WorkflowTick(sim int64, states []SensorState) {
	var epoch int64
	if r.eng != nil {
		epoch, _, _ = r.eng.SimBase()
	}
	r.workflowTick(sim, epoch, states)
}

func (r *Reasoner) workflowTick(sim, epoch int64, states []SensorState) {
	live := make(map[string]*SensorState, len(states))
	for i := range states {
		live[key(states[i].Node, states[i].Metric)] = &states[i]
	}
	now := wfNow()
	type out struct {
		inc *Incident
		ev  map[string]any
	}
	var changed []out
	r.mu.Lock()
	for _, inc := range r.incidents {
		wf := wfOf(inc)
		if wf == wfClosed || wf == wfAnalysing || wf == wfInterrupted || inc.State == "running" {
			continue
		}
		ev := map[string]any{}
		// an unacknowledged critical incident re-alerts once after 15 min (sound + Android notification)
		if wf == wfNeeds && !inc.Reminded && normSeverity(inc.Severity) == "critical" && inc.NeedsSince > 0 &&
			now.Sub(time.Unix(inc.NeedsSince, 0)) >= remindAfter {
			inc.Reminded = true
			inc.event("system", "reminder", "", "", "", "critical and not acknowledged for 15 min")
			ev["change"] = "reminder"
		}
		// live return to normal (ISA-18.2 "return to normal"; resolved while unacknowledged stays visible)
		if inc.LiveEpoch != 0 && inc.LiveEpoch == epoch {
			n, normal, abnormal := 0, 0, false
			for _, s := range inc.Sensors {
				if s.Context {
					continue
				}
				n++
				st := live[key(s.Node, s.Metric)]
				if st == nil || st.Quality == "maintenance" {
					continue
				}
				if st.Status == "normal" && st.normalRun >= liveNormalRun {
					normal++
				}
				if reportRank[normSeverity(st.Status)] > 0 && st.AbnormalFor > 0 {
					abnormal = true
				}
			}
			switch {
			case wf != wfResolved && n > 0 && normal == n:
				r.resolveLocked(inc, sim, "readings back to normal (live)")
				ev["workflow_change"] = "resolved"
			case wf == wfResolved && abnormal && inc.ResolvedSim != 0 && sim > inc.ResolvedSim:
				inc.Workflow, inc.ResolvedAt, inc.ResolvedSim = wfNeeds, 0, 0
				if inc.Owner != "" {
					inc.Workflow = wfInProgress
				} else {
					inc.NeedsSince = now.Unix()
				}
				inc.SuggestOutcome = suggestOutcome(inc)
				inc.event("system", "abnormal_again", "", "", "", "a flagged reading is abnormal again")
				ev["workflow_change"] = "abnormal_again"
			}
		}
		// resolved for 24 h: auto-close, unless the owner still has a step open
		if wfOf(inc) == wfResolved && inc.ResolvedAt > 0 && now.Sub(time.Unix(inc.ResolvedAt, 0)) >= autoCloseAfter &&
			!(inc.Owner != "" && openSteps(inc) > 0) {
			// the pre-filled outcome when the owner did steps (fixed by action, repaired ...), else resolved on its own
			out := suggestOutcome(inc)
			if out == "" || out == "no_action_needed" {
				out = "resolved_on_its_own"
			}
			inc.Workflow, inc.Outcome, inc.OutcomeNote, inc.ClosedAt, inc.ClosedBy = wfClosed, out, "auto", now.Unix(), "system"
			if inc.Approval == "" || inc.Approval == "pending" {
				inc.Approval = "approved"
			}
			inc.event("system", "auto_closed", "", out, "auto", "back to normal for 24 h")
			ev["workflow_change"] = "auto_closed"
		}
		if len(ev) > 0 {
			ev["id"], ev["state"], ev["workflow"], ev["approval"] = inc.ID, inc.State, inc.Workflow, inc.Approval
			changed = append(changed, out{inc, ev})
		}
	}
	r.mu.Unlock()
	for _, c := range changed {
		r.persist(c.inc)
		r.notify("incident", c.ev)
	}
}

// ---- grouping (list view) -----------------------------------------------------------------------

// GroupInfo: the incident list collapses repeats into one card. Lead is the newest member.
type GroupInfo struct {
	Lead string
	Size int
}

func wallOf(inc *Incident) time.Time {
	t, err := time.ParseInLocation("2006-01-02 15:04:05", inc.CreatedWall, IST)
	if err != nil {
		return time.Time{}
	}
	return t
}

// groupKeys: the flagged sensors, and each flagged sensor's domain + pattern.
func groupKeys(inc *Incident) []string {
	var ks []string
	for _, s := range inc.Sensors {
		if s.Context {
			continue
		}
		ks = append(ks, "s:"+s.Node+"|"+s.Metric)
		if p := s.Rule.Pattern; p != "" && p != "-" && p != "stable" {
			ks = append(ks, "p:"+s.Role+"|"+p)
		}
	}
	return ks
}

// groupIncidents: repeat incidents on the same sensor, or the same domain and pattern, created within
// 30 minutes of each other (device clock) form one group. list is newest first (Reasoner.List).
func groupIncidents(list []*Incident) map[string]GroupInfo {
	type grp struct {
		lead    string
		members []string
		keys    map[string]bool
		oldest  time.Time
	}
	var groups []*grp
	of := map[string]*grp{}
	for _, inc := range list {
		t, ks := wallOf(inc), groupKeys(inc)
		var g *grp
		if !t.IsZero() {
			for _, c := range groups {
				d := c.oldest.Sub(t)
				if d < 0 {
					d = -d
				}
				if d > groupWindow {
					continue
				}
				for _, k := range ks {
					if c.keys[k] {
						g = c
						break
					}
				}
				if g != nil {
					break
				}
			}
		}
		if g == nil {
			g = &grp{lead: inc.ID, keys: map[string]bool{}}
			groups = append(groups, g)
		}
		g.members = append(g.members, inc.ID)
		for _, k := range ks {
			g.keys[k] = true
		}
		if !t.IsZero() {
			g.oldest = t
		}
		of[inc.ID] = g
	}
	out := make(map[string]GroupInfo, len(of))
	for id, g := range of {
		out[id] = GroupInfo{Lead: g.lead, Size: len(g.members)}
	}
	return out
}

// ---- memory: history of a sensor, maintenance rows ----------------------------------------------

// MaintRow is one maintenance action from the sensor sheet (out of service, back in service, replaced).
type MaintRow struct {
	At       int64  `json:"at"` // wall unix
	Node     string `json:"node"`
	Metric   string `json:"metric,omitempty"` // "" = every metric of the node
	Kind     string `json:"kind"`             // out_of_service | back_in_service | replaced
	Minutes  int    `json:"minutes,omitempty"`
	Reason   string `json:"reason,omitempty"`
	Operator string `json:"operator,omitempty"`
}

var maintMu sync.Mutex

func (r *Reasoner) maintPath() string {
	return filepath.Join(filepath.Dir(r.store), "maintenance.jsonl")
}

// LogMaintenance appends one row (append-only file next to the incident store).
func (r *Reasoner) LogMaintenance(m MaintRow) {
	if m.At == 0 {
		m.At = wfNow().Unix()
	}
	b, err := json.Marshal(m)
	if err != nil {
		return
	}
	maintMu.Lock()
	defer maintMu.Unlock()
	if f, err := os.OpenFile(r.maintPath(), os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o644); err == nil {
		f.Write(append(b, '\n'))
		f.Close()
	}
}

// Maintenance reads the rows for one sensor (metric "" rows apply to every metric of the node).
func (r *Reasoner) Maintenance(node, metric string) []MaintRow {
	maintMu.Lock()
	defer maintMu.Unlock()
	f, err := os.Open(r.maintPath())
	if err != nil {
		return nil
	}
	defer f.Close()
	var out []MaintRow
	sc := bufio.NewScanner(f)
	sc.Buffer(make([]byte, 0, 4096), 1<<20)
	for sc.Scan() {
		var m MaintRow
		if json.Unmarshal(sc.Bytes(), &m) != nil || m.Node != node || (m.Metric != "" && m.Metric != metric) {
			continue
		}
		out = append(out, m)
	}
	sort.SliceStable(out, func(i, j int) bool { return out[i].At > out[j].At })
	if len(out) > 20 {
		out = out[:20]
	}
	return out
}

// HistItem is one past incident on a sensor, with what was done and how it ended.
type HistItem struct {
	ID          string `json:"id"`
	CreatedWall string `json:"created_wall"`
	Title       string `json:"title"`
	Severity    string `json:"severity"`
	Workflow    string `json:"workflow"`
	Owner       string `json:"owner,omitempty"`
	Outcome     string `json:"outcome,omitempty"`
	OutcomeNote string `json:"outcome_note,omitempty"`
	ClosedBy    string `json:"closed_by,omitempty"`
	ClosedAt    int64  `json:"closed_at,omitempty"`
	Steps       []Step `json:"steps,omitempty"` // done / not needed only
	Recurred    string `json:"recurred_by,omitempty"`
	Legacy      bool   `json:"legacy_decision,omitempty"`
}

type SensorHist struct {
	Node        string     `json:"node"`
	Metric      string     `json:"metric"`
	Location    string     `json:"location"`
	Incidents   []HistItem `json:"incidents"`
	Maintenance []MaintRow `json:"maintenance"`
}

// History lists, per flagged sensor of an incident, the earlier incidents on that sensor (newest
// first, at most 10) and its maintenance rows. A closed incident followed by another on the same
// sensor within 7 days is marked recurred (the label that says whether the action worked, §3.3).
func (r *Reasoner) History(id string) ([]SensorHist, error) {
	r.mu.RLock()
	var inc *Incident
	for _, i := range r.incidents {
		if i.ID == id {
			inc = i
		}
	}
	if inc == nil {
		r.mu.RUnlock()
		return nil, wfErr(404, "not found")
	}
	var out []SensorHist
	for _, s := range inc.Sensors {
		if s.Context {
			continue
		}
		h := SensorHist{Node: s.Node, Metric: s.Metric, Location: s.Location, Incidents: []HistItem{}}
		var same []*Incident
		for _, o := range r.incidents {
			if flags(o, s.Node, s.Metric) {
				same = append(same, o)
			}
		}
		sort.Slice(same, func(i, j int) bool { return incNum(same[i].ID) > incNum(same[j].ID) })
		for k, o := range same {
			if incNum(o.ID) >= incNum(inc.ID) || len(h.Incidents) >= 10 {
				continue
			}
			it := HistItem{ID: o.ID, CreatedWall: o.CreatedWall, Title: o.Title, Severity: normSeverity(o.Severity), Workflow: wfOf(o),
				Owner: o.Owner, Outcome: o.Outcome, OutcomeNote: o.OutcomeNote, ClosedBy: o.ClosedBy, ClosedAt: o.ClosedAt, Legacy: o.Legacy}
			for _, st := range o.Steps {
				if st.State == "done" || st.State == "not_needed" {
					it.Steps = append(it.Steps, st)
				}
			}
			if o.ClosedAt > 0 && k > 0 { // the next newer incident on this sensor
				nx := same[k-1]
				if t := wallOf(nx); !t.IsZero() && t.Unix() >= o.ClosedAt && t.Sub(time.Unix(o.ClosedAt, 0)) <= recurWindow {
					it.Recurred = nx.ID
				}
			}
			h.Incidents = append(h.Incidents, it)
		}
		out = append(out, h)
	}
	r.mu.RUnlock()
	for i := range out {
		out[i].Maintenance = r.Maintenance(out[i].Node, out[i].Metric)
		if out[i].Maintenance == nil {
			out[i].Maintenance = []MaintRow{}
		}
	}
	return out, nil
}

// ---- small API helpers (server.go) --------------------------------------------------------------

// Groups computes the list grouping under the read lock.
func (r *Reasoner) Groups(list []*Incident) map[string]GroupInfo {
	r.mu.RLock()
	defer r.mu.RUnlock()
	return groupIncidents(list)
}

// Snapshot is one incident as JSON, marshalled under the read lock (operator clicks and the workflow
// tick change incidents concurrently).
func (r *Reasoner) Snapshot(id string) json.RawMessage {
	r.mu.RLock()
	defer r.mu.RUnlock()
	for _, i := range r.incidents {
		if i.ID == id {
			if b, err := json.Marshal(i); err == nil {
				return b
			}
		}
	}
	return json.RawMessage("null")
}

func wfHTTPError(w http.ResponseWriter, err error) {
	code := 400
	if we, ok := err.(*WfError); ok {
		code = we.Code
	}
	http.Error(w, err.Error(), code)
}
