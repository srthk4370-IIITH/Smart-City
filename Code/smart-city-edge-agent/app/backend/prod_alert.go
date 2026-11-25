package main

// Alert delivery (ROADMAP 2026-11-09 §4 "Alert delivery"). OFF unless alert_webhook or alert_smtp is set.
//
//	alert_webhook=https://ntfy.sh/my-topic,https://hooks.slack.com/...   one or more URLs (POST)
//	alert_webhook_format=json            json (the alert object) | slack ({"text"}) | ntfy (text + Title/Priority
//	                                     headers) | text (plain body). Telegram/SMS gateways: json or text + their URL.
//	alert_webhook_header=Authorization: Bearer xyz      optional extra header
//	alert_smtp=smtp.example.com:587  alert_smtp_user=  alert_smtp_pass=  alert_email_from=  alert_email_to=a@x,b@y
//	alert_on=critical,approved           what alerts: critical (fast path / reasoner / rules), approved (operator
//	                                     approved an incident), warning (every warning; off by default)
//	alert_injected=0                     demo-injected incidents do not page people (1 = they do)
//	alert_escalate_min=15                an unacknowledged critical is sent again after N, 2N and 4N min (15 / 30 / 60), the
//	                                     last time also to the backup contact (0 = off)
//	alert_escalate_webhook= / alert_escalate_email=      escalation target (absent = the normal channels)
//	alert_backup_email=a@x               backup contact (SMTP): told at the third reminder, 4x alert_escalate_min (60 min)
//	alert_rate_per_hour=30               flood guard: more waits (critical ones first), nothing is dropped
//	alert_link=http://<board>:8000/      base link put in the message ("#incident=<id>" appended)
//
// Queue: state/alert_queue.json (rewritten atomically on every change), so a restart or power cut never loses an
// alert that was not delivered. Retry with backoff 15 s .. 15 min; an alert older than 24 h is dropped with a log
// line. Dedup: one alert per (incident, reason); the sent keys are kept 7 days.

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"net/smtp"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"sync"
	"time"
)

type alertPayload struct {
	Key       string `json:"key"` // incident|reason (dedup)
	Incident  string `json:"incident"`
	Reason    string `json:"reason"` // critical | approved | warning | escalation
	Severity  string `json:"severity"`
	Title     string `json:"title"`
	Text      string `json:"text"`
	Created   string `json:"created_wall,omitempty"`
	Link      string `json:"link,omitempty"`
	Escalated bool   `json:"escalated,omitempty"`
	Board     string `json:"board_id,omitempty"`
}

type alertItem struct {
	Chan    string       `json:"chan"`
	Msg     alertPayload `json:"msg"`
	Tries   int          `json:"tries"`
	NextTry int64        `json:"next_try"`
	First   int64        `json:"first"`
	LastErr string       `json:"last_err,omitempty"`
}

type alertChan struct {
	name string
	send func(ctx context.Context, m alertPayload) error
}

type alertWatch struct {
	Since     int64     `json:"since"`
	Escalated bool      `json:"escalated"`
	Level     int       `json:"level,omitempty"` // reminders sent: 1 = first (alert_escalate_min), 2 = 2x, 3 = 4x + the backup contact
	Inc       incFields `json:"inc"`             // newest version seen (escalation text)
}

type alerter struct {
	mu         sync.Mutex
	file       string
	chans      []alertChan
	escal      []alertChan
	backup     []alertChan // the backup contact (alert_backup_email), told at the last reminder level
	escalAfter time.Duration
	rate       int
	on         map[string]bool
	injected   bool
	link       string
	now        func() time.Time

	Queue  []alertItem            `json:"queue"`
	Sent   map[string]int64       `json:"sent"`
	Watch  map[string]*alertWatch `json:"watch"`
	sentAt []time.Time
	stats  map[string]int
}

