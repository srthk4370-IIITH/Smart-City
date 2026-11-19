package main

// Site model + chat r5 parity vs core/sitegraph.py and rsn/gen_chat_v4.SiteTools (site_tools_fixtures.json), the r5
// header vs tools_v4.json, and the API-registry tree builder on a real /nodes snapshot.

import (
	"encoding/json"
	"os"
	"reflect"
	"strings"
	"testing"
)

const tools4Path = "../../../../proofs/2026-11-13_v3_data/rsn/data/final/tools_v4.json"

type siteFx struct {
	Sites []SiteConfig `json:"sites"`
	Rows  []struct {
		Site      int                       `json:"site"`
		Status    map[string]string         `json:"status"`
		Incidents map[string]map[string]any `json:"incidents"`
		Calls     []struct {
			Name   string         `json:"name"`
			Args   map[string]any `json:"args"`
			Result any            `json:"result"`
		} `json:"calls"`
		Relations []struct {
			A, B     string
			Relation string `json:"relation"`
			Window   *int   `json:"window"`
			Hops     *int   `json:"hops"`
		} `json:"relations"`
		Suspects []struct {
			Onsets   map[string]int64 `json:"onsets"`
			Suspects []SiteSuspect    `json:"suspects"`
		} `json:"suspects"`
	} `json:"rows"`
}

func loadSiteFx(t *testing.T) siteFx {
	raw, err := os.ReadFile("testdata/site_tools_fixtures.json")
	if err != nil {
		t.Fatal(err)
	}
	var fx siteFx
	if err := json.Unmarshal(raw, &fx); err != nil {
		t.Fatal(err)
	}
	return fx
}

func roundTrip(v any) any {
	b, _ := json.Marshal(v)
	var out any
	_ = json.Unmarshal(b, &out)
	return out
}

func TestSiteToolsParity(t *testing.T) {
	fx := loadSiteFx(t)
	n, bad := 0, 0
	for _, r := range fx.Rows {
		if r.Calls == nil {
			continue
		}
		st := NewSiteTools(&fx.Sites[r.Site], r.Status, r.Incidents)
		for _, c := range r.Calls {
			n++
			got, err := st.Call(c.Name, c.Args)
			if err != nil {
				t.Fatal(err)
			}
			if !reflect.DeepEqual(roundTrip(got), roundTrip(c.Result)) {
				bad++
				if bad <= 4 {
					g, _ := json.Marshal(got)
					w, _ := json.Marshal(c.Result)
					t.Errorf("site %d %s %v:\n go %s\n py %s", r.Site, c.Name, c.Args, trunc(string(g), 600), trunc(string(w), 600))
				}
			}
		}
	}
	t.Logf("%d site tool calls on %d sites: %d mismatches", n, len(fx.Sites), bad)
	if n < 200 || bad > 0 {
		t.Fail()
	}
}

func TestSiteRelationAndSuspectParity(t *testing.T) {
	fx := loadSiteFx(t)
	nr, ns, bad := 0, 0, 0
	for _, r := range fx.Rows {
		if r.Relations == nil {
			continue
		}
		ix := NewSiteIndex(&fx.Sites[r.Site])
		for _, x := range r.Relations {
			nr++
			rel, w, h := ix.Relation(x.A, x.B)
			if rel != x.Relation || !reflect.DeepEqual(w, x.Window) || !reflect.DeepEqual(h, x.Hops) {
				bad++
				if bad <= 4 {
					t.Errorf("site %d relation %s %s: go %s %v %v py %s %v %v", r.Site, x.A, x.B, rel, deref(w), deref(h), x.Relation, deref(x.Window), deref(x.Hops))
				}
			}
		}
		for _, s := range r.Suspects {
			ns++
			got := ix.Suspects(s.Onsets)
			if !reflect.DeepEqual(roundTrip(got), roundTrip(s.Suspects)) {
				bad++
				if bad <= 6 {
					t.Errorf("site %d suspects go %+v py %+v", r.Site, got, s.Suspects)
				}
			}
		}
	}
	t.Logf("%d relations, %d suspect sets: %d mismatches", nr, ns, bad)
	if bad > 0 || nr < 100 {
		t.Fail()
	}
}

