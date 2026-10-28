package main

// Retrieval preliminary (2026-10-28, owner: the first report must appear at once and be as good as possible
// without a new model). CPU only, no NPU, < 5 ms at 500 reports (TestRetrievalSpeed).
//
// Every finished AI report (the reasoner's final report of a Mode 2/3 incident, plus its validated agent
// findings) is indexed with
//   - a structured vector: role / metric / domain set, the rule pattern, status and cause of the lead sensor,
//     magnitude bins (z-score vs the window's first hour, % of the critical limit), time-of-day bin, sensor count;
//   - a TF-IDF vector over the title, root cause and observations.
// A new incident is described the same way from its rule findings and live window. Hybrid similarity =
// 0.7 structured + 0.3 text, only among reports with the same role and metric, above a threshold tuned on the
// index itself (leave-one-out: the lowest threshold whose retrieved severity agrees with the AI's >= 90%; 0.70 until 30 reports).
// Hit -> the preliminary is the rules report built from the LIVE values (numbers never come from the old report),
// with the retrieved label / action / root-cause wording and severity = max(rules, retrieved) so it cannot
// under-alert, labelled "Preliminary - based on N similar past incidents (best match X%, INC-...)".
// Miss -> the rules report, "Full AI report coming". The AI report replaces it as before. The index is rebuilt
// from the incident store at start and updated whenever an AI report finishes.

import (
	"encoding/json"
	"fmt"
	"math"
	"os"
	"regexp"
	"sort"
	"strings"
	"sync"
	"time"
)

const (
	retWStruct   = 0.7
	retWText     = 0.3
	retDefThresh = 0.70
	retMinTune   = 30 // fewer indexed reports than this: keep the default threshold
)

type retDoc struct {
	ID, Role, Metric        string
	Domains                 map[string]bool
	Pattern, Status, Cause  string
	Mag, Pct, Tod, NSensors int
	tf                      map[string]float64
	Sev, Label, Action      string
	RootCause               string
	Seed                    bool   // a reference case from the seed library (rag_seed.json), not a real past incident
	Prov                    string // seed provenance ("seed:<id>, model:<tag>")
}

// seedPenalty: a live report outranks a seed reference case that is equally close
const seedPenalty = 0.97

// SeedDoc is one entry of data/rag_seed.json (retrieval_seed.py writes it from reasoner outputs).
type SeedDoc struct {
	ID        string   `json:"id"`
	Prov      string   `json:"provenance"`
	Role      string   `json:"role"`
	Metric    string   `json:"metric"`
	Domains   []string `json:"domains"`
	Pattern   string   `json:"pattern"`
	Status    string   `json:"status"`
	Cause     string   `json:"cause"`
	Mag       int      `json:"mag_bin"`
	Pct       int      `json:"pct_bin"`
	Tod       int      `json:"tod_bin"`
	NSensors  int      `json:"n_sensors"`
	Text      string   `json:"text"`
	Severity  string   `json:"severity"`
	Label     string   `json:"label"`
	Action    string   `json:"action"`
	RootCause string   `json:"root_cause"`
}

type retIndex struct {
	mu     sync.RWMutex
	docs   []retDoc
	df     map[string]int
	thresh float64
}

// RetMatch is one retrieved past report (shown on the preliminary and used for the consistency check).
type RetMatch struct {
	ID    string  `json:"id"`
	Score float64 `json:"score"`
	Sev   string  `json:"severity"`
	Label string  `json:"label"`
	Seed  bool    `json:"seed,omitempty"`
}

var retTok = regexp.MustCompile(`[a-z][a-z_]{2,}`)

func retTokens(s string) map[string]float64 {
	tf := map[string]float64{}
	for _, w := range retTok.FindAllString(strings.ToLower(s), -1) {
		tf[w]++
	}
	return tf
}

func binOf(v float64, edges ...float64) int {
	for i, e := range edges {
		if v < e {
			return i
		}
	}
	return len(edges)
}

