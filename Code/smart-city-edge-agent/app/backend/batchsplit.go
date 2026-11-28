package main

// Unrelated co-occurring events become separate incidents (sweep 2026-11-27, INC-0015: a water pH spike at the KH
// tank and an AC failure on KH level 03 were batched into ONE incident whose report then missed a sensor and fell
// back to the template). Owner rule (2026-11-27): distance in the site tree decides - sensors in the SAME building
// (lowest common ancestor below the campus root) are related; sensors in DIFFERENT buildings are separate unless they
// share a domain (role) or a CONFIRMED site link relates them (a link path, outdoor-for, shared equipment: Relation
// != "campus_no_link" on the tree without inferred links). The tree distance (edges via the common ancestor) normalised by the tree diameter is logged with
// each split so the decision is visible. No site tree, or htpd_profile batch_split=0: unchanged (one batch).

import (
	"fmt"
	"sort"
	"strings"
	"sync"
	"sync/atomic"
)

func batchSplitOn() bool { return profStr("batch_split") != "0" }

func siteSensorID(c Candidate) string { return c.Node + "/" + c.Metric }

// relatedSensors: are two sensors related (owner rule above)? roleA/roleB are the sensors' domains ("" = unknown).
// Unknown sensors (not in the tree) count as related, so a missing tree never splits anything.
func relatedSensors(ix *SiteIndex, a, b, roleA, roleB string) bool {
	if ix == nil || a == b {
		return true
	}
	if _, ok := ix.nodes[a]; !ok {
		return true
	}
	if _, ok := ix.nodes[b]; !ok {
		return true
	}
	if roleA != "" && roleA == roleB {
		return true
	}
	if l := ix.LCA(a, b); l != "" && ix.kind(l) != "campus" && ix.Parent(l) != "" {
		return true // same building (or a wing / floor / room inside it)
	}
	// different buildings, different domains: only a CONFIRMED site link relates them. Inferred links (the auto
	// tree's guesses, e.g. "feeder assumed to supply KH") do not: board run 2026-11-27 INC-0016 merged a KH level 03
	// AC failure with an SB00 power-factor drop through such a guess.
	rel, _, _ := confirmedIndex(ix).Relation(a, b)
	return rel != "campus_no_link"
}

var confIx struct {
	sync.Mutex
	src, ix *SiteIndex
}

// confirmedIndex: the site index without inferred links (cached per source index).
func confirmedIndex(ix *SiteIndex) *SiteIndex {
	confIx.Lock()
	defer confIx.Unlock()
	if confIx.src == ix {
		return confIx.ix
	}
	cfg := *ix.cfg
	cfg.Links = nil
	for _, l := range ix.cfg.Links {
		if !l.Inferred {
			cfg.Links = append(cfg.Links, l)
		}
	}
	confIx.src, confIx.ix = ix, NewSiteIndex(&cfg)
	return confIx.ix
}

// siteDistance: tree distance in edges between two nodes through their lowest common ancestor, and the tree diameter
// (longest such distance between any two sensors), for the split log. ok=false when a node is not in the tree.
func siteDistance(ix *SiteIndex, a, b string) (dist, diam int, ok bool) {
	if ix == nil || ix.nodes[a] == nil || ix.nodes[b] == nil {
		return 0, 0, false
	}
	depth := func(x string) int { return len(ix.Ancestors(x)) }
	l := ix.LCA(a, b)
	dl := -1
	if l != "" {
		dl = depth(l)
	}
	dist = depth(a) + depth(b) - 2*dl
	return dist, siteDiameter(ix), true
}

var siteDiam struct {
	sync.Mutex
	ix *SiteIndex
	d  int
}

// siteDiameter: max over sensor pairs of the tree distance, cached per index (the index is rebuilt on every site save).
// Per root child, the two deepest sensors in different child subtrees give the diameter through that node.
func siteDiameter(ix *SiteIndex) int {
	siteDiam.Lock()
	defer siteDiam.Unlock()
	if siteDiam.ix == ix {
		return siteDiam.d
	}
	var deep func(id string) int // deepest sensor below id, in edges from id (-1 = none)
	best := 0
	deep = func(id string) int {
		d1, d2 := -1, -1
		for _, c := range ix.children[id] {
			if v := deep(c); v >= 0 {
				v++
				if v > d1 {
					d1, d2 = v, d1
				} else if v > d2 {
					d2 = v
				}
			}
		}
		if d1 >= 0 && d2 >= 0 && d1+d2 > best {
			best = d1 + d2
		}
		if n := ix.nodes[id]; n != nil && n.Kind == "sensor" && d1 < 0 {
			return 0
		}
		return d1
	}
	for _, id := range ix.order {
		if ix.Parent(id) == "" {
			deep(id)
		}
	}
	siteDiam.ix, siteDiam.d = ix, best
	return best
}

