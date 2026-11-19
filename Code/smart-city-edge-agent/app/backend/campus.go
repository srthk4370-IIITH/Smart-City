package main

// Campus API input (Phase 1, owner 2026-11-16): the IIITH smart-city API replaces the sliders as the live input.
// GET only, nothing is sent:
//   /verticals/all/nodes      node registry (site tree + map, site.go), refreshed every hour
//   /verticals/all/latest     polled every campus_poll_s (5 s); only nodes whose created_at changed are ingested
//   /verticals/all/temporal   ?from=..Z&to=..Z: full-precision values. /latest rounds to integers ("8 pH", pf "1"),
//                             so a changed node is read from /temporal (the last minutes); /latest values are the
//                             fallback when /temporal fails. On start the last campus_backfill_h (12 h) are read in
//                             1 h chunks so every agent window is full at once (fast first alert); after an outage the
//                             gap is backfilled on reconnect.
// Values arrive as "421 ppm" strings (latest) or numbers (temporal); the unit is learned per node field from /latest and
// checked against the metric (W -> kW converted, anything else unexpected is rejected_unit). created_at is UTC.
// Every reading goes through Engine.IngestReading (range check, dedupe, late merge) exactly like MQTT / POST /api/ingest.
// The API cadence is ~10 min, the engine bucket 5 min: two consecutive readings <= campus_fill_max_min apart get the
// empty bucket between them linearly interpolated (what Window does for inner gaps anyway; 0 = off). States
// (occupancy, AC on, unit counts) are held instead of interpolated.
//
// Profile keys: input=campus (turns it on; sliders are then hidden), campus_url (default http://10.2.203.214:9999),
// campus_poll_s (5), campus_backfill_h (12), campus_fill_max_min (20).

import (
	"encoding/json"
	"fmt"
	"io"
	"log"
	"math"
	"net/http"
	"net/url"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"
)

const defCampusURL = "http://10.2.203.214:9999,http://127.0.0.1:9999"

// campusReprobe: how often the preferred (earlier) URL is re-tried while a later one is active.
var campusReprobe = 60 * time.Second

func campusEnabled() bool { return strings.EqualFold(profStr("input"), "campus") }

type campusField struct {
	metric string
	fields []string // first non-null wins
	units  []string // accepted units ("" = unitless)
}

// campusMap: API vertical -> fields of the bank metrics (training/extract_series.py column choices).
var campusMap = map[string][]campusField{
	"sr_aq": {{"co2", []string{"co2"}, []string{"ppm"}}, {"temp", []string{"temperature"}, []string{"°C", "C"}},
		{"rh", []string{"relative_humidity"}, []string{"%"}}, {"pm25", []string{"calibrated_pm25", "pm25"}, []string{"µg/m³", "ug/m3"}},
		{"pm10", []string{"calibrated_pm10", "pm10"}, []string{"µg/m³", "ug/m3"}}},
	"aq": {{"pm25", []string{"calibrated_pm25", "pm25"}, []string{"µg/m³", "ug/m3"}}, {"pm10", []string{"calibrated_pm10", "pm10"}, []string{"µg/m³", "ug/m3"}},
		{"temp", []string{"calibrated_temperature", "temperature"}, []string{"°C", "C"}},
		{"rh", []string{"calibrated_relative_humidity", "relative_humidity"}, []string{"%"}}},
	"wl":    {{"level", []string{"water_level"}, []string{"cm", ""}}},
	"wf":    {{"flow", []string{"flowrate"}, []string{"m³/h", "m3/h"}}},
	"wd":    {{"tds", []string{"compensated_tds_value"}, []string{"ppm"}}, {"ph", []string{"ph"}, []string{"pH", ""}}},
	"sr_em": {{"power_kw", []string{"power"}, []string{"W", "kW"}}},
	"em":    {{"power_kw", []string{"gdpower"}, []string{"W", "kW"}}, {"pf", []string{"gdpower_factor"}, []string{""}}},
	"sl":    {{"power_kw", []string{"active_power_3", "active_power"}, []string{"kW", "W"}}},
	"we": {{"temp", []string{"temperature"}, []string{"°C", "C"}}, {"rh", []string{"relative_humidity"}, []string{"%"}},
		{"wind", []string{"wind_speed"}, []string{"m/s"}}},
	"sr_ac": {{"room_temp", []string{"room_temp"}, []string{"°C", "C"}}, {"setpoint", []string{"temp_adjust"}, []string{"°C", "C"}},
		{"ac_on", []string{"start_stop_status"}, []string{""}}},
}

