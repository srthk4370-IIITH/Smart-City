package main

// v4 reasoner prompt parity vs fmt_v4.render_v4 / system_v4 (fixtures captured from gen_inc_v4 by
// proofs/2026-11-16_phase1/parity/make_fix_v4.py).

import (
	"encoding/json"
	"os"
	"strings"
	"testing"
)

type v4FxSensor struct {
	Ref, Role, Metric, Node, Loc string
	Flagged                      bool
	Why                          *string
	Quality                      *string
	Head                         []string
	Stale                        *string
	Ev                           [][2]string
	Agent                        *struct {
		Pattern, Status, Cause string
		Conf                   float64
		Obs                    []string
	}
	UnitShown *string   `json:"unit_shown"`
	Rule      [2]string `json:"rule"`
	Card      *Card     `json:"card"`
}

type v4FxRow struct {
	Case struct {
		End struct {
			Dt int64 `json:"__dt__"`
		} `json:"end"`
		Outdoor     []string     `json:"outdoor"`
		IncID       string       `json:"inc_id"`
		Mode        *string      `json:"mode"`
		WinH        any          `json:"win_h"`
		Sensors     []v4FxSensor `json:"sensors"`
		MissingNote *string      `json:"missing_note"`
		Recheck     []string     `json:"recheck"`
		Memory      *[]string    `json:"memory"`
		Notes       []string     `json:"notes"`
		Ask         *string      `json:"ask"`
	} `json:"case"`
	Ctx struct {
		SiteLine  string               `json:"site_line"`
		Links     map[string][2]string `json:"links"`
		AgentData map[string]string    `json:"agent_data"`
		LinksLine string               `json:"links_line"`
		Siblings  []json.RawMessage    `json:"siblings"`
		Nearby    []json.RawMessage    `json:"nearby"`
		Suspect   *string              `json:"suspect"`
	} `json:"ctx"`
	Text string `json:"text"`
}

func sv(p *string) string {
	if p == nil {
		return ""
	}
	return *p
}

func v4Input(r v4FxRow) (V3Input, V4Ctx) {
	c := r.Case
	in := V3Input{End: c.End.Dt, IncID: c.IncID, Mode: sv(c.Mode), MissingNote: sv(c.MissingNote), Recheck: c.Recheck, Notes: c.Notes}
	switch w := c.WinH.(type) {
	case string:
		in.WinH = w
	case float64:
		in.WinH = strings.TrimSuffix(strings.TrimRight(strings.TrimRight(jsonNum(w), "0"), "."), ".")
	}
	if len(c.Outdoor) == 3 {
		in.Outdoor = &[3]string{c.Outdoor[0], c.Outdoor[1], c.Outdoor[2]}
	}
	if c.Memory != nil {
		in.MemoryKnown, in.Memory = true, *c.Memory
	}
	if c.Ask != nil {
		in.Ask, in.AskSet = *c.Ask, true
	}
	for _, s := range c.Sensors {
		x := V3Sensor{Ref: s.Ref, Node: s.Node, Metric: s.Metric, Unit: sv(s.UnitShown), Loc: s.Loc, Role: s.Role, Flagged: s.Flagged,
			Why: sv(s.Why), Head: s.Head, Quality: sv(s.Quality), Stale: sv(s.Stale), Rule: s.Rule, Ev: s.Ev, Card: s.Card}
		if s.Why == nil {
			x.Why = "None"
		}
		if s.Agent != nil {
			x.Agent = &V3Agent{Pattern: s.Agent.Pattern, Status: s.Agent.Status, Cause: s.Agent.Cause, Conf: s.Agent.Conf, Obs: s.Agent.Obs}
		}
		in.Sensors = append(in.Sensors, x)
	}
	cx := V4Ctx{SiteLine: r.Ctx.SiteLine, Links: r.Ctx.Links, AgentData: r.Ctx.AgentData, LinksLine: r.Ctx.LinksLine, Suspect: sv(r.Ctx.Suspect)}
	pair := func(raw []json.RawMessage) (string, []string) {
		var t string
		var l []string
		if len(raw) == 2 {
			_ = json.Unmarshal(raw[0], &t)
			_ = json.Unmarshal(raw[1], &l)
		}
		return t, l
	}
	cx.SiblingsTitle, cx.Siblings = pair(r.Ctx.Siblings)
	cx.NearbyTitle, cx.Nearby = pair(r.Ctx.Nearby)
	return in, cx
}

func jsonNum(f float64) string { b, _ := json.Marshal(f); return string(b) }

func TestSitePromptParity(t *testing.T) {
	raw, err := os.ReadFile("testdata/v4_fixtures.json")
	if err != nil {
		t.Fatal(err)
	}
	var fx struct {
		SystemR3 string    `json:"system_r3"`
		SystemV4 string    `json:"system_v4"`
		Rows     []v4FxRow `json:"rows"`
	}
	if err := json.Unmarshal(raw, &fx); err != nil {
		t.Fatal(err)
	}
	if fx.SystemR3 != v3System {
		t.Fatal("fixture r3 system differs from reasoner_v3_system.txt")
	}
	if g := SystemV4(v3System); g != fx.SystemV4 {
		firstDiff(t, "system v4", g, fx.SystemV4)
	}
	bad, agd, sus, cards := 0, 0, 0, 0
	for i, r := range fx.Rows {
		in, cx := v4Input(r)
		if len(cx.AgentData) > 0 {
			agd++
		}
		if cx.Suspect != "" {
			sus++
		}
		for _, s := range in.Sensors {
			if s.Card != nil {
				cards++
			}
		}
		if g := RenderV4User(in, cx); g != r.Text {
			bad++
			if bad <= 4 {
				firstDiff(t, "row "+jsonNum(float64(i))+" "+in.IncID, g, r.Text)
			}
		}
	}
	t.Logf("%d v4 rows (agent data %d, suspect %d, card sensors %d): %d mismatches", len(fx.Rows), agd, sus, cards, bad)
	if len(fx.Rows) < 100 || bad > 0 || agd == 0 || sus == 0 || cards == 0 {
		t.Fail()
	}
}

func TestReasonerPromptV4OffByDefault(t *testing.T) {
	if reasonerPromptV4() {
		t.Fatal("reasoner_prompt=v4 must be off without the key")
	}
	if !strings.HasPrefix(v3StaticPrefix(), v3Header+v3System) {
		t.Fatal("default prefix changed")
	}
	if strings.Contains(v4Header(), `"description": "Incident-time only."`) || !strings.Contains(v4Header(), "walks the site links") {
		t.Fatal("v4 header related_context description not replaced")
	}
}
