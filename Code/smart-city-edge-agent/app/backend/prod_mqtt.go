package main

// MQTT ingest bridge (ROADMAP 2026-11-09 §4 "Sensor ingestion"). OFF unless htpd_profile mqtt_url is set.
//
//	mqtt_url=tcp://192.168.1.10:1883      (mqtts:// or ssl:// = TLS; user:pass@ in the URL also works)
//	mqtt_topics=sce/#                     comma list of subscriptions (default sce/#)
//	mqtt_user= / mqtt_pass=               broker credentials (override the URL's)
//	mqtt_client_id=sce-edge               fixed id: with mqtt_clean=0 (default) the broker keeps QoS 1 messages
//	                                      queued while the board is offline (a backlog arrives on reconnect)
//	mqtt_qos=1                            0 or 1
//	mqtt_keepalive_s=30
//
// Payload (JSON, UTF-8), one of:
//
//	{"node":"SR-AQ-KH03-03","metric":"co2","value":850,"ts":1793000000,"quality":"good",
//	 "unit":"ppm","firmware":"1.4.2","replaced":0}
//	{"readings":[{...}, ...]}                          a gateway batch (backlog after a reconnect), at most 5000
//	850   or   {"value":850,"ts":...}                  node and metric from the topic: .../<node>/<metric>
//
// Every reading goes through the same path as POST /api/ingest with "ts" (Engine.IngestReading: range check, quality
// good|uncertain|bad, dedupe by device time, late/out-of-order merge, clock checks). Extra checks here: "unit" must
// match the sensor's unit when both are known (else rejected_unit); "firmware" changes are counted and logged;
// "replaced" (unix time of a sensor swap) starts a fresh history once per new value (POST /api/maintenance replaced).
// QoS 1 messages are acknowledged after they were ingested (at-least-once; duplicates are dropped by device time).
// No external library: MQTT 3.1.1 CONNECT/SUBSCRIBE/PUBLISH/PUBACK/PINGREQ is about 200 lines.

import (
	"bufio"
	"crypto/tls"
	"encoding/binary"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log"
	"math"
	"math/rand"
	"net"
	"net/url"
	"os"
	"strconv"
	"strings"
	"sync"
	"time"
)

type mqttConfig struct {
	URL       string
	Topics    []string
	User      string
	Pass      string
	ClientID  string
	QoS       byte
	Clean     bool
	KeepAlive time.Duration
	TrustTime bool // payload ts may set an invalid board clock (prod_time.go)
}

func mqttConfigFromProfile() mqttConfig {
	host, _ := os.Hostname()
	c := mqttConfig{URL: profStr("mqtt_url"), Topics: profList("mqtt_topics"), User: profStr("mqtt_user"),
		Pass: profStr("mqtt_pass"), ClientID: profStr("mqtt_client_id"), QoS: byte(profInt("mqtt_qos", 1, 0, 1)),
		Clean: profOn("mqtt_clean"), KeepAlive: time.Duration(profInt("mqtt_keepalive_s", 30, 5, 600)) * time.Second,
		TrustTime: profStr("time_trust_mqtt") != "0"}
	if len(c.Topics) == 0 {
		c.Topics = []string{"sce/#"}
	}
	if c.ClientID == "" {
		c.ClientID = "sce-edge-" + host
	}
	return c
}

type mqttBridge struct {
	cfg mqttConfig
	eng *Engine

	mu         sync.Mutex
	connected  bool
	reconnects int
	lastErr    string
	lastMsg    time.Time
	messages   int
	results    map[string]int
	firmware   map[string]string // sensor key -> last firmware
	replacedAt map[string]int64  // sensor key -> last "replaced" value acted on
}

func newMQTTBridge(c mqttConfig, e *Engine) *mqttBridge {
	return &mqttBridge{cfg: c, eng: e, results: map[string]int{}, firmware: map[string]string{}, replacedAt: map[string]int64{}}
}

func (b *mqttBridge) Stats() map[string]any {
	b.mu.Lock()
	defer b.mu.Unlock()
	res := map[string]int{}
	for k, v := range b.results {
		res[k] = v
	}
	out := map[string]any{"connected": b.connected, "reconnects": b.reconnects, "messages": b.messages, "results": res,
		"last_error": b.lastErr, "topics": b.cfg.Topics}
	if !b.lastMsg.IsZero() {
		out["last_message_age_s"] = int(time.Since(b.lastMsg).Seconds())
	}
	return out
}

