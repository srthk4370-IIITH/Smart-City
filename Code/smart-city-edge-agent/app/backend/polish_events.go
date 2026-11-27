package main

// Polish pass, engine and AI flow (owner 2026-11-19/20, proofs/POLISH.md):
//   - short/rare events: a fast-path critical whose AI has not started after 15 min (2 cadences for slow sensors) runs
//     the agent + reasoner on the last 4 h window that already exists (no invented readings);
//   - swallowed events: new abnormal episodes join the open incident (promote.go), fine incidents auto-close after 2 h
//     of sensor time with nothing new, and any closed incident can be reopened;
//   - event mode: an alarm flood in one building becomes one incident, critical at once from the rules, the AI reads
//     the zones (floors) in turn, critical first;
//   - deploy-check incidents are tagged system_check, hidden from the operator and auto-closed;
//   - a failed (interrupted) incident is re-run automatically after a restart and hosts its sensors again.

import (
	"fmt"
	"sort"
	"strings"
	"sync"
	"time"
)

const (
	shortEventMin   = 15 * time.Minute // wall = sensor time on live feeds
	fineCloseSec    = 2 * 3600         // a fine incident with nothing new for 2 h of sensor time closes itself
	evWindowSec     = 600              // event mode counts alarms inside this many seconds of sensor time
	evHoldSec       = 1800             // event mode lasts this long after the last alarm
	systemCheckKeep = 5 * time.Minute  // an announced deploy check that was never analysed expires
)

type evAlarm struct {
	c  Candidate
	at int64
}

type zoneBatch struct {
	level string
	cands []Candidate
}

type polishState struct {
	track   map[string]map[string]evAlarm // building -> sensor key -> newest alarm
	until   map[string]int64              // building -> sensor time event mode lasts until
	inc     map[string]*Incident          // building -> its event incident
	zones   map[string][]zoneBatch        // incident ID -> zones still waiting for the AI
	running map[string]bool               // incident ID -> a zone run is booked
	checks  map[string][]time.Time        // sensor key -> announced deploy checks
	mu      sync.Mutex                    // guards checks only
}

func (p *polishState) init() {
	if p.track == nil {
		p.track, p.until, p.inc = map[string]map[string]evAlarm{}, map[string]int64{}, map[string]*Incident{}
		p.zones, p.running = map[string][]zoneBatch{}, map[string]bool{}
	}
}

// incidentOpenWF: not resolved, not closed.
func incidentOpenWF(inc *Incident) bool {
	w := wfOf(inc)
	return w != wfClosed && w != wfResolved && inc.ClosedAt == 0
}

// visibleCountLocked: incidents the operator sees (no system checks). Takes the read lock itself.
func (r *Reasoner) visibleCountLocked() int {
	r.mu.RLock()
	defer r.mu.RUnlock()
	n := 0
	for _, i := range r.incidents {
		if !i.SystemCheck {
			n++
		}
	}
	return n
}

// openHostFor: an open incident (or a fast-path incident) already holds the sensor.
func (r *Reasoner) openHostFor(c Candidate) bool {
	r.mu.RLock()
	defer r.mu.RUnlock()
	return r.hostedLocked(c)
}

func (r *Reasoner) hostedLocked(c Candidate) bool {
	if r.fastInc[key(c.Node, c.Metric)] != nil {
		return true
	}
	for k := len(r.incidents) - 1; k >= 0; k-- {
		if _, ok := promotionHost(r.incidents[k], c); ok {
			return true
		}
	}
	return false
}

// ---------------------------------------------------------------- 1. short / rare events

