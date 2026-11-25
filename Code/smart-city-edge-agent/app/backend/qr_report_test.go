package main

import (
	"crypto/ed25519"
	"encoding/hex"
	"strings"
	"testing"
)

func qrTestIncident() *Incident {
	i := &Incident{ID: "INC-0042", Severity: "critical", Title: "Water pressure drop in Block C pump room", CreatedWall: "2026-11-18 14:05:00",
		Scope: "Block C", Sensors: []SensorRef{{Node: "water_c", Metric: "pressure", Location: "Block C pump room"}},
		Mode1: Report{RootCause: "Pressure fell 40% over two hours while the pump current stayed flat, which points at a leak downstream of the pump.",
			Explanation: "A sustained leak wastes water and can flood the basement. Nearby flow sensors are normal.", Confidence: 0.82, Source: "device:qwen3.5-4b (htpd)"}}
	i.Steps = []Step{{ID: "s1", Text: "Send a technician to inspect the Block C pump room pipework", State: "done"},
		{ID: "s2", Text: "Close the valve to the east wing if water is visible", State: "open"},
		{ID: "s3", Text: "Old step", State: "withdrawn"}, {ID: "s4", Text: "Check pump bearing", State: "not_needed"}}
	i.Owner = "Ravi"
	i.Outcome = "fixed_by_action"
	return i
}

func TestQRRoundTripAndTamper(t *testing.T) {
	pub, priv, _ := ed25519.GenerateKey(nil)
	i := qrTestIncident()
	full, err := qrPackFit(i, "qidk-1", priv)
	if err != nil {
		t.Fatal(err)
	}
	d, ok, err := qrUnpack(full, pub)
	if err != nil || !ok {
		t.Fatalf("unpack ok=%v err=%v", ok, err)
	}
	if d.I != "INC-0042" || d.S != "critical" || d.B != "qidk-1" || d.T != i.Title || d.A != "ai" || d.CF != 82 || d.O != "Ravi" || d.U != "fixed_by_action" {
		t.Fatalf("fields: %+v", d)
	}
	if len(d.C) != 3 || d.C[0].S != 1 || d.C[1].S != 0 || d.C[2].S != 2 { // withdrawn step dropped
		t.Fatalf("checklist: %+v", d.C)
	}
	if d.W == 0 || !strings.Contains(d.P, "Block C") || d.D == "" || d.M == "" {
		t.Fatalf("time/place/text: %+v", d)
	}
	// wrong key: decodes but is not verified
	pub2, _, _ := ed25519.GenerateKey(nil)
	if _, ok, _ := qrUnpack(full, pub2); ok {
		t.Fatal("verified with the wrong key")
	}
	// tamper with every position of the first part: never verified
	parts := strings.Split(full, ".")
	for _, pos := range []int{0, 5, len(parts[0]) / 2, len(parts[0]) - 2} {
		b := []byte(parts[0])
		if b[pos] == 'A' {
			b[pos] = 'B'
		} else {
			b[pos] = 'A'
		}
		if _, ok, _ := qrUnpack(string(b)+"."+parts[1], pub); ok {
			t.Fatalf("tampered payload at %d verified", pos)
		}
	}
	if _, _, err := qrUnpack("garbage", pub); err == nil {
		t.Fatal("garbage accepted")
	}
}

func TestQRSizeLimits(t *testing.T) {
	_, priv, _ := ed25519.GenerateKey(nil)
	i := qrTestIncident()
	typ, _ := qrPack(qrDocOf(i, "qidk-1", 1), priv)
	t.Logf("typical payload: %d chars", len(typ))
	if n := len(typ); n > qrChunkChars*2 {
		t.Fatalf("typical incident should need at most 2 codes, got %d chars", n)
	}
	// a huge incident is trimmed to at most qrMaxChunks codes
	long := strings.Repeat("sensor reading abnormal near the north building, ", 40)
	i.Title, i.Mode1.RootCause, i.Mode1.Explanation = long, long, long
	for k := 0; k < 30; k++ {
		i.Steps = append(i.Steps, Step{ID: "x", Text: long, State: "open"})
	}
	full, err := qrPackFit(i, "qidk-1", priv)
	if err != nil {
		t.Fatal(err)
	}
	urls, gid := qrSplit(full, qrDefaultURL)
	if len(urls) > qrMaxChunks || len(gid) != 6 {
		t.Fatalf("chunks=%d gid=%s", len(urls), gid)
	}
	// reassemble from the fragments
	var sb strings.Builder
	for k, u := range urls {
		f := strings.SplitN(u[strings.Index(u, "#")+1:], ".", 4)
		if f[0] != gid || f[1] != string(rune('1'+k)) || f[2] != string(rune('0'+len(urls))) {
			t.Fatalf("fragment head %v", f[:3])
		}
		sb.WriteString(f[3])
	}
	if sb.String() != full {
		t.Fatal("reassembled payload differs")
	}
	for _, u := range urls {
		mod, ver, err := qrEncode([]byte(u))
		if err != nil || ver > 25 || len(mod) != ver*4+17 {
			t.Fatalf("qr ver=%d err=%v", ver, err)
		}
	}
	if _, _, err := qrEncode(make([]byte, 2400)); err == nil {
		t.Fatal("over-capacity data accepted")
	}
}

func TestQREncoderStructure(t *testing.T) {
	// known ECC-M data codeword counts (ISO 18004 table 7) and byte capacities
	for v, want := range map[int]int{1: 16, 2: 28, 5: 86, 10: 216, 20: 669, 40: 2334} {
		if got := qrDataCodewords(v); got != want {
			t.Errorf("v%d data codewords %d want %d", v, got, want)
		}
	}
	if qrMaxBytes(1) != 14 || qrMaxBytes(10) != 213 || qrMaxBytes(40) != 2331 {
		t.Errorf("capacities %d %d %d", qrMaxBytes(1), qrMaxBytes(10), qrMaxBytes(40))
	}
	mod, ver, err := qrEncode([]byte("HELLO"))
	if err != nil || ver != 1 || len(mod) != 21 {
		t.Fatalf("hello: %v v%d", err, ver)
	}
	// finder patterns: dark 7x7 ring around a dark 3x3 core at three corners
	for _, o := range [][2]int{{0, 0}, {14, 0}, {0, 14}} {
		if !mod[o[1]][o[0]] || mod[o[1]+1][o[0]+1] || !mod[o[1]+3][o[0]+3] {
			t.Errorf("finder at %v", o)
		}
	}
	if !mod[13][8] { // the fixed dark module
		t.Error("dark module")
	}
	svg := qrSVG(mod)
	if !strings.HasPrefix(svg, "<svg") || !strings.Contains(svg, "viewBox=\"0 0 29 29\"") {
		t.Error("svg")
	}
}

func TestQRKeyPersists(t *testing.T) {
	dir := t.TempDir()
	k1, err := qrLoadKey(dir)
	if err != nil {
		t.Fatal(err)
	}
	qrKeyMu.Lock()
	delete(qrKeyMap, dir) // force a re-read from state/qr_key
	qrKeyMu.Unlock()
	k2, err := qrLoadKey(dir)
	if err != nil || hex.EncodeToString(k1) != hex.EncodeToString(k2) {
		t.Fatal("key not persisted")
	}
	resp, err := qrResponse(qrTestIncident(), dir)
	if err != nil || resp["chunks"].(int) < 1 || resp["pubkey"].(string) != hex.EncodeToString(k1.Public().(ed25519.PublicKey)) {
		t.Fatalf("response: %v %v", err, resp["chunks"])
	}
}
