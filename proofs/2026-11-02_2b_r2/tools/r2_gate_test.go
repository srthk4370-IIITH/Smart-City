//go:build r2gate

package main

// r2 dataset harness: every gold report of a jsonl file through the app's own gate (checkReportV3For, weatherOnlyIncident),
// knownText = the exact prompt the app builds (reasonerPromptV3). Never part of the app build: go_gate.sh copies it next to a
// COPY of app/backend. Non-fatal: writes per-row results (id, pass, errors) to R2_OUT for filtering.
// env: R2_ROWS = comma-separated jsonl files, R2_OUT = result jsonl path.

import (
	"bufio"
	"encoding/json"
	"os"
	"regexp"
	"strings"
	"testing"
)

var r2FlagRe = regexp.MustCompile(`(?m)^S\d+ \[FLAGGED\]: .*\((\w+)\)$`)

func TestR2Gate(t *testing.T) {
	of, err := os.Create(os.Getenv("R2_OUT"))
	if err != nil {
		t.Fatal(err)
	}
	defer of.Close()
	w := bufio.NewWriter(of)
	defer w.Flush()
	pass, total := 0, 0
	for _, path := range strings.Split(os.Getenv("R2_ROWS"), ",") {
		f, err := os.Open(path)
		if err != nil {
			t.Fatal(err)
		}
		sc := bufio.NewScanner(f)
		sc.Buffer(make([]byte, 1<<20), 1<<26)
		for sc.Scan() {
			var row struct {
				ID       string `json:"id"`
				Tools    string `json:"tools"`
				Messages []struct {
					Role      string `json:"role"`
					Content   string `json:"content"`
					ToolCalls []struct {
						Function struct {
							Name      string                     `json:"name"`
							Arguments json.RawMessage `json:"arguments"`
						} `json:"function"`
					} `json:"tool_calls"`
				} `json:"messages"`
			}
			if err := json.Unmarshal(sc.Bytes(), &row); err != nil {
				t.Fatal(err)
			}
			if row.Tools != "incident" || len(row.Messages) < 3 {
				continue
			}
			user := row.Messages[1].Content
			text := row.Messages[len(row.Messages)-1].Content
			var roles []string
			for _, m := range r2FlagRe.FindAllStringSubmatch(user, -1) {
				roles = append(roles, m[1])
			}
			wo := weatherOnlyIncident(&Incident{Roles: roles})
			var turns []v3Turn
			for _, m := range row.Messages[2 : len(row.Messages)-1] {
				if m.Role == "assistant" {
					var tt v3Turn
					for _, c := range m.ToolCalls {
						vc := V3Call{Name: c.Function.Name}
						args := map[string]json.RawMessage{}
						if json.Unmarshal(c.Function.Arguments, &args) != nil {
							var as string // arguments as a JSON string (round-1 row format)
							if json.Unmarshal(c.Function.Arguments, &as) == nil {
								json.Unmarshal([]byte(as), &args)
							}
						}
						for k, v := range args {
							var s string
							if json.Unmarshal(v, &s) != nil {
								s = string(v)
							}
							vc.Params = append(vc.Params, V3Param{k, s})
						}
						tt.Calls = append(tt.Calls, vc)
					}
					turns = append(turns, tt)
				} else if m.Role == "tool" && len(turns) > 0 {
					turns[len(turns)-1].Results = append(turns[len(turns)-1].Results, m.Content)
				}
			}
			known := reasonerPromptV3(user, turns)
			rep, errs, repairs := checkReportV3For(text, known, wo)
			ok := rep != nil && len(errs) == 0
			total++
			if ok {
				pass++
			}
			b, _ := json.Marshal(map[string]any{"id": row.ID, "pass": ok, "errors": errs, "repairs": repairs})
			w.Write(append(b, '\n'))
		}
		f.Close()
	}
	t.Logf("r2 gate: %d/%d pass", pass, total)
}
