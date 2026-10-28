package main

// Three-mode reasoning over gated anomaly events.
//   Mode 1 Rules       : Mode-1 rule findings + rule-based cross-domain summary. No LLM.
//   Mode 2 Single-SLM  : ONE NPU call: all flagged sensors' evidence in one prompt -> cross-domain report.
//   Mode 3 Multi-Agent : one NPU call per flagged sensor (domain agent, fine-tuned bundle if deployed)
//                        -> DomainFinding JSON, then one NPU synthesizer call -> cross-domain report.
// Mode 1 always runs as a shadow baseline. Every LLM output passes the PolicyGate.

import (
	"context"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
	"sync"
	"time"
	"unicode/utf8"
)

var ReportLabels = []string{"ventilation_issue", "hvac_or_thermal_issue", "occupancy_driven_load", "air_pollution_event",
	"water_leak_or_overuse", "water_supply_issue", "water_quality_issue", "power_load_anomaly", "power_quality_issue",
	"weather_driven", "sensor_fault", "normal_operation", "unknown"}

type Report struct {
	RootCause       string   `json:"root_cause"`
	Label           string   `json:"label"`
	AffectedDomains []string `json:"affected_domains"`
	Evidence        []string `json:"evidence"`
	Confidence      float64  `json:"confidence"`
	Action          string   `json:"action"`
	Explanation     string   `json:"explanation"`
	RequiresHuman   bool     `json:"requires_human_approval"`
	// critical | warning | normal (shown as "fine") | sensor_fault, decided by the cross-domain
	// reasoner (severity.go), not by the rule that opened the incident
	Severity string `json:"severity"`
	// optional headline written by the reasoner; title.go builds one from the findings otherwise
	Title string `json:"title,omitempty"`
	// reasoner v3 (reasoner_v3.go, SPEC §3); absent on synthesizer / rule reports
	CausalChain    string            `json:"causal_chain,omitempty"`
	Observations   []V3Observation   `json:"observations,omitempty"`
	AgentChecks    []V3AgentCheck    `json:"agent_checks,omitempty"`
	Checklist      []V3ChecklistItem `json:"checklist,omitempty"`
	SuspectSensors []string          `json:"suspect_sensors,omitempty"`
	MonitorNext    string            `json:"monitor_next,omitempty"`
	NeedsMoreData  bool              `json:"needs_more_data,omitempty"`
	NeedsDeeper    bool              `json:"needs_deeper,omitempty"`
	// source badge: who wrote this report, e.g. "device:qwen3.5-4b (htpd)" or "device:rules (reasoner output rejected)"
	Source        string         `json:"source,omitempty"`
	Escalation    *V3Escalation  `json:"escalation,omitempty"`     // deterministic offer only; nothing is sent
	SeverityBasis *SeverityBasis `json:"severity_basis,omitempty"` // reasoner v3: rule anchor vs reasoner (severityGuard)
}

type SensorRef struct {
	Ref      string     `json:"ref"` // S1, S2 ...
	Node     string     `json:"node"`
	Metric   string     `json:"metric"`
	Role     string     `json:"role"`
	Location string     `json:"location"`
	End      int64      `json:"window_end"`
	Injected bool       `json:"injected"`
	Xs       []float64  `json:"window"`
	Evidence []Evidence `json:"evidence"`
	GlobalEv []string   `json:"global_evidence_ids"`
	Rule     Finding    `json:"rule_finding"`
	Context  bool       `json:"context"` // pulled in by the cross-domain orchestrator (not flagged itself)
	Why      string     `json:"why,omitempty"`
	// 12 h checks for what the 4 h agent misses (longrange.go): flagged sensors only, cited as E9/E10
	LongRange []LongRange `json:"long_range,omitempty"`
	// v2 agent only (agentversion.go): the agent's window length (0 = the 4 h alert window; the
	// refinement ladder sets 48/96/144) and the 12 h history its prompt is built from (not stored)
	WinN int       `json:"win_n,omitempty"`
	Hist []float64 `json:"-"`
}

type CallMetrics struct {
	TTFTMs       float64 `json:"ttft_ms"`
	GenTokens    int     `json:"gen_tokens"`
	TokensPerS   float64 `json:"tokens_per_s"`
	EarlyStopped bool    `json:"early_stopped"`
}

func metricsOf(r GenieResult) CallMetrics {
	return CallMetrics{r.TTFTMs, r.GenTokens, r.TokensPerS, r.EarlyStopped}
}

type AgentCall struct {
	CallMetrics
	Ref       string   `json:"ref"`
	Role      string   `json:"role"`
	Model     string   `json:"model"`
	FineTuned bool     `json:"fine_tuned"`
	LatencyMs float64  `json:"latency_ms"`
	Raw       string   `json:"raw"`
	Parsed    *Finding `json:"parsed"`
	Valid     bool     `json:"valid"`
	Errors    []string `json:"errors"`
	Repairs   []string `json:"repairs,omitempty"`
	Prompt    string   `json:"prompt"`
	// claim verifier (claimcheck.go): observation claims that contradict the window's own facts. Flags only - the
	// observation text is never changed; the reasoner owns operator-facing wording.
	ClaimFlags []ClaimFlag `json:"claim_flags,omitempty"`
}

type ReportCall struct {
	CallMetrics
	Model     string   `json:"model"`
	LatencyMs float64  `json:"latency_ms"`
	Raw       string   `json:"raw"`
	Parsed    *Report  `json:"parsed"`
	Valid     bool     `json:"valid"`
	Repairs   []string `json:"repairs,omitempty"`
	Errors    []string `json:"errors"`
	Prompt    string   `json:"prompt"`
	// two-stage report (owner, 2026-10-27): the instant deterministic report shown while the reasoner writes;
	// replaced by the reasoner's report (or its fallback) when the analysis completes
	Preliminary bool `json:"preliminary,omitempty"`
	// what the preliminary is based on, shown on its banner (retrieval.go)
	Note string `json:"note,omitempty"`
}

type TimelineItem struct {
	T   string `json:"t"`
	Msg string `json:"msg"`
}