func webhookChan(name, u, format, header string) alertChan {
	return alertChan{name: name, send: func(ctx context.Context, m alertPayload) error {
		var body []byte
		ctype := "application/json"
		switch format {
		case "slack":
			body, _ = json.Marshal(map[string]string{"text": m.Text})
		case "ntfy", "text":
			body, ctype = []byte(m.Text), "text/plain; charset=utf-8"
		default:
			body, _ = json.Marshal(m)
		}
		req, err := http.NewRequestWithContext(ctx, http.MethodPost, u, bytes.NewReader(body))
		if err != nil {
			return err
		}
		req.Header.Set("Content-Type", ctype)
		if format == "ntfy" {
			req.Header.Set("Title", m.Title)
			if m.Severity == "critical" || m.Escalated {
				req.Header.Set("Priority", "urgent")
			}
			if m.Link != "" {
				req.Header.Set("Click", m.Link)
			}
		}
		if k, v, ok := strings.Cut(header, ":"); ok {
			req.Header.Set(strings.TrimSpace(k), strings.TrimSpace(v))
		}
		resp, err := http.DefaultClient.Do(req)
		if err != nil {
			return err
		}
		io.Copy(io.Discard, io.LimitReader(resp.Body, 64<<10))
		resp.Body.Close()
		if resp.StatusCode/100 != 2 {
			return fmt.Errorf("HTTP %d", resp.StatusCode)
		}
		return nil
	}}
}

// smtpSend is net/smtp.SendMail (STARTTLS when the server offers it); tests swap the address only.
func smtpChan(name, addr, user, pass, from string, to []string) alertChan {
	return alertChan{name: name, send: func(ctx context.Context, m alertPayload) error {
		var auth smtp.Auth
		if user != "" {
			host, _, _ := strings.Cut(addr, ":")
			auth = smtp.PlainAuth("", user, pass, host)
		}
		msg := fmt.Sprintf("From: %s\r\nTo: %s\r\nSubject: %s\r\nContent-Type: text/plain; charset=utf-8\r\n\r\n%s\r\n",
			from, strings.Join(to, ", "), strings.ReplaceAll(m.Title, "\n", " "), strings.ReplaceAll(m.Text, "\n", "\r\n"))
		done := make(chan error, 1)
		go func() { done <- smtp.SendMail(addr, auth, from, to, []byte(msg)) }()
		select {
		case err := <-done:
			return err
		case <-ctx.Done():
			return ctx.Err()
		}
	}}
}

func newAlerterFromProfile(dir string) *alerter {
	format, header := profStr("alert_webhook_format"), profStr("alert_webhook_header")
	var chans, escal []alertChan
	for i, u := range profList("alert_webhook") {
		chans = append(chans, webhookChan(fmt.Sprintf("webhook%d", i+1), u, format, header))
	}
	from := profStr("alert_email_from")
	if a := profStr("alert_smtp"); a != "" && len(profList("alert_email_to")) > 0 {
		chans = append(chans, smtpChan("email", a, profStr("alert_smtp_user"), profStr("alert_smtp_pass"), from, profList("alert_email_to")))
	}
	if len(chans) == 0 {
		return nil
	}
	if u := profStr("alert_escalate_webhook"); u != "" {
		escal = append(escal, webhookChan("escalate_webhook", u, format, header))
	}
	if to := profList("alert_escalate_email"); len(to) > 0 && profStr("alert_smtp") != "" {
		escal = append(escal, smtpChan("escalate_email", profStr("alert_smtp"), profStr("alert_smtp_user"), profStr("alert_smtp_pass"), from, to))
	}
	on := map[string]bool{}
	for _, s := range profList("alert_on") {
		on[s] = true
	}
	if len(on) == 0 {
		on = map[string]bool{"critical": true, "approved": true}
	}
	a := newAlerter(filepath.Join(dir, "state", "alert_queue.json"), chans, escal)
	if to := profList("alert_backup_email"); len(to) > 0 && profStr("alert_smtp") != "" {
		a.backup = append(a.backup, smtpChan("backup_email", profStr("alert_smtp"), profStr("alert_smtp_user"), profStr("alert_smtp_pass"), from, to))
	}
	a.on, a.injected, a.link = on, profOn("alert_injected"), profStr("alert_link")
	a.escalAfter = time.Duration(profInt("alert_escalate_min", 15, 0, 1440)) * time.Minute
	a.rate = profInt("alert_rate_per_hour", 30, 1, 10000)
	return a
}