func (b *mqttBridge) count(res string) {
	b.mu.Lock()
	b.results[res]++
	b.mu.Unlock()
}

// Run connects, subscribes and ingests until stop is closed, reconnecting with exponential backoff (1 s .. 60 s,
// jittered; reset after a connection that lasted 30 s).
func (b *mqttBridge) Run(stop <-chan struct{}) {
	backoff := time.Second
	for {
		t0 := time.Now()
		err := b.session(stop)
		b.mu.Lock()
		b.connected = false
		if err != nil {
			b.lastErr = err.Error()
		}
		b.mu.Unlock()
		select {
		case <-stop:
			return
		default:
		}
		if time.Since(t0) > 30*time.Second {
			backoff = time.Second
		}
		wait := backoff/2 + time.Duration(rand.Int63n(int64(backoff/2)+1))
		log.Printf("mqtt: %v; reconnecting in %v", err, wait.Round(time.Millisecond))
		select {
		case <-stop:
			return
		case <-time.After(wait):
		}
		if backoff *= 2; backoff > time.Minute {
			backoff = time.Minute
		}
		b.mu.Lock()
		b.reconnects++
		b.mu.Unlock()
	}
}

func (b *mqttBridge) dial() (net.Conn, string, string, error) {
	u, err := url.Parse(b.cfg.URL)
	if err != nil {
		return nil, "", "", err
	}
	user, pass := b.cfg.User, b.cfg.Pass
	if u.User != nil && user == "" {
		user = u.User.Username()
		pass, _ = u.User.Password()
	}
	host := u.Host
	d := &net.Dialer{Timeout: 10 * time.Second}
	switch u.Scheme {
	case "mqtts", "ssl", "tls":
		if u.Port() == "" {
			host += ":8883"
		}
		c, err := tls.DialWithDialer(d, "tcp", host, &tls.Config{ServerName: u.Hostname()})
		return c, user, pass, err
	case "tcp", "mqtt", "":
		if u.Port() == "" {
			host += ":1883"
		}
		c, err := d.Dial("tcp", host)
		return c, user, pass, err
	}
	return nil, "", "", fmt.Errorf("mqtt_url scheme %q (use tcp:// or mqtts://)", u.Scheme)
}

// session: one connection's life. Returns why it ended.
func (b *mqttBridge) session(stop <-chan struct{}) error {
	conn, user, pass, err := b.dial()
	if err != nil {
		return err
	}
	defer conn.Close()
	br := bufio.NewReader(conn)
	conn.SetDeadline(time.Now().Add(10 * time.Second))
	if _, err := conn.Write(mqttConnect(b.cfg.ClientID, user, pass, b.cfg.Clean, b.cfg.KeepAlive)); err != nil {
		return err
	}
	h, body, err := mqttRead(br)
	if err != nil {
		return err
	}
	if h>>4 != 2 || len(body) < 2 {
		return fmt.Errorf("expected CONNACK, got packet type %d", h>>4)
	}
	if body[1] != 0 {
		return fmt.Errorf("broker refused the connection (CONNACK code %d%s)", body[1], map[byte]string{4: ": bad user name or password", 5: ": not authorised"}[body[1]])
	}
	if _, err := conn.Write(mqttSubscribe(1, b.cfg.Topics, b.cfg.QoS)); err != nil {
		return err
	}
	b.mu.Lock()
	b.connected, b.lastErr = true, ""
	b.mu.Unlock()
	log.Printf("mqtt: connected to %s", redactURL(b.cfg.URL))

	var wmu sync.Mutex
	write := func(p []byte) error {
		wmu.Lock()
		defer wmu.Unlock()
		conn.SetWriteDeadline(time.Now().Add(10 * time.Second))
		_, err := conn.Write(p)
		return err
	}
	done := make(chan struct{})
	defer close(done)
	go func() { // keepalive pings, and close on stop
		t := time.NewTicker(b.cfg.KeepAlive / 2)
		defer t.Stop()
		for {
			select {
			case <-done:
				return
			case <-stop:
				conn.Close()
				return
			case <-t.C:
				if write([]byte{0xC0, 0}) != nil {
					conn.Close()
					return
				}
			}
		}
	}()
	for {
		conn.SetReadDeadline(time.Now().Add(b.cfg.KeepAlive * 3 / 2))
		h, body, err := mqttRead(br)
		if err != nil {
			return err
		}
		switch h >> 4 {
		case 3: // PUBLISH
			topic, pid, payload, err := parsePublish(h, body)
			if err != nil {
				return err
			}
			b.Handle(topic, payload)
			if pid != 0 { // QoS 1: acknowledge after ingesting
				if err := write([]byte{0x40, 2, byte(pid >> 8), byte(pid)}); err != nil {
					return err
				}
			}
		case 9: // SUBACK
			for _, rc := range body[min(2, len(body)):] {
				if rc == 0x80 {
					return errors.New("broker refused a subscription (SUBACK 0x80): check mqtt_topics and the ACL")
				}
			}
		}
	}
}