var campusStateMetric = map[string]bool{"occ": true, "ac_on": true, "ac_units_on": true}

type campusPrev struct {
	ts float64
	v  float64
}

type acUnitState struct {
	ts   int64
	on   bool
	temp float64
	ok   bool
}

type campusClient struct {
	base      string   // active URL
	bases     []string // ordered preference list (campus_url, comma-separated)
	baseIdx   int
	probeAt   time.Time
	switched  bool
	eng       *Engine
	http      *http.Client
	every     time.Duration
	backfillH int
	fillMax   float64

	mu         sync.Mutex
	bank       map[string]bool // node|metric
	nodes      []APINode
	nodesAt    time.Time
	online     bool
	everOK     bool
	fails      int
	lastOK     time.Time
	lastErr    string
	lastData   time.Time // wall time of the newest ingested reading's arrival
	lastDataTs int64     // newest device time ingested
	polls      int
	results    map[string]int
	seen       map[string]int64 // API node -> newest created_at ingested
	units      map[string]string
	prev       map[string]campusPrev
	acUnits    map[string]acUnitState // SR-AC unit -> last state (floor aggregates AC-<B><LL>)
	acEmitted  map[string]int64       // aggregate -> last bucket emitted
	sensorAt   map[string]int64       // bank key -> newest device time
	backfill   string                 // "" | running | done (n readings) | error
	gapFrom    time.Time
}

var campus *campusClient

// campusOnRegistry runs once, after the first successful /nodes read (phase1.go: build + save the site tree).
var campusOnRegistry func()

func newCampusClient(eng *Engine) *campusClient {
	u := profStr("campus_url")
	if u == "" {
		u = defCampusURL
	}
	var bases []string
	for _, p := range strings.Split(u, ",") {
		if p = strings.TrimRight(strings.TrimSpace(p), "/"); p != "" {
			bases = append(bases, p)
		}
	}
	if len(bases) == 0 {
		bases = []string{strings.TrimRight(defCampusURL, "/")}
	}
	c := &campusClient{base: bases[0], bases: bases, eng: eng, http: &http.Client{Timeout: 30 * time.Second},
		every: time.Duration(profInt("campus_poll_s", 5, 1, 600)) * time.Second, backfillH: profInt("campus_backfill_h", 12, 0, 24),
		fillMax: float64(profInt("campus_fill_max_min", 20, 0, 60)) * 60,
		bank:    map[string]bool{}, results: map[string]int{}, seen: map[string]int64{}, units: map[string]string{},
		prev: map[string]campusPrev{}, acUnits: map[string]acUnitState{}, acEmitted: map[string]int64{}, sensorAt: map[string]int64{}}
	if eng != nil {
		for _, s := range eng.Sensors() {
			c.bank[key(s.Node, s.Metric)] = true
		}
	}
	return c
}

// campusRegistry: the node registry (empty when the campus input is off or the API was never reached).
func campusRegistry() []APINode {
	if campus == nil {
		return nil
	}
	campus.mu.Lock()
	defer campus.mu.Unlock()
	return append([]APINode(nil), campus.nodes...)
}

func (c *campusClient) get(path string, v any) error {
	c.mu.Lock()
	base := c.base
	c.mu.Unlock()
	resp, err := c.http.Get(base + path)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode == 200 {
		noteHTTPDate(resp.Header, "campus Date header")
	}
	b, err := io.ReadAll(io.LimitReader(resp.Body, 64<<20))
	if err != nil {
		return err
	}
	if resp.StatusCode != 200 {
		return fmt.Errorf("%s: HTTP %d %s", path, resp.StatusCode, strings.TrimSpace(string(b[:min(len(b), 120)])))
	}
	return json.Unmarshal(b, v)
}