type Incident struct {
	ID            string         `json:"id"`
	Mode          int            `json:"mode"`
	State         string         `json:"state"` // running | done | failed
	CreatedSim    int64          `json:"created_sim"`
	CreatedWall   string         `json:"created_wall"`
	Severity      string         `json:"severity"`       // rule severity (provisional) until SeverityFinal
	SeverityFinal bool           `json:"severity_final"` // set once the reasoner has decided (severity.go)
	Title         string         `json:"title"`
	RuleTitle     string         `json:"rule_title,omitempty"` // what the rules said when the incident opened (title.go)
	Roles         []string       `json:"roles"`
	Injected      bool           `json:"injected"`
	FastPath      bool           `json:"fast_path,omitempty"` // opened by the critical fast path (fastpath.go)
	Retrieved     []RetMatch     `json:"retrieved,omitempty"` // similar past AI reports behind the preliminary (retrieval.go)
	Sensors       []SensorRef    `json:"sensors"`
	Mode1         Report         `json:"mode1_report"`
	Agents        []AgentCall    `json:"agents"`
	Final         *ReportCall    `json:"final"`
	TotalMs       float64        `json:"total_ms"`
	NPUCalls      int            `json:"npu_calls"`
	Timeline      []TimelineItem `json:"timeline"`
	Approval      string         `json:"approval"` // pending | approved | dismissed
	ApprovalNote  string         `json:"approval_note"`
	// Early alert + refined re-analysis (refine.go). Absent on incidents stored before it existed.
	RefineStage   string     `json:"refine_stage,omitempty"`    // early | 1.5h | 3h: the analysis shown now
	NextRefineSim int64      `json:"next_refine_sim,omitempty"` // sensor time the next refinement is due (0 = none)
	RefineNote    string     `json:"refine_note,omitempty"`     // why a refinement was skipped, if one was
	SimEpoch      int64      `json:"sim_epoch,omitempty"`       // engine history epoch the windows came from
	SimShift      int64      `json:"sim_shift,omitempty"`       // engine clock shift NextRefineSim is expressed in
	Revisions     []Revision `json:"revisions,omitempty"`       // every analysis of this incident, oldest first
	// Approval lifecycle, checklist and append-only event log (workflow.go), serialised inline
	WorkflowState

	quiet   bool        // a refinement's working copy: no SSE, no token stream (refine.go)
	preempt func() bool // checked between NPU calls; true = stop, more urgent work is waiting
}

type Reasoner struct {
	mu         sync.RWMutex
	genie      *GenieRunner
	eng        *Engine
	Mode       int
	incidents  []*Incident
	store      string
	notify     func(string, any)
	seq        int
	active     bool
	pending    []Candidate
	coolWait   bool            // a runWhenCool watcher is waiting for the thermal guard to clear
	jobs       []job           // explicitly requested analyses (Analyze, Rerun), run in order after pending alerts
	refines    []string        // incident IDs whose refinement is due, run after everything else (refine.go)
	refineQ    map[string]bool // IDs in refines
	lastNPU    time.Time
	storeLines int // lines in the store file, guarded by storeMu (store.go)
	// critical fast path (fastpath.go): sensor key -> the incident opened early with the rules-only preliminary
	// report; the AI analysis at persistReadings updates that incident instead of opening a new one
	fastInc map[string]*Incident
	early   []earlyJob // provisional early AI runs (earlyai.go), after alerts and jobs, before refinements
	ret     retIndex   // finished AI reports for the retrieval preliminary (retrieval.go)
}

func NewReasoner(g *GenieRunner, e *Engine, dir string, notify func(string, any)) *Reasoner {
	r := &Reasoner{genie: g, eng: e, Mode: 3, store: filepath.Join(dir, "state", "incidents.jsonl"), notify: notify,
		refineQ: map[string]bool{}}
	os.MkdirAll(filepath.Dir(r.store), 0o755)
	r.load()
	r.ret.rebuild(r.incidents)
	if n := r.ret.loadSeed(filepath.Join(dir, "data", "rag_seed.json")); n > 0 {
		trace("retrieval: %d seed reference cases loaded", n)
	}
	return r
}

func (r *Reasoner) List() []*Incident {
	r.mu.RLock()
	defer r.mu.RUnlock()
	out := append([]*Incident(nil), r.incidents...)
	// newest first by ID, not by wall clock: the device clock can jump back years after a power loss
	sort.Slice(out, func(i, j int) bool { return incNum(out[i].ID) > incNum(out[j].ID) })
	return out
}

func (r *Reasoner) Get(id string) *Incident {
	r.mu.RLock()
	defer r.mu.RUnlock()
	for _, i := range r.incidents {
		if i.ID == id {
			return i
		}
	}
	return nil
}

func (r *Reasoner) SetApproval(id, state, note string) bool {
	r.mu.Lock()
	var inc *Incident
	for _, i := range r.incidents {
		if i.ID == id {
			inc = i
		}
	}
	if inc == nil {
		r.mu.Unlock()
		return false
	}
	inc.Approval, inc.ApprovalNote = state, note
	switch { // the lifecycle follows (workflow.go): approved = acknowledged, dismissed = closed
	case state == "approved" && wfOf(inc) == wfNeeds:
		ackLocked(inc, "operator", "approve")
	case state == "dismissed" && wfOf(inc) != wfClosed:
		inc.Workflow, inc.Outcome, inc.OutcomeNote, inc.ClosedAt, inc.ClosedBy = wfClosed, "no_action_needed", note, wfNow().Unix(), "operator"
		inc.event("operator", "dismissed", "", "no_action_needed", note, "")
	}
	r.mu.Unlock()
	r.persist(inc)
	r.notify("incident", map[string]any{"id": id, "state": inc.State, "approval": state})
	return true
}

func (r *Reasoner) Busy() bool {
	r.mu.RLock()
	defer r.mu.RUnlock()
	for _, i := range r.incidents {
		if i.State == "running" {
			return true
		}
	}
	return false
}

// HandleCandidates is called by the engine on gated events (non-blocking). One incident runs at a
// time; while busy, the LATEST event waits in a single pending slot (older pending ones are replaced),
// so the NPU never builds a backlog and the user's most recent sensor change is always analysed.
// The thermal guard defers LLM analysis while the device is hot (rules keep running).
func (r *Reasoner) HandleCandidates(cands []Candidate) {
	if cands = r.splitFast(cands); len(cands) == 0 {
		return
	}
	r.mu.Lock()
	if r.active {
		// NPU busy: MERGE into the pending batch (newest reading per sensor wins), never drop an alert
		r.mergePending(cands)
		r.mu.Unlock()
		return
	}
	if r.Mode != 1 {
		if hot, npu, skin := ThermalHot(); hot {
			// Defer for real. This used to `return` and discard the candidates - and because the event
			// gate has already marked those sensors as alerted, they would not re-trigger until they
			// went back to normal: a hot board silently LOST the incident. Queue it instead, and let one
			// watcher start it once the board is below the guard.
			r.mergePending(cands)
			if !r.coolWait {
				r.coolWait = true
				go r.runWhenCool()
			}
			r.mu.Unlock()
			r.notify("log", map[string]any{"msg": fmt.Sprintf("Thermal guard: NPU %.0f C, skin %.0f C - LLM analysis queued until the board cools (rules still active)", npu, skin)})
			return
		}
	}
	r.lastNPU = time.Now()
	r.active = true
	mode := r.Mode
	r.mu.Unlock()
	go r.loop(work{cands: cands, mode: mode})
}

// mergePending folds candidates into the pending batch, newest reading per sensor winning.
// Caller holds r.mu.
func (r *Reasoner) mergePending(cands []Candidate) {
	seen := map[string]int{}
	for i, c := range r.pending {
		seen[key(c.Node, c.Metric)] = i
	}
	for _, c := range cands {
		if i, ok := seen[key(c.Node, c.Metric)]; ok {
			r.pending[i] = c
		} else {
			seen[key(c.Node, c.Metric)] = len(r.pending)
			r.pending = append(r.pending, c)
		}
	}
}

