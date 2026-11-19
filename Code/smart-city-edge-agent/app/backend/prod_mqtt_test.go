package main

import (
	"bufio"
	"encoding/binary"
	"fmt"
	"net"
	"os/exec"
	"strings"
	"sync"
	"testing"
	"time"
)

// testBroker: a minimal in-process MQTT 3.1.1 broker (CONNECT with optional auth, SUBSCRIBE, PUBLISH QoS 0/1 fan-out,
// PUBACK, PINGREQ). Enough for the bridge and for tools/mqtt_pub.py.
type testBroker struct {
	ln         net.Listener
	user, pass string
	mu         sync.Mutex
	subs       map[net.Conn]*sync.Mutex
	conns      []net.Conn
	pid        uint16
	acks       chan uint16
}

func newTestBroker(t *testing.T, user, pass string) *testBroker {
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	b := &testBroker{ln: ln, user: user, pass: pass, subs: map[net.Conn]*sync.Mutex{}, acks: make(chan uint16, 100)}
	go func() {
		for {
			c, err := ln.Accept()
			if err != nil {
				return
			}
			b.mu.Lock()
			b.conns = append(b.conns, c)
			b.mu.Unlock()
			go b.serve(c)
		}
	}()
	t.Cleanup(func() { ln.Close(); b.kick() })
	return b
}

func (b *testBroker) url() string { return "tcp://" + b.ln.Addr().String() }

func readStr(p []byte) (string, []byte) {
	if len(p) < 2 {
		return "", nil
	}
	n := int(binary.BigEndian.Uint16(p))
	if len(p) < 2+n {
		return "", nil
	}
	return string(p[2 : 2+n]), p[2+n:]
}

func (b *testBroker) serve(c net.Conn) {
	defer c.Close()
	r := bufio.NewReader(c)
	wmu := &sync.Mutex{}
	h, body, err := mqttRead(r)
	if err != nil || h>>4 != 1 {
		return
	}
	_, rest := readStr(body) // "MQTT"
	flags := rest[1]
	rest = rest[4:]
	_, rest = readStr(rest) // client id
	var u, p string
	if flags&0x80 != 0 {
		u, rest = readStr(rest)
	}
	if flags&0x40 != 0 {
		p, _ = readStr(rest)
	}
	if b.user != "" && (u != b.user || p != b.pass) {
		c.Write([]byte{0x20, 2, 0, 4})
		return
	}
	c.Write([]byte{0x20, 2, 0, 0})
	for {
		h, body, err := mqttRead(r)
		if err != nil {
			b.mu.Lock()
			delete(b.subs, c)
			b.mu.Unlock()
			return
		}
		switch h >> 4 {
		case 8: // SUBSCRIBE
			b.mu.Lock()
			b.subs[c] = wmu
			b.mu.Unlock()
			wmu.Lock()
			c.Write([]byte{0x90, 3, body[0], body[1], 1})
			wmu.Unlock()
		case 3: // PUBLISH from a client: ack, then fan out
			topic, pid, payload, _ := parsePublish(h, body)
			if pid != 0 {
				wmu.Lock()
				c.Write([]byte{0x40, 2, byte(pid >> 8), byte(pid)})
				wmu.Unlock()
			}
			b.publish(topic, payload)
		case 4: // PUBACK
			b.acks <- binary.BigEndian.Uint16(body)
		case 12:
			wmu.Lock()
			c.Write([]byte{0xD0, 0})
			wmu.Unlock()
		case 14:
			return
		}
	}
}

// publish sends a QoS 1 message to every subscriber.
func (b *testBroker) publish(topic string, payload []byte) int {
	b.mu.Lock()
	defer b.mu.Unlock()
	n := 0
	for c, wmu := range b.subs {
		b.pid++
		wmu.Lock()
		c.Write(mqttPublishPacket(topic, payload, 1, b.pid))
		wmu.Unlock()
		n++
	}
	return n
}