// parseValue: "421 ppm" -> 421, "ppm"; numbers pass; "null ..." / "" -> false.
func parseValue(v any) (float64, string, bool) {
	switch x := v.(type) {
	case float64:
		return x, "", !math.IsNaN(x)
	case string:
		s := strings.TrimSpace(x)
		if s == "" || strings.HasPrefix(s, "null") {
			return 0, "", false
		}
		num, unit, _ := strings.Cut(s, " ")
		f, err := strconv.ParseFloat(num, 64)
		if err != nil {
			return 0, "", false
		}
		return f, strings.TrimSpace(unit), true
	}
	return 0, "", false
}

func parseCreated(s string) (int64, bool) {
	for _, l := range []string{time.RFC3339, "2006-01-02T15:04:05Z", "2006-01-02T15:04:05.999999Z07:00", "2006-01-02 15:04:05"} {
		if t, err := time.Parse(l, s); err == nil {
			return t.Unix(), true
		}
	}
	return 0, false
}

func (c *campusClient) count(r string) { c.results[r]++ }

type campusRd struct {
	node, metric string
	v            float64
	ts           int64
	unit         string
	field        string
}

// extract: the bank readings in one API record (vertical v). latest=true: values carry their units.
func (c *campusClient) extract(v string, rec map[string]any, latest bool) []campusRd {
	node, _ := rec["node_id"].(string)
	ca, _ := rec["created_at"].(string)
	ts, ok := parseCreated(ca)
	if node == "" || !ok {
		return nil
	}
	var out []campusRd
	if v == "sr_oc" { // occupancyN = "<sensor id>:<0|1>"
		for i := 1; i <= 8; i++ {
			s, _ := rec[fmt.Sprintf("occupancy%d", i)].(string)
			id, val, ok := strings.Cut(strings.TrimSpace(s), ":")
			if !ok {
				continue
			}
			f, err := strconv.ParseFloat(strings.TrimSpace(val), 64)
			if err == nil && c.bank[key(id, "occ")] {
				out = append(out, campusRd{node: id, metric: "occ", v: f, ts: ts, field: fmt.Sprintf("occupancy%d", i)})
			}
		}
		return out
	}
	for _, f := range campusMap[v] {
		if !c.bank[key(node, f.metric)] && !(v == "sr_ac" && f.metric != "setpoint") {
			continue
		}
		for _, fld := range f.fields {
			val, unit, ok := parseValue(rec[fld])
			if !ok {
				continue
			}
			uk := node + "|" + fld
			if latest {
				c.units[uk] = unit
			} else if u, ok := c.units[uk]; ok {
				unit = u
			} else {
				unit = f.units[0]
			}
			out = append(out, campusRd{node: node, metric: f.metric, v: val, ts: ts, unit: unit, field: fld})
			break
		}
	}
	if v == "em" && c.bank[key(node, "pf")] && !hasMetric(out, "pf") { // PF = P / (sqrt3 V_LL I) on the grid side
		p, _, ok1 := parseValue(rec["gdpower"])
		vl, _, ok2 := parseValue(rec["gdvll"])
		i, _, ok3 := parseValue(rec["gdcurrent"])
		if ok1 && ok2 && ok3 && vl > 0 && i > 0 && p >= 0 {
			pf := p / (math.Sqrt(3) * vl * i)
			if pf > 0 && pf <= 1.05 {
				out = append(out, campusRd{node: node, metric: "pf", v: math.Min(pf, 1), ts: ts, field: "gdpower/(sqrt3*gdvll*gdcurrent)"})
			}
		}
	}
	return out
}

func hasMetric(rs []campusRd, m string) bool {
	for _, r := range rs {
		if r.metric == m {
			return true
		}
	}
	return false
}

// unitOK: checks the unit and converts to the bank unit. false = rejected_unit.
func unitOK(r *campusRd) bool {
	for v, fs := range campusMap {
		_ = v
		for _, f := range fs {
			if f.metric != r.metric || !contains(f.fields, r.field) {
				continue
			}
			if !contains(f.units, r.unit) {
				return false
			}
			if r.metric == "power_kw" && r.unit == "W" {
				r.v /= 1000
			}
			return true
		}
	}
	return true // derived fields (pf, occupancy)
}