// Submit queues an explicitly requested analysis (dashboard Analyze, Rerun) behind whatever the
// NPU is doing, instead of starting a pipeline of its own.
//
// Both used to call `go Process(...)` directly, bypassing the single-flight queue. Measured in the
// app stress test: 8 Analyze requests at once became 8 concurrent pipelines whose NPU calls
// INTERLEAVED (incident A's agent, then B's, then C's...), so every incident finished late - one took
// 58.3 s for 10.8 s of model time, waiting ~80% of its life. Now requests run one incident at a
// time, first in first out, after any pending event-gate alert (real alerts come first).
//
// Mode 1 is rules only and never touches the NPU, so it still answers immediately.
// Returns false when the request queue is full (maxJobs); the API answers 429.
func (r *Reasoner) Submit(cands []Candidate, mode int) bool {
	if mode == 1 {
		go r.Process(cands, mode)
		return true
	}
	r.mu.Lock()
	if r.active || r.coolWait {
		ok := r.enqueue(cands, mode)
		r.mu.Unlock()
		return ok
	}
	if hot, npu, skin := ThermalHot(); hot {
		ok := r.enqueue(cands, mode)
		r.coolWait = true
		r.mu.Unlock()
		go r.runWhenCool()
		r.notify("log", map[string]any{"msg": fmt.Sprintf("Thermal guard: NPU %.0f C, skin %.0f C - requested analysis queued until the board cools", npu, skin)})
		return ok
	}
	r.active = true
	r.lastNPU = time.Now()
	r.mu.Unlock()
	go r.loop(work{cands: cands, mode: mode})
	return true
}

// work is one unit for the NPU queue: an analysis of candidates, or the refinement of an incident.
type work struct {
	cands  []Candidate
	mode   int
	refine string    // incident ID (refine.go); cands and mode unused
	early  *earlyJob // provisional early AI run (earlyai.go)
}

// next takes the next unit of work: a pending event-gate alert first, then requested jobs in order,
// then due refinements (low priority: they improve a report the operator already has).
// Caller holds r.mu. ok=false means the queue is empty.
func (r *Reasoner) next() (w work, ok bool) {
	if r.pending != nil {
		w = work{cands: r.pending, mode: r.Mode}
		r.pending = nil
		return w, true
	}
	if len(r.jobs) > 0 {
		j := r.jobs[0]
		r.jobs = r.jobs[1:]
		return work{cands: j.cands, mode: j.mode}, true
	}
	if len(r.early) > 0 {
		j := r.early[0]
		r.early = r.early[1:]
		return work{early: &j}, true
	}
	if len(r.refines) > 0 {
		id := r.refines[0]
		r.refines = r.refines[1:]
		delete(r.refineQ, id)
		return work{refine: id}, true
	}
	return work{}, false
}

// runWhenCool starts the queued analysis as soon as the thermal guard clears.
func (r *Reasoner) runWhenCool() {
	for {
		time.Sleep(5 * time.Second)
		if hot, _, _ := ThermalHot(); hot {
			continue
		}
		r.mu.Lock()
		r.coolWait = false
		if r.active {
			// something else already picked the queue up
			r.mu.Unlock()
			return
		}
		w, ok := r.next()
		if !ok {
			r.mu.Unlock()
			return
		}
		r.active = true
		r.lastNPU = time.Now()
		r.mu.Unlock()
		r.notify("log", map[string]any{"msg": "Board cooled - running the queued analysis"})
		r.loop(w)
		return
	}
}

func (r *Reasoner) loop(w work) {
	for {
		if w.early != nil {
			r.runEarly(*w.early)
		} else if w.refine != "" {
			r.runRefine(w.refine)
		} else {
			r.Process(w.cands, w.mode)
		}
		r.mu.Lock()
		var ok bool
		if w, ok = r.next(); !ok {
			r.active = false
			r.mu.Unlock()
			return
		}
		if w.refine != "" && r.refineHeld() {
			// hot board or rules-only mode: low-priority work waits; nothing else is queued
			r.requeueRefine(w.refine)
			r.active = false
			r.mu.Unlock()
			return
		}
		r.mu.Unlock()
	}
}

func (r *Reasoner) sensorRef(ref string, c Candidate, ctxWhy string) SensorRef {
	info := r.eng.Meta.Nodes[c.Node]
	ev := evidenceFor(c.Role, c.Node, info.Location, c.Metric, c.Xs, c.End)
	var gl []string
	for _, e := range ev {
		gl = append(gl, fmt.Sprintf("ev:%s:%s:%s:%d", c.Node, c.Metric, e.Stat, c.End))
	}
	sr := SensorRef{Ref: ref, Node: c.Node, Metric: c.Metric, Role: c.Role, Location: info.Location, End: c.End,
		Injected: c.Injected, Xs: c.Xs, Evidence: ev, GlobalEv: gl, Rule: c.Finding, Context: ctxWhy != "", Why: ctxWhy}
	if hvacAgentSensor(c.Role, c.Node, c.Metric) && !sr.Context && r.eng != nil {
		r.applyV2Evidence(&sr) // v2 HVAC unit: the HVAC agent's own evidence (E1..E10)
		return sr
	}
	if !sr.Context && r.eng != nil {
		if xs := r.eng.HistoryAt(c.Node, c.Metric, c.End, lrPoints); xs != nil {
			if agentV2() {
				sr.Hist = xs
			}
			sr.LongRange = longRange(c.Role, c.Metric, xs)
			for i := range sr.LongRange {
				sr.LongRange[i].ID = fmt.Sprintf("E%d", 9+i)
			}
		}
		r.applyV2Evidence(&sr)
	}
	return sr
}

// longRangeLines: the 12 h findings as citable evidence lines for the reasoner prompts.
func longRangeLines(b *strings.Builder, s SensorRef, indent string) {
	for _, e := range s.Evidence {
		if e.ID == "E9" { // v2 evidence: its E9 line is the same 12 h view (features_v2.go)
			return
		}
	}
	for _, l := range s.LongRange {
		fmt.Fprintf(b, "%s%s.%s %s\n", indent, s.Ref, l.ID, l.Text)
	}
}

func (r *Reasoner) newIncident(cands []Candidate, mode int) *Incident {
	inc := r.buildIncident(cands, mode)
	r.mu.Lock()
	r.seq++
	inc.ID = fmt.Sprintf("INC-%04d", r.seq)
	r.incidents = append(r.incidents, inc)
	r.mu.Unlock()
	return inc
}