// mqttRead reads one packet: the fixed-header byte (type<<4 | flags) and the body.
func mqttRead(r *bufio.Reader) (byte, []byte, error) {
	h, err := r.ReadByte()
	if err != nil {
		return 0, nil, err
	}
	n, mul := 0, 1
	for i := 0; ; i++ {
		c, err := r.ReadByte()
		if err != nil {
			return 0, nil, err
		}
		n += int(c&127) * mul
		if c&128 == 0 {
			break
		}
		if mul *= 128; i >= 3 {
			return 0, nil, errors.New("mqtt: malformed remaining length")
		}
	}
	if n > 4<<20 {
		return 0, nil, fmt.Errorf("mqtt: packet of %d bytes refused (max 4 MiB)", n)
	}
	body := make([]byte, n)
	if _, err := io.ReadFull(r, body); err != nil {
		return 0, nil, err
	}
	return h, body, nil
}

func mqttRemLen(n int) []byte {
	var out []byte
	for {
		c := byte(n % 128)
		n /= 128
		if n > 0 {
			c |= 128
		}
		out = append(out, c)
		if n == 0 {
			return out
		}
	}
}

func mqttStr(s string) []byte {
	b := make([]byte, 2, 2+len(s))
	binary.BigEndian.PutUint16(b, uint16(len(s)))
	return append(b, s...)
}

func mqttPacket(h byte, body []byte) []byte {
	return append(append([]byte{h}, mqttRemLen(len(body))...), body...)
}

func mqttConnect(id, user, pass string, clean bool, ka time.Duration) []byte {
	flags := byte(0)
	if clean {
		flags |= 0x02
	}
	if user != "" {
		flags |= 0x80
		if pass != "" {
			flags |= 0x40
		}
	}
	body := append(mqttStr("MQTT"), 4, flags, byte(int(ka.Seconds())>>8), byte(int(ka.Seconds())))
	body = append(body, mqttStr(id)...)
	if user != "" {
		body = append(body, mqttStr(user)...)
		if pass != "" {
			body = append(body, mqttStr(pass)...)
		}
	}
	return mqttPacket(0x10, body)
}

func mqttSubscribe(pid uint16, topics []string, qos byte) []byte {
	body := []byte{byte(pid >> 8), byte(pid)}
	for _, t := range topics {
		body = append(append(body, mqttStr(t)...), qos)
	}
	return mqttPacket(0x82, body)
}

func mqttPublishPacket(topic string, payload []byte, qos byte, pid uint16) []byte {
	body := mqttStr(topic)
	if qos > 0 {
		body = append(body, byte(pid>>8), byte(pid))
	}
	return mqttPacket(0x30|qos<<1, append(body, payload...))
}

// parsePublish splits a PUBLISH body (header byte h) into topic, packet id (0 for QoS 0) and payload.
func parsePublish(h byte, body []byte) (string, uint16, []byte, error) {
	if len(body) < 2 {
		return "", 0, nil, errors.New("short PUBLISH")
	}
	tl := int(binary.BigEndian.Uint16(body))
	if len(body) < 2+tl {
		return "", 0, nil, errors.New("short PUBLISH topic")
	}
	topic, rest := string(body[2:2+tl]), body[2+tl:]
	var pid uint16
	if (h>>1)&3 > 0 {
		if len(rest) < 2 {
			return "", 0, nil, errors.New("short PUBLISH id")
		}
		pid, rest = binary.BigEndian.Uint16(rest), rest[2:]
	}
	return topic, pid, rest, nil
}