// ingest: one batch of records, oldest first. Returns readings accepted (incl. late).
func (c *campusClient) ingest(recs []struct {
	v   string
	rec map[string]any
}, latest bool) int {
	var rds []campusRd
	for _, x := range recs {
		node, _ := x.rec["node_id"].(string)
		ca, _ := x.rec["created_at"].(string)
		ts, ok := parseCreated(ca)
		if !ok || ts <= c.seen[node] {
			continue
		}
		rs := c.extract(x.v, x.rec, latest)
		if x.v == "sr_ac" {
			rs = c.acAggregate(node, rs, ts)
		}
		rds = append(rds, rs...)
		c.seen[node] = ts
	}
	sort.SliceStable(rds, func(i, j int) bool { return rds[i].ts < rds[j].ts })
	n := 0
	now := nowTime().Unix()
	for _, r := range rds {
		if !c.bank[key(r.node, r.metric)] {
			continue
		}
		if !unitOK(&r) {
			c.count("rejected_unit")
			continue
		}
		k := key(r.node, r.metric)
		p, had := c.prev[k]
		if had && c.fillMax > 0 && float64(r.ts)-p.ts > bucketSec && float64(r.ts)-p.ts <= c.fillMax {
			for t := p.ts + bucketSec; t < float64(r.ts)-bucketSec/2; t += bucketSec {
				val := p.v
				if !campusStateMetric[r.metric] {
					val = p.v + (r.v-p.v)*(t-p.ts)/(float64(r.ts)-p.ts)
				}
				c.put(r.node, r.metric, val, t, now, "filled")
			}
		}
		if c.put(r.node, r.metric, r.v, float64(r.ts), now, "") {
			n++
		}
		c.prev[k] = campusPrev{float64(r.ts), r.v}
		if r.ts > c.sensorAt[k] {
			c.sensorAt[k] = r.ts
		}
		if r.ts > c.lastDataTs {
			c.lastDataTs = r.ts
		}
	}
	if n > 0 {
		c.lastData = nowTime()
	}
	return n
}

func (c *campusClient) put(node, metric string, v, ts float64, now int64, tag string) bool {
	vv := v
	res, err := c.eng.IngestReading(Reading{Node: node, Metric: metric, Value: &vv, Ts: ts, Quality: "good"}, now)
	if err != nil {
		c.count("error")
		return false
	}
	base, _, _ := strings.Cut(res, "+")
	if tag != "" {
		c.count(tag + "_" + base)
	} else {
		c.count(base)
	}
	return base == "accepted" || base == "late"
}

// acAggregate: per-floor AC aggregates (bank node AC-<B><LL>: ac_units_on, room_temp) from the unit states, one
// reading per 5-min bucket when a unit of the floor reports in a new bucket (units seen in the last 15 min count).
func (c *campusClient) acAggregate(unit string, rs []campusRd, ts int64) []campusRd {
	b, lvl, _, ok := nodeCode(unit)
	agg := "AC-" + b + lvl
	if ok && (c.bank[key(agg, "ac_units_on")] || c.bank[key(agg, "room_temp")]) {
		// a reading in a later bucket completes the pending one: emit it from the unit states before this update
		bucket := ts / bucketSec * bucketSec
		if p := c.acEmitted[agg]; p != 0 && bucket > p {
			rs = append(rs, c.acSnapshot(agg, b+lvl, p+bucketSec-1)...)
		}
		if bucket > c.acEmitted[agg] {
			c.acEmitted[agg] = bucket
		}
	}
	st := c.acUnits[unit]
	st.ts = ts
	for _, r := range rs {
		if r.node != unit {
			continue
		}
		switch r.metric {
		case "ac_on":
			st.on = r.v >= 0.5
		case "room_temp":
			if r.v >= 10 && r.v <= 45 {
				st.temp, st.ok = r.v, true
			} else {
				st.ok = false
			}
		}
	}
	c.acUnits[unit] = st
	return rs
}

