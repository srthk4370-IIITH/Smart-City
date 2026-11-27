package main

// Phase 1 additions (proofs/2026-11-16_phase1/README.md):
//   - site grouping (site_group=1): a new incident whose flagged sensors are site-linked to an open incident within the
//     link's adaptive window (V3_DESIGN §3.4 table, site.go Relation) joins its group: one group card in the app,
//     related_incidents both ways, the group root keeps the alert; scope = the LCA site node of the flagged sensors.
//   - live data-health panel   GET /api/health/data
//   - incident export          GET /api/incidents/export?format=csv|json[&days=N]
//   - daily summary            daily_summary=1: once a day (daily_summary_hour, IST, default 08) one chat-reasoner
//     summary of the previous day's stored incidents, grounded by the digest; GET /api/daily, POST /api/daily/run
//   - campus link              GET /api/campus/status (no-network page)

import (
	"context"
	"encoding/csv"
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"time"
)

func incClosed(inc *Incident) bool {
	return inc.Workflow == wfClosed || inc.Approval == "dismissed"
}

func incSeverity(inc *Incident) string {
	if inc.Severity == "" {
		return "warning"
	}
	return inc.Severity
}

func incTitle(inc *Incident) string { return inc.Title }

func siteGroupOn() bool { return profOn("site_group") }

// siteGroupLocked: join inc to a linked open incident (caller holds r.mu). Returns the root id or "".
func (r *Reasoner) siteGroupLocked(inc *Incident) string {
	cfg, ix := siteS.Get()
	if cfg == nil || ix == nil {
		return ""
	}
	var mine []string
	roles := map[string]bool{}
	for _, s := range inc.Sensors {
		if !s.Context {
			mine = append(mine, s.Node+"/"+s.Metric)
			roles[s.Role] = true
		}
	}
	inc.Scope = siteScope(ix, mine)
	if !siteGroupOn() || len(mine) == 0 {
		return ""
	}
	best, bestWin, bestRel := (*Incident)(nil), 1<<30, ""
	for _, o := range r.incidents {
		if o == inc || o.ID == inc.ID || incClosed(o) || o.Injected != inc.Injected {
			continue
		}
		root := o
		if o.SiteGroup != "" {
			if rr := r.findLocked(o.SiteGroup); rr != nil {
				root = rr
			}
		}
		if inc.CreatedSim-root.CreatedSim > 3*3600 || inc.CreatedSim < o.CreatedSim-3600 {
			continue // past the 3 h refinement: a late joiner opens its own incident
		}
		n, rs := 0, map[string]bool{}
		for k := range roles {
			rs[k] = true
		}
		for _, s := range o.Sensors {
			if !s.Context {
				n++
				rs[s.Role] = true
			}
		}
		if n+len(mine) > 12 || len(rs) > 4 {
			continue
		}
		dt := inc.CreatedSim - o.CreatedSim
		if dt < 0 {
			dt = -dt
		}
		for _, s := range o.Sensors {
			if s.Context {
				continue
			}
			for _, m := range mine {
				if ix.nodes[m] == nil || ix.nodes[s.Node+"/"+s.Metric] == nil {
					continue
				}
				rel, w, _ := ix.Relation(m, s.Node+"/"+s.Metric)
				if w == nil { // link_path walks from the first host: try the other way round too
					rel, w, _ = ix.Relation(s.Node+"/"+s.Metric, m)
				}
				if w == nil || dt > int64(*w)*60 {
					continue
				}
				// an outdoor-for path groups only when one side IS the outdoor driver (weather / outdoor air station);
				// two indoor sensors that merely share the campus weather station stay separate incidents
				if rel == "outdoor-for" && !outdoorHost(ix, m) && !outdoorHost(ix, s.Node+"/"+s.Metric) {
					continue
				}
				if *w < bestWin || *w == bestWin && best != nil && o.CreatedSim > best.CreatedSim {
					best, bestWin, bestRel = root, *w, rel
				}
			}
		}
	}
	if best == nil {
		return ""
	}
	inc.SiteGroup = best.ID
	inc.Related = appendUniq(inc.Related, best.ID)
	best.Related = appendUniq(best.Related, inc.ID)
	inc.GroupWhy = fmt.Sprintf("joined %s: %s link, window %d min", best.ID, bestRel, bestWin)
	return best.ID
}

func outdoorHost(ix *SiteIndex, sensor string) bool {
	h := ix.nodes[ix.Parent(sensor)]
	return h != nil && (h.Etype == "weather_station" || strings.HasPrefix(h.ID, "AQ-"))
}

