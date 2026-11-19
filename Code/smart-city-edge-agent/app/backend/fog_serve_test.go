package main

import (
	"bufio"
	"encoding/json"
	"net/http"
	"os"
	"sort"
	"strconv"
	"strings"
	"testing"
	"time"
)

// TestFogServe (opt-in, never in a normal `go test`): a laptop fog for the board's fog-online test
// (proofs/2026-11-06_4b_local/board/DEPLOY_R3.md). It serves FogHandler's contract (POST /v1/tool, GET /v1/status) over
// incident files pulled from the board, every incident a full record (live store + archive), until killed.
//
//	SCE_FOG_SERVE=127.0.0.1:8091                    listen address (then `adb reverse tcp:8091 tcp:8091`, fog_url=http://127.0.0.1:8091)
//	SCE_FOG_STORE=incidents.jsonl,incidents.archive.jsonl   files pulled from the board (later lines of an id win)
//	SCE_FOG_KB=.../tools/knowledge_r3.json           the full 46-passage knowledge base (default: the r3 tools dir)
//	SCE_FOG_NOW=<unix s>                             the board's sim_time at launch (/api/status); the clock then runs at 1x
//
//	go test -run TestFogServe -count=1 -timeout 0 .
func TestFogServe(t *testing.T) {
	addr := os.Getenv("SCE_FOG_SERVE")
	if addr == "" {
		t.Skip("opt-in: set SCE_FOG_SERVE")
	}
	last := map[string]*Incident{}
	var order []string
	for _, p := range strings.FieldsFunc(os.Getenv("SCE_FOG_STORE"), func(c rune) bool { return c == ',' }) {
		f, err := os.Open(p)
		if err != nil {
			t.Fatal(err)
		}
		sc := bufio.NewScanner(f)
		sc.Buffer(make([]byte, 1<<20), 64<<20)
		for sc.Scan() {
			var inc Incident
			if json.Unmarshal(sc.Bytes(), &inc) != nil || inc.ID == "" {
				continue
			}
			if _, ok := last[inc.ID]; !ok {
				order = append(order, inc.ID)
			}
			c := inc
			last[inc.ID] = &c
		}
		f.Close()
	}
	r := &Reasoner{}
	for _, id := range order {
		r.incidents = append(r.incidents, last[id])
	}
	sort.SliceStable(r.incidents, func(i, j int) bool { return r.incidents[i].CreatedSim < r.incidents[j].CreatedSim })
	kbPath := os.Getenv("SCE_FOG_KB")
	if kbPath == "" {
		kbPath = r3Dir + "/tools/knowledge_r3.json"
	}
	b, err := os.ReadFile(kbPath)
	if err != nil {
		t.Fatal(err)
	}
	var kb []kbPassage
	if err := json.Unmarshal(b, &kb); err != nil {
		t.Fatal(err)
	}
	start, base := time.Now(), time.Now()
	if s, err := strconv.ParseInt(os.Getenv("SCE_FOG_NOW"), 10, 64); err == nil && s > 0 {
		base = time.Unix(s, 0)
	}
	now := func() time.Time { return base.Add(time.Since(start)) }
	t.Logf("fog: %d incidents, %d passages, now %s, listening on %s", len(r.incidents), len(kb), now().In(IST).Format(time.RFC3339), addr)
	t.Fatal(http.ListenAndServe(addr, fogHandlerAt(r, kb, now)))
}
