package main

// Campus API input against a fake API (httptest): unit parsing + conversion, 12 h backfill through IngestReading on the
// live engine, the 10-min -> 5-min interpolation, AC floor aggregate, occupancy gateway channels, derived PF, unit
// rejection, offline detection + gap backfill, data-health / network state, export, grouping.

import (
	"encoding/csv"
	"encoding/json"
	"errors"
	"fmt"
	"math"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

type fakeAPI struct {
	mu      sync.Mutex
	now     time.Time
	down    atomic.Bool
	tempReq atomic.Int32
}

// rec: the API records of one 10-min step k (ts = now - k*10 min).
func (f *fakeAPI) recs(ts time.Time, latest bool) map[string][]map[string]any {
	ca := ts.UTC().Format("2006-01-02T15:04:05Z")
	k := float64(ts.Unix()%86400) / 600
	co2 := 450 + 10*k
	val := func(v float64, unit string) any {
		if latest {
			return fmt.Sprintf("%.0f %s", v, unit) // /latest rounds to integers
		}
		return v
	}
	on := 0.0
	if int(k)%2 == 0 {
		on = 1
	}
	out := map[string][]map[string]any{
		"sr_aq": {{"node_id": "SR-AQ-KH03-03", "created_at": ca, "co2": val(co2, "ppm"), "temperature": val(24.37, "°C"), "relative_humidity": val(55.5, "%")}},
		"em": {{"node_id": "EM-CR-SB00-00", "created_at": ca, "gdpower": val(362405.106, "W"), "gdvll": val(11259.347, "V"),
			"gdcurrent": val(18.679, "A"), "power_factor": 0}},
		"wd":    {{"node_id": "WM-WD-KH98-00", "created_at": ca, "ph": val(8.146, "pH"), "compensated_tds_value": val(3.1, "furlongs")}},
		"sr_oc": {{"node_id": "SR-OC-GW-KH95-00", "created_at": ca, "occupancy1": "SR-OC-GW-KH95-01:1 ", "occupancy2": "SR-OC-GW-KH95-02:0 "}},
		"sr_ac": {{"node_id": "SR-AC-KH03-01", "created_at": ca, "room_temp": val(27, "°C"), "start_stop_status": val(on, ""), "temp_adjust": val(24, "°C")},
			{"node_id": "SR-AC-KH03-02", "created_at": ca, "room_temp": val(25, "°C"), "start_stop_status": val(1, ""), "temp_adjust": val(24, "°C")}},
		"wn": {{"node_id": "WN-LP01-03", "created_at": ca, "rssi": "-82 dBm"}},
	}
	return out
}

func (f *fakeAPI) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	if f.down.Load() {
		http.Error(w, "down", 503)
		return
	}
	f.mu.Lock()
	now := f.now
	f.mu.Unlock()
	switch r.URL.Path {
	case "/verticals/all/nodes":
		_ = json.NewEncoder(w).Encode(map[string]any{"nodes": []APINode{{NodeID: "SR-AQ-KH03-03", Name: "Kohli Block", X: 300, Y: 600, Type: "SR-AQ"}}})
	case "/verticals/all/latest":
		last := now.Add(-time.Duration(now.Unix()%600) * time.Second)
		_ = json.NewEncoder(w).Encode(f.recs(last, true))
	case "/verticals/all/temporal":
		f.tempReq.Add(1)
		from, err1 := time.Parse("2006-01-02T15:04:05Z", r.URL.Query().Get("from"))
		to, err2 := time.Parse("2006-01-02T15:04:05Z", r.URL.Query().Get("to"))
		if err1 != nil || err2 != nil {
			http.Error(w, `{"error": "Missing 'from' or 'to' timestamp"}`, 400)
			return
		}
		out := map[string]map[string]any{}
		t := from.Add(time.Duration(600-from.Unix()%600) % 600 * time.Second)
		for ; !t.After(to) && !t.After(now); t = t.Add(10 * time.Minute) {
			for v, rs := range f.recs(t, false) {
				if out[v] == nil {
					out[v] = map[string]any{"table": v, "data": []any{}}
				}
				for _, x := range rs {
					out[v]["data"] = append(out[v]["data"].([]any), x)
				}
			}
		}
		_ = json.NewEncoder(w).Encode(out)
	default:
		http.NotFound(w, r)
	}
}