func newAlerter(file string, chans, escal []alertChan) *alerter {
	a := &alerter{file: file, chans: chans, escal: escal, escalAfter: 15 * time.Minute, rate: 30,
		on: map[string]bool{"critical": true, "approved": true}, now: time.Now,
		Sent: map[string]int64{}, Watch: map[string]*alertWatch{}, stats: map[string]int{}}
	if b, err := os.ReadFile(file); err == nil {
		if json.Unmarshal(b, a) != nil {
			log.Printf("alerts: %s unreadable, starting with an empty queue", file)
		}
	}
	if a.Sent == nil {
		a.Sent = map[string]int64{}
	}
	if a.Watch == nil {
		a.Watch = map[string]*alertWatch{}
	}
	now := a.now().Unix()
	for i := range a.Queue { // the clock may have jumped while the board was off: retry what is queued now
		a.Queue[i].NextTry = now
	}
	return a
}

func (a *alerter) Stats() map[string]any {
	a.mu.Lock()
	defer a.mu.Unlock()
	st := map[string]int{}
	for k, v := range a.stats {
		st[k] = v
	}
	return map[string]any{"queued": len(a.Queue), "watching": len(a.Watch), "counts": st}
}

// save writes the queue state atomically (caller holds a.mu).
func (a *alerter) save() {
	b, err := json.Marshal(a)
	if err != nil {
		return
	}
	if err := atomicWrite(a.file, b, 0o644); err != nil {
		log.Printf("alerts: queue not saved: %v", err)
	}
}

// incFields: what alerting reads from a stored incident line.
type incFields struct {
	ID          string   `json:"id"`
	State       string   `json:"state"`
	Severity    string   `json:"severity"`
	Title       string   `json:"title"`
	Injected    bool     `json:"injected"`
	Approval    string   `json:"approval"`
	Workflow    string   `json:"workflow"`
	AckedAt     int64    `json:"acked_at"`
	CreatedWall string   `json:"created_wall"`
	Roles       []string `json:"roles"`
	FastPath    bool     `json:"fast_path"`
	Sensors     []struct {
		Node     string `json:"node"`
		Metric   string `json:"metric"`
		Location string `json:"location"`
		Context  bool   `json:"context"`
	} `json:"sensors"`
}

func (a *alerter) message(f incFields, reason string) alertPayload {
	sev := normSeverity(f.Severity)
	var where []string
	for _, s := range f.Sensors {
		if !s.Context {
			where = append(where, strings.TrimSpace(s.Node+" "+s.Metric+" "+s.Location))
		}
	}
	m := alertPayload{Key: f.ID + "|" + reason, Incident: f.ID, Reason: reason, Severity: sev, Created: f.CreatedWall,
		Board: profStr("board_id")}
	head := map[string]string{"critical": "CRITICAL", "approved": "Approved", "warning": "Warning", "escalation": "ESCALATION (not acknowledged)"}[reason]
	m.Title = fmt.Sprintf("%s: %s (%s)", head, f.Title, f.ID)
	if a.link != "" {
		m.Link = strings.TrimRight(a.link, "/") + "/#incident=" + f.ID
	}
	m.Text = fmt.Sprintf("%s\nSeverity: %s\nSensors: %s\nCreated: %s", m.Title, sev, strings.Join(where, "; "), f.CreatedWall)
	if m.Link != "" {
		m.Text += "\nOpen: " + m.Link
	}
	if reason == "escalation" {
		m.Escalated = true
	}
	return m
}