// buildIncident: a new incident for the gated candidates (flagged + cross-domain context), not yet registered.
func (r *Reasoner) buildIncident(cands []Candidate, mode int) *Incident {
	// flagged sensors: every alarming sensor in the batch (already sorted by severity), one incident
	// Every alarming sensor stays in the incident and gets its own NPU agent - no cap (owner's
	// decision, 2026-10-15). This loop used to stop at 8: with more alarms than that the rest were
	// silently dropped - not analysed, not reported - and since the event gate had already marked
	// them alerted they never came back. Latency grows with the alarm count instead (~3-5 s per
	// agent); the synthesizer prompt that results is sized by the large context window.
	var flagged []Candidate
	seen := map[string]bool{}
	for _, c := range cands {
		if seen[key(c.Node, c.Metric)] {
			continue
		}
		seen[key(c.Node, c.Metric)] = true
		flagged = append(flagged, c)
	}
	// cross-domain context (parallel deterministic context agents, CPU, microseconds)
	ctxPicks := r.eng.ContextFor(flagged, 4)
	r.mu.Lock()
	inc := &Incident{Mode: mode, State: "running", CreatedSim: cands[0].End,
		CreatedWall: nowTime().In(IST).Format("2006-01-02 15:04:05"), Approval: "pending"}
	for _, c := range flagged {
		inc.Sensors = append(inc.Sensors, r.sensorRef(fmt.Sprintf("S%d", len(inc.Sensors)+1), c, ""))
		inc.Roles = appendUnique(inc.Roles, c.Role)
		inc.Injected = inc.Injected || c.Injected
		if sevRank(c.Finding.Status) > sevRank(inc.Severity) {
			inc.Severity = c.Finding.Status
		}
	}
	for _, p := range ctxPicks {
		inc.Sensors = append(inc.Sensors, r.sensorRef(fmt.Sprintf("S%d", len(inc.Sensors)+1), p.Cand, p.Why))
	}
	if inc.Severity == "" {
		inc.Severity = "info"
	}
	s0 := inc.Sensors[0]
	what := strings.ReplaceAll(s0.Rule.Pattern, "_", " ")
	if steadyPatterns[s0.Rule.Pattern] && s0.Rule.Status != "normal" && s0.Rule.Status != "" {
		what = strings.ReplaceAll(s0.Rule.Status, "_", " ") // steady shape, abnormal value: say so
	}
	inc.Title = fmt.Sprintf("%s %s: %s", nice[s0.Metric], what, s0.Location)
	if len(flagged) > 1 {
		// multi-sensor alert: name every alarming sensor and its status
		var parts []string
		for _, c := range flagged {
			parts = append(parts, nice[c.Metric]+" "+strings.ReplaceAll(c.Finding.Status, "_", " "))
		}
		inc.Title = fmt.Sprintf("%d sensors alarming: %s", len(flagged), strings.Join(parts, ", "))
	}
	inc.Mode1 = mode1Report(inc.Sensors)
	wfCreated(inc) // workflow.go: analysing
	r.mu.Unlock()
	return inc
}

func appendUnique(a []string, s string) []string {
	for _, x := range a {
		if x == s {
			return a
		}
	}
	return append(a, s)
}

// tokenSink streams one NPU call's answer to the dashboard. One sink = one call: its first chunk
// carries reset, so a re-run of the same agent (NPU retry, solo re-run) replaces the earlier live
// text instead of being appended to it.
func (r *Reasoner) tokenSink(inc *Incident, ref string) func(string) {
	// A refinement works on a copy of a finished incident: its tokens go out as "rtoken", which
	// the dashboard shows in a separate "refining" panel - as "token" they would repaint that
	// incident's report page as if it were running again (and older dashboards ignore rtoken).
	kind := "token"
	if inc.quiet {
		kind = "rtoken"
	}
	first := true
	pend := ""
	return func(t string) {
		// never publish half a UTF-8 character: byte-level tokens and the answerScanner holdback
		// both cut inside multi-byte characters ("°C", "µg/m³"), and JSON-encoding the half turns
		// it into U+FFFD on the dashboard. The rest of the character comes with the next chunk.
		t, pend = pend+t, ""
		if i := utf8CompletePrefix(t); i < len(t) {
			t, pend = t[:i], t[i:]
		}
		if t == "" {
			return
		}
		m := map[string]any{"incident": inc.ID, "ref": ref, "text": t}
		if first {
			m["reset"], first = true, false
		}
		r.notify(kind, m)
	}
}

// utf8CompletePrefix is the length of s without a trailing incomplete UTF-8 sequence.
func utf8CompletePrefix(s string) int {
	for i := len(s) - 1; i >= 0 && i >= len(s)-utf8.UTFMax; i-- {
		if utf8.RuneStart(s[i]) {
			if utf8.FullRuneInString(s[i:]) {
				return len(s)
			}
			return i
		}
	}
	return len(s)
}

func (r *Reasoner) log(inc *Incident, msg string) {
	r.mu.Lock()
	inc.Timeline = append(inc.Timeline, TimelineItem{time.Now().Format("15:04:05"), msg})
	r.mu.Unlock()
	if !inc.quiet {
		r.notify("incident", map[string]any{"id": inc.ID, "state": inc.State, "msg": msg})
	}
}

// Process runs the selected mode for one incident.
func (r *Reasoner) Process(cands []Candidate, mode int) *Incident {
	inc := r.adoptFast(cands, mode)
	if inc == nil {
		inc = r.newIncident(cands, mode)
	}
	// persisted as "running" straight away: if the process dies mid-analysis the alert is not lost -
	// it reloads as "failed" and the operator can rerun it (found by killing the backend mid-run)
	r.persist(inc)
	t0 := time.Now()
	r.log(inc, fmt.Sprintf("Event gated: %d sensor(s) flagged, mode %d", len(inc.Sensors), mode))
	if mode != 1 {
		// instant first report (retrieval + rules, CPU, < 5 ms) while the agents and the reasoner run
		r.preliminary(inc, r.retrievalPreliminary(inc))
	}
	var epoch, shift int64
	if r.eng != nil {
		epoch, shift, _ = r.eng.SimBase() // the history the refinements will re-read (refine.go)
	}
	r.analyse(context.Background(), inc, mode, t0, nil)
	r.mu.Lock()
	inc.TotalMs = float64(time.Since(t0).Milliseconds())
	inc.State = "done"
	surfaceDisagreements(inc)
	finaliseSeverity(inc) // from here the displayed severity is the reasoner's, not the rules'
	if mode != 1 && (inc.Final == nil || !inc.Final.Valid) {
		inc.State = "done_with_errors"
	}
	r.mu.Unlock()
	if mode != 1 {
		r.retConsistency(inc)
		r.ret.add(inc) // the index learns every finished AI report
	}
	r.mu.Lock()
	r.scheduleRefine(inc, epoch, shift) // early alert done; its sensors are re-read at 1.5 h and 3 h (refine.go)
	r.wfAnalysedLocked(inc, epoch)      // workflow.go: needs a decision; the checklist is built
	r.mu.Unlock()
	trace("phase %s done +%dms", inc.ID, time.Since(t0).Milliseconds())
	r.log(inc, fmt.Sprintf("Finished in %.1fs, %d NPU call(s)", inc.TotalMs/1000, inc.NPUCalls))
	r.persist(inc)
	return inc
}