func (b *testBroker) subscribers() int {
	b.mu.Lock()
	defer b.mu.Unlock()
	return len(b.subs)
}

// kick drops every connection (a broker restart / network cut).
func (b *testBroker) kick() {
	b.mu.Lock()
	defer b.mu.Unlock()
	for _, c := range b.conns {
		c.Close()
	}
	b.conns = nil
	b.subs = map[net.Conn]*sync.Mutex{}
}

func waitFor(t *testing.T, what string, d time.Duration, cond func() bool) {
	t.Helper()
	end := time.Now().Add(d)
	for time.Now().Before(end) {
		if cond() {
			return
		}
		time.Sleep(20 * time.Millisecond)
	}
	t.Fatalf("timed out waiting for %s", what)
}

func testMQTTCfg(url string) mqttConfig {
	return mqttConfig{URL: url, Topics: []string{"sce/#"}, ClientID: "t", QoS: 1, KeepAlive: 5 * time.Second}
}

// Validation and quality flags: every payload form maps onto Engine.IngestReading, and bad input is counted, never stored.
func TestMQTTHandleSchemaAndValidation(t *testing.T) {
	e := dqEngine(t)
	b := newMQTTBridge(testMQTTCfg("tcp://unused:1"), e)
	now := time.Now().Unix()
	unit := e.bank[key(dqNode, dqMetric)].Unit
	cases := []struct {
		topic, payload string
		want           []string
	}{
		{"sce/x", fmt.Sprintf(`{"node":%q,"metric":%q,"value":700,"ts":%d,"unit":%q,"firmware":"1.0"}`, dqNode, dqMetric, now-600, unit), []string{"accepted"}},
		{"sce/x", fmt.Sprintf(`{"node":%q,"metric":%q,"value":700,"ts":%d}`, dqNode, dqMetric, now-600), []string{"duplicate"}},
		{"sce/" + dqNode + "/" + dqMetric, "710", []string{"accepted"}},                                                               // bare number, sensor from the topic
		{"sce/" + dqNode + "/" + dqMetric, fmt.Sprintf(`{"value":720,"ts":%d,"quality":"uncertain"}`, now-300), []string{"accepted"}}, // topic + object
		{"sce/x", fmt.Sprintf(`{"readings":[{"node":%q,"metric":%q,"value":650,"ts":%d},{"node":%q,"metric":%q,"value":9999,"ts":%d}]}`,
			dqNode, dqMetric, now-1200, dqNode, dqMetric, now-900), []string{"accepted", "rejected_range"}},
		{"sce/x", fmt.Sprintf(`{"node":%q,"metric":%q,"value":700,"ts":%d,"quality":"bad"}`, dqNode, dqMetric, now-60), []string{"rejected_bad"}},
		{"sce/x", fmt.Sprintf(`{"node":%q,"metric":%q,"value":700,"unit":"mg/m3"}`, dqNode, dqMetric), []string{"rejected_unit"}},
		{"sce/x", `{"node":"NOPE","metric":"co2","value":1}`, []string{"unknown_sensor"}},
		{"sce/x", `{"node":"` + dqNode + `","metric":"co2","value":"abc"}`, []string{"invalid_value"}},
		{"sce/x", `{"node":`, []string{"invalid_json"}},
		{"sce/x", `{"node":"` + dqNode + `","metric":"co2","value":700,"quality":"great"}`, []string{"invalid"}},
	}
	for i, c := range cases {
		got := b.Handle(c.topic, []byte(c.payload))
		for j := range got {
			if got[j] == "late" { // a past reading merged into an earlier bucket: stored as well
				got[j] = "accepted"
			}
		}
		if strings.Join(got, ",") != strings.Join(c.want, ",") {
			t.Errorf("case %d %s: got %v want %v", i, c.payload, got, c.want)
		}
	}
	st := b.Stats()["results"].(map[string]int)
	if st["accepted"]+st["late"] != 4 || st["duplicate"] != 1 || st["rejected_unit"] != 1 {
		t.Errorf("stats %v", st)
	}
	if fs := e.dq[key(dqNode, dqMetric)]; fs == nil || fs.stats.Accepted != 4 {
		t.Errorf("engine did not store the accepted readings: %+v", fs)
	}
	// a sensor swap is acted on once per new "replaced" value
	b.Handle("sce/x", []byte(fmt.Sprintf(`{"node":%q,"metric":%q,"value":700,"ts":%d,"replaced":%d}`, dqNode, dqMetric, now-30, now-40)))
	if e.dq[key(dqNode, dqMetric)].replacedAt == 0 {
		t.Error("replaced did not start a fresh history")
	}
}