func TestParseValue(t *testing.T) {
	for _, c := range []struct {
		in   any
		v    float64
		unit string
		ok   bool
	}{{"421 ppm", 421, "ppm", true}, {"19 °C", 19, "°C", true}, {"null kWh", 0, "", false}, {"63 ", 63, "", true}, {12.5, 12.5, "", true}, {"", 0, "", false}} {
		v, u, ok := parseValue(c.in)
		if v != c.v || u != c.unit || ok != c.ok {
			t.Errorf("%v -> %v %q %v", c.in, v, u, ok)
		}
	}
}

func TestCampusBackfillLiveOffline(t *testing.T) {
	f := &fakeAPI{now: time.Now()}
	srv := httptest.NewServer(f)
	defer srv.Close()
	t.Setenv("SCE_CAMPUS_URL", srv.URL)
	t.Setenv("SCE_CAMPUS_POLL_S", "1")
	eng := newTestEngine(t)
	c := newCampusClient(eng)
	eng.SetLive(12 * time.Hour)
	campus = c
	defer func() { campus = nil }()
	stop := make(chan struct{})
	go c.Run(stop)
	defer close(stop)
	deadline := time.Now().Add(20 * time.Second)
	for {
		c.mu.Lock()
		bf := c.backfill
		c.mu.Unlock()
		if strings.HasPrefix(bf, "done") || strings.HasPrefix(bf, "partial") {
			t.Log("backfill:", bf)
			break
		}
		if time.Now().After(deadline) {
			t.Fatal("no backfill")
		}
		time.Sleep(50 * time.Millisecond)
	}
	for i := 0; i < 3; i++ { // catch up 12 h of buckets (160 per poll)
		eng.Tick()
	}
	h := eng.HistoryAt("SR-AQ-KH03-03", "co2", eng.sim, 144)
	if len(h) == 0 { // the newest 10-min reading may sit one bucket back (Window forward-fills the live edge)
		h = eng.HistoryAt("SR-AQ-KH03-03", "co2", eng.sim-bucketSec, 144)
	}
	if len(h) < 130 {
		t.Fatalf("co2 history after backfill: %d points (want ~144: 10-min readings + interpolated buckets)", len(h))
	}
	eng.mu.RLock()
	pw := eng.series[key("EM-CR-SB00-00", "power_kw")]
	pf := eng.series[key("EM-CR-SB00-00", "pf")]
	ac := eng.series[key("AC-KH03", "ac_units_on")]
	occ := eng.series[key("SR-OC-GW-KH95-01", "occ")]
	tds := eng.series[key("WM-WD-KH98-00", "tds")]
	ph := eng.series[key("WM-WD-KH98-00", "ph")]
	eng.mu.RUnlock()
	anyV := func(m map[int64]float64) float64 {
		for _, v := range m {
			return v
		}
		return math.NaN()
	}
	if v := anyV(pw); math.Abs(v-362.405) > 0.01 {
		t.Errorf("power_kw %v (W -> kW)", v)
	}
	if v := anyV(pf); math.Abs(v-0.995) > 0.01 {
		t.Errorf("derived pf %v", v)
	}
	if len(ac) < 100 || len(occ) < 100 {
		t.Errorf("AC aggregate %d / occupancy %d buckets", len(ac), len(occ))
	}
	odd := 0
	for _, v := range ac {
		if v < 1 || v > 2 {
			odd++ // only the first bucket can miss a unit that has not reported yet
		}
	}
	if odd > 1 {
		t.Errorf("ac_units_on outside 1..2 in %d buckets", odd)
	}
	if len(tds) != 0 {
		t.Errorf("tds with unit 'furlongs' must be rejected, got %d", len(tds))
	}
	if v := anyV(ph); math.Abs(v-8.146) > 1e-6 {
		t.Errorf("ph %v: temporal full precision expected, not the rounded /latest", v)
	}
	st := c.Status()
	if st["online"] != true || c.results["rejected_unit"] == 0 {
		t.Errorf("status %v", st)
	}
	// live poll: a new 10-min reading arrives
	f.mu.Lock()
	f.now = f.now.Add(10 * time.Minute)
	f.mu.Unlock()
	n0 := f.tempReq.Load()
	time.Sleep(2500 * time.Millisecond)
	if f.tempReq.Load() == n0 {
		t.Error("a changed node did not trigger a /temporal read")
	}
	// outage -> offline -> reconnect backfills the gap
	f.down.Store(true)
	time.Sleep(4500 * time.Millisecond)
	s := &Server{eng: eng}
	if ns := s.networkState(); ns["offline"] != true {
		t.Fatalf("network state while down: %v", ns)
	}
	f.down.Store(false)
	time.Sleep(2500 * time.Millisecond)
	if ns := s.networkState(); ns["offline"] != false {
		t.Fatalf("network state after reconnect: %v", ns)
	}
	dh := s.dataHealth()
	if dh["counts"].(map[string]int)["fresh"] < 5 {
		t.Errorf("data health %v", dh["counts"])
	}
}