// retFeatures: the structured description of an incident's lead sensor (rule finding + live window).
func retFeatures(sensors []SensorRef) (d retDoc, ok bool) {
	var lead *SensorRef
	d.Domains = map[string]bool{}
	for i := range sensors {
		if sensors[i].Context {
			continue
		}
		if lead == nil {
			lead = &sensors[i]
		}
		d.Domains[sensors[i].Role] = true
		d.NSensors++
	}
	if lead == nil {
		return d, false
	}
	d.Role, d.Metric = lead.Role, lead.Metric
	d.Pattern, d.Status, d.Cause = lead.Rule.Pattern, normSeverity(lead.Rule.Status), lead.Rule.LikelyCause
	xs := lead.Xs
	if n := len(xs); n >= 12 {
		mu, sd := 0.0, 0.0
		for _, v := range xs[:12] {
			mu += v
		}
		mu /= 12
		for _, v := range xs[:12] {
			sd += (v - mu) * (v - mu)
		}
		sd = math.Sqrt(sd / 12)
		if m, ok := Metrics[lead.Role+"/"+lead.Metric]; ok && m.Floor > sd {
			sd = m.Floor
		}
		z := math.Abs(xs[n-1]-mu) / math.Max(sd, 1e-9)
		d.Mag = binOf(z, 2, 4, 8, 16)
		if m, ok := Metrics[lead.Role+"/"+lead.Metric]; ok && m.HasLimits && m.Crit != 0 {
			d.Pct = 1 + binOf(xs[n-1]/m.Crit, 0.6, 0.8, 1.0, 1.2)
		}
	}
	d.Tod = time.Unix(lead.End, 0).In(IST).Hour() / 4
	if d.NSensors > 3 {
		d.NSensors = 3
	}
	return d, true
}

// retDocOf indexes a finished AI incident; ok=false when it has no usable AI report.
func retDocOf(inc *Incident) (retDoc, bool) {
	if inc == nil || inc.Mode == 1 || inc.Final == nil || inc.Final.Preliminary || !inc.Final.Valid || inc.Final.Parsed == nil ||
		(inc.State != "done" && inc.State != "done_with_errors") {
		return retDoc{}, false
	}
	d, ok := retFeatures(inc.Sensors)
	if !ok {
		return d, false
	}
	p := inc.Final.Parsed
	txt := []string{inc.Title, p.Title, p.RootCause, p.Label}
	for _, o := range p.Observations {
		txt = append(txt, o.Text)
	}
	for _, a := range inc.Agents {
		if a.Valid && a.Parsed != nil {
			txt = append(txt, a.Parsed.Pattern, a.Parsed.LikelyCause)
			txt = append(txt, a.Parsed.Observations...)
		}
	}
	d.ID, d.tf = inc.ID, retTokens(strings.Join(txt, " "))
	d.Sev = normSeverity(p.Severity)
	if d.Sev == "" {
		d.Sev = normSeverity(inc.Severity)
	}
	d.Label, d.Action, d.RootCause = p.Label, p.Action, p.RootCause
	return d, true
}

// retQueryText: the new incident's rule/feature description.
func retQueryText(sensors []SensorRef, title string) map[string]float64 {
	txt := []string{title}
	for _, s := range sensors {
		if s.Context {
			continue
		}
		txt = append(txt, s.Rule.Pattern, s.Rule.LikelyCause, s.Rule.Status)
		txt = append(txt, s.Rule.Observations...)
	}
	return retTokens(strings.Join(txt, " "))
}

func structSim(a, b *retDoc) float64 {
	type g struct {
		w  float64
		eq bool
	}
	gs := []g{{3, a.Pattern == b.Pattern}, {2, a.Status == b.Status}, {2, a.Cause == b.Cause}, {1.5, a.Mag == b.Mag},
		{1.5, a.Pct == b.Pct}, {0.5, a.Tod == b.Tod}, {1, a.NSensors == b.NSensors}}
	num, den := 0.0, 0.0
	for _, x := range gs {
		den += x.w
		if x.eq {
			num += x.w
		}
	}
	inter, union := 0, 0
	for k := range a.Domains {
		union++
		if b.Domains[k] {
			inter++
		}
	}
	for k := range b.Domains {
		if !a.Domains[k] {
			union++
		}
	}
	den += 1.5
	if union > 0 {
		num += 1.5 * float64(inter) / float64(union)
	}
	return num / den
}

func (ix *retIndex) idf(w string) float64 {
	return math.Log(float64(1+len(ix.docs))/float64(1+ix.df[w])) + 1 // smoothed: a word in every report still counts
}