// cadenceSec: the median gap between the sensor's real readings over the last 24 (5 min when unknown).
func (e *Engine) cadenceSec(node, metric string) int64 {
	k := key(node, metric)
	e.mu.RLock()
	defer e.mu.RUnlock()
	var ts []int64
	if fs := e.dq[k]; fs != nil && len(fs.cnt) >= 3 {
		for b := range fs.cnt {
			ts = append(ts, b)
		}
	} else {
		for b := range e.series[k] {
			ts = append(ts, b)
		}
	}
	if len(ts) < 3 {
		return bucketSec
	}
	sort.Slice(ts, func(i, j int) bool { return ts[i] < ts[j] })
	if len(ts) > 25 {
		ts = ts[len(ts)-25:]
	}
	gaps := make([]int64, 0, len(ts)-1)
	for i := 1; i < len(ts); i++ {
		gaps = append(gaps, ts[i]-ts[i-1])
	}
	sort.Slice(gaps, func(i, j int) bool { return gaps[i] < gaps[j] })
	if g := gaps[len(gaps)/2]; g > bucketSec {
		return g
	}
	return bucketSec
}

// shortEventWait: how long a fast-path incident waits for the AI gate before the AI runs on what exists.
func (r *Reasoner) shortEventWait(inc *Incident) time.Duration {
	for _, s := range inc.Sensors { // critical fast path (owner 2026-11-20): early AI on the history right away
		if !s.Context && normSeverity(s.Rule.Status) == "critical" {
			return 0
		}
	}
	w := shortEventMin
	for _, s := range inc.Sensors {
		if s.Context || r.eng == nil {
			continue
		}
		if d := 2 * time.Duration(r.eng.cadenceSec(s.Node, s.Metric)) * time.Second; d > w {
			w = d
		}
	}
	return w
}

// shortEventSweep: fast-path incidents whose AI has not started although the event is old enough get the AI on the
// last 4 h window that already exists (the same window an operator's Analyze would read). Returns how many it queued.
func (r *Reasoner) shortEventSweep(now time.Time) int {
	if r.eng == nil {
		return 0
	}
	type item struct {
		inc  *Incident
		keys []string
	}
	var items []*item
	idx := map[*Incident]*item{}
	r.mu.RLock()
	mode := r.Mode
	var ks []string
	for k := range r.fastInc {
		ks = append(ks, k)
	}
	sort.Strings(ks)
	for _, k := range ks {
		f := r.fastInc[k]
		if f.ShortRunAt != 0 || f.openedAt.IsZero() || !incidentOpenWF(f) {
			continue
		}
		it := idx[f]
		if it == nil {
			it = &item{inc: f}
			idx[f] = it
			items = append(items, it)
		}
		it.keys = append(it.keys, k)
	}
	r.mu.RUnlock()
	if mode == 1 {
		return 0
	}
	n := 0
	for _, it := range items {
		r.mu.RLock()
		opened, busy := it.inc.openedAt, it.inc.NPUCalls > 0 || len(it.inc.Agents) > 0
		r.mu.RUnlock()
		if busy || now.Sub(opened) < r.shortEventWait(it.inc) {
			continue
		}
		_, _, sim := r.eng.SimBase()
		var cands []Candidate
		var noWhy []string
		for _, k := range it.keys {
			p := strings.SplitN(k, "|", 2)
			xs, ok := r.eng.WindowAt(p[0], p[1], sim)
			if !ok {
				// slow-cadence sensor (hourly pH probe): the AI window is its real readings, time-compressed; never invented
				why := "no complete real window"
				{
					var w string
					if xs, w, ok = r.eng.SparseWindowAt(p[0], p[1], sim); !ok {
						why = w
					}
				}
				if !ok {
					noWhy = append(noWhy, p[1]+": "+why)
					continue
				}
			}
			role := r.eng.Meta.Nodes[p[0]].Role
			cands = append(cands, Candidate{p[0], p[1], role, RuleFinding(role, p[1], p[0], xs, sim), xs, sim, false, false, false})
		}
		if len(cands) == 0 {
			if len(noWhy) > 0 && !it.inc.shortNoWin {
				r.mu.Lock()
				it.inc.shortNoWin = true
				r.mu.Unlock()
				r.log(it.inc, "AI analysis not possible yet: "+strings.Join(noWhy, "; ")+". It starts when enough real readings exist.")
			}
			continue
		}
		r.mu.Lock()
		it.inc.ShortRunAt = now.Unix()
		r.mu.Unlock()
		r.log(it.inc, fmt.Sprintf("Early AI: the event is shorter than %d readings, so the AI reads the real readings that exist now (the full analysis follows at %d)",
			trigRules().PersistReadings, trigRules().PersistReadings))
		r.persist(it.inc)
		if r.Submit(cands, mode) {
			n++
		} else {
			r.mu.Lock()
			it.inc.ShortRunAt = 0 // queue full: try again next sweep
			r.mu.Unlock()
		}
	}
	return n
}