func TestSiteGroupingAndExport(t *testing.T) {
	raw := mustRead(t, "testdata/campus_nodes.json")
	var nf struct {
		Nodes []APINode `json:"nodes"`
	}
	_ = json.Unmarshal(raw, &nf)
	eng := newTestEngine(t)
	siteS = &siteStore{}
	if err := siteS.Save(BuildSiteFromAPI(nf.Nodes, eng.Sensors()), "auto"); err != nil {
		t.Fatal(err)
	}
	defer func() { siteS = &siteStore{} }()
	t.Setenv("SCE_SITE_GROUP", "1")
	r := &Reasoner{eng: eng}
	mk := func(node, metric, role string, at int64) *Incident {
		inc := &Incident{CreatedSim: at, Severity: "warning", Title: node + " " + metric, Roles: []string{role},
			Sensors: []SensorRef{{Node: node, Metric: metric, Role: role}}}
		r.mu.Lock()
		r.seq++
		inc.ID = fmt.Sprintf("INC-%04d", r.seq)
		r.siteGroupLocked(inc)
		r.incidents = append(r.incidents, inc)
		r.mu.Unlock()
		return inc
	}
	t0 := int64(1795000000)
	a := mk("SR-OC-GW-KH95-01", "occ", "occupancy", t0)
	b := mk("SR-AQ-KH03-03", "co2", "air_quality", t0+600)     // same room, 10 min later: joins
	c := mk("SR-AQ-KH03-03", "temp", "air_quality", t0+3*3600) // same room but 3 h later: own incident
	d := mk("WM-WL-KH98-00", "level", "water", t0+900)         // water tank, no site link to the room in 15 min
	if b.SiteGroup != a.ID || c.SiteGroup != "" || d.SiteGroup != "" {
		t.Fatalf("groups: b=%q c=%q d=%q (%s)", b.SiteGroup, c.SiteGroup, d.SiteGroup, b.GroupWhy)
	}
	if b.Scope == "" || len(a.Related) != 1 {
		t.Fatalf("scope %q related %v", b.Scope, a.Related)
	}
	s := &Server{eng: eng, rsn: r}
	rec := httptest.NewRecorder()
	s.exportIncidents(rec, httptest.NewRequest("GET", "/api/incidents/export?format=csv", nil))
	rows, err := csv.NewReader(strings.NewReader(rec.Body.String())).ReadAll()
	if err != nil || len(rows) != 5 || rows[2][10] != a.ID {
		t.Fatalf("csv export: %v %v", err, rows)
	}
	rec = httptest.NewRecorder()
	s.exportIncidents(rec, httptest.NewRequest("GET", "/api/incidents/export?format=json", nil))
	var js []map[string]any
	if json.Unmarshal(rec.Body.Bytes(), &js) != nil || len(js) != 4 {
		t.Fatal("json export")
	}
	ds := s.dailyDigest(time.Unix(t0, 0).In(IST))
	if ds.Incidents == 0 || !strings.Contains(ds.Digest, "incidents") {
		t.Fatalf("digest %+v", ds)
	}
	// site chat tools over the live site
	st := liveSiteTools(r)
	if res := st.SiteStatus("KH"); res["status"] == nil {
		t.Fatalf("site_status %v", res)
	}
}

func mustRead(t *testing.T, p string) []byte {
	b, err := os.ReadFile(p)
	if err != nil {
		t.Fatal(err)
	}
	return b
}