// Connect with auth, QoS 1 acks after ingest, reconnect with backoff after the broker drops the connection.
func TestMQTTBridgeBrokerAckReconnect(t *testing.T) {
	e := dqEngine(t)
	br := newTestBroker(t, "edge", "s3cret")
	cfg := testMQTTCfg(br.url())
	cfg.User, cfg.Pass = "edge", "s3cret"
	b := newMQTTBridge(cfg, e)
	stop := make(chan struct{})
	defer close(stop)
	go b.Run(stop)
	waitFor(t, "subscription", 5*time.Second, func() bool { return br.subscribers() == 1 })
	now := time.Now().Unix()
	br.publish("sce/a", []byte(fmt.Sprintf(`{"node":%q,"metric":%q,"value":800,"ts":%d}`, dqNode, dqMetric, now-120)))
	select {
	case <-br.acks:
	case <-time.After(5 * time.Second):
		t.Fatal("no PUBACK")
	}
	if b.Stats()["results"].(map[string]int)["accepted"] != 1 {
		t.Fatalf("stats %v", b.Stats())
	}
	br.kick()
	waitFor(t, "reconnect", 10*time.Second, func() bool { return br.subscribers() == 1 && b.Stats()["reconnects"].(int) >= 1 })
	br.publish("sce/a", []byte(fmt.Sprintf(`{"node":%q,"metric":%q,"value":810,"ts":%d}`, dqNode, dqMetric, now-60)))
	select {
	case <-br.acks:
	case <-time.After(5 * time.Second):
		t.Fatal("no PUBACK after reconnect")
	}
	if b.Stats()["connected"] != true {
		t.Error("not connected")
	}
}

func TestMQTTBridgeBadPassword(t *testing.T) {
	br := newTestBroker(t, "edge", "s3cret")
	cfg := testMQTTCfg(br.url())
	cfg.User, cfg.Pass = "edge", "wrong"
	b := newMQTTBridge(cfg, dqEngine(t))
	err := b.session(nil)
	if err == nil || !strings.Contains(err.Error(), "bad user name or password") {
		t.Fatalf("err = %v", err)
	}
}

// tools/mqtt_pub.py (the laptop test publisher) end to end through the broker into the engine.
func TestMQTTPublishScript(t *testing.T) {
	py, err := exec.LookPath("python3")
	if err != nil {
		t.Skip("python3 not installed")
	}
	e := dqEngine(t)
	br := newTestBroker(t, "", "")
	b := newMQTTBridge(testMQTTCfg(br.url()), e)
	stop := make(chan struct{})
	defer close(stop)
	go b.Run(stop)
	waitFor(t, "subscription", 5*time.Second, func() bool { return br.subscribers() == 1 })
	host, port, _ := net.SplitHostPort(br.ln.Addr().String())
	out, err := exec.Command(py, "../tools/mqtt_pub.py", "--host", host, "--port", port, "--node", dqNode, "--metric", dqMetric,
		"--value", "600", "--count", "6", "--batch").CombinedOutput()
	if err != nil {
		t.Fatalf("mqtt_pub.py: %v\n%s", err, out)
	}
	waitFor(t, "readings", 5*time.Second, func() bool { r := b.Stats()["results"].(map[string]int); return r["accepted"]+r["late"] == 6 })
}