// ---------------------------------------------------------------- 2. swallowed events

// reopenAgainLocked: a sensor of the incident turned abnormal in a new episode. A resolved incident needs a decision
// again; the notification says so even when the severity did not rise. Caller holds r.mu.
func (r *Reasoner) reopenAgainLocked(inc *Incident, ev map[string]any, said []string) {
	repeat := false
	for _, m := range said {
		repeat = repeat || strings.Contains(m, "(new episode)")
	}
	if !repeat {
		return
	}
	if wfOf(inc) == wfResolved {
		inc.Workflow, inc.ResolvedAt, inc.ResolvedSim, inc.Reminded = wfNeeds, 0, 0, false
		inc.NeedsSince = wfNow().Unix()
		if inc.Owner != "" {
			inc.Workflow = wfInProgress
		}
		inc.event("system", "abnormal_again", "", "", "", "a flagged sensor turned abnormal again; the AI re-read the incident")
		ev["workflow_change"] = "abnormal_again"
	}
	inc.WorseAt = wfNow().Unix()
	ev["change"] = "again"
	ev["workflow"] = inc.Workflow
}

// fineAutoCloseLocked closes an incident the AI judged fine once nothing new has happened for 2 h of sensor time.
// Caller holds r.mu. Returns true when it closed it.
func (r *Reasoner) fineAutoCloseLocked(inc *Incident, sim int64, now time.Time) bool {
	if !inc.SeverityFinal || normSeverity(inc.Severity) != "normal" || inc.ClosedAt != 0 {
		return false
	}
	if inc.State != "done" && inc.State != "done_with_errors" {
		return false
	}
	if inc.Owner != "" && openSteps(inc) > 0 {
		return false
	}
	last := inc.CreatedSim
	if inc.promoSim > last {
		last = inc.promoSim
	}
	for _, rv := range inc.Revisions {
		if rv.Stage == "promotion" && rv.SimEnd > last {
			last = rv.SimEnd
		}
	}
	if sim-last < fineCloseSec {
		return false
	}
	inc.Workflow, inc.Outcome, inc.OutcomeNote, inc.ClosedAt, inc.ClosedBy = wfClosed, "no_action_needed", "auto", now.Unix(), "system"
	if inc.Approval == "" || inc.Approval == "pending" {
		inc.Approval = "approved"
	}
	inc.event("system", "auto_closed", "", "no_action_needed", "auto", "auto-closed: fine, nothing new for 2 h")
	inc.Timeline = append(inc.Timeline, TimelineItem{nowTime().In(IST).Format("15:04:05"), "Auto-closed: fine, nothing new for 2 h (reopen it if you disagree)"})
	return true
}

// Reopen: a closed incident (also an auto-closed one) goes back to needing a decision.
func (r *Reasoner) Reopen(id, op, note string) (*Incident, error) {
	op, err := cleanOperator(op)
	if err != nil {
		return nil, err
	}
	inc, err := r.mutate(id, func(inc *Incident) error {
		if wfOf(inc) != wfClosed {
			return wfErr(409, "this incident is not closed")
		}
		inc.Undo, inc.DismissUnconfirmed = nil, false // a reopened incident is open again: the dismissal is void
		inc.Workflow, inc.ClosedAt, inc.ClosedBy, inc.Outcome, inc.OutcomeNote = wfNeeds, 0, "", "", ""
		inc.NeedsSince, inc.Reminded = wfNow().Unix(), false
		inc.Approval = "pending"
		inc.promoSim = 0
		inc.event(op, "reopened", "", "", strings.TrimSpace(note), "reopened")
		inc.Timeline = append(inc.Timeline, TimelineItem{nowTime().In(IST).Format("15:04:05"), "Reopened by " + op})
		return nil
	})
	if err == nil {
		r.retRefresh(inc)
	}
	return inc, err
}