// acSnapshot: the floor aggregate at time at (last bucket second) from the units seen in the 15 min before it.
func (c *campusClient) acSnapshot(agg, floor string, at int64) []campusRd {
	on, sum, n, seen := 0, 0.0, 0, 0
	for u, s := range c.acUnits {
		if !strings.HasPrefix(u, "SR-AC-"+floor+"-") || at-s.ts > 900 || s.ts > at {
			continue
		}
		seen++
		if s.on {
			on++
		}
		if s.ok {
			sum += s.temp
			n++
		}
	}
	if seen == 0 {
		return nil
	}
	out := []campusRd{{node: agg, metric: "ac_units_on", v: float64(on), ts: at, field: "start_stop_status"}}
	if n > 0 {
		out = append(out, campusRd{node: agg, metric: "room_temp", v: math.Round(sum/float64(n)*1000) / 1000, ts: at, field: "room_temp", unit: "°C"})
	}
	return out
}

type vrec = struct {
	v   string
	rec map[string]any
}

// temporal reads [from, to] (UTC) and returns the records, oldest first.
func (c *campusClient) temporal(from, to time.Time) ([]vrec, error) {
	var raw map[string]struct {
		Data []map[string]any `json:"data"`
	}
	q := fmt.Sprintf("/verticals/all/temporal?from=%s&to=%s", from.UTC().Format("2006-01-02T15:04:05Z"), to.UTC().Format("2006-01-02T15:04:05Z"))
	if err := c.get(q, &raw); err != nil {
		return nil, err
	}
	var out []vrec
	for v, d := range raw {
		if _, ok := campusMap[v]; !ok && v != "sr_oc" {
			continue
		}
		for _, r := range d.Data {
			out = append(out, vrec{v, r})
		}
	}
	sort.SliceStable(out, func(i, j int) bool {
		a, _ := out[i].rec["created_at"].(string)
		b, _ := out[j].rec["created_at"].(string)
		return a < b
	})
	return out, nil
}

func (c *campusClient) latest() ([]vrec, error) {
	var raw map[string][]map[string]any
	if err := c.get("/verticals/all/latest", &raw); err != nil {
		return nil, err
	}
	var out []vrec
	for v, d := range raw {
		if _, ok := campusMap[v]; !ok && v != "sr_oc" {
			continue
		}
		for _, r := range d {
			out = append(out, vrec{v, r})
		}
	}
	return out, nil
}

func (c *campusClient) refreshNodes() {
	var raw struct {
		Nodes []APINode `json:"nodes"`
	}
	if err := c.get("/verticals/all/nodes", &raw); err != nil {
		log.Printf("campus: nodes: %v", err)
		return
	}
	c.mu.Lock()
	first := len(c.nodes) == 0
	c.nodes, c.nodesAt = raw.Nodes, time.Now()
	c.mu.Unlock()
	if first && campusOnRegistry != nil {
		campusOnRegistry()
	}
}

// backfillRange reads [from, to] in 1 h chunks into the engine.
func (c *campusClient) backfillRange(from, to time.Time) (int, error) {
	n := 0
	for t := from; t.Before(to); t = t.Add(time.Hour) {
		e := t.Add(time.Hour)
		if e.After(to) {
			e = to
		}
		recs, err := c.temporal(t, e)
		if err != nil {
			return n, err
		}
		c.mu.Lock()
		n += c.ingest(recs, false)
		c.mu.Unlock()
	}
	return n, nil
}

// probe: does the API at base answer (short timeout, /synthetic/status)?
func (c *campusClient) probe(base string) bool {
	cl := &http.Client{Timeout: 2 * time.Second}
	resp, err := cl.Get(base + "/synthetic/status")
	if err != nil {
		return false
	}
	resp.Body.Close()
	return resp.StatusCode < 500
}

// useBase switches the active URL; the gap since the last good read is backfilled by the next poll.
func (c *campusClient) useBase(i int) {
	c.mu.Lock()
	defer c.mu.Unlock()
	if i == c.baseIdx {
		return
	}
	log.Printf("campus: link %s -> %s", c.base, c.bases[i])
	c.base, c.baseIdx, c.switched = c.bases[i], i, true
	if c.gapFrom.IsZero() && !c.lastOK.IsZero() {
		c.gapFrom = c.lastOK
	}
}

