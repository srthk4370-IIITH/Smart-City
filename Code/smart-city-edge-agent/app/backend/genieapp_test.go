package main

// Device test for the batched NPU path. It needs the real QIDK, so it is skipped unless
// SCE_BATCH_TEST=1 is set. Build it for the board and run it there:
//
//	CGO_ENABLED=0 GOOS=linux GOARCH=arm64 go test -c -o ../device/batch.test .
//	adb push ../device/batch.test /data/local/tmp/smart_city_edge/
//	adb shell "cd /data/local/tmp/smart_city_edge && SCE_BATCH_TEST=1 SCE_GENIE_BATCH=1 \
//	    ./batch.test -test.v -test.run TestBatch -test.timeout 20m"
//
// training/export/verify_batch.py already proved that genie-app answers a batch exactly as
// separate calls do. What that does NOT cover is the Go code in genieapp.go: the stdout parser
// that has to split one stream into per-prompt answers on [BEGIN]:/[END] boundaries, including
// markers split across reads. That is what this exercises.

import (
	"context"
	"encoding/json"
	"os"
	"strings"
	"testing"
	"time"
)

func testRunner(t *testing.T) *GenieRunner {
	t.Helper()
	if os.Getenv("SCE_BATCH_TEST") != "1" {
		t.Skip("device-only: set SCE_BATCH_TEST=1 on the QIDK")
	}
	rt := envOr("SCE_GENIE_RUNTIME", "/data/local/tmp/genie_bundle")
	g := NewGenieRunner(rt, envOr("SCE_APP_DIR", "/data/local/tmp/smart_city_edge"), false)
	if !g.Tuned.Available {
		t.Fatalf("tuned bundle not available: %s", g.Tuned.Note)
	}
	return g
}

// readPrompts loads the prompt files the test was pointed at, one prompt per file.
func readPrompts(t *testing.T) []string {
	t.Helper()
	spec := os.Getenv("SCE_BATCH_TEST_PROMPTS")
	if spec == "" {
		t.Skip("set SCE_BATCH_TEST_PROMPTS to a comma-separated list of prompt files")
	}
	var out []string
	for _, p := range strings.Split(spec, ",") {
		b, err := os.ReadFile(strings.TrimSpace(p))
		if err != nil {
			t.Fatalf("reading %s: %v", p, err)
		}
		out = append(out, string(b))
	}
	if len(out) < 2 {
		t.Fatalf("need at least 2 prompts to test batching, got %d", len(out))
	}
	return out
}

// TestBatchSplitsAnswers is the parser test: N prompts in one process must come back as N
// separate, individually well-formed answers, in order.
func TestBatchSplitsAnswers(t *testing.T) {
	g := testRunner(t)
	prompts := readPrompts(t)
	ctx, cancel := context.WithTimeout(context.Background(), 15*time.Minute)
	defer cancel()

	streamed := make([]string, len(prompts))
	texts, counts, err := g.runBatch(ctx, g.Tuned, prompts, func(i int, chunk string) {
		streamed[i] += chunk
	})
	if err != nil {
		t.Fatalf("runBatch: %v", err)
	}
	if len(texts) != len(prompts) {
		t.Fatalf("got %d answers for %d prompts", len(texts), len(prompts))
	}
	for i, got := range texts {
		if strings.TrimSpace(got) == "" {
			t.Errorf("answer %d is empty", i)
			continue
		}
		// the prompt primes the opening of the JSON object, so the answer completes it
		if !json.Valid([]byte(AgentPrefill + got)) {
			t.Errorf("answer %d is not valid JSON once the prefill is restored: %.200s", i, got)
		}
		// an answer must not contain a later answer's content: the markers delimit them
		if strings.Contains(got, "[BEGIN]") || strings.Contains(got, "[END]") {
			t.Errorf("answer %d still contains a stream marker: %.200s", i, got)
		}
		if counts[i] == 0 {
			t.Errorf("answer %d reported 0 chunks", i)
		}
		if strings.TrimSpace(streamed[i]) != strings.TrimSpace(got) {
			t.Errorf("answer %d: streamed text differs from returned text\n stream: %.160s\n return: %.160s",
				i, streamed[i], got)
		}
		t.Logf("answer %d ok (%d chunks): %.120s", i, counts[i], got)
	}
}

// TestBatchMatchesPerCall is the correctness gate: batching must not change a single byte.
func TestBatchMatchesPerCall(t *testing.T) {
	g := testRunner(t)
	prompts := readPrompts(t)
	ctx, cancel := context.WithTimeout(context.Background(), 25*time.Minute)
	defer cancel()

	tb := time.Now()
	batch, _, err := g.runBatch(ctx, g.Tuned, prompts, nil)
	batchDur := time.Since(tb)
	if err != nil {
		t.Fatalf("runBatch: %v", err)
	}

	var singleDur time.Duration
	for i, p := range prompts {
		ts := time.Now()
		single, _, err := g.exec(ctx, g.Tuned, p, AgentPrefill, 120*time.Second, nil)
		singleDur += time.Since(ts)
		if err != nil {
			t.Fatalf("per-call run %d: %v", i, err)
		}
		if strings.TrimSpace(single) != strings.TrimSpace(batch[i]) {
			t.Errorf("prompt %d differs\n single: %.200s\n batch : %.200s", i, single, batch[i])
		}
		// the per-call path spaces NPU sessions out by 250 ms (see GenieRunner.Run); that gap is
		// real serving cost the batch does not pay, so count it
		if i < len(prompts)-1 {
			singleDur += 250 * time.Millisecond
		}
		time.Sleep(700 * time.Millisecond)
	}
	t.Logf("%d prompts: per-call %v, batched %v, saved %v (%.0f ms per extra prompt)",
		len(prompts), singleDur.Round(time.Millisecond), batchDur.Round(time.Millisecond),
		(singleDur - batchDur).Round(time.Millisecond),
		float64((singleDur-batchDur).Milliseconds())/float64(len(prompts)-1))
}