// splitUnrelated partitions candidates into groups of site-related sensors (connected components), biggest and most
// severe group first. One group (or the switch off) returns the input as one group.
func splitUnrelated(cands []Candidate) [][]Candidate {
	if len(cands) < 2 || !batchSplitOn() {
		return [][]Candidate{cands}
	}
	_, ix := siteS.Get()
	if ix == nil {
		return [][]Candidate{cands}
	}
	par := make([]int, len(cands))
	for i := range par {
		par[i] = i
	}
	var find func(int) int
	find = func(i int) int {
		for par[i] != i {
			par[i] = par[par[i]]
			i = par[i]
		}
		return i
	}
	for i := range cands {
		for j := i + 1; j < len(cands); j++ {
			if relatedSensors(ix, siteSensorID(cands[i]), siteSensorID(cands[j]), cands[i].Role, cands[j].Role) {
				par[find(i)] = find(j)
			}
		}
	}
	byRoot := map[int][]Candidate{}
	var roots []int
	for i, c := range cands {
		r := find(i)
		if _, ok := byRoot[r]; !ok {
			roots = append(roots, r)
		}
		byRoot[r] = append(byRoot[r], c)
	}
	if len(roots) == 1 {
		return [][]Candidate{cands}
	}
	splitLast.Store(splitNote(ix, cands, roots, find))
	out := make([][]Candidate, 0, len(roots))
	for _, r := range roots {
		out = append(out, byRoot[r])
	}
	worst := func(g []Candidate) int {
		w := 0
		for _, c := range g {
			if s := sevRank(c.Finding.Status); s > w {
				w = s
			}
		}
		return w
	}
	sort.SliceStable(out, func(i, j int) bool {
		if a, b := worst(out[i]), worst(out[j]); a != b {
			return a > b
		}
		return len(out[i]) > len(out[j])
	})
	return out
}

// keySite: engine key "node|metric" -> site sensor id "node/metric".
func keySite(k string) string {
	for i := 0; i < len(k); i++ {
		if k[i] == '|' {
			return k[:i] + "/" + k[i+1:]
		}
	}
	return k
}

// relatedToBatch: is engine sensor k related (site tree) to the sensor that opened the current batch? With the split
// off, no tree or no opener, every sensor counts as related (the old behaviour). Caller holds e.mu.
func (e *Engine) relatedToBatch(k string) bool {
	if !batchSplitOn() || e.batchKey == "" || k == e.batchKey {
		return true
	}
	_, ix := siteS.Get()
	ra, rb := "", ""
	if st := e.states[e.batchKey]; st != nil {
		ra = st.Role
	}
	if st := e.states[k]; st != nil {
		rb = st.Role
	}
	return relatedSensors(ix, keySite(e.batchKey), keySite(k), ra, rb)
}

// anyOtherAbnormalRelated: anyOtherAbnormal restricted to sensors related to the batch opener (an unrelated young
// event elsewhere on campus no longer keeps this batch waiting). Caller holds e.mu.
func anyOtherAbnormalRelated(e *Engine, abnormal map[string]Candidate) bool {
	for k := range abnormal {
		if e.holdsBatchLocked(k) {
			return true
		}
	}
	return false
}

// holdsBatchLocked: night sweep 2026-11-27 #77, sensor k keeps the open batch waiting: not reported, still too young,
// related to the opener and abnormal NOW (its newest reading counted). A sensor back to normal cannot mature, so it
// never holds (board: one 2600 ppm CO2 reading held the KH batch 25 min). Caller holds e.mu.
func (e *Engine) holdsBatchLocked(k string) bool {
	st := e.states[k]
	return st != nil && !st.alerted && st.nowAb && st.AbnormalInWindow < trigRules().AbnormalOfWindow && e.relatedToBatch(k)
}