// preempted: a refinement's working copy stops between NPU calls when more urgent work is waiting.
func (inc *Incident) preempted() bool { return inc.preempt != nil && inc.preempt() }

// analyse runs the mode's pipeline over inc.Sensors and fills inc.Agents and inc.Final. Shared by the
// first analysis (Process) and its refinements (refine.go), so both take the same NPU path, the same
// policy gate and the same fallbacks. hold, when set, may swap agent findings after the agents have
// answered and before the synthesizer reads them. false = preempted (refinements only).
func (r *Reasoner) analyse(ctx context.Context, inc *Incident, mode int, t0 time.Time, hold func([]AgentCall)) bool {
	switch mode {
	case 1:
		r.log(inc, "Mode 1: rule findings + rule summary (no LLM)")
	case 2:
		// Mode 2 and the Mode-3 synthesizer use the same bundle as the agents. Keeping one model
		// resident avoids Genie's "could not create context from binary" failures that appeared when
		// alternating two 2.9 GB bundles, and isolates the comparison to the architecture, not the model.
		prompt := singlePrompt(inc.Sensors)
		r.log(inc, fmt.Sprintf("Mode 2: single NPU call with all %d sensors (flagged + related)", len(inc.Sensors)))
		res := r.genie.Run(ctx, r.genie.AgentModel(), prompt+ReportPrefill, ReportPrefill, 120*time.Second, r.tokenSink(inc, "final"))
		res.Text = ReportPrefill + res.Text
		if !res.Cached {
			inc.NPUCalls++
		}
		rc := r.checkReport(res, prompt+ReportPrefill, inc.Sensors)
		rc.CallMetrics = metricsOf(res)
		if !rc.Valid {
			// Same rule as the Mode 3 synthesizer: never show the operator a report the gate rejected.
			// Mode 2 has no agents, so fallbackReport builds it from the deterministic rule findings.
			// Seen in the app stress test: an invented label ("heat_drives_cooling_load") and an evidence
			// "id" that was really prose ("rule view pattern=flatline status=sensor_fault").
			rejected := strings.Join(rc.Errors, "; ")
			rc = fallbackReport(inc.Sensors, nil, rc)
			r.log(inc, "Single-call report rejected by policy ("+rejected+"); report rebuilt from the rule findings")
		}
		r.mu.Lock()
		inc.Final = rc
		r.mu.Unlock()
		r.log(inc, fmt.Sprintf("Report from %s in %.1fs (first token %.1fs, %d tokens), policy %s", res.Model, res.LatencyMs/1000, res.TTFTMs/1000, res.GenTokens, okStr(rc.Valid)))
	case 3:
		am := r.genie.AgentModel()
		// NPU agents: every flagged sensor + related sensors that are themselves abnormal No cap.
		// All other related sensors are covered by their deterministic context agent (already computed).
		var llm []int
		for i, s := range inc.Sensors {
			if !s.Context || ((s.Rule.Status == "warning" || s.Rule.Status == "critical") && s.Role != "hvac") {
				llm = append(llm, i)
			}
		}
		isLLM := map[int]bool{}
		for _, i := range llm {
			isLLM[i] = true
		}
		findings := make([]AgentCall, len(inc.Sensors))
		for i, s := range inc.Sensors {
			if !isLLM[i] {
				f := s.Rule
				findings[i] = AgentCall{Ref: s.Ref, Role: s.Role, Model: "context agent (rules, CPU)", Parsed: &f, Valid: true}
			}
		}
		nctx := len(inc.Sensors) - len(llm)
		r.log(inc, fmt.Sprintf("Orchestrator: %d sensor(s) to NPU agents, %d related sensor(s) checked by context agents in parallel", len(llm), nctx))
		// An agent whose NPU session could not be created (hardware, no model output) is run once more at
		// the end of the batch, when the HTP has had time to recover; its slot in inc.Agents is replaced.
		var npuDown, badOut []int
		slot := map[int]int{}
		solo := map[int]bool{} // agents re-run alone after an invalid batched answer
		runAgent := func(i int, again bool) {
			s := inc.Sensors[i]
			ai, okPrompt := r.agentPrompt(s) // v1, or v2 at s.WinN readings (agentversion.go)
			if !okPrompt {
				f := s.Rule
				findings[i] = AgentCall{Ref: s.Ref, Role: s.Role, Model: "rules (no complete window for the agent)", Parsed: &f, Valid: true}
				r.mu.Lock()
				inc.Agents = append(inc.Agents, findings[i])
				r.mu.Unlock()
				r.log(inc, fmt.Sprintf("%s agent: no complete window for %s %s - rule finding kept", title(s.Role), s.Node, s.Metric))
				return
			}
			verb := "analysing"
			if solo[i] {
				verb = "re-running alone (its batched answer was invalid)"
				r.genie.Forget(am, ai.Prompt+AgentPrefill)
			} else if again {
				verb = "re-running (NPU was unavailable)"
			}
			r.log(inc, fmt.Sprintf("%s agent %s %s %s on NPU (%s)", title(s.Role), verb, s.Node, s.Metric, shortModel(am)))
			res := r.genie.Run(ctx, am, ai.Prompt+AgentPrefill, AgentPrefill, 90*time.Second, r.tokenSink(inc, s.Ref))
			res.Text = AgentPrefill + res.Text
			if !res.Cached {
				inc.NPUCalls++
			}
			call := checkAgentWin(s, res, ai.Prompt+AgentPrefill, ai.Xs, ai.HVRule) // ai.Xs: post-rules (htpd_profile post_rules=)
			call.CallMetrics = metricsOf(res)
			applyConfidenceRecal(&call, s.End, ai.Prompt) // D4: the confidence shown is the calibrated one (v2 only)
			if solo[i] && !call.Valid {
				r.log(inc, fmt.Sprintf("%s agent: solo re-run also invalid - first answer kept", title(s.Role)))
				return
			}
			// solo_rerun=runaway (htpd_profile, USER DECISION, proofs/2026-10-21_latency_ladder): re-run alone only
			// answers that did not end cleanly (cap, context, JSON abort) or did not parse. A complete answer the gate
			// rejected for an off-label value (5 of 9 v2 chaos incidents: water "acidic_condition") came back invalid
			// again when re-run alone, costing ~2.5-3.5 s each time. Default (key absent) = every invalid answer.
			rerunnable := htpdProfile()["solo_rerun"] != "runaway" || !res.EarlyStopped || call.Parsed == nil
			if !solo[i] && !again && !call.Valid && res.Error == "" && !res.Cached && rerunnable {
				// a batched answer that failed the policy gate (runaway, off-label pattern, broken JSON):
				// 0.8% of batched v2 answers on the device eval, in runs of neighbouring streams, so a
				// batch artefact rather than the model; one solo re-run at the end of the batch
				badOut = append(badOut, i)
			}
			findings[i] = call
			r.mu.Lock()
			if k, ok := slot[i]; ok {
				inc.Agents[k] = call
			} else {
				slot[i] = len(inc.Agents)
				inc.Agents = append(inc.Agents, call)
			}
			r.mu.Unlock()
			if res.Error != "" && strings.HasPrefix(res.Error, "NPU unavailable") {
				if !again {
					npuDown = append(npuDown, i)
					r.log(inc, fmt.Sprintf("%s agent: NPU temporarily unavailable (hardware, not a model or safety failure) - will re-run at the end", title(s.Role)))
				} else {
					r.log(inc, fmt.Sprintf("%s agent: NPU still unavailable - rule finding kept for this sensor, no AI output to check", title(s.Role)))
				}
				return
			}
			pat := "invalid output"
			if call.Parsed != nil {
				pat = call.Parsed.Pattern + " / " + call.Parsed.Status
			}
			src := fmt.Sprintf("in %.1fs (first token %.1fs, %d tokens)", res.LatencyMs/1000, res.TTFTMs/1000, res.GenTokens)
			if res.Cached {
				src = "instantly (identical window already analysed, cached)"
			}
			if res.Retries > 0 {
				src += fmt.Sprintf(", after %d NPU retr%s", res.Retries, map[bool]string{true: "y", false: "ies"}[res.Retries == 1])
			}
			r.log(inc, fmt.Sprintf("%s agent done %s: %s (policy %s)", title(s.Role), src, pat, okStr(call.Valid)))
		}
		// Optional (SCE_GENIE_BATCH=1): answer every agent's prompt in ONE NPU process first and
		// park the answers in the prompt cache, so each runAgent below finds its own already done.
		// Saves the ~695 ms model init and the 600 ms inter-call gap on every agent after the
		// first - about 1.3 s each. The answers are byte-identical to running them separately
		// (training/export/verify_batch.py, 16/16). If the batch fails, nothing is cached and the
		// loop below just runs normally.
		// Batching and genied are alternatives, never both: genie-app loads its own copy of the
		// model, and two resident contexts is what hits the DSP SMMU limit. When the daemon is up,
		// every agent call already skips model init, which was batching's whole benefit.
		if inc.preempted() {
			return false
		}
		if batchEnabled() && len(llm) > 1 && !daemonUp() {
			prompts := make([]string, len(llm))
			for k, i := range llm {
				s := inc.Sensors[i]
				ai, _ := r.agentPrompt(s)
				prompts[k] = ai.Prompt + AgentPrefill
			}
			r.log(inc, fmt.Sprintf("Orchestrator: running all %d NPU agents in one model load (batched)", len(llm)))
			// one sink per agent for the whole batch (a sink per chunk would reset on every chunk)
			sinks := make([]func(string), len(llm))
			refs := make([]string, len(llm))
			for k, i := range llm {
				refs[k] = inc.Sensors[i].Ref
				sinks[k] = r.tokenSink(inc, refs[k])
			}
			// the dashboard marks these agents "reading the prompt" until their first token arrives
			r.notify("batch", map[string]any{"incident": inc.ID, "refs": refs, "refine": inc.quiet})
			r.genie.Prefetch(ctx, am, prompts, AgentPrefill, func(k int, chunk string) { sinks[k](chunk) })
		}
		trace("phase %s agents-start +%dms (%d agents)", inc.ID, time.Since(t0).Milliseconds(), len(llm))
		for _, i := range llm {
			if inc.preempted() {
				return false
			}
			runAgent(i, false)
		}
		for _, i := range npuDown {
			if inc.preempted() {
				return false
			}
			runAgent(i, true)
		}
		for k, i := range badOut {
			if inc.preempted() {
				return false
			}
			if k >= 3 { // bound the extra NPU time per incident
				break
			}
			solo[i] = true
			runAgent(i, false)
		}
		trace("phase %s agents-done +%dms", inc.ID, time.Since(t0).Milliseconds())
		r.mu.Lock()
		for i := range inc.Sensors {
			if !isLLM[i] {
				inc.Agents = append(inc.Agents, findings[i])
			}
		}
		if hold != nil {
			hold(findings)
		}
		r.mu.Unlock()
		if inc.preempted() {
			return false
		}
		// synthesize whenever two or more domains carry information (flagged, or related with a
		// non-steady pattern/status); otherwise the related domains were verified steady -> isolated event.
		doms := map[string]bool{}
		for i, s := range inc.Sensors {
			f := s.Rule
			if findings[i].Parsed != nil && findings[i].Valid {
				f = *findings[i].Parsed
			}
			if !s.Context || informative(f) {
				doms[s.Role] = true
			}
		}
		if len(doms) < 2 && reasonerV3Enabled() {
			// reasoner v3 owns the wording of every report (owner, 2026-10-27): the single-domain incident goes
			// through it too; the deterministic isolated report is only the fallback (engine error or gate reject)
			r.log(inc, fmt.Sprintf("Related domains checked and steady (%d context agents): reasoner v3 writes the report", nctx))
			trace("phase %s reasoner-start +%dms (isolated)", inc.ID, time.Since(t0).Milliseconds())
			r.preliminary(inc, isolatedReport(inc.Sensors, findings))
			rc := r.reasonV3Fallback(ctx, inc, findings, func() *ReportCall { return isolatedReport(inc.Sensors, findings) })
			r.mu.Lock()
			inc.Final = rc
			r.mu.Unlock()
			break
		}
		if len(doms) < 2 {
			rc := isolatedReport(inc.Sensors, findings)
			r.mu.Lock()
			inc.Final = rc
			r.mu.Unlock()
			r.log(inc, fmt.Sprintf("Related domains checked and steady (%d context agents): isolated event, no synthesizer call needed", nctx))
			break
		}
		if reasonerV3Enabled() { // htpd_profile reasoner=v3 (reasoner_v3.go); default off
			r.log(inc, fmt.Sprintf("Reasoner v3 combining %d domains", len(doms)))
			trace("phase %s reasoner-start +%dms", inc.ID, time.Since(t0).Milliseconds())
			r.preliminary(inc, fallbackReport(inc.Sensors, findings, nil))
			rc := r.reasonV3(ctx, inc, findings)
			r.mu.Lock()
			inc.Final = rc
			r.mu.Unlock()
			break
		}
		prompt := synthPrompt(inc.Sensors, findings)
		r.log(inc, fmt.Sprintf("Synthesizer combining %d domains on NPU", len(doms)))
		trace("phase %s synth-start +%dms", inc.ID, time.Since(t0).Milliseconds())
		res := r.genie.Run(ctx, r.genie.AgentModel(), prompt+ReportPrefill, ReportPrefill, 120*time.Second, r.tokenSink(inc, "final"))
		trace("phase %s synth-done +%dms (call %.0fms)", inc.ID, time.Since(t0).Milliseconds(), res.LatencyMs)
		res.Text = ReportPrefill + res.Text
		if !res.Cached {
			inc.NPUCalls++
		}
		rc := r.checkReport(res, prompt+ReportPrefill, inc.Sensors)
		rc.CallMetrics = metricsOf(res)
		rejected := ""
		if !rc.Valid {
			// The gate knows this report is unsound, so do not show it to the operator. Rebuild it
			// deterministically from the agent findings that DID pass (fallback.go); the rejected
			// text and its errors are carried through for audit.
			rejected = strings.Join(rc.Errors, "; ")
			rc = fallbackReport(inc.Sensors, findings, rc)
		}
		r.mu.Lock()
		inc.Final = rc
		r.mu.Unlock()
		if rejected != "" {
			r.log(inc, "Synthesizer report rejected by policy ("+rejected+"); cross-domain report rebuilt from the validated agent findings")
		}
		r.log(inc, fmt.Sprintf("Cross-domain report in %.1fs, policy %s", res.LatencyMs/1000, okStr(rc.Valid)))
	}
	return true
}