func (r *Reasoner) findLocked(id string) *Incident {
	for _, x := range r.incidents {
		if x.ID == id {
			return x
		}
	}
	return nil
}

func appendUniq(a []string, s string) []string {
	for _, x := range a {
		if x == s {
			return a
		}
	}
	return append(a, s)
}

// siteScope: the name of the lowest site node holding every flagged sensor (equipment host when there is one).
func siteScope(ix *SiteIndex, sensors []string) string {
	var known []string
	for _, s := range sensors {
		if ix.nodes[s] != nil {
			known = append(known, s)
		}
	}
	if len(known) == 0 {
		return ""
	}
	l := ix.Parent(known[0])
	for _, s := range known[1:] {
		l = ix.LCA(l, ix.Parent(s))
	}
	if l == "" {
		return ""
	}
	return ix.Name(l)
}

// ---------------------------------------------------------------- data health

func (s *Server) dataHealth() map[string]any {
	now := nowTime().Unix()
	_, states, _ := s.eng.Snapshot()
	var seen map[string]int64
	if campus != nil {
		seen = campus.SensorAt()
	}
	staleS := int64(profInt("health_stale_min", 30, 5, 1440)) * 60
	var rows []map[string]any
	counts := map[string]int{}
	for _, st := range states {
		k := key(st.Node, st.Metric)
		row := map[string]any{"node": st.Node, "metric": st.Metric, "role": st.Role, "quality": st.Quality, "quality_reason": st.QualityWhy,
			"status": st.Status, "data_ok": st.DataOK}
		ts := seen[k]
		state := "missing"
		if ts > 0 {
			row["last_seen_utc"] = time.Unix(ts, 0).UTC().Format(time.RFC3339)
			row["age_s"] = now - ts
			state = "fresh"
			if now-ts > staleS {
				state = "stale"
			}
		} else if st.Updated > 0 {
			// slider / MQTT / /api/ingest input (or the campus API down while another feed runs): the engine's own
			// update time. Sweep 2026-11-27: with a campus URL set, live MQTT/ingest readings were reported "missing".
			state = "fresh"
			row["age_s"] = now - st.Updated
			if now-st.Updated > staleS {
				state = "stale"
			}
		}
		row["state"] = state
		counts[state]++
		rows = append(rows, row)
	}
	sort.Slice(rows, func(i, j int) bool {
		return fmt.Sprint(rows[i]["node"], rows[i]["metric"]) < fmt.Sprint(rows[j]["node"], rows[j]["metric"])
	})
	out := map[string]any{"sensors": rows, "counts": counts, "stale_after_s": staleS, "now_utc": time.Unix(now, 0).UTC().Format(time.RFC3339)}
	if campus != nil {
		out["campus"] = campus.Status()
	} else {
		out["campus"] = map[string]any{"enabled": false}
	}
	if prod.mqtt != nil {
		out["mqtt"] = prod.mqtt.Stats()
	} else {
		out["mqtt"] = map[string]any{"enabled": false}
	}
	return out
}

// networkState: what the no-network page needs. offline = the campus API (and the MQTT broker, when configured)
// cannot be reached.
func (s *Server) networkState() map[string]any {
	out := map[string]any{"campus_enabled": campus != nil}
	apiUp, mqttUp := false, false
	if campus != nil {
		st := campus.Status()
		apiUp, _ = st["online"].(bool)
		out["campus"] = st
	}
	if prod.mqtt != nil {
		st := prod.mqtt.Stats()
		mqttUp, _ = st["connected"].(bool)
		out["mqtt"] = map[string]any{"connected": mqttUp}
	}
	// sweep 2026-11-27: readings POSTed to /api/ingest (a gateway, a test feeder) also count as a live feed: the
	// full-screen "No data available" page hid a live critical incident while readings were flowing.
	fresh := false
	if t := lastIngestUnix.Load(); t > 0 && nowTime().Unix()-t <= 15*60 {
		fresh = true
	}
	out["fresh_data"] = fresh
	out["offline"] = campus != nil && !apiUp && !mqttUp && !fresh
	return out
}

// ---------------------------------------------------------------- export

func reportOf(inc *Incident) *Report {
	if inc.Final != nil && inc.Final.Parsed != nil {
		return inc.Final.Parsed
	}
	return nil
}