// ---------------------------------------------------------------- 3. failed incidents after a restart

// RerunFailed books an automatic re-run (through the promotion path: same incident, no duplicate) for every
// interrupted incident that is still open. The windows are the current ones when the engine has them, else the stored
// ones. Returns how many incidents it booked.
func (r *Reasoner) RerunFailed() int {
	if r.Mode != 3 || r.eng == nil {
		return 0
	}
	_, _, sim := r.eng.SimBase()
	type job struct {
		id    string
		cands []Candidate
	}
	var jobs []job
	r.mu.RLock()
	for _, inc := range r.incidents {
		if inc.State != "failed" || inc.Mode != 3 || !incidentOpenWF(inc) || inc.Approval == "dismissed" {
			continue
		}
		var cs []Candidate
		for _, s := range inc.Sensors {
			if s.Context {
				continue
			}
			c := Candidate{s.Node, s.Metric, s.Role, s.Rule, s.Xs, s.End, s.Injected, false, false}
			if xs, ok := r.eng.WindowAt(s.Node, s.Metric, sim); ok && sim >= inc.CreatedSim {
				c.Xs, c.End, c.Finding = xs, sim, RuleFinding(s.Role, s.Metric, s.Node, xs, sim)
			}
			cs = append(cs, c)
		}
		if len(cs) > 0 {
			jobs = append(jobs, job{inc.ID, cs})
		}
	}
	r.mu.RUnlock()
	for _, j := range jobs {
		r.mu.Lock()
		if r.promos == nil {
			r.promos = map[string]*promoJob{}
		}
		pj := r.promos[j.id]
		if pj == nil {
			pj = &promoJob{cands: map[string]Candidate{}}
			r.promos[j.id] = pj
		}
		var end int64
		for _, c := range j.cands {
			pj.cands[key(c.Node, c.Metric)] = c
			if c.End > end {
				end = c.End
			}
		}
		r.mu.Unlock()
		r.releasePromos(end)
	}
	return len(jobs)
}

// ---------------------------------------------------------------- 6. event mode

func (r *Reasoner) buildingOf(node string) string {
	if r.eng == nil {
		return ""
	}
	return r.eng.Meta.Nodes[node].Building
}

func sortCandsCritical(cs []Candidate) {
	sort.SliceStable(cs, func(i, j int) bool {
		if a, b := sevRank(cs[i].Finding.Status), sevRank(cs[j].Finding.Status); a != b {
			return a > b
		}
		return cs[i].Node+cs[i].Metric < cs[j].Node+cs[j].Metric
	})
}

func (r *Reasoner) zonesOf(cs []Candidate) []zoneBatch {
	by := map[string][]Candidate{}
	for _, c := range cs {
		l := r.eng.Meta.Nodes[c.Node].Level
		by[l] = append(by[l], c)
	}
	var out []zoneBatch
	for l, list := range by {
		sortCandsCritical(list)
		out = append(out, zoneBatch{l, list})
	}
	sortZones(out)
	return out
}

func sortZones(z []zoneBatch) {
	worst := func(b zoneBatch) int {
		w := 0
		for _, c := range b.cands {
			if s := sevRank(c.Finding.Status); s > w {
				w = s
			}
		}
		return w
	}
	sort.SliceStable(z, func(i, j int) bool {
		if a, b := worst(z[i]), worst(z[j]); a != b {
			return a > b
		}
		if len(z[i].cands) != len(z[j].cands) {
			return len(z[i].cands) > len(z[j].cands)
		}
		return z[i].level < z[j].level
	})
}