func okStr(b bool) string {
	if b {
		return "PASSED"
	}
	return "REJECTED"
}

func title(role string) string {
	return map[string]string{"air_quality": "Air Quality", "water": "Water", "power": "Power", "occupancy": "Occupancy", "weather": "Weather", "hvac": "HVAC"}[role]
}

func shortModel(b ModelBundle) string {
	if b.FineTuned {
		return "fine-tuned"
	}
	return "base"
}

// Assistant-turn prefills. The agent prefill is the exact first tokens of every training target
// ({"pattern": "...), so it does not change the fine-tuned model's distribution, while forcing the base
// model straight into the JSON object instead of a prose preamble.
const AgentPrefill = `{"pattern": "`
const ReportPrefill = `{"root_cause": "`

// isolatedReport: Mode-3 report when only one domain carries information and all related domains were
// verified steady by their context agents. Built from the validated agent finding (or rule finding).
func isolatedReport(sensors []SensorRef, calls []AgentCall) *ReportCall {
	s := sensors[0]
	f := s.Rule
	src := "rule finding (agent output rejected)"
	if calls[0].Parsed != nil && calls[0].Valid {
		f = *calls[0].Parsed
		src = "domain agent finding"
	}
	lab := causeToLabel[f.LikelyCause]
	if lab == "" {
		lab = "normal_operation"
	}
	var ev []string
	for _, o := range f.Observations {
		for _, id := range idRe.FindAllString(o, -1) {
			ev = appendUnique(ev, s.Ref+"."+id)
		}
	}
	var checked, faulty []string
	for _, c := range sensors[1:] {
		if c.Rule.Status == "sensor_fault" {
			faulty = append(faulty, fmt.Sprintf("%s %s (%s)", c.Node, nice[c.Metric], c.Ref))
			continue
		}
		checked = append(checked, fmt.Sprintf("%s %s (%s)", nice[c.Metric], strings.ReplaceAll(c.Rule.Pattern, "_", " "), c.Ref))
		ev = appendUnique(ev, c.Ref+".E1")
	}
	if len(ev) == 0 {
		ev = []string{s.Ref + ".E1"}
	}
	expl := strings.Join(f.Observations, " ") + " (from " + src + ")."
	if len(checked) > 0 {
		expl += " Related domains checked and steady: " + strings.Join(checked, ", ") + ", so the cause is local to this domain."
	}
	if len(faulty) > 0 {
		expl += " Data quality note: related sensor(s) look faulty and were not used: " + strings.Join(faulty, ", ") + "."
	}
	rep := &Report{RootCause: fmt.Sprintf("%s %s on %s (%s)", nice[s.Metric], strings.ReplaceAll(f.Pattern, "_", " "), s.Location,
		strings.ReplaceAll(f.LikelyCause, "_", " ")), Label: lab, AffectedDomains: []string{s.Role}, Evidence: ev,
		Confidence: f.Confidence, Action: f.Action, Explanation: expl, RequiresHuman: true}
	return &ReportCall{Model: "deterministic (related domains verified steady)", Parsed: rep, Valid: true}
}