func (s *Server) exportIncidents(w http.ResponseWriter, r *http.Request) {
	days, _ := strconv.Atoi(r.URL.Query().Get("days"))
	cut := int64(0)
	if days > 0 {
		cut = time.Now().Add(-time.Duration(days) * 24 * time.Hour).Unix()
	}
	s.rsn.mu.RLock()
	var list []*Incident
	for _, inc := range s.rsn.incidents {
		if cut > 0 && inc.CreatedSim < cut {
			continue
		}
		list = append(list, inc)
	}
	s.rsn.mu.RUnlock()
	stamp := nowTime().In(IST).Format("20060102-1504")
	if r.URL.Query().Get("format") == "json" {
		w.Header().Set("Content-Disposition", "attachment; filename=incidents-"+stamp+".json")
		s.rsn.mu.RLock()
		b, _ := json.MarshalIndent(list, "", " ")
		s.rsn.mu.RUnlock()
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write(b)
		return
	}
	w.Header().Set("Content-Type", "text/csv; charset=utf-8")
	w.Header().Set("Content-Disposition", "attachment; filename=incidents-"+stamp+".csv")
	cw := csv.NewWriter(w)
	_ = cw.Write([]string{"id", "opened_ist", "severity", "title", "domains", "sensors", "state", "workflow", "outcome", "scope",
		"site_group", "related", "label", "root_cause", "confidence", "injected"})
	s.rsn.mu.RLock()
	for _, inc := range list {
		var sens []string
		for _, x := range inc.Sensors {
			if !x.Context {
				sens = append(sens, x.Node+"/"+x.Metric)
			}
		}
		lab, root, conf := "", "", ""
		if rp := reportOf(inc); rp != nil {
			lab, root, conf = rp.Label, rp.RootCause, strconv.FormatFloat(rp.Confidence, 'f', 2, 64)
		}
		_ = cw.Write([]string{inc.ID, time.Unix(inc.CreatedSim, 0).In(IST).Format("2006-01-02 15:04"), incSeverity(inc), inc.Title,
			strings.Join(inc.Roles, ";"), strings.Join(sens, ";"), inc.State, inc.Workflow, inc.Outcome, inc.Scope, inc.SiteGroup,
			strings.Join(inc.Related, ";"), lab, root, conf, strconv.FormatBool(inc.Injected)})
	}
	s.rsn.mu.RUnlock()
	cw.Flush()
}

// ---------------------------------------------------------------- daily summary

var chatMain *chatStore

type DailySummary struct {
	Date      string         `json:"date"` // IST day summarised
	Made      string         `json:"made"`
	Incidents int            `json:"incidents"`
	BySev     map[string]int `json:"by_severity"`
	ByDomain  map[string]int `json:"by_domain"`
	Top       []string       `json:"top"`
	Digest    string         `json:"digest"`
	AI        string         `json:"ai,omitempty"`
	AIMs      int64          `json:"ai_ms,omitempty"`
	AIError   string         `json:"ai_error,omitempty"`
}

func (s *Server) dailyDigest(day time.Time) DailySummary {
	d0 := time.Date(day.Year(), day.Month(), day.Day(), 0, 0, 0, 0, IST)
	d1 := d0.Add(24 * time.Hour)
	ds := DailySummary{Date: d0.Format("2006-01-02"), BySev: map[string]int{}, ByDomain: map[string]int{}}
	s.rsn.mu.RLock()
	var incs []*Incident
	for _, inc := range s.rsn.incidents {
		if inc.Injected || inc.CreatedSim < d0.Unix() || inc.CreatedSim >= d1.Unix() {
			continue
		}
		incs = append(incs, inc)
	}
	sort.Slice(incs, func(i, j int) bool {
		a, b := rollRank[incSeverity(incs[i])], rollRank[incSeverity(incs[j])]
		if a != b {
			return a > b
		}
		return incs[i].ID < incs[j].ID
	})
	for _, inc := range incs {
		ds.Incidents++
		ds.BySev[incSeverity(inc)]++
		for _, r := range inc.Roles {
			ds.ByDomain[r]++
		}
		if len(ds.Top) < 5 {
			ds.Top = append(ds.Top, fmt.Sprintf("[%s] %s %s (%s)", inc.ID, incSeverity(inc), inc.Title,
				time.Unix(inc.CreatedSim, 0).In(IST).Format("15:04")))
		}
	}
	s.rsn.mu.RUnlock()
	doms := make([]string, 0, len(ds.ByDomain)) // plain words, not Go map syntax (2026-11-19 hands-on)
	for d, n := range ds.ByDomain {
		doms = append(doms, fmt.Sprintf("%s %d", strings.ReplaceAll(d, "_", " "), n))
	}
	sort.Strings(doms)
	ds.Digest = fmt.Sprintf("%s: %d incidents (critical %d, warning %d); by area: %s.", ds.Date, ds.Incidents, ds.BySev["critical"], ds.BySev["warning"], strings.Join(doms, ", "))
	if len(ds.Top) > 0 {
		ds.Digest += " Top: " + strings.Join(ds.Top, "; ")
	}
	return ds
}