// eventMode tracks the alarms per building. When EventAlarms or more sensors of one building alarm within 10 min of
// sensor time, the alarms that no open incident holds yet go into ONE incident for the building; the others return.
func (r *Reasoner) eventMode(cands []Candidate) []Candidate {
	if len(cands) == 0 || r.eng == nil {
		return cands
	}
	thr := trigRules().EventAlarms
	var maxEnd int64
	for _, c := range cands {
		if c.End > maxEnd {
			maxEnd = c.End
		}
	}
	type todo struct {
		b    string
		cs   []Candidate
		into *Incident
	}
	var work []todo
	absorbed := map[string]bool{}
	r.mu.Lock()
	p := &r.pol
	p.init()
	for _, c := range cands {
		if b := r.buildingOf(c.Node); b != "" {
			if p.track[b] == nil {
				p.track[b] = map[string]evAlarm{}
			}
			p.track[b][key(c.Node, c.Metric)] = evAlarm{c, c.End}
		}
	}
	var bs []string
	for b := range p.track {
		bs = append(bs, b)
	}
	sort.Strings(bs)
	for _, b := range bs {
		for k, a := range p.track[b] {
			if maxEnd-a.at > evWindowSec {
				delete(p.track[b], k)
			}
		}
		if len(p.track[b]) == 0 {
			delete(p.track, b)
			continue
		}
		if len(p.track[b]) >= thr && p.until[b] < maxEnd+evHoldSec {
			p.until[b] = maxEnd + evHoldSec
		}
		if p.until[b] <= maxEnd {
			continue
		}
		ei := p.inc[b]
		if ei != nil && !incidentOpenWF(ei) {
			ei = nil
		}
		var pool []Candidate
		if ei == nil { // the flood just started: everything tracked in the window that no incident holds
			for _, a := range p.track[b] {
				pool = append(pool, a.c)
			}
		} else {
			for _, c := range cands {
				if r.buildingOf(c.Node) == b {
					pool = append(pool, c)
				}
			}
		}
		var group []Candidate
		for _, c := range pool {
			if r.hostedLocked(c) {
				continue
			}
			if ei != nil {
				in := false
				for _, s := range ei.Sensors {
					in = in || (s.Node == c.Node && s.Metric == c.Metric)
				}
				if in {
					continue // a new episode of a member: the promotion path escalates the incident
				}
			}
			group = append(group, c)
		}
		if len(group) == 0 || (ei == nil && len(group) < 2) {
			continue
		}
		sortCandsCritical(group)
		work = append(work, todo{b, group, ei})
		for _, c := range group {
			absorbed[key(c.Node, c.Metric)] = true
		}
	}
	r.mu.Unlock()
	if len(work) == 0 {
		return cands
	}
	for _, w := range work {
		if w.into != nil {
			r.eventJoin(w.into, w.cs)
		} else {
			r.openEventIncident(w.b, w.cs)
		}
	}
	var rest []Candidate
	for _, c := range cands {
		if !absorbed[key(c.Node, c.Metric)] {
			rest = append(rest, c)
		}
	}
	return rest
}

func (r *Reasoner) openEventIncident(b string, cs []Candidate) *Incident {
	inc := r.buildIncident(cs, r.Mode) // domain sensors first: the rules report is built from them
	r.mu.Lock()
	r.seq++
	inc.ID = fmt.Sprintf("INC-%04d", r.seq)
	inc.openedAt = time.Now()
	inc.EventMode, inc.Zone = true, b
	inc.Title = fmt.Sprintf("Event mode: %d sensors alarming in building %s", len(cs), b)
	inc.Severity = "critical"
	r.incidents = append(r.incidents, inc)
	r.pol.init()
	r.pol.inc[b] = inc
	zones := r.zonesOf(cs)
	r.pol.zones[inc.ID] = zones
	r.mu.Unlock()
	rc := r.retrievalPreliminary(inc)
	if rc != nil && rc.Parsed != nil {
		rc.Parsed.Severity = "critical" // the rules say critical at once; the zones' AI refines it
	}
	r.preliminary(inc, rc)
	var names []string
	for _, z := range zones {
		names = append(names, fmt.Sprintf("level %s (%d)", z.level, len(z.cands)))
	}
	r.mu.Lock()
	inc.Severity, inc.Mode1.Severity = "critical", "critical"
	for i := range inc.Sensors { // the AI promotes a zone's sensors when its turn comes
		if !inc.Sensors[i].Context {
			inc.Sensors[i].Context, inc.Sensors[i].Why = true, "event mode: the AI reads this zone in turn"
		}
	}
	mode := inc.Mode
	if mode != 3 {
		inc.State = "done"
		r.wfAnalysedLocked(inc, 0)
	}
	r.mu.Unlock()
	r.log(inc, fmt.Sprintf("Event mode: %d sensors alarming in building %s within 10 min - one incident for the building, "+
		"rules critical at once; the AI reads the zones in turn, critical first: %s", len(cs), b, strings.Join(names, ", ")))
	r.persist(inc)
	r.notify("incident", map[string]any{"id": inc.ID, "state": inc.State, "msg": "Event mode: " + inc.Title, "event_mode": true, "change": "elevated"})
	if mode == 3 {
		r.nextEventZone(inc.ID, 0)
	}
	return inc
}