// ------------------------------------------------------------- Mode 1 summary
var causeToLabel = map[string]string{
	"ventilation_insufficient": "ventilation_issue", "occupancy_load": "occupancy_driven_load",
	"outdoor_pollution_ingress": "air_pollution_event", "indoor_emission_source": "air_pollution_event",
	"hvac_cooling_issue": "hvac_or_thermal_issue", "humidity_control_issue": "hvac_or_thermal_issue",
	"possible_leak": "water_leak_or_overuse", "high_demand": "water_leak_or_overuse", "tank_draining": "water_leak_or_overuse",
	"supply_interruption": "water_supply_issue", "pump_cycling": "water_supply_issue", "tank_filling": "normal_operation",
	"water_quality_issue": "water_quality_issue", "load_surge": "power_load_anomaly", "equipment_startup": "power_load_anomaly",
	"load_drop_or_outage": "power_load_anomaly", "capacity_limit_throttling": "power_load_anomaly",
	"gradual_load_growth": "power_load_anomaly", "cyclic_equipment": "power_load_anomaly", "power_quality_issue": "power_quality_issue",
	"heat_buildup": "weather_driven", "cooling_trend": "weather_driven", "weather_front": "weather_driven", "gusty_wind": "weather_driven",
	"off_hours_presence": "occupancy_driven_load", "intermittent_presence": "occupancy_driven_load", "sensor_fault": "sensor_fault",
}

func mode1Report(sensors []SensorRef) Report {
	s := sensors[0]
	lab := causeToLabel[s.Rule.LikelyCause]
	if lab == "" {
		lab = "normal_operation"
	}
	var doms []string
	var ev []string
	var parts []string
	for _, x := range sensors {
		doms = appendUnique(doms, x.Role)
		ev = append(ev, x.Ref+".E1")
		parts = append(parts, fmt.Sprintf("%s %s %s (%s)", x.Node, x.Metric, strings.ReplaceAll(x.Rule.Pattern, "_", " "), x.Rule.Status))
	}
	return Report{RootCause: "Rule engine: " + strings.Join(parts, "; "), Label: lab, AffectedDomains: doms, Evidence: ev,
		Confidence: s.Rule.Confidence, Action: s.Rule.Action, Explanation: strings.Join(s.Rule.Observations, " "), RequiresHuman: true,
		Severity: ruleSeverity(sensors)}
}

// ------------------------------------------------------------- prompts for Mode 2 / synthesizer (base model)
const reasonerSystem = "You are the cross-domain reasoning engine of a smart-campus edge monitor (IIIT Hyderabad) running on a Qualcomm QIDK." +
	" You receive flagged sensors from several domains (air quality, water, power, occupancy, weather) with evidence." +
	" Decide the single most likely root cause across domains, citing evidence ids like S1.E2." +
	" Use only the given numbers. Never order physical actuation; recommend at most an inspection action. Reply with one JSON object only." +
	" JSON keys: root_cause (one sentence, max 20 words), label (" + "%s" + "), affected_domains (list), evidence (list of 2-6 most relevant ids like S1.E1)," +
	" confidence (0-1), action (none|monitor|inspect_ventilation|inspect_hvac|check_sensor|inspect_water_system|inspect_electrical|review_schedule|request_facility_review)," +
	" explanation (max 35 words linking the domains)." +
	" Keep every string short; output the JSON object and nothing else." +
	` Format: {"root_cause": "<max 20 words>", "label": "<one label>", "affected_domains": ["<domain>"], "evidence": ["S1.E1"], "confidence": 0.0, "action": "<one action>", "explanation": "<max 35 words>"}`

