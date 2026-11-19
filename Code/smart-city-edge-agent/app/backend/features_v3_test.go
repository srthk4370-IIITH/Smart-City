package main

// agt_v3 + card parity (fixtures: proofs/2026-11-16_phase1/parity/make_fixtures.py, Python = reference).

import (
	"encoding/json"
	"os"
	"reflect"
	"strings"
	"testing"
)

func TestCardRenderParity(t *testing.T) {
	raw, err := os.ReadFile("testdata/cards_fixtures.json")
	if err != nil {
		t.Fatal(err)
	}
	var fx struct {
		Existing []struct {
			CardID    string   `json:"card_id"`
			Line      string   `json:"line"`
			Full      *string  `json:"full"`
			FullPlace *string  `json:"full_place"`
			Validate  []string `json:"validate"`
		} `json:"existing"`
		Synthetic []struct {
			Card     json.RawMessage `json:"card"`
			Full     string          `json:"full"`
			Line     string          `json:"line"`
			Validate []string        `json:"validate"`
		} `json:"synthetic"`
		Broken []struct {
			Mut      string         `json:"mut"`
			Card     map[string]any `json:"card"`
			Validate []string       `json:"validate"`
		} `json:"broken"`
	}
	if err := json.Unmarshal(raw, &fx); err != nil {
		t.Fatal(err)
	}
	bad := 0
	for _, e := range fx.Existing {
		c, ok := existingCards[e.CardID]
		if !ok {
			t.Fatalf("card %s not embedded", e.CardID)
		}
		if g := RenderCardLine(c); g != e.Line {
			bad++
			t.Errorf("%s line:\n go %q\n py %q", e.CardID, g, e.Line)
		}
		if e.Full != nil {
			if g := RenderCardFull(c, ""); g != *e.Full {
				bad++
				firstDiff(t, e.CardID+" full", g, *e.Full)
			}
			if g := RenderCardFull(c, "lecture hall, capacity 120"); g != *e.FullPlace {
				bad++
				firstDiff(t, e.CardID+" full place", g, *e.FullPlace)
			}
			if g := ValidateCardRaw(existingCardRaw[e.CardID]); !sameStrs(g, e.Validate) {
				t.Errorf("%s validate go %v py %v", e.CardID, g, e.Validate)
			}
		}
	}
	for i, s := range fx.Synthetic {
		var c Card
		if err := json.Unmarshal(s.Card, &c); err != nil {
			t.Fatal(err)
		}
		if g := RenderCardFull(c, ""); g != s.Full {
			bad++
			firstDiff(t, c.CardID+" synthetic full", g, s.Full)
		}
		if g := RenderCardLine(c); g != s.Line {
			bad++
			t.Errorf("synthetic %d line:\n go %q\n py %q", i, g, s.Line)
		}
		var m map[string]any
		_ = json.Unmarshal(s.Card, &m)
		if g := ValidateCardRaw(m); !sameStrs(g, s.Validate) {
			t.Errorf("synthetic %s validate go %v py %v", c.CardID, g, s.Validate)
		}
	}
	for _, b := range fx.Broken {
		if g := ValidateCardRaw(b.Card); !sameStrs(g, b.Validate) {
			t.Errorf("broken %s: go %v py %v", b.Mut, g, b.Validate)
		}
	}
	t.Logf("%d existing + %d synthetic cards rendered, %d broken cards validated: %d mismatches", len(fx.Existing), len(fx.Synthetic), len(fx.Broken), bad)
}

func sameStrs(a, b []string) bool {
	if len(a) == 0 && len(b) == 0 {
		return true
	}
	return reflect.DeepEqual(a, b)
}

// Today's cards restate today's limits (features.go Metrics): direction, warning / critical, decimals.
func TestCardsMatchMetrics(t *testing.T) {
	for k, m := range Metrics {
		role, metric, _ := strings.Cut(k, "/")
		node := ""
		if metric == "pm25" || metric == "pm10" {
			node = "AQ-X"
		}
		c, ok := existingCards[MetricToCard(role, metric, node, "")]
		if !ok {
			t.Errorf("%s: no card", k)
			continue
		}
		if c.Decimals != m.Dec && role != "occupancy" {
			t.Errorf("%s: decimals %d vs %d", k, c.Decimals, m.Dec)
		}
		if !m.HasLimits {
			continue
		}
		w := c.Warning
		if w == nil {
			t.Errorf("%s: card has no warning limit", k)
			continue
		}
		at := w.At
		if w.Dir == "both" {
			at = w.High
			if m.Dir == "low" {
				at = w.Low
			}
		}
		if at == nil || *at != m.Warn {
			t.Errorf("%s: warning %v vs %v", k, at, m.Warn)
		}
	}
}

type agtRow struct {
	ID       string          `json:"id"`
	Card     json.RawMessage `json:"card"`
	Node     string          `json:"node"`
	Location string          `json:"location"`
	Place    *string         `json:"place"`
	Hist     []float64       `json:"hist"`
	N        int             `json:"n"`
	End      int64           `json:"end"`
	HvacCtx  *HVACCtx        `json:"hvac_ctx"`
	Prompt   string          `json:"prompt"`
}