// criticalMatureLocked: #77, a mature, unreported sensor related to the batch reads beyond its critical limit now:
// the batch closes at once. Caller holds e.mu.
func (e *Engine) criticalMatureLocked(abnormal map[string]Candidate) bool {
	need := trigRules().AbnormalOfWindow
	for k := range abnormal {
		st := e.states[k]
		if st == nil || st.alerted || st.AbnormalInWindow < need || !e.relatedToBatch(k) {
			continue
		}
		if nowStatusOf(st, e.sim) == "critical" {
			return true
		}
	}
	return false
}

// batchWaitingLocked: the sensors (site ids, sorted) the open batch waits for (#84 gate.batch.waiting_for).
func (e *Engine) batchWaitingLocked() []string {
	out := []string{}
	if e.batchUntil == 0 {
		return out
	}
	for k := range e.states {
		if e.holdsBatchLocked(k) {
			out = append(out, keySite(k))
		}
	}
	sort.Strings(out)
	return out
}

// splitLast: the newest split decision as text (for the event log and /api/status), e.g.
// "split 3 sensors into 2 groups: [KH/ph] | [KH-L03/room_temp, KH-L03/co2] (KH/ph-KH-L03/room_temp: 7 of 8 edges, other building, other domain)".
var splitLast atomic.Value // string

func splitNote(ix *SiteIndex, cands []Candidate, roots []int, find func(int) int) string {
	var g []string
	for _, r := range roots {
		var ids []string
		for i, c := range cands {
			if find(i) == r {
				ids = append(ids, siteSensorID(c))
			}
		}
		g = append(g, "["+strings.Join(ids, ", ")+"]")
	}
	note := fmt.Sprintf("split %d sensors into %d groups: %s", len(cands), len(roots), strings.Join(g, " | "))
	a, b := -1, -1
	for i := range cands {
		for j := i + 1; j < len(cands); j++ {
			if find(i) != find(j) {
				a, b = i, j
				break
			}
		}
		if a >= 0 {
			break
		}
	}
	if a >= 0 {
		if d, dm, ok := siteDistance(ix, siteSensorID(cands[a]), siteSensorID(cands[b])); ok {
			note += fmt.Sprintf(" (%s-%s: %d of %d edges, other building, other domain)", siteSensorID(cands[a]), siteSensorID(cands[b]), d, dm)
		}
	}
	return note
}

// releaseUnrelatedLocked: while a batch waits for its own young related sensors, a MATURE sensor unrelated to the
// batch opener does not wait with it (board run 2026-11-27: an SB00 power-factor warning sat 4/4 in a KH batch that
// waited for a young KH level 03 sensor). It goes out at once (its own incident), unless a young sensor related to IT
// is still maturing (that one keeps it, as its own batch would). Caller holds e.mu.
func (e *Engine) releaseUnrelatedLocked(abnormal map[string]Candidate) []Candidate {
	if !batchSplitOn() || e.batchKey == "" {
		return nil
	}
	_, ix := siteS.Get()
	if ix == nil {
		return nil
	}
	tr := trigRules()
	role := func(k string) string {
		if st := e.states[k]; st != nil {
			return st.Role
		}
		return ""
	}
	var out []Candidate
	for k, c := range abnormal {
		st := e.states[k]
		if st == nil || st.alerted || st.AbnormalInWindow < tr.AbnormalOfWindow || e.relatedToBatch(k) {
			continue
		}
		wait := false
		for k2 := range abnormal {
			st2 := e.states[k2]
			if k2 != k && st2 != nil && !st2.alerted && st2.nowAb && st2.AbnormalInWindow < tr.AbnormalOfWindow && // #77
				relatedSensors(ix, keySite(k), keySite(k2), role(k), role(k2)) {
				wait = true
				break
			}
		}
		if wait {
			continue
		}
		st.alerted, st.Reported, st.clearedAt, st.alertedAt = true, true, 0, e.sim
		st.reportedSev = sevRank(c.Finding.Status)
		out = append(out, c)
	}
	sort.Slice(out, func(i, j int) bool { return sevRank(out[i].Finding.Status) > sevRank(out[j].Finding.Status) })
	if len(out) > 0 {
		trace("gate: %d mature sensor(s) unrelated to the open batch released now", len(out))
	}
	return out
}