// evidenceBudget: how many evidence lines a sensor gets in the base-model prompts (Mode 2 / synthesizer).
// Flagged sensors: all; informative related sensors: 3; steady related sensors: 1 (the current value).
// Fewer prompt tokens -> faster prefill, no information about the anomaly is dropped.
func evidenceBudget(s SensorRef) int {
	if !s.Context {
		return len(s.Evidence)
	}
	if informative(s.Rule) {
		return 3
	}
	return 1
}

func sensorBlock(s SensorRef) string {
	var b strings.Builder
	tag := "FLAGGED"
	if s.Context {
		tag = "related: " + s.Why
	}
	fmt.Fprintf(&b, "%s [%s]: %s %s at %s (%s), rule view pattern=%s status=%s\n", s.Ref, tag, s.Node, s.Metric, s.Location, s.Role, s.Rule.Pattern, s.Rule.Status)
	for _, e := range s.Evidence[:min(evidenceBudget(s), len(s.Evidence))] {
		fmt.Fprintf(&b, "%s.%s %s\n", s.Ref, e.ID, e.Text)
	}
	longRangeLines(&b, s, "")
	return b.String()
}

func singlePrompt(sensors []SensorRef) string {
	var b strings.Builder
	b.WriteString("SENSORS (4-hour windows, 5-min samples). FLAGGED = anomaly detected; related = context from causally linked domains:\n")
	for _, s := range sensors {
		b.WriteString(sensorBlock(s))
	}
	b.WriteString("Find the cross-domain root cause.")
	return Llama3Prompt(fmt.Sprintf(reasonerSystem, strings.Join(ReportLabels, "|")), b.String())
}

// estTokens estimates Llama 3 tokens from characters (calibrated on device: 548 tokens / 1712 chars).
// Used to choose the context window, never to trim a prompt: evidence is not degraded to fit.
func estTokens(s string) int { return len(s)*100/310 + 1 }

func synthPrompt(sensors []SensorRef, calls []AgentCall) string {
	var b strings.Builder
	b.WriteString("DOMAIN AGENT FINDINGS:\n")
	for i, s := range sensors {
		tag := "FLAGGED"
		if s.Context {
			tag = "related: " + s.Why
		}
		fmt.Fprintf(&b, "%s [%s]: %s %s at %s (%s)\n", s.Ref, tag, s.Node, s.Metric, s.Location, s.Role)
		if i < len(calls) && calls[i].Parsed != nil && calls[i].Valid {
			f := calls[i].Parsed
			fmt.Fprintf(&b, "  pattern=%s status=%s cause=%s confidence=%.2f\n", f.Pattern, f.Status, f.LikelyCause, f.Confidence)
			for _, o := range f.Observations {
				b.WriteString("  - " + prefixIDs(o, s.Ref) + "\n")
			}
		} else {
			fmt.Fprintf(&b, "  agent output rejected; rule engine says pattern=%s status=%s\n", s.Rule.Pattern, s.Rule.Status)
		}
		n := 3
		if s.Context && !informative(s.Rule) {
			n = 1
		}
		for _, e := range s.Evidence[:min(n, len(s.Evidence))] {
			fmt.Fprintf(&b, "  %s.%s %s\n", s.Ref, e.ID, e.Text)
		}
		longRangeLines(&b, s, "  ")
	}
	b.WriteString("Combine these findings into one cross-domain root cause.")
	return Llama3Prompt(fmt.Sprintf(reasonerSystem, strings.Join(ReportLabels, "|")), b.String())
}

var bracketIDs = regexp.MustCompile(`\[(E\d+(?:\s*,\s*E\d+)*)\]`)

func prefixIDs(o, ref string) string {
	return bracketIDs.ReplaceAllStringFunc(o, func(m string) string {
		inner := strings.Trim(m, "[]")
		parts := strings.Split(inner, ",")
		for i, p := range parts {
			parts[i] = ref + "." + strings.TrimSpace(p)
		}
		return "[" + strings.Join(parts, ",") + "]"
	})
}

func min(a, b int) int {
	if a < b {
		return a
	}
	return b
}

// job is one explicitly requested analysis waiting for the NPU.
type job struct {
	cands []Candidate
	mode  int
}

// maxJobs bounds explicitly requested analyses waiting for the NPU. Each costs seconds of NPU time,
// so an unbounded queue (a script hammering /api/analyze, an operator tapping "rerun") would build
// up hours of work and memory; the API answers 429 instead.
const maxJobs = 16

// enqueue adds a requested analysis unless the same sensors in the same mode are already waiting.
// Caller holds r.mu. false = queue full.
func (r *Reasoner) enqueue(cands []Candidate, mode int) bool {
	sig := func(cs []Candidate) string {
		var b strings.Builder
		for _, c := range cs {
			b.WriteString(key(c.Node, c.Metric) + ";")
		}
		return b.String()
	}
	s := sig(cands)
	for _, j := range r.jobs {
		if j.mode == mode && sig(j.cands) == s {
			return true // already queued: one analysis will answer both requests
		}
	}
	if len(r.jobs) >= maxJobs {
		return false
	}
	r.jobs = append(r.jobs, job{cands, mode})
	return true
}

// QueueAhead is how much NPU work is waiting or running: the in-flight incident, pending event-gate
// alerts and requested analyses. Returned by Analyze/Rerun so the operator sees "queued, N ahead"
// instead of nothing until their request starts.
func (r *Reasoner) QueueAhead() int {
	r.mu.RLock()
	defer r.mu.RUnlock()
	n := len(r.jobs)
	if r.active {
		n++
	}
	if r.pending != nil {
		n++
	}
	return n
}

// preliminary: stage 1 of the two-stage report. The deterministic report (rules + validated agent findings) is shown
// at once, marked preliminary, while the reasoner writes the real one (stage 2 replaces inc.Final).
func (r *Reasoner) preliminary(inc *Incident, rc *ReportCall) {
	if rc == nil || rc.Parsed == nil {
		return
	}
	rc.Preliminary = true
	if !strings.HasPrefix(rc.Model, "preliminary") {
		rc.Model = "preliminary (rules + agent findings)"
	}
	r.mu.Lock()
	if rc.Note == "" && inc.Final != nil && inc.Final.Preliminary {
		rc.Note = inc.Final.Note // keep what the first preliminary was based on
	}
	inc.Final = rc
	r.mu.Unlock()
	r.log(inc, "Preliminary report shown (rules + agent findings); the reasoner is writing the full report")
}