// Fast first alert: a sensor critical for the last 50 min of the backfill raises its candidate on the first catch-up
// poll; an event that ended 5 h ago does not.
func TestLiveCatchUpFirstAlert(t *testing.T) {
	eng := newTestEngine(t)
	eng.SetLive(12 * time.Hour)
	now := nowTime().Unix()
	for ts := now - 12*3600 + 300; ts <= now; ts += 300 {
		v := 600.0
		if ts > now-50*60 || ts > now-6*3600 && ts < now-5*3600 {
			v = 1700
		}
		vv := v
		if _, err := eng.IngestReading(Reading{Node: "SR-AQ-KH03-03", Metric: "co2", Value: &vv, Ts: float64(ts)}, now); err != nil {
			t.Fatal(err)
		}
	}
	var got []Candidate
	eng.onEvent = func(c []Candidate) { got = append(got, c...) }
	eng.Tick() // held: nothing happens before LiveReady
	if len(got) > 0 {
		t.Fatal("ticked during the backfill hold")
	}
	eng.LiveReady()
	for i := 0; i < 3; i++ {
		eng.Tick()
	}
	n := 0
	for _, c := range got {
		if c.Node == "SR-AQ-KH03-03" && c.Metric == "co2" {
			n++
			if now-c.End > 3600 {
				t.Errorf("alert from the old event at %d s ago", now-c.End)
			}
		}
	}
	if n == 0 {
		t.Fatalf("no first alert after the catch-up (%d candidates)", len(got))
	}
}

// Scenario injections (chaos, stories, fastcheck-style demos) still work on the live engine: they ride on the real
// readings and open an injected incident.
func TestLiveInjectionOnMeasured(t *testing.T) {
	eng := newTestEngine(t)
	eng.SetLive(4 * time.Hour)
	now := nowTime().Unix()
	put := func(ts int64) {
		v := 600.0
		if _, err := eng.IngestReading(Reading{Node: "SR-AQ-KH03-03", Metric: "co2", Value: &v, Ts: float64(ts)}, nowTime().Unix()); err != nil {
			t.Fatal(err)
		}
	}
	for ts := now - 4*3600 + 300; ts <= now; ts += 300 {
		put(ts)
	}
	eng.LiveReady()
	eng.Tick()
	var sc *Scenario
	for i := range Scenarios {
		for _, tg := range Scenarios[i].Targets {
			if tg.Node == "SR-AQ-KH03-03" && tg.Metric == "co2" && sc == nil {
				sc = &Scenarios[i]
			}
		}
	}
	if sc == nil {
		t.Skip("no CO2 scenario")
	}
	eng.Inject(*sc)
	var got []Candidate
	eng.onEvent = func(c []Candidate) { got = append(got, c...) }
	saved := clockOffset
	defer func() { clockOffset = saved }()
	for i := 1; i <= 40 && len(got) == 0; i++ {
		clockOffset = saved + time.Duration(i)*5*time.Minute
		put(nowTime().Unix())
		eng.Tick()
	}
	if len(got) == 0 || !got[0].Injected {
		t.Fatalf("no injected candidate from scenario %s on the live engine (%d)", sc.ID, len(got))
	}
	t.Logf("scenario %s -> injected candidate %s/%s %s", sc.ID, got[0].Node, got[0].Metric, got[0].Finding.Status)
}

// Ordered campus_url list: Wi-Fi first, USB relay second; switch on failure, switch back when the preferred answers.
func TestCampusLinkFailover(t *testing.T) {
	a, b := &fakeAPI{now: time.Now()}, &fakeAPI{now: time.Now()}
	sa, sb := httptest.NewServer(a), httptest.NewServer(b)
	defer sa.Close()
	defer sb.Close()
	t.Setenv("SCE_CAMPUS_URL", sa.URL+", "+sb.URL+"/")
	t.Setenv("SCE_CAMPUS_POLL_S", "1")
	old := campusReprobe
	campusReprobe = 50 * time.Millisecond
	defer func() { campusReprobe = old }()
	c := newCampusClient(newTestEngine(t))
	if len(c.bases) != 2 || c.base != sa.URL || c.bases[1] != sb.URL {
		t.Fatalf("bases %v base %s", c.bases, c.base)
	}
	if c.link() != "none" || linkLabel("none") != "none" || linkLabel("usb") != "USB cable (laptop)" || linkLabel("wifi") != "Wi-Fi" {
		t.Fatal("link labels")
	}
	a.down.Store(true) // primary down -> secondary
	if err := func() error { var v map[string]any; return c.get("/verticals/all/nodes", &v) }(); err == nil {
		t.Fatal("primary should fail")
	}
	c.pickBase(true)
	if c.base != sb.URL || c.baseIdx != 1 || !c.switched {
		t.Fatalf("no switch to secondary: %s", c.base)
	}
	var v map[string]any
	if err := c.get("/verticals/all/nodes", &v); err != nil {
		t.Fatal(err)
	}
	// primary back -> switch back after the re-probe interval
	a.down.Store(false)
	time.Sleep(80 * time.Millisecond)
	c.pickBase(false)
	if c.base != sa.URL || c.baseIdx != 0 {
		t.Fatalf("no switch back: %s", c.base)
	}
	// both down -> stays, offline state
	a.down.Store(true)
	b.down.Store(true)
	c.pickBase(true)
	for i := 0; i < 3; i++ {
		c.setOnline(false, fmt.Errorf("down"))
	}
	c.everOK = true
	c.setOnline(false, fmt.Errorf("down"))
	st := c.Status()
	if st["link"] != "none" || st["link_label"] != "none" || st["online"] != false {
		t.Fatalf("offline state: %v", st)
	}
	// loopback = USB label
	c.online, c.base = true, "http://127.0.0.1:9999"
	if c.link() != "usb" {
		t.Fatal("usb")
	}
	c.base = "http://10.2.203.214:9999"
	if c.link() != "wifi" {
		t.Fatal("wifi")
	}
}