func deref(p *int) any {
	if p == nil {
		return nil
	}
	return *p
}

func headerTools(t *testing.T, h string) []any {
	var out []any
	for _, l := range strings.Split(h, "\n") {
		if strings.HasPrefix(l, `{"type": "function"`) {
			var v any
			if err := json.Unmarshal([]byte(l), &v); err != nil {
				t.Fatal(err)
			}
			out = append(out, v)
		}
	}
	return out
}

func TestChatHeaderR5MatchesTraining(t *testing.T) {
	if !strings.HasPrefix(chatSystemR5, strings.SplitN(chatSystemR3, "\n- The tools are read-only:", 2)[0]) || !strings.Contains(chatSystemR5, "use the site tools") {
		t.Fatal("chat_system_r5.txt is not r3 + SITE_RULE")
	}
	if len(headerTools(t, chatHeaderR5)) != len(headerTools(t, chatHeaderR3))+4 {
		t.Fatal("r5 header must be the r3 tools + 4 site tools")
	}
	raw, err := os.ReadFile(tools4Path)
	if err != nil {
		t.Skip("tools_v4.json not here: ", err)
	}
	var tv map[string]any
	_ = json.Unmarshal(raw, &tv)
	if !reflect.DeepEqual(headerTools(t, chatHeaderR5), tv["chat_r5"]) {
		t.Fatal("chat_header_r5 tools != tools_v4.json chat_r5")
	}
	if !reflect.DeepEqual(headerTools(t, v4Header()), tv["incident_v4"]) {
		t.Fatal("v4 incident header tools != tools_v4.json incident_v4")
	}
	if chatSiteV4() {
		t.Fatal("site chat must be off by default")
	}
}

func TestBuildSiteFromAPI(t *testing.T) {
	raw, err := os.ReadFile("testdata/campus_nodes.json")
	if err != nil {
		t.Fatal(err)
	}
	var nf struct {
		Nodes []APINode `json:"nodes"`
	}
	if err := json.Unmarshal(raw, &nf); err != nil {
		t.Fatal(err)
	}
	e := newTestEngine(t)
	c := BuildSiteFromAPI(nf.Nodes, e.Sensors())
	if bad := ValidateSite(c); len(bad) > 0 {
		t.Fatalf("auto tree invalid: %v", bad)
	}
	ix := NewSiteIndex(c)
	kinds := map[string]int{}
	for _, n := range c.Nodes {
		kinds[n.Kind]++
	}
	// every bank sensor is a leaf with a card
	for _, s := range e.Sensors() {
		if s.Role == "hvac" && s.Metric != "room_temp" && strings.HasPrefix(s.Node, "SR-AC") {
			continue
		}
		if ix.nodes[s.Node+"/"+s.Metric] == nil {
			t.Errorf("bank sensor %s/%s not in the tree", s.Node, s.Metric)
		}
	}
	if !strings.Contains(ix.Name("KH"), "Kohli") || ix.kind("KH-03") != "floor" {
		t.Errorf("building / floor naming: %q %q", ix.Name("KH"), ix.kind("KH-03"))
	}
	// cross-domain stories the rules must allow: occupancy -> CO2 same room, AC -> room temp, weather -> room
	if rel, w, _ := ix.Relation("SR-OC-GW-KH95-01/occ", "SR-AQ-KH03-03/co2"); rel != "located-in" || *w != 15 {
		t.Errorf("occ->co2: %s", rel)
	}
	if rel, _, _ := ix.Relation("AC-KH03/ac_units_on", "SR-AQ-KH03-03/temp"); rel != "serves" {
		t.Errorf("ac->temp: %s", rel)
	}
	if rel, _, _ := ix.Relation("SR-AQ-KH03-03/temp", "WE-VN04-00/temp"); rel != "outdoor-for" {
		t.Errorf("weather->room: %s", rel)
	}
	b, _ := json.Marshal(c)
	t.Logf("auto tree: %v nodes, %d links, %d bytes", kinds, len(c.Links), len(b))
}

func newTestEngine(t *testing.T) *Engine {
	e, err := NewEngine("../device")
	if err != nil {
		t.Fatal(err)
	}
	return e
}