// pickBase: the first URL that answers. force = current link failed (try all in order); otherwise only re-probe the
// earlier (preferred) URLs, at most every campusReprobe.
func (c *campusClient) pickBase(force bool) {
	if len(c.bases) < 2 {
		return
	}
	c.mu.Lock()
	idx := c.baseIdx
	if !force && (idx == 0 || time.Since(c.probeAt) < campusReprobe) {
		c.mu.Unlock()
		return
	}
	c.probeAt = time.Now()
	c.mu.Unlock()
	lim := idx
	if force {
		lim = len(c.bases)
	}
	for i := 0; i < lim; i++ {
		if i != idx {
			if c.probe(c.bases[i]) {
				c.useBase(i)
				return
			}
		}
	}
}

// link: "wifi" | "usb" | "none" for the active URL (loopback = USB cable through the laptop relay).
func (c *campusClient) link() string {
	if !c.online {
		return "none"
	}
	if u, err := url.Parse(c.base); err == nil {
		if h := u.Hostname(); h == "127.0.0.1" || h == "localhost" {
			return "usb"
		}
	}
	return "wifi"
}

func (c *campusClient) setOnline(ok bool, err error) {
	c.mu.Lock()
	defer c.mu.Unlock()
	if ok {
		if !c.online && c.everOK {
			log.Printf("campus: API reachable again")
		}
		c.online, c.everOK, c.fails, c.lastOK, c.lastErr = true, true, 0, nowTime(), ""
		return
	}
	c.fails++
	c.lastErr = err.Error()
	if c.fails >= 3 && c.online {
		c.online = false
		c.gapFrom = c.lastOK
		log.Printf("campus: API unreachable (%v)", err)
	}
	if !c.everOK {
		c.online = false
	}
}

// Run: registry, latest (units), backfill, then the 5 s poll. stop closes it (tests).
func (c *campusClient) Run(stop <-chan struct{}) {
	tries := 0
	for {
		c.refreshNodes()
		recs, err := c.latest()
		c.setOnline(err == nil, err)
		if err != nil {
			c.pickBase(true)
		}
		if err == nil {
			c.mu.Lock()
			for _, x := range recs { // learn units only
				c.extract(x.v, x.rec, true)
			}
			c.mu.Unlock()
			break
		}
		tries++
		if tries == 6 && c.eng != nil { // API down at boot: the engine runs on (empty buckets); reconnect backfills
			c.eng.LiveReady()
		}
		select {
		case <-stop:
			return
		case <-time.After(c.every * 2):
		}
	}
	if c.backfillH > 0 {
		c.mu.Lock()
		c.backfill = "running"
		c.mu.Unlock()
		now := nowTime()
		n, err := c.backfillRange(now.Add(-time.Duration(c.backfillH)*time.Hour), now.Add(time.Minute))
		c.mu.Lock()
		c.backfill = fmt.Sprintf("done (%d readings, %d h)", n, c.backfillH)
		if err != nil {
			c.backfill = fmt.Sprintf("partial (%d readings): %v", n, err)
		}
		c.mu.Unlock()
		log.Printf("campus: backfill %s", c.backfill)
	}
	if c.eng != nil {
		c.eng.LiveReady()
	}
	tick := time.NewTicker(c.every)
	defer tick.Stop()
	for {
		select {
		case <-stop:
			return
		case <-tick.C:
		}
		c.poll()
	}
}

