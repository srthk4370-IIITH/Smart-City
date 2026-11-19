package main

// The 15-tool chat header (rsn_v3, chat_think=adaptive) against the training files of proofs/2026-11-02_2b_r2:
//   - chat_header15.txt is byte-identical to tools/chat_header15.txt (rendered from data/final/tools_r2.json["chat"]
//     by the Qwen3.5 HF chat template, tools/render_chat_header15.py), and its tool lines are tools_r2.json["chat"]
//     in order; chat_header.txt (rsn_v1) is still tools_r2.json["chat9"];
//   - chatStaticPrefixMode sends the 9-tool header with thinking off (rsn_v1, unchanged) and the 15-tool one adaptive;
//   - every tool the 15-tool header names is served by the executor, and each of the 6 tools rsn_v1 never saw answers
//     on the parity fixture (read-only results, no error) and rejects a bad argument with an error result.
// Skipped when the proofs folder is not there.

import (
	"context"
	"encoding/json"
	"os"
	"path/filepath"
	"reflect"
	"regexp"
	"strings"
	"testing"
	"time"
)

const r2Dir = "../../../../proofs/2026-11-02_2b_r2"

var chatToolLineRe = regexp.MustCompile(`(?m)^\{.*\}$`)

func chatHeaderTools(t *testing.T, h string) []any {
	t.Helper()
	var out []any
	for _, l := range chatToolLineRe.FindAllString(h, -1) {
		var v any
		if err := json.Unmarshal([]byte(l), &v); err != nil {
			t.Fatalf("bad tool line %q: %v", l[:min(len(l), 80)], err)
		}
		out = append(out, v)
	}
	return out
}

func chatToolNamesOf(tools []any) []string {
	var n []string
	for _, x := range tools {
		n = append(n, x.(map[string]any)["function"].(map[string]any)["name"].(string))
	}
	return n
}

func TestChatHeader15MatchesTraining(t *testing.T) {
	want, err := os.ReadFile(filepath.Join(r2Dir, "tools", "chat_header15.txt"))
	if err != nil {
		t.Skip("training header not here: ", err)
	}
	if chatHeader15 != string(want) {
		t.Fatalf("chat_header15.txt differs from the training header (%d vs %d bytes)", len(chatHeader15), len(want))
	}
	tb, err := os.ReadFile(filepath.Join(r2Dir, "data", "final", "tools_r2.json"))
	if err != nil {
		t.Skip("tools_r2.json not here: ", err)
	}
	var tools map[string][]any
	if err := json.Unmarshal(tb, &tools); err != nil {
		t.Fatal(err)
	}
	if got := chatHeaderTools(t, chatHeader15); !reflect.DeepEqual(got, tools["chat"]) {
		t.Fatalf("15-tool header tools %v != tools_r2 chat %v", chatToolNamesOf(got), chatToolNamesOf(tools["chat"]))
	}
	if got := chatHeaderTools(t, chatHeader); !reflect.DeepEqual(got, tools["chat9"]) {
		t.Fatalf("9-tool header tools %v != tools_r2 chat9 %v", chatToolNamesOf(got), chatToolNamesOf(tools["chat9"]))
	}
	// everything outside the <tools> block is the same template text in both headers
	lineNL := regexp.MustCompile(`(?m)^\{.*\}\n`)
	strip := func(h string) string { return lineNL.ReplaceAllString(h, "") }
	if strip(chatHeader15) != strip(chatHeader) {
		t.Fatal("15-tool header template text differs from the 9-tool header")
	}
}

func TestChatStaticPrefixByMode(t *testing.T) {
	now := time.Date(2026, 11, 2, 14, 37, 0, 0, IST)
	off, ad := chatStaticPrefixMode(now, false), chatStaticPrefixMode(now, true)
	if !strings.HasPrefix(off, chatHeader) || strings.Contains(off, `"name": "rank_readings"`) {
		t.Fatal("thinking off (rsn_v1) must send the 9-tool header")
	}
	if !strings.HasPrefix(ad, chatHeader15) {
		t.Fatal("adaptive (rsn_v3) must send the 15-tool header")
	}
	if off[len(chatHeader):] != ad[len(chatHeader15):] {
		t.Fatal("system text must not depend on the header")
	}
	if !strings.Contains(ad[len(chatHeader15):], "Device time: 2026-11-02 14:") {
		t.Fatal("device time line missing after the 15-tool header")
	}
	t.Setenv("SCE_CHAT_THINK", "adaptive")
	if chatThinkAdaptive() && chatStaticPrefix(now) != ad {
		t.Fatal("chatStaticPrefix must follow chat_think")
	}
}

func TestChatHeader15ToolsExecute(t *testing.T) {
	b, err := os.ReadFile(filepath.Join(parityDir, "parity_cases.json"))
	if err != nil {
		t.Skip("parity fixture not here: ", err)
	}
	var c parityCase
	if err := json.Unmarshal(b, &c); err != nil {
		t.Fatal(err)
	}
	tools := parityTools(t, c)
	nine := map[string]bool{}
	for _, n := range chatToolNamesOf(chatHeaderTools(t, chatHeader)) {
		nine[n] = true
	}
	all := chatToolNamesOf(chatHeaderTools(t, chatHeader15))
	if len(all) != 15 {
		t.Fatalf("15-tool header has %d tools", len(all))
	}
	// every advertised tool is dispatched (an argument error is fine here, "unknown tool" is not)
	for _, n := range all {
		if res := tools.Exec(context.Background(), n, map[string]any{}); strings.Contains(res, "unknown tool") {
			t.Errorf("%s: not served by the executor: %s", n, res)
		}
	}
	good := map[string]map[string]any{
		"rank_readings":    {"metric": "co2", "order": "highest", "time": map[string]any{"preset": "today"}},
		"current_levels":   {"metric": "co2"},
		"recent_incidents": {"limit": float64(3)},
		"open_incidents":   {},
		"faulty_sensors":   {"time": map[string]any{"preset": "last_7d"}},
		"what_if":          {"driver": "occ", "change_pct": float64(50)},
	}
	bad := map[string]map[string]any{
		"rank_readings":    {"metric": "co2", "order": "middle"},
		"current_levels":   {"domain": "kitchen"},
		"recent_incidents": {"domain": "kitchen"},
		"open_incidents":   {"domain": "kitchen"},
		"faulty_sensors":   {"time": map[string]any{"preset": "next_week"}},
		"what_if":          {},
	}
	var newTools []string
	for _, n := range all {
		if !nine[n] {
			newTools = append(newTools, n)
		}
	}
	if len(newTools) != 6 {
		t.Fatalf("new tools %v", newTools)
	}
	for _, n := range newTools {
		args, ok := good[n]
		if !ok {
			t.Fatalf("%s: no test call", n)
		}
		var res map[string]any
		if err := json.Unmarshal([]byte(tools.Exec(context.Background(), n, args)), &res); err != nil {
			t.Fatalf("%s: result is not JSON: %v", n, err)
		}
		if e, ok := res["error"]; ok {
			t.Errorf("%s %v: error %v", n, args, e)
		}
		if len(res) < 2 { // query_id + at least one field
			t.Errorf("%s: empty result %v", n, res)
		}
		var br map[string]any
		json.Unmarshal([]byte(tools.Exec(context.Background(), n, bad[n])), &br)
		if _, ok := br["error"]; !ok {
			t.Errorf("%s %v: bad argument accepted: %v", n, bad[n], br)
		}
	}
}
