package main

// Unrelated co-occurring events become separate incidents (sweep 2026-11-27, INC-0015: a water pH spike at the KH
// tank and an AC failure on KH level 03 were batched into ONE incident whose report then missed a sensor and fell
// back to the template). Two flagged sensors belong together when the site tree relates them (same host, a link
// path, the same floor, or shared building equipment): SiteIndex.Relation != "campus_no_link". Outdoor/weather
// sensors relate through "outdoor-for" links like any other. No site tree, or htpd_profile batch_split=0: unchanged.

import "sort"

func batchSplitOn() bool { return profStr("batch_split") != "0" }

func siteSensorID(c Candidate) string { return c.Node + "/" + c.Metric }

// relatedSensors: are two sensors related in the site tree? Unknown sensors (not in the tree) count as related, so a
// missing tree never splits anything.
func relatedSensors(ix *SiteIndex, a, b string) bool {
	if ix == nil || a == b {
		return true
	}
	if _, ok := ix.nodes[a]; !ok {
		return true
	}
	if _, ok := ix.nodes[b]; !ok {
		return true
	}
	rel, _, _ := ix.Relation(a, b)
	return rel != "campus_no_link"
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
			if relatedSensors(ix, siteSensorID(cands[i]), siteSensorID(cands[j])) {
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
	return relatedSensors(ix, keySite(e.batchKey), keySite(k))
}

// anyOtherAbnormalRelated: anyOtherAbnormal restricted to sensors related to the batch opener (an unrelated young
// event elsewhere on campus no longer keeps this batch waiting). Caller holds e.mu.
func anyOtherAbnormalRelated(e *Engine, abnormal map[string]Candidate) bool {
	pr := trigRules().AbnormalOfWindow
	for k := range abnormal {
		if st := e.states[k]; st != nil && !st.alerted && st.AbnormalInWindow < pr && e.relatedToBatch(k) {
			return true
		}
	}
	return false
}
