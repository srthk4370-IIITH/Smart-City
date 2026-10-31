//go:build heatr2

package main

// Harness for proofs/2026-10-29_rsn_v3/pipeline/gen_heat_r2.py: runs every gold report through the app's own gate
// (checkReportV3For with weatherOnlyIncident), with knownText = the exact prompt the app builds (reasonerPromptV3).
// Never part of the app build: heat_r2_go_check.sh copies it next to a COPY of app/backend and runs
//   go test -tags heatr2 -run TestHeatR2Gate
// env: HEAT_R2_ROWS = comma-separated jsonl files, HEAT_R2_OUT = result json path.

import (
	"bufio"
	"encoding/json"
	"os"
	"regexp"
	"strings"
	"testing"
)

var heatFlagRe = regexp.MustCompile(`(?m)^S\d+ \[FLAGGED\]: .*\((\w+)\)$`)

func TestHeatR2Gate(t *testing.T) {
	type res struct {
		ID          string   `json:"id"`
		Family      string   `json:"family"`
		WeatherOnly bool     `json:"weather_only"`
		Severity    string   `json:"severity"`
		First       string   `json:"first_action"`
		Errors      []string `json:"errors"`
		Repairs     []string `json:"repairs"`
		// control: the same report judged as a non-weather incident (critical + monitor/review first must fail there)
		ControlErrors []string `json:"control_errors,omitempty"`
	}
	var out []res
	pass, total, ctlRejected, ctlNeeded := 0, 0, 0, 0
	for _, path := range strings.Split(os.Getenv("HEAT_R2_ROWS"), ",") {
		f, err := os.Open(path)
		if err != nil {
			t.Fatal(err)
		}
		sc := bufio.NewScanner(f)
		sc.Buffer(make([]byte, 1<<20), 1<<24)
		for sc.Scan() {
			var row struct {
				ID       string `json:"id"`
				Family   string `json:"family"`
				Messages []struct {
					Role    string `json:"role"`
					Content string `json:"content"`
				} `json:"messages"`
			}
			if err := json.Unmarshal(sc.Bytes(), &row); err != nil {
				t.Fatal(err)
			}
			user := row.Messages[1].Content
			text := row.Messages[len(row.Messages)-1].Content
			var roles []string
			for _, m := range heatFlagRe.FindAllStringSubmatch(user, -1) {
				roles = append(roles, m[1])
			}
			wo := weatherOnlyIncident(&Incident{Roles: roles})
			known := reasonerPromptV3(user, nil)
			rep, errs, repairs := checkReportV3For(text, known, wo)
			r := res{ID: row.ID, Family: row.Family, WeatherOnly: wo, Errors: errs, Repairs: repairs}
			if rep != nil {
				r.Severity = rep.Severity
				if len(rep.Checklist) > 0 {
					r.First = rep.Checklist[0].Action
				}
			}
			total++
			if rep != nil && len(errs) == 0 {
				pass++
			}
			if r.Severity == "critical" && (r.First == "monitor" || r.First == "review_schedule") {
				ctlNeeded++
				_, cerrs, _ := checkReportV3For(text, known, false)
				r.ControlErrors = cerrs
				if len(cerrs) > 0 {
					ctlRejected++
				}
			}
			out = append(out, r)
		}
		f.Close()
	}
	sum := map[string]any{"rows": total, "pass": pass, "critical_monitor_or_review_first": ctlNeeded,
		"control_rejected_without_weather_rule": ctlRejected, "results": out}
	b, _ := json.MarshalIndent(sum, "", " ")
	if p := os.Getenv("HEAT_R2_OUT"); p != "" {
		if err := os.WriteFile(p, b, 0o644); err != nil {
			t.Fatal(err)
		}
	}
	t.Logf("heat_r2 gate: %d/%d pass; control (weather rule off) rejected %d/%d critical monitor/review-first rows",
		pass, total, ctlRejected, ctlNeeded)
	if pass != total {
		t.Fatalf("%d rows fail the app gate", total-pass)
	}
}