// OnIncident: the persist hook. Queues the alerts this incident version triggers and tracks acknowledgement.
func (a *alerter) OnIncident(b []byte) {
	var f incFields
	if json.Unmarshal(b, &f) != nil || f.ID == "" {
		return
	}
	if f.Injected && !a.injected {
		return
	}
	sev := normSeverity(f.Severity)
	a.mu.Lock()
	defer a.mu.Unlock()
	changed := false
	if sev == "critical" && a.on["critical"] {
		changed = a.enqueue(a.message(f, "critical"), a.chans) || changed
	}
	if sev == "warning" && a.on["warning"] && f.State != "running" {
		changed = a.enqueue(a.message(f, "warning"), a.chans) || changed
	}
	if f.Approval == "approved" && a.on["approved"] {
		changed = a.enqueue(a.message(f, "approved"), a.chans) || changed
	}
	open := sev == "critical" && f.AckedAt == 0 && f.Approval != "dismissed" && f.Approval != "approved" && f.Workflow != "closed"
	if w := a.Watch[f.ID]; w != nil && !open {
		delete(a.Watch, f.ID)
		changed = true
	} else if w == nil && open && a.escalAfter > 0 && a.Sent[f.ID+"|escalation"] == 0 {
		a.Watch[f.ID] = &alertWatch{Since: a.now().Unix()}
		changed = true
	}
	if w := a.Watch[f.ID]; w != nil {
		w.Inc = f
	}
	if changed {
		a.save()
	}
}

// enqueue adds one message per channel unless its key was sent or queued already (caller holds a.mu).
func (a *alerter) enqueue(m alertPayload, chans []alertChan) bool {
	if _, sent := a.Sent[m.Key]; sent {
		return false
	}
	for _, it := range a.Queue {
		if it.Msg.Key == m.Key {
			return false
		}
	}
	now := a.now().Unix()
	for _, c := range chans {
		a.Queue = append(a.Queue, alertItem{Chan: c.name, Msg: m, NextTry: now, First: now})
	}
	a.stats["queued"]++
	if len(a.Queue) > 1000 { // a dead channel for days: keep the newest
		a.Queue = a.Queue[len(a.Queue)-1000:]
	}
	return true
}

func (a *alerter) chanByName(n string) *alertChan {
	for _, l := range [][]alertChan{a.chans, a.escal, a.backup} {
		for i := range l {
			if l[i].name == n {
				return &l[i]
			}
		}
	}
	return nil
}

// Tick: escalations that are due, then every queued message that is due (within the rate limit).
func (a *alerter) Tick() {
	a.mu.Lock()
	now := a.now()
	a.escalateDue(now)
	// rate window
	keep := a.sentAt[:0]
	for _, t := range a.sentAt {
		if now.Sub(t) < time.Hour {
			keep = append(keep, t)
		}
	}
	a.sentAt = keep
	var due []int
	for i, it := range a.Queue {
		if it.NextTry <= now.Unix() {
			due = append(due, i)
		}
	}
	rank := func(m alertPayload) int {
		switch {
		case m.Escalated:
			return 0
		case m.Severity == "critical":
			return 1
		}
		return 2
	}
	sort.SliceStable(due, func(x, y int) bool { return rank(a.Queue[due[x]].Msg) < rank(a.Queue[due[y]].Msg) })
	type job struct {
		it alertItem
		c  *alertChan
	}
	var jobs []job
	for _, i := range due {
		if len(a.sentAt)+len(jobs) >= a.rate {
			a.stats["rate_limited"]++
			break
		}
		jobs = append(jobs, job{a.Queue[i], a.chanByName(a.Queue[i].Chan)})
	}
	a.mu.Unlock()

	type result struct {
		it  alertItem
		err error
	}
	var res []result
	for _, j := range jobs {
		var err error
		if j.c == nil {
			err = fmt.Errorf("channel %s no longer configured", j.it.Chan)
		} else {
			ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
			err = j.c.send(ctx, j.it.Msg)
			cancel()
		}
		res = append(res, result{j.it, err})
	}

	a.mu.Lock()
	defer a.mu.Unlock()
	if len(res) == 0 {
		return
	}
	for _, r := range res {
		idx := -1
		for i, it := range a.Queue {
			if it.Chan == r.it.Chan && it.Msg.Key == r.it.Msg.Key {
				idx = i
				break
			}
		}
		if idx < 0 {
			continue
		}
		it := &a.Queue[idx]
		switch {
		case r.err == nil:
			a.sentAt = append(a.sentAt, now)
			a.stats["sent"]++
			a.Queue = append(a.Queue[:idx], a.Queue[idx+1:]...)
			if !a.queuedKey(r.it.Msg.Key) {
				a.Sent[r.it.Msg.Key] = now.Unix()
			}
		case now.Unix()-it.First > 24*3600:
			log.Printf("alerts: %s via %s dropped after 24 h: %v", it.Msg.Key, it.Chan, r.err)
			a.stats["dropped"]++
			a.Queue = append(a.Queue[:idx], a.Queue[idx+1:]...)
		default:
			it.Tries++
			it.LastErr = r.err.Error()
			back := 15 * time.Second
			for i := 1; i < it.Tries && back < 15*time.Minute; i++ {
				back *= 2
			}
			if back > 15*time.Minute {
				back = 15 * time.Minute
			}
			it.NextTry = now.Add(back).Unix()
			a.stats["retries"]++
			log.Printf("alerts: %s via %s failed (%v), retry %d in %v", it.Msg.Key, it.Chan, r.err, it.Tries, back)
		}
	}
	for k, t := range a.Sent {
		if now.Unix()-t > 7*24*3600 {
			delete(a.Sent, k)
		}
	}
	a.save()
}