// mqttMsg is one reading as the gateway sends it (Reading plus feed metadata).
type mqttMsg struct {
	Node     string          `json:"node"`
	Metric   string          `json:"metric"`
	Value    json.RawMessage `json:"value"`
	Ts       float64         `json:"ts"`
	Quality  string          `json:"quality"`
	Unit     string          `json:"unit"`
	Firmware string          `json:"firmware"`
	Replaced int64           `json:"replaced"`
}

// Handle ingests one PUBLISH payload and returns one result per reading.
func (b *mqttBridge) Handle(topic string, payload []byte) []string {
	b.mu.Lock()
	b.messages++
	b.lastMsg = time.Now()
	b.mu.Unlock()
	var msgs []mqttMsg
	p := strings.TrimSpace(string(payload))
	switch {
	case strings.HasPrefix(p, "{"):
		var one struct {
			mqttMsg
			Readings []mqttMsg `json:"readings"`
		}
		if err := json.Unmarshal([]byte(p), &one); err != nil {
			b.count("invalid_json")
			return []string{"invalid_json"}
		}
		if len(one.Readings) > 5000 {
			b.count("batch_too_big")
			return []string{"batch_too_big"}
		}
		msgs = one.Readings
		if len(one.Value) > 0 {
			msgs = append(msgs, one.mqttMsg)
		}
	default: // a bare number
		msgs = []mqttMsg{{Value: json.RawMessage(p)}}
	}
	parts := strings.Split(topic, "/")
	out := make([]string, 0, len(msgs))
	for _, m := range msgs {
		if m.Node == "" && m.Metric == "" && len(parts) >= 2 {
			m.Node, m.Metric = parts[len(parts)-2], parts[len(parts)-1]
		}
		res := b.ingest(m)
		b.count(res)
		out = append(out, res)
	}
	return out
}

func normUnit(u string) string {
	u = strings.ToLower(strings.ReplaceAll(strings.TrimSpace(u), " ", ""))
	return strings.NewReplacer("°", "", "µ", "u", "³", "3").Replace(u)
}

func (b *mqttBridge) ingest(m mqttMsg) string {
	v, err := strconv.ParseFloat(strings.Trim(string(m.Value), `"`), 64)
	if err != nil || math.IsNaN(v) || math.IsInf(v, 0) {
		return "invalid_value"
	}
	k := key(m.Node, m.Metric)
	b.eng.mu.RLock()
	sn := b.eng.bank[k]
	unit := ""
	if sn != nil {
		unit = sn.Unit
	}
	b.eng.mu.RUnlock()
	if sn == nil {
		return "unknown_sensor"
	}
	if m.Unit != "" && unit != "" && normUnit(m.Unit) != normUnit(unit) {
		return "rejected_unit"
	}
	if m.Ts > 0 && b.cfg.TrustTime {
		timeSyncObserve(int64(m.Ts), "mqtt")
	}
	b.mu.Lock()
	if m.Firmware != "" && b.firmware[k] != m.Firmware {
		if old := b.firmware[k]; old != "" {
			log.Printf("mqtt: %s firmware %s -> %s", k, old, m.Firmware)
		}
		b.firmware[k] = m.Firmware
	}
	newSwap := m.Replaced > 0 && b.replacedAt[k] != m.Replaced
	if newSwap {
		b.replacedAt[k] = m.Replaced
	}
	b.mu.Unlock()
	if newSwap {
		if _, err := b.eng.SetMaintenance(m.Node, m.Metric, 0, "sensor replaced (MQTT feed)", true); err != nil {
			log.Printf("mqtt: replaced %s: %v", k, err)
		}
	}
	st, err := b.eng.IngestReading(Reading{Node: m.Node, Metric: m.Metric, Value: &v, Ts: m.Ts, Quality: m.Quality}, nowTime().Unix())
	if err != nil {
		return "invalid"
	}
	return st
}
