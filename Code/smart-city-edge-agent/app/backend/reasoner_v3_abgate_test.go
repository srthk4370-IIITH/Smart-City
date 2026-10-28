package main

import (
	"bufio"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strconv"
	"testing"
)

// TestReasonerV3ABGate runs the v3 gate (checkReportV3) over board A/B outputs (htpd reason responses saved by
// proofs/2026-10-27_reasoner_fast/scripts/ab_board.sh). Skipped unless SCE_AB_DIR (outputs) and SCE_AB_PROMPTS
// (bench/prompts.jsonl) are set. Prints one line per output: file, valid, errors, severity, label.
func TestReasonerV3ABGate(t *testing.T) {
	dir, pf := os.Getenv("SCE_AB_DIR"), os.Getenv("SCE_AB_PROMPTS")
	if dir == "" || pf == "" {
		t.Skip("SCE_AB_DIR / SCE_AB_PROMPTS not set")
	}
	var prompts []string
	f, err := os.Open(pf)
	if err != nil {
		t.Fatal(err)
	}
	sc := bufio.NewScanner(f)
	sc.Buffer(make([]byte, 1<<20), 1<<24)
	for sc.Scan() {
		var p struct{ Prompt string }
		json.Unmarshal(sc.Bytes(), &p)
		prompts = append(prompts, p.Prompt)
	}
	f.Close()
	files, _ := filepath.Glob(filepath.Join(dir, "*_q*_*.json"))
	sort.Strings(files)
	re := regexp.MustCompile(`_q(\d+)_\d+\.json$`)
	bad := 0
	for _, fn := range files {
		m := re.FindStringSubmatch(fn)
		q, _ := strconv.Atoi(m[1])
		b, _ := os.ReadFile(fn)
		var resp struct {
			Outputs []struct{ Text, Stop string }
		}
		for _, ln := range regexp.MustCompile(`\n`).Split(string(b), -1) {
			if json.Unmarshal([]byte(ln), &resp) == nil && len(resp.Outputs) > 0 {
				break
			}
		}
		if len(resp.Outputs) == 0 {
			fmt.Printf("ABGATE %s NO-OUTPUT\n", filepath.Base(fn))
			bad++
			continue
		}
		r, errs, repairs := checkReportV3(resp.Outputs[0].Text, prompts[q])
		sev, lab := "", ""
		if r != nil {
			sev, lab = r.Severity, r.Label
		}
		if len(errs) > 0 || r == nil {
			bad++
		}
		fmt.Printf("ABGATE %s valid=%v sev=%s label=%s errs=%q repairs=%q\n", filepath.Base(fn), r != nil && len(errs) == 0, sev, lab, errs, repairs)
	}
	fmt.Printf("ABGATE total=%d rejected=%d\n", len(files), bad)
}
