package main

import (
	"bufio"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

// Offline replay of a board chat sweep through the router (deploy25 regression check, not part of the normal test
// run): SCE_CHAT_REPLAY=<proofs/2026-11-01_chat> SCE_CHAT_SETS=questions.json:sweep6_d24.jsonl,... go test -run TestChatReplay
// Incidents come from the sweep's /api/incidents snapshot (SCE_CHAT_INC), the clock from each record's sim_time; a
// question the router does not answer takes the board's answer (and tools) as history, as the model gave it.
// Output: <dir>/replay_<sweep>.jsonl (route v25 | router | model, text).
func TestChatReplay(t *testing.T) {
	dir := os.Getenv("SCE_CHAT_REPLAY")
	if dir == "" {
		t.Skip("set SCE_CHAT_REPLAY")
	}
	e, r, _ := chatV25Fixture(t)
	var raw []map[string]any
	b, err := os.ReadFile(filepath.Join(dir, os.Getenv("SCE_CHAT_INC")))
	if err != nil {
		t.Fatal(err)
	}
	json.Unmarshal(b, &raw)
	for _, x := range raw {
		inc := &Incident{ID: x["id"].(string), State: "done", Severity: x["severity"].(string), Title: x["title"].(string)}
		inc.CreatedSim = int64(x["created_sim"].(float64))
		inc.Approval, _ = x["approval"].(string)
		inc.Injected, _ = x["injected"].(bool)
		inc.Workflow, _ = x["workflow"].(string)
		inc.Outcome, _ = x["outcome"].(string)
		if l, _ := x["label"].(string); l != "" {
			inc.Final = &ReportCall{Parsed: &Report{Label: l}}
		}
		ss, _ := x["sensors"].([]any)
		for i, s := range ss {
			f := strings.Fields(s.(string))
			if len(f) < 2 {
				continue
			}
			role := e.Meta.Nodes[f[0]].Role
			inc.Sensors = append(inc.Sensors, SensorRef{Ref: "S" + string(rune('1'+i)), Node: f[0], Metric: f[1], Role: role,
				Rule: Finding{Status: map[bool]string{true: "sensor_fault", false: inc.Severity}[inc.Severity == "sensor_fault"]}})
		}
		r.incidents = append(r.incidents, inc)
	}
	for _, set := range strings.Split(os.Getenv("SCE_CHAT_SETS"), ",") {
		p := strings.SplitN(set, ":", 2)
		var qs [][2]string
		qb, _ := os.ReadFile(filepath.Join(dir, p[0]))
		json.Unmarshal(qb, &qs)
		recs := map[int]map[string]any{}
		f, err := os.Open(filepath.Join(dir, p[1]))
		if err != nil {
			t.Fatal(err)
		}
		sc := bufio.NewScanner(f)
		sc.Buffer(make([]byte, 1<<20), 1<<22)
		for sc.Scan() {
			var rec map[string]any
			if json.Unmarshal(sc.Bytes(), &rec) == nil {
				recs[int(rec["i"].(float64))] = rec
			}
		}
		f.Close()
		out, _ := os.Create(filepath.Join(dir, "replay_"+strings.TrimSuffix(p[1], ".jsonl")+".jsonl"))
		hist := map[string][]ChatMsg{}
		for i, q := range qs {
			rec := recs[i+1]
			now := time.Unix(e.sim, 0)
			if rec != nil {
				if s, ok := rec["sim_time"].(float64); ok && s > 0 {
					now = time.Unix(int64(s), 0)
				}
			}
			tools := chatTools{r: r, now: now}
			h := hist[q[0]]
			question := chatWithNodeOf(chatNormalize(q[1]), e.Meta.Nodes)
			route, text := "model", ""
			var used []ChatTool
			if v, ok := tools.chatRouteV25(question, h); ok && v.Text != "" {
				route, text, used = "v25", v.Text, v.Tools
			} else if tx, tl, ok := tools.chatRouted(question, h); ok {
				route, text, used = "router", tx, []ChatTool{tl}
			} else if rec != nil {
				text, _ = rec["text"].(string)
				if tl, ok := rec["tools"].([]any); ok {
					for _, x := range tl {
						m := x.(map[string]any)
						a, _ := json.Marshal(m["args"])
						used = append(used, ChatTool{Name: m["name"].(string), Args: string(a), Result: m["result"].(string)})
					}
				}
				g := tools.chatGuardOf(question, h)
				_ = g
			}
			hist[q[0]] = append(h, ChatMsg{Role: "user", Text: q[1]}, ChatMsg{Role: "assistant", Text: text, Tools: used})
			var names []string
			for _, u := range used {
				names = append(names, u.Name+" "+u.Args)
			}
			line, _ := json.Marshal(map[string]any{"i": i + 1, "q": q[1], "route": route, "text": text, "tools": names, "board_text": rec["text"]})
			out.Write(append(line, '\n'))
		}
		out.Close()
	}
}