func (s *Server) dailyDir() string { return filepath.Join(s.dir, "state", "daily") }

func (s *Server) runDaily(ctx context.Context, day time.Time, ai bool) DailySummary {
	ds := s.dailyDigest(day)
	if ai && chatMain != nil && ds.Incidents > 0 {
		q := fmt.Sprintf("Daily report: summarise the incidents of %s (yesterday) in at most 3 sentences for the facility manager, "+
			"with the most serious first and [INC-] citations.", ds.Date)
		t0 := time.Now()
		ans := chatMain.answer(ctx, s.rsn, nil, q)
		ds.AIMs = time.Since(t0).Milliseconds()
		if ans.Error || ans.Busy {
			ds.AIError = ans.Text
		} else {
			ds.AI = ans.Text
		}
	} else if ds.Incidents == 0 {
		ds.AI = "No incidents on " + ds.Date + "."
	}
	ds.Made = nowTime().UTC().Format(time.RFC3339)
	_ = os.MkdirAll(s.dailyDir(), 0o755)
	b, _ := json.MarshalIndent(ds, "", " ")
	_ = atomicWrite(filepath.Join(s.dailyDir(), ds.Date+".json"), b, 0o644)
	return ds
}

func (s *Server) dailyLoop() {
	hour := profInt("daily_summary_hour", 8, 0, 23)
	for {
		now := nowTime().In(IST)
		y := now.Add(-24 * time.Hour)
		f := filepath.Join(s.dailyDir(), y.Format("2006-01-02")+".json")
		if _, err := os.Stat(f); err != nil && now.Hour() >= hour && !s.rsn.Busy() {
			ctx, cancel := context.WithTimeout(context.Background(), 10*time.Minute)
			ds := s.runDaily(ctx, y, true)
			cancel()
			log.Printf("daily: summary of %s (%d incidents, AI %d ms)", ds.Date, ds.Incidents, ds.AIMs)
		}
		time.Sleep(5 * time.Minute)
	}
}

// ---------------------------------------------------------------- routes

func (s *Server) phase1Routes(mux *http.ServeMux) {
	s.siteRoutes(mux)
	s.rulesRoutes(mux)
	mux.HandleFunc("/api/health/data", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Cache-Control", "no-store")
		writeJSON(w, s.dataHealth())
	})
	mux.HandleFunc("/api/campus/status", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Cache-Control", "no-store")
		writeJSON(w, s.networkState())
	})
	mux.HandleFunc("/api/incidents/export", s.exportIncidents)
	mux.HandleFunc("/api/daily", func(w http.ResponseWriter, r *http.Request) {
		if d := r.URL.Query().Get("date"); d != "" {
			b, err := os.ReadFile(filepath.Join(s.dailyDir(), filepath.Base(d)+".json"))
			if err != nil {
				http.Error(w, "no summary for "+d, 404)
				return
			}
			w.Header().Set("Content-Type", "application/json")
			_, _ = w.Write(b)
			return
		}
		ents, _ := os.ReadDir(s.dailyDir())
		var out []DailySummary
		for i := len(ents) - 1; i >= 0 && len(out) < 30; i-- {
			b, err := os.ReadFile(filepath.Join(s.dailyDir(), ents[i].Name()))
			var d DailySummary
			if err == nil && json.Unmarshal(b, &d) == nil {
				out = append(out, d)
			}
		}
		writeJSON(w, map[string]any{"enabled": profOn("daily_summary"), "days": out, "today_digest": s.dailyDigest(nowTime().In(IST)).Digest})
	})
	mux.HandleFunc("/api/daily/run", func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			http.Error(w, "POST", 405)
			return
		}
		day := nowTime().In(IST).Add(-24 * time.Hour)
		if d := r.URL.Query().Get("date"); d != "" {
			t, err := time.ParseInLocation("2006-01-02", d, IST)
			if err != nil {
				http.Error(w, "date YYYY-MM-DD", 400)
				return
			}
			day = t
		}
		ctx, cancel := context.WithTimeout(r.Context(), 10*time.Minute)
		defer cancel()
		writeJSON(w, s.runDaily(ctx, day, r.URL.Query().Get("ai") != "0"))
	})
}

// startPhase1: campus input, site store, daily summary loop.
func startPhase1(s *Server) {
	// save the auto site tree as soon as the registry is in (before the backfill), so the first incidents get a scope
	campusOnRegistry = func() { s.siteEnsure() }
	startCampus(s)
	if profOn("daily_summary") {
		safeGo("daily loop", s.dailyLoop)
	}
}