func (ix *retIndex) textSim(q, d map[string]float64) float64 {
	dot, nq, nd := 0.0, 0.0, 0.0
	for w, c := range q {
		x := c * ix.idf(w)
		nq += x * x
		if dc, ok := d[w]; ok {
			dot += x * dc * ix.idf(w)
		}
	}
	for w, c := range d {
		x := c * ix.idf(w)
		nd += x * x
	}
	if nq == 0 || nd == 0 {
		return 0
	}
	return dot / math.Sqrt(nq*nd)
}

// search: matches above the threshold (best first; at most k) among reports with the same role and metric.
// skip excludes one ID (leave-one-out tuning). Caller holds ix.mu (read).
func (ix *retIndex) search(q *retDoc, qtf map[string]float64, k int, thresh float64, skip string) []RetMatch {
	var out []RetMatch
	for i := range ix.docs {
		d := &ix.docs[i]
		if d.ID == skip || d.Role != q.Role || d.Metric != q.Metric {
			continue
		}
		s := retWStruct*structSim(q, d) + retWText*ix.textSim(qtf, d.tf)
		if d.Seed {
			s *= seedPenalty
		}
		if s >= thresh {
			out = append(out, RetMatch{ID: d.ID, Score: math.Round(s*1000) / 1000, Sev: d.Sev, Label: d.Label, Seed: d.Seed})
		}
	}
	sort.Slice(out, func(i, j int) bool { return out[i].Score > out[j].Score })
	if len(out) > k {
		out = out[:k]
	}
	return out
}

func (ix *retIndex) addLocked(d retDoc) {
	for i := range ix.docs {
		if ix.docs[i].ID == d.ID { // a refined incident replaces its earlier entry
			for w := range ix.docs[i].tf {
				ix.df[w]--
			}
			ix.docs = append(ix.docs[:i], ix.docs[i+1:]...)
			break
		}
	}
	ix.docs = append(ix.docs, d)
	for w := range d.tf {
		ix.df[w]++
	}
}

// rebuild indexes every finished AI incident and tunes the threshold (leave-one-out severity agreement).
func (ix *retIndex) rebuild(incs []*Incident) {
	ix.mu.Lock()
	defer ix.mu.Unlock()
	ix.docs, ix.df, ix.thresh = nil, map[string]int{}, retDefThresh
	for _, inc := range incs {
		if d, ok := retDocOf(inc); ok {
			ix.addLocked(d)
		}
	}
	if len(ix.docs) < retMinTune {
		return
	}
	for _, th := range []float64{0.6, 0.65, 0.7, 0.75, 0.8, 0.85, 0.9} {
		agree, n := 0, 0
		for i := range ix.docs {
			d := &ix.docs[i]
			if d.Seed {
				continue
			}
			if m := ix.search(d, d.tf, 1, th, d.ID); len(m) > 0 {
				n++
				if m[0].Sev == d.Sev {
					agree++
				}
			}
		}
		if n >= 5 && float64(agree) >= 0.9*float64(n) {
			ix.thresh = th
			return
		}
	}
	ix.thresh = 0.9
}

func (ix *retIndex) add(inc *Incident) {
	d, ok := retDocOf(inc)
	if !ok {
		return
	}
	ix.mu.Lock()
	if ix.df == nil {
		ix.df, ix.thresh = map[string]int{}, retDefThresh
	}
	ix.addLocked(d)
	ix.mu.Unlock()
}

// query: the top matches for a new incident (same role and metric, above the tuned threshold).
func (ix *retIndex) query(sensors []SensorRef, title string, k int) []RetMatch {
	q, ok := retFeatures(sensors)
	if !ok {
		return nil
	}
	ix.mu.RLock()
	defer ix.mu.RUnlock()
	if len(ix.docs) == 0 {
		return nil
	}
	return ix.search(&q, retQueryText(sensors, title), k, ix.thresh, "")
}

func (ix *retIndex) doc(id string) *retDoc {
	for i := range ix.docs {
		if ix.docs[i].ID == id {
			return &ix.docs[i]
		}
	}
	return nil
}

var retNum = regexp.MustCompile(`[-+]?\d+([.,]\d+)?\s*(%|ppm|ug/m3|kW|C|pH|m3/h|m/s|level)?`)

// stripNumbers: retrieved wording without any number from the old incident.
func stripNumbers(s string) string {
	s = retNum.ReplaceAllString(s, "")
	return strings.Join(strings.Fields(s), " ")
}