func (a *alerter) queuedKey(k string) bool {
	for _, it := range a.Queue {
		if it.Msg.Key == k {
			return true
		}
	}
	return false
}

func (a *alerter) Run(stop <-chan struct{}) {
	t := time.NewTicker(5 * time.Second)
	defer t.Stop()
	for {
		select {
		case <-stop:
			return
		case <-t.C:
			safeIter("alerter", a.Tick)
		}
	}
}

// escalateDue re-notifies every unacknowledged critical at 1x, 2x and 4x alert_escalate_min (15 / 30 / 60 min by
// default) on the escalation channels (or the normal ones), and at the last level also tells the backup contact
// (alert_backup_email, by SMTP). The first level keeps the key "<id>|escalation" (older queue files stay valid).
// Caller holds a.mu.
func (a *alerter) escalateDue(now time.Time) {
	if a.escalAfter <= 0 {
		return
	}
	changed := false
	for _, w := range a.Watch {
		for w.Level < 3 {
			due := int64(a.escalAfter/time.Second) * int64(1<<w.Level) // 1x, 2x, 4x
			if now.Unix()-w.Since < due {
				break
			}
			w.Level++
			w.Escalated = true
			m := a.message(w.Inc, "escalation")
			if w.Level > 1 {
				m.Key = fmt.Sprintf("%s|escalation%d", w.Inc.ID, w.Level)
				m.Title = fmt.Sprintf("ESCALATION %d (not acknowledged for %d min): %s (%s)", w.Level, int(due/60), w.Inc.Title, w.Inc.ID)
				m.Text = strings.Replace(m.Text, m.Text[:strings.Index(m.Text, "\n")], m.Title, 1)
			}
			chans := a.escal
			if len(chans) == 0 {
				chans = a.chans
			}
			a.enqueue(m, chans)
			if w.Level == 3 && len(a.backup) > 0 {
				mb := m
				mb.Key += "|backup"
				a.enqueue(mb, a.backup)
			}
			changed = true
		}
	}
	if changed {
		a.save()
	}
}

// SendSystem queues a non-incident alert (disk full, ...) once per key on the normal channels.
func (a *alerter) SendSystem(key, title, text string) {
	a.mu.Lock()
	defer a.mu.Unlock()
	if a.enqueue(alertPayload{Key: "system|" + key, Reason: "system", Severity: "warning", Title: title, Text: title + "\n" + text, Board: profStr("board_id")}, a.chans) {
		a.save()
	}
}

// alertChannelConfigured: at least one delivery channel exists (else /api/health says no_alert_channel).
func alertChannelConfigured() bool { return prod.alert != nil && len(prod.alert.chans) > 0 }