// Device RTC 3 years behind + a correction offset: every request range and age must use the corrected wall clock.
func TestCampusUsesCorrectedClock(t *testing.T) {
	rtcReset(t, false)
	saved := clockOffset
	clockOffset = time.Since(devClock())
	defer func() { clockOffset = saved }()
	f := &fakeAPI{now: time.Now()}
	var bad atomic.Int32
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/verticals/all/temporal" {
			fr, e1 := time.Parse(time.RFC3339, r.URL.Query().Get("from"))
			to, e2 := time.Parse(time.RFC3339, r.URL.Query().Get("to"))
			if e1 != nil || e2 != nil || to.Before(fr) || time.Since(to) > 3*time.Hour || time.Until(to) > time.Hour {
				bad.Add(1)
				http.Error(w, "bad range", 400)
				return
			}
		}
		f.ServeHTTP(w, r)
	}))
	defer srv.Close()
	t.Setenv("SCE_CAMPUS_URL", srv.URL)
	c := newCampusClient(newTestEngine(t))
	if d := nowTime().Sub(time.Now()); d > time.Hour || d < -time.Hour {
		t.Fatalf("corrected clock off by %v", d)
	}
	n, err := c.backfillRange(nowTime().Add(-2*time.Hour), nowTime().Add(time.Minute))
	if err != nil || bad.Load() != 0 {
		t.Fatalf("backfill n=%d err=%v bad=%d", n, err, bad.Load())
	}
	c.setOnline(true, nil)
	if a := c.Status()["last_ok_age_s"].(int); a < 0 || a > 5 {
		t.Fatalf("last_ok_age_s %d", a)
	}
	c.poll()
	if bad.Load() != 0 {
		t.Fatalf("poll sent %d bad ranges", bad.Load())
	}
}

// night sweep 2026-11-27 #108: a down campus API is retried less and less often (cap 2 min) and reports since when.
func TestCampusBackoffOfflineSince(t *testing.T) {
	if campusBackoff(5*time.Second, 9) != 0 || campusBackoff(5*time.Second, 10) != 10*time.Second ||
		campusBackoff(5*time.Second, 12) != 40*time.Second || campusBackoff(5*time.Second, 40) != 2*time.Minute {
		t.Fatal("backoff", campusBackoff(5*time.Second, 12), campusBackoff(5*time.Second, 40))
	}
	c := &campusClient{every: 5 * time.Second, results: map[string]int{}}
	c.setOnline(true, nil)
	good := c.lastOK
	for i := 0; i < 12; i++ {
		c.setOnline(false, errors.New("connection refused"))
	}
	st := c.Status()
	if st["offline_since_unix"].(int64) != good.Unix() || st["online"] != false {
		t.Fatal("offline since", st)
	}
	c.poll() // inside the back-off window: skipped, no request
	if c.Status()["skipped_polls"].(int) != 1 {
		t.Fatal("poll not skipped", c.Status())
	}
	c.setOnline(true, nil)
	if c.Status()["offline_since_unix"].(int64) != 0 {
		t.Fatal("not cleared", c.Status())
	}
}