// retrievalPreliminary: the instant first report for inc (rules from the live windows, plus the retrieved wording
// and severity floor on a hit). Records the top-3 matches on inc for the consistency check.
func (r *Reasoner) retrievalPreliminary(inc *Incident) *ReportCall {
	rc := fallbackReport(inc.Sensors, nil, nil)
	if rc == nil || rc.Parsed == nil {
		return rc
	}
	t0 := time.Now()
	ms := r.ret.query(inc.Sensors, inc.Title, 3)
	r.mu.Lock()
	inc.Retrieved = ms
	r.mu.Unlock()
	if len(ms) == 0 {
		rc.Note = "Preliminary from the rules - full AI report coming"
		return rc
	}
	r.ret.mu.RLock()
	best := r.ret.doc(ms[0].ID)
	var lab, act, root string
	if best != nil {
		lab, act, root = best.Label, best.Action, stripNumbers(best.RootCause)
	}
	r.ret.mu.RUnlock()
	p := rc.Parsed
	sev := normSeverity(p.Severity)
	for _, m := range ms {
		if reportRank[m.Sev] > reportRank[sev] {
			sev = m.Sev
		}
	}
	p.Severity = sev
	if lab != "" {
		p.Label = lab
	}
	if act != "" && actionAllowed(act) {
		p.Action = act
	}
	if root != "" {
		p.Explanation = strings.TrimSpace(p.Explanation + " Similar past incidents: " + root + ".")
	}
	live := 0
	for _, m := range ms {
		if !m.Seed {
			live++
		}
	}
	what := fmt.Sprintf("%d similar past incident(s)", live)
	if live == 0 {
		what = fmt.Sprintf("%d similar reference case(s) (not real past incidents)", len(ms))
	} else if live < len(ms) {
		what += fmt.Sprintf(" and %d reference case(s)", len(ms)-live)
	}
	rc.Note = fmt.Sprintf("Preliminary - based on %s (best match %.0f%%, %s) - full AI report coming", what, 100*ms[0].Score, ms[0].ID)
	rc.Model = "preliminary (retrieval + rules)"
	trace("retrieval %s: %d match(es), best %.2f, %v", inc.ID, len(ms), ms[0].Score, time.Since(t0))
	return rc
}

// retConsistency: the AI severity against the top-3 retrieved reports (logged, never changes the report).
func (r *Reasoner) retConsistency(inc *Incident) {
	if len(inc.Retrieved) == 0 || inc.Final == nil || inc.Final.Parsed == nil || inc.Final.Preliminary {
		return
	}
	ai := normSeverity(inc.Final.Parsed.Severity)
	var differ []string
	for _, m := range inc.Retrieved {
		if m.Sev != ai {
			differ = append(differ, m.ID+"="+m.Sev)
		}
	}
	if len(differ) > 0 {
		r.log(inc, fmt.Sprintf("Consistency check: AI severity %s differs from %d of %d similar past incident(s) (%s)", ai, len(differ), len(inc.Retrieved), strings.Join(differ, ", ")))
	}
}

// loadSeed adds the seed library (reference cases written from the finalized reasoner's outputs) to the index.
func (ix *retIndex) loadSeed(path string) int {
	b, err := os.ReadFile(path)
	if err != nil {
		return 0
	}
	var seeds []SeedDoc
	if json.Unmarshal(b, &seeds) != nil {
		return 0
	}
	ix.mu.Lock()
	defer ix.mu.Unlock()
	if ix.df == nil {
		ix.df, ix.thresh = map[string]int{}, retDefThresh
	}
	n := 0
	for _, s := range seeds {
		if s.ID == "" || s.Role == "" || s.Metric == "" {
			continue
		}
		d := retDoc{ID: s.ID, Role: s.Role, Metric: s.Metric, Domains: map[string]bool{}, Pattern: s.Pattern, Status: normSeverity(s.Status),
			Cause: s.Cause, Mag: s.Mag, Pct: s.Pct, Tod: s.Tod, NSensors: s.NSensors, tf: retTokens(s.Text), Sev: normSeverity(s.Severity),
			Label: s.Label, Action: s.Action, RootCause: s.RootCause, Seed: true, Prov: s.Prov}
		for _, x := range s.Domains {
			d.Domains[x] = true
		}
		ix.addLocked(d)
		n++
	}
	return n
}
