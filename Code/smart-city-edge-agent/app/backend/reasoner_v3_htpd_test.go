package main

import (
	"bufio"
	"context"
	"encoding/json"
	"net"
	"os"
	"strings"
	"testing"
)

// The forced-token schema is shared with the C++ host test (app/htpd/test_reason.cpp reads the golden file and
// runs the forcer over every gold answer). Regenerate with SCE_UPDATE_GOLDEN=1.
func TestV3ForceSchemaGolden(t *testing.T) {
	b, _ := json.MarshalIndent(v3ForceSchema(), "", " ")
	b = append(b, '\n')
	const f = "testdata/reasoner_v3_force_schema.json"
	if os.Getenv("SCE_UPDATE_GOLDEN") == "1" {
		if err := os.WriteFile(f, b, 0o644); err != nil {
			t.Fatal(err)
		}
	}
	want, err := os.ReadFile(f)
	if err != nil {
		t.Fatal(err)
	}
	if string(want) != string(b) {
		t.Fatalf("%s is stale (SCE_UPDATE_GOLDEN=1)", f)
	}
	// the gate's own answer type must decode a schema-shaped answer with every key
	ans := `{"title": "T", "severity": "warning", "label": "unknown", "root_cause": "r", "causal_chain": "c", ` +
		`"observations": [{"text": "t", "src": ["S1.E1"]}], "agent_checks": [], "affected_domains": ["power"], ` +
		`"suspect_sensors": [], "evidence": ["S1.E1"], "confidence": 0.5, "checklist": [{"action": "monitor", ` +
		`"target": "S1", "why": "w"}], "monitor_next": "m", "needs_more_data": false, "needs_deeper": false, "explanation": "e"}`
	var r reportV3Raw
	dec := json.NewDecoder(strings.NewReader(ans))
	dec.DisallowUnknownFields()
	if err := dec.Decode(&r); err != nil {
		t.Fatal(err)
	}
}

// fakeReasonHtpd answers caps and one reason request; v7 = no reasoner slot.
func fakeReasonHtpd(t *testing.T, v7 bool, got chan<- map[string]any) string {
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { ln.Close() })
	go func() {
		for {
			c, err := ln.Accept()
			if err != nil {
				return
			}
			go func(c net.Conn) {
				defer c.Close()
				line, err := bufio.NewReader(c).ReadBytes('\n')
				if err != nil {
					return
				}
				var req map[string]any
				json.Unmarshal(line, &req)
				switch {
				case v7 && req["kind"] == "caps":
					c.Write([]byte(`{"error":"bad request"}` + "\n"))
				case req["kind"] == "caps":
					c.Write([]byte(`{"caps":["agents","synth","reason","release"],"reasoner":"q.gguf"}` + "\n"))
				case v7:
					c.Write([]byte(`{"outputs":[{"text":"llama text","tokens":2,"ttft_ms":1,"ms":2,"stop":"json"}],"prefill_ms":1,"total_ms":2}` + "\n"))
				default:
					got <- req
					c.Write([]byte(`{"kind":"toks","t":["{\"title\": \"A"]}` + "\n"))
					c.Write([]byte(`{"outputs":[{"text":"{\"title\": \"A\"}","tokens":5,"ttft_ms":10,"ms":100,"stop":"json","forced":3}],` +
						`"prefill_ms":5,"swap_ms":0,"total_ms":100,"reason":{"load_ms":2000,"cache":"hit"}}` + "\n"))
				}
			}(c)
		}
	}()
	return ln.Addr().String()
}

func TestHtpdReasonLLM(t *testing.T) {
	got := make(chan map[string]any, 1)
	t.Setenv("SCE_HTPD", fakeReasonHtpd(t, false, got))
	var streamed strings.Builder
	text, m, err := htpdReasonLLM{Force: true}.Complete(context.Background(), "P", 640, func(s string) { streamed.WriteString(s) })
	if err != nil {
		t.Fatal(err)
	}
	if text != `{"title": "A"}` || m.GenTokens != 5 || streamed.String() != `{"title": "A` {
		t.Fatalf("text %q tokens %d streamed %q", text, m.GenTokens, streamed.String())
	}
	req := <-got
	if req["kind"] != "reason" || req["prompt"] != "P" || req["keep"] != true || req["max_new"] != float64(640) ||
		req["prefix"] != v3StaticPrefix() || req["schema"] == nil || req["stream"] != true {
		t.Fatalf("request %v", req)
	}
	// without forcing no schema is sent
	_, _, err = htpdReasonLLM{}.Complete(context.Background(), "P", 0, nil)
	if err != nil {
		t.Fatal(err)
	}
	if req := <-got; req["schema"] != nil || req["max_new"] != nil {
		t.Fatalf("request %v", req)
	}
}

func TestHtpdReasonLLMRefusesV7(t *testing.T) {
	t.Setenv("SCE_HTPD", fakeReasonHtpd(t, true, nil))
	if _, _, err := (htpdReasonLLM{}).Complete(context.Background(), "P", 0, nil); err != errHtpdNoReasoner {
		t.Fatalf("want errHtpdNoReasoner, got %v", err)
	}
}

func TestReasonerHtpdModelDefaultOff(t *testing.T) {
	t.Setenv("SCE_REASONER_MODEL", "/data/local/tmp/q.gguf")
	t.Setenv("SCE_REASONER", "")
	t.Setenv("SCE_REASONER_ENGINE", "htpd")
	if m := reasonerHtpdModel(); m != "" {
		t.Fatalf("reasoner off but model %q", m)
	}
	t.Setenv("SCE_REASONER", "v3")
	if m := reasonerHtpdModel(); m != "/data/local/tmp/q.gguf" {
		t.Fatalf("got %q", m)
	}
	t.Setenv("SCE_REASONER_ENGINE", "")
	if m := reasonerHtpdModel(); m != "" {
		t.Fatalf("llama-server engine but model %q", m)
	}
}