func loadAgtFixtures(t *testing.T) ([]struct {
	Idx    int       `json:"idx"`
	CardID string    `json:"card_id"`
	Tank   *CardTank `json:"tank"`
	Prompt string    `json:"prompt"`
}, []agtRow) {
	raw, err := os.ReadFile("testdata/agt_v3_fixtures.json")
	if err != nil {
		t.Fatal(err)
	}
	var fx struct {
		FromV2 []struct {
			Idx    int       `json:"idx"`
			CardID string    `json:"card_id"`
			Tank   *CardTank `json:"tank"`
			Prompt string    `json:"prompt"`
		} `json:"from_v2"`
		Rows []agtRow `json:"rows"`
	}
	if err := json.Unmarshal(raw, &fx); err != nil {
		t.Fatal(err)
	}
	return fx.FromV2, fx.Rows
}

// Every v2 Go fixture (real windows, all roles incl. hvac + tank) through the gate's conversion and the generic builder.
func TestAgentV3ParityFromV2(t *testing.T) {
	v2, limits := loadV2Fixtures(t)
	saved := NodeLimitsV2
	NodeLimitsV2 = limits
	defer func() { NodeLimitsV2 = saved }()
	conv, _ := loadAgtFixtures(t)
	bad, gen, genBad, kinds := 0, 0, 0, map[string]int{}
	for _, c := range conv {
		f := v2[c.Idx]
		cd, ok := existingCardFor(f.Role, f.Metric, f.Node, f.Location)
		if !ok || cd.CardID != c.CardID {
			t.Fatalf("%s/%s: card %s want %s", f.Node, f.Metric, cd.CardID, c.CardID)
		}
		kinds[cd.Kind]++
		var got AgentInputV2
		if f.Kind == "hvac" {
			hc := *f.Ctx
			hc.End = f.End
			got = AgentPromptV3FromV2(cd, f.Node, f.Location, "", BuildHVACPromptV2(f.Node, f.Location, f.Xs, hc, f.Hist))
			// the generic builder must agree on hvac too
			g2 := BuildAgentPromptV3(cd, f.Node, f.Location, "", f.Hist, len(f.Xs), f.End, &hc)
			gen++
			if g2.Prompt != c.Prompt {
				genBad++
				if genBad <= 2 {
					firstDiff(t, "generic hvac "+f.Node, g2.Prompt, c.Prompt)
				}
			}
		} else {
			got = AgentPromptV3FromV2(cd, f.Node, f.Location, "", BuildAgentPromptV2(f.Role, f.Node, f.Location, f.Metric, f.Hist[len(f.Hist)-f.N:], f.End, f.Hist))
			g2 := BuildAgentPromptV3(cd, f.Node, f.Location, "", f.Hist, f.N, f.End, nil)
			gen++
			if g2.Prompt != c.Prompt {
				genBad++
				if genBad <= 3 {
					firstDiff(t, "generic "+f.Node+"/"+f.Metric, g2.Prompt, c.Prompt)
				}
			}
		}
		if got.Prompt != c.Prompt {
			bad++
			if bad <= 3 {
				firstDiff(t, "conv "+f.Node+"/"+f.Metric, got.Prompt, c.Prompt)
			}
		}
	}
	t.Logf("%d v2 fixtures -> agt_v3 %v: %d conversion mismatches; generic builder %d/%d mismatches", len(conv), kinds, bad, genBad, gen)
	if len(conv) < 250 || bad > 0 || genBad > 0 {
		t.Fail()
	}
}

// Synthetic / campus / unseen-metric rows (hvac_unit, binary_state, count, synthetic cards) through the generic builder.
func TestAgentV3ParityRows(t *testing.T) {
	_, rows := loadAgtFixtures(t)
	bad, kinds, syn := 0, map[string]int{}, 0
	for _, r := range rows {
		var c Card
		if err := json.Unmarshal(r.Card, &c); err != nil {
			t.Fatal(err)
		}
		kinds[c.Kind]++
		if a, _ := cardMetricKey(c); a == "card" {
			syn++
		}
		place := ""
		if r.Place != nil {
			place = *r.Place
		}
		got := BuildAgentPromptV3(c, r.Node, r.Location, place, r.Hist, r.N, r.End, r.HvacCtx)
		if got.Prompt != r.Prompt {
			bad++
			if bad <= 4 {
				firstDiff(t, r.ID+" "+c.CardID, got.Prompt, r.Prompt)
			}
		}
	}
	t.Logf("%d rows %v (%d synthetic-card rows): %d mismatches", len(rows), kinds, syn, bad)
	if len(rows) < 200 || bad > 0 || kinds["hvac_unit"] == 0 || kinds["binary_state"] == 0 || syn == 0 {
		t.Fail()
	}
}

func TestAgentV3FieldsChecked(t *testing.T) {
	js := `{"pattern":"gradual_increase","status":"critical","data_quality":{"verdict":"insufficient","why":"gaps","src":["E8","E99"]},
"severity_reason":"E1 above critical (card)","evidence":["E1","E4","E42"],"observations":["CO2 rose [E1,E4]"],"likely_cause":"occupancy_load",
"confidence":0.8,"event_active":true,"onset":"11:10","action":"inspect_ventilation"}`
	var f Finding
	if err := json.Unmarshal([]byte(js), &f); err != nil {
		t.Fatal(err)
	}
	rep := checkAgentV3Fields(&f, map[string]bool{"E1": true, "E4": true, "E8": true})
	if f.Status != "warning" || len(f.EvidenceIDs) != 2 || len(f.DataQuality.Src) != 1 || f.SeverityReason == "" || len(rep) < 2 {
		t.Fatalf("%+v %v", f, rep)
	}
}