func (c *campusClient) poll() {
	c.mu.Lock()
	c.polls++
	needNodes := time.Since(c.nodesAt) > time.Hour
	c.mu.Unlock()
	c.pickBase(false) // preferred URL answering again -> switch back
	c.mu.Lock()
	wasOffline, gapFrom := (!c.online && c.everOK) || c.switched, c.gapFrom
	c.switched = false
	c.mu.Unlock()
	if needNodes {
		c.refreshNodes()
	}
	recs, err := c.latest()
	c.setOnline(err == nil, err)
	if err != nil {
		c.mu.Lock()
		c.switched = c.switched || wasOffline
		c.mu.Unlock()
		c.pickBase(true) // the next poll reads from the first URL that answers
		return
	}
	if wasOffline && !gapFrom.IsZero() { // reconnect: backfill the gap (<= backfill hours)
		from := gapFrom.Add(-10 * time.Minute)
		if lim := nowTime().Add(-time.Duration(max(c.backfillH, 1)) * time.Hour); from.Before(lim) {
			from = lim
		}
		n, _ := c.backfillRange(from, nowTime().Add(time.Minute))
		log.Printf("campus: gap backfill from %s: %d readings", from.Format(time.RFC3339), n)
		c.mu.Lock()
		c.gapFrom = time.Time{}
		c.mu.Unlock()
	}
	c.mu.Lock()
	var changed []vrec
	oldest := int64(0)
	for _, x := range recs {
		node, _ := x.rec["node_id"].(string)
		ca, _ := x.rec["created_at"].(string)
		ts, ok := parseCreated(ca)
		if !ok || ts <= c.seen[node] || !c.relevant(x.v, node) {
			continue
		}
		c.extract(x.v, x.rec, true) // units
		changed = append(changed, x)
		if s := c.seen[node]; oldest == 0 || s < oldest {
			oldest = s
		}
	}
	c.mu.Unlock()
	if len(changed) == 0 {
		return
	}
	from := time.Unix(oldest+1, 0)
	if lim := nowTime().Add(-30 * time.Minute); from.Before(lim) {
		from = lim
	}
	if t, err := c.temporal(from, nowTime().Add(time.Minute)); err == nil {
		c.mu.Lock()
		c.ingest(t, false)
		c.mu.Unlock()
	} else {
		log.Printf("campus: temporal failed (%v): using /latest values", err)
	}
	c.mu.Lock()
	c.ingest(changed, true) // whatever temporal did not have yet (seen[] skips the rest)
	c.mu.Unlock()
}

// relevant: an API node that feeds a bank sensor (directly, an occupancy gateway, or an AC unit of an aggregated floor).
func (c *campusClient) relevant(v, node string) bool {
	switch v {
	case "sr_oc":
		return true
	case "sr_ac":
		if b, lvl, _, ok := nodeCode(node); ok && c.bank[key("AC-"+b+lvl, "ac_units_on")] {
			return true
		}
	}
	for _, f := range campusMap[v] {
		if c.bank[key(node, f.metric)] {
			return true
		}
	}
	return false
}

// Status: the API link state for /api/campus/status, the health panel and the no-network page.
func (c *campusClient) Status() map[string]any {
	c.mu.Lock()
	defer c.mu.Unlock()
	out := map[string]any{"enabled": true, "url": c.base, "urls": c.bases, "link": c.link(), "link_label": linkLabel(c.link()), "online": c.online, "polls": c.polls, "results": c.results,
		"nodes": len(c.nodes), "backfill": c.backfill, "poll_s": c.every.Seconds(), "last_error": c.lastErr}
	if !c.lastOK.IsZero() {
		out["last_ok_age_s"] = int(nowTime().Sub(c.lastOK).Seconds())
	}
	if c.lastDataTs > 0 {
		out["last_data_age_s"] = nowTime().Unix() - c.lastDataTs
		out["last_data_utc"] = time.Unix(c.lastDataTs, 0).UTC().Format(time.RFC3339)
	}
	return out
}

func linkLabel(l string) string {
	switch l {
	case "wifi":
		return "Wi-Fi"
	case "usb":
		return "USB cable (laptop)"
	}
	return "none"
}

// SensorAt: newest device time ingested per bank sensor (data-health panel).
func (c *campusClient) SensorAt() map[string]int64 {
	c.mu.Lock()
	defer c.mu.Unlock()
	out := make(map[string]int64, len(c.sensorAt))
	for k, v := range c.sensorAt {
		out[k] = v
	}
	return out
}

// startCampus: input=campus -> the engine runs on the wall clock with measured feeds only, and the client starts.
func startCampus(s *Server) {
	if !campusEnabled() {
		return
	}
	campus = newCampusClient(s.eng)
	s.eng.SetLive(time.Duration(campus.backfillH) * time.Hour)
	go campus.Run(nil)
	log.Printf("campus: input from %s every %v (backfill %d h)", campus.base, campus.every, campus.backfillH)
}