// eventJoin: more sensors of the flooded building alarm; they join the building's incident and wait for their zone.
func (r *Reasoner) eventJoin(inc *Incident, cs []Candidate) {
	r.mu.Lock()
	for _, c := range cs {
		inc.Sensors = append(inc.Sensors, r.sensorRef(fmt.Sprintf("S%d", len(inc.Sensors)+1), c, "event mode: the AI reads this zone in turn"))
		inc.Roles = appendUnique(inc.Roles, c.Role)
	}
	add := r.zonesOf(cs)
	zs := r.pol.zones[inc.ID]
	for _, z := range add {
		merged := false
		for i := range zs {
			if zs[i].level == z.level {
				zs[i].cands = append(zs[i].cands, z.cands...)
				merged = true
			}
		}
		if !merged {
			zs = append(zs, z)
		}
	}
	sortZones(zs)
	r.pol.zones[inc.ID] = zs
	idle := !r.pol.running[inc.ID]
	inc.Title = fmt.Sprintf("Event mode: %d sensors alarming in building %s", len(inc.Sensors), inc.Zone)
	r.mu.Unlock()
	r.log(inc, fmt.Sprintf("Event mode: %d more sensor(s) alarming in building %s joined this incident", len(cs), inc.Zone))
	r.persist(inc)
	if idle && inc.Mode == 3 {
		r.nextEventZone(inc.ID, 0)
	}
}

// zonesLeftLocked: zones of the event incident still waiting for their AI turn. Caller holds r.mu.
func (r *Reasoner) zonesLeftLocked(id string) bool { return len(r.pol.zones[id]) > 0 }

// nextEventZone books the AI run of the next waiting zone of an event incident (through the promotion path, without
// its 2-reading debounce). Called when a zone run has finished (or an early exit left the chain).
func (r *Reasoner) nextEventZone(id string, sim int64) {
	r.mu.Lock()
	zs := r.pol.zones[id]
	if len(zs) == 0 {
		delete(r.pol.zones, id)
		delete(r.pol.running, id)
		r.mu.Unlock()
		return
	}
	var inc *Incident
	for _, i := range r.incidents {
		if i.ID == id {
			inc = i
		}
	}
	if inc == nil || !incidentOpenWF(inc) {
		delete(r.pol.zones, id)
		delete(r.pol.running, id)
		r.mu.Unlock()
		return
	}
	z := zs[0]
	r.pol.zones[id] = zs[1:]
	r.pol.running[id] = true
	if r.promos == nil {
		r.promos = map[string]*promoJob{}
	}
	job := r.promos[id]
	if job == nil {
		job = &promoJob{cands: map[string]Candidate{}}
		r.promos[id] = job
	}
	for _, c := range z.cands {
		job.cands[key(c.Node, c.Metric)] = c
		if c.End > sim {
			sim = c.End
		}
	}
	inc.promoSim = 0
	r.mu.Unlock()
	r.log(inc, fmt.Sprintf("Event mode: the AI reads level %s now (%d sensor(s))", z.level, len(z.cands)))
	r.releasePromos(sim)
}

// EventModeOut is /api/health's event_mode.
type EventModeOut struct {
	Active    bool     `json:"active"`
	Threshold int      `json:"threshold"`
	Buildings []string `json:"buildings"`
	Incidents []string `json:"incidents"`
}

func (r *Reasoner) EventModeStatus() EventModeOut {
	out := EventModeOut{Threshold: trigRules().EventAlarms, Buildings: []string{}, Incidents: []string{}}
	var sim int64
	if r.eng != nil {
		_, _, sim = r.eng.SimBase()
	}
	r.mu.RLock()
	defer r.mu.RUnlock()
	for b, u := range r.pol.until {
		if u > sim {
			out.Buildings = append(out.Buildings, b)
			if i := r.pol.inc[b]; i != nil && incidentOpenWF(i) {
				out.Incidents = append(out.Incidents, i.ID)
			}
		}
	}
	sort.Strings(out.Buildings)
	sort.Strings(out.Incidents)
	out.Active = len(out.Buildings) > 0
	return out
}

// ---------------------------------------------------------------- 8. deploy-check incidents

// ExpectSystemCheck announces that the next analysis of this sensor is the forced deploy check.
func (r *Reasoner) ExpectSystemCheck(node, metric string) {
	r.pol.mu.Lock()
	defer r.pol.mu.Unlock()
	if r.pol.checks == nil {
		r.pol.checks = map[string][]time.Time{}
	}
	r.pol.checks[key(node, metric)] = append(r.pol.checks[key(node, metric)], time.Now())
}

// markSystemCheck tags the incident that a announced deploy check opened (one sensor, announced in the last 5 min).
func (r *Reasoner) markSystemCheck(inc *Incident, cands []Candidate) {
	if len(cands) != 1 {
		return
	}
	k := key(cands[0].Node, cands[0].Metric)
	r.pol.mu.Lock()
	var keep []time.Time
	for _, t := range r.pol.checks[k] {
		if time.Since(t) < systemCheckKeep {
			keep = append(keep, t)
		}
	}
	hit := len(keep) > 0
	if hit {
		keep = keep[1:]
	}
	if r.pol.checks != nil {
		r.pol.checks[k] = keep
	}
	r.pol.mu.Unlock()
	if !hit {
		return
	}
	r.mu.Lock()
	inc.SystemCheck = true
	inc.Timeline = append(inc.Timeline, TimelineItem{nowTime().In(IST).Format("15:04:05"), "System check (deploy): hidden from the operator list, closed automatically"})
	r.mu.Unlock()
}

// autoCloseSystemCheck closes a finished system-check incident so it never waits for a person.
func (r *Reasoner) autoCloseSystemCheck(inc *Incident) {
	r.mu.Lock()
	if !inc.SystemCheck || inc.ClosedAt != 0 {
		r.mu.Unlock()
		return
	}
	inc.Workflow, inc.Outcome, inc.OutcomeNote, inc.ClosedAt, inc.ClosedBy = wfClosed, "no_action_needed", "system check", wfNow().Unix(), "system"
	inc.Approval = "dismissed"
	inc.event("system", "auto_closed", "", "no_action_needed", "system check", "deploy check finished")
	r.mu.Unlock()
	r.persist(inc)
}

// StartRerunFailed re-runs interrupted incidents once the engine has its first readings (the campus backfill is in).
func (r *Reasoner) StartRerunFailed() {
	go func() {
		defer recoverLog("rerun failed")
		for i := 0; i < 60; i++ { // up to 5 min
			time.Sleep(5 * time.Second)
			if r.eng != nil {
				r.eng.mu.RLock()
				hold := r.eng.liveHold
				r.eng.mu.RUnlock()
				if hold {
					continue
				}
			}
			if n := r.RerunFailed(); n > 0 {
				trace("restart: %d interrupted incident(s) re-run", n)
			}
			return
		}
	}()
}
