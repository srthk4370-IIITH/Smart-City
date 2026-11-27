package main

// Fog uploader (ROADMAP 2026-11-09 §4 "Fog / cloud sync"; DECISIONS.md "What goes to the cloud"). OFF unless
// htpd_profile fog_upload=1 and fog_url are set.
//
//	fog_upload=1  fog_url=http://fog:8100  fog_token=   (fog_url/fog_token are the chat's fog keys, chat_fog.go)
//	fog_sync_s=60                  upload period
//	fog_outbox_mb=50               offline queue cap (oldest health/summary rows go first, then the oldest incidents)
//	fog_upload_inputs=0            1 = keep the model prompts and sensor windows in uploaded incidents (raw readings)
//	fog_upload_occupancy=0         1 = hourly summaries include per-room occupancy sensors
//	board_id= / site_id=           stamped on every row
//
// Derived data only: incidents with their re-check history, checklist steps, events and outcomes (one row per stored
// version; prompts and 5-min windows stripped), health snapshots (prod_heartbeat.go) and hourly per-sensor summaries
// (mean/min/max/n; occupancy only when allowed). Raw 5-min readings never leave the board.
//
// Outbox: state/fog_outbox.jsonl (append + fsync) and state/fog_outbox.pos (the byte offset sent so far). Each row
// carries (stream, seq): stream is fixed when the outbox is first created, seq rises by one per row. The fog applies a
// row only when its seq is above the highest it applied for that (board, stream), so a retried batch is idempotent and
// an outage just delays rows. POST {fog_url}/v1/ingest {"board_id","site_id","stream","rows":[...]} -> {"ok":true}.
// The fog side is FogIngestHandler (served next to FogHandler by `edge-agent -fog-addr :8100` on a laptop/fog box).

import (
	"bufio"
	"bytes"
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"math"
	"net/http"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"time"
)

type fogRow struct {
	Seq  int64           `json:"seq"`
	Kind string          `json:"kind"` // incident | health | summary
	Key  string          `json:"key"`  // incident id; sensor key for summaries
	TS   int64           `json:"ts"`   // board wall time when queued
	Data json.RawMessage `json:"data"`
}

type fogUploader struct {
	mu        sync.Mutex
	dir       string
	eng       *Engine
	every     time.Duration
	capBytes  int64
	inputs    bool
	occupancy bool
	stream    string
	seq       int64
	lastHour  int64 // sim hour of the last summary
	sent      int
	fails     int
	lastErr   string
	lastOK    time.Time
	dropped   int
	url       func() string
	client    *http.Client
}

func newFogUploaderFromProfile(dir string, e *Engine) *fogUploader {
	if !profOn("fog_upload") || fogURL() == "" {
		return nil
	}
	f := newFogUploader(dir, e)
	f.every = time.Duration(profInt("fog_sync_s", 60, 5, 3600)) * time.Second
	f.capBytes = int64(profInt("fog_outbox_mb", 50, 1, 2000)) << 20
	f.inputs, f.occupancy = profOn("fog_upload_inputs"), profOn("fog_upload_occupancy")
	return f
}

func newFogUploader(dir string, e *Engine) *fogUploader {
	f := &fogUploader{dir: filepath.Join(dir, "state"), eng: e, every: time.Minute, capBytes: 50 << 20, url: fogURL,
		client: &http.Client{Timeout: 30 * time.Second}}
	os.MkdirAll(f.dir, 0o755)
	if b, err := os.ReadFile(f.path("fog_outbox.stream")); err == nil && len(bytes.TrimSpace(b)) > 0 {
		f.stream = strings.TrimSpace(string(b))
	} else {
		var r [8]byte
		rand.Read(r[:])
		f.stream = hex.EncodeToString(r[:])
		writeFileAtomic(f.path("fog_outbox.stream"), []byte(f.stream+"\n"))
	}
	if b, err := os.ReadFile(f.path("fog_outbox.seq")); err == nil {
		f.seq, _ = strconv.ParseInt(strings.TrimSpace(string(b)), 10, 64)
	}
	for _, r := range f.readRows(0, math.MaxInt) { // a seq file older than the outbox (power cut between writes)
		f.seq = max(f.seq, r.Seq)
	}
	return f
}

func (f *fogUploader) path(n string) string { return filepath.Join(f.dir, n) }

func writeFileAtomic(p string, b []byte) error { return atomicWrite(p, b, 0o644) }

func (f *fogUploader) pos() int64 {
	b, _ := os.ReadFile(f.path("fog_outbox.pos"))
	n, _ := strconv.ParseInt(strings.TrimSpace(string(b)), 10, 64)
	return n
}

func (f *fogUploader) Stats() map[string]any {
	f.mu.Lock()
	defer f.mu.Unlock()
	size := int64(0)
	if st, err := os.Stat(f.path("fog_outbox.jsonl")); err == nil {
		size = st.Size()
	}
	out := map[string]any{"outbox_bytes": size - f.pos(), "seq": f.seq, "sent_rows": f.sent, "failures": f.fails,
		"last_error": f.lastErr, "dropped_rows": f.dropped, "stream": f.stream}
	if !f.lastOK.IsZero() {
		out["last_sync_age_s"] = int(time.Since(f.lastOK).Seconds())
	}
	return out
}

// Enqueue appends one row to the outbox (data is marshalled as is).
func (f *fogUploader) Enqueue(kind, key string, data any) {
	b, err := json.Marshal(data)
	if err != nil {
		return
	}
	f.mu.Lock()
	defer f.mu.Unlock()
	f.seq++
	line, _ := json.Marshal(fogRow{Seq: f.seq, Kind: kind, Key: key, TS: nowTime().Unix(), Data: b})
	fh, err := os.OpenFile(f.path("fog_outbox.jsonl"), os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o644)
	if err != nil {
		log.Printf("fog: outbox: %v", err)
		return
	}
	fh.Write(append(line, '\n'))
	fh.Sync()
	fh.Close()
	os.WriteFile(f.path("fog_outbox.seq"), []byte(strconv.FormatInt(f.seq, 10)), 0o644)
	if st, err := os.Stat(f.path("fog_outbox.jsonl")); err == nil && st.Size() > f.capBytes {
		f.compactLocked(true)
	}
}

// OnIncident: the persist hook. One stripped row per stored incident version.
func (f *fogUploader) OnIncident(b []byte) {
	var m map[string]any
	if json.Unmarshal(b, &m) != nil {
		return
	}
	id, _ := m["id"].(string)
	if id == "" {
		return
	}
	if !f.inputs {
		stripIncident(m)
	}
	f.Enqueue("incident", id, m)
}

// stripIncident removes what carries raw readings: the sensor windows and the model prompts (which embed them).
func stripIncident(m map[string]any) {
	if ss, ok := m["sensors"].([]any); ok {
		for _, s := range ss {
			if sm, ok := s.(map[string]any); ok {
				delete(sm, "window")
			}
		}
	}
	if as, ok := m["agents"].([]any); ok {
		for _, a := range as {
			if am, ok := a.(map[string]any); ok {
				delete(am, "prompt")
			}
		}
	}
	if fm, ok := m["final"].(map[string]any); ok {
		delete(fm, "prompt")
	}
}

// summarise queues the hourly per-sensor summaries for every sim hour completed since the last one.
func (f *fogUploader) summarise() {
	if f.eng == nil {
		return
	}
	sim, states, _ := f.eng.Snapshot()
	hour := sim / 3600
	f.mu.Lock()
	last := f.lastHour
	f.lastHour = hour
	f.mu.Unlock()
	if last == 0 || hour <= last {
		return
	}
	end := hour * 3600
	for _, st := range states {
		if st.Role == "occupancy" && !f.occupancy {
			continue
		}
		xs := f.eng.HistoryAt(st.Node, st.Metric, end, 3600/bucketSec)
		if len(xs) == 0 {
			continue
		}
		lo, hi, sum := math.Inf(1), math.Inf(-1), 0.0
		for _, x := range xs {
			lo, hi, sum = math.Min(lo, x), math.Max(hi, x), sum+x
		}
		f.Enqueue("summary", st.Node+"|"+st.Metric, map[string]any{"node": st.Node, "metric": st.Metric, "role": st.Role,
			"unit": st.Unit, "hour_end_sim": end, "n": len(xs), "mean": round1(sum / float64(len(xs))), "min": lo, "max": hi})
	}
}

// readRows reads up to n rows starting at byte offset off.
func (f *fogUploader) readRows(off int64, n int) []fogRow {
	fh, err := os.Open(f.path("fog_outbox.jsonl"))
	if err != nil {
		return nil
	}
	defer fh.Close()
	fh.Seek(off, io.SeekStart)
	sc := bufio.NewScanner(fh)
	sc.Buffer(make([]byte, 1<<20), 16<<20)
	var out []fogRow
	for len(out) < n && sc.Scan() {
		var r fogRow
		if json.Unmarshal(sc.Bytes(), &r) == nil && r.Seq > 0 {
			out = append(out, r)
		}
	}
	return out
}

// Sync sends every unsent row in batches (at most 200 rows / 1 MB each). Returns the first error.
func (f *fogUploader) Sync(ctx context.Context) error {
	for {
		f.mu.Lock()
		off := f.pos()
		fh, err := os.Open(f.path("fog_outbox.jsonl"))
		if err != nil {
			f.mu.Unlock()
			return nil // nothing queued yet
		}
		fh.Seek(off, io.SeekStart)
		rd := bufio.NewReader(fh)
		var rows []json.RawMessage
		var used int64
		size := 0
		for len(rows) < 200 && size < 1<<20 {
			line, err := rd.ReadBytes('\n')
			if err != nil { // a torn last line (power cut) is left for the next compaction
				break
			}
			used += int64(len(line))
			if t := bytes.TrimSpace(line); len(t) > 0 && json.Valid(t) {
				rows = append(rows, json.RawMessage(t))
				size += len(t)
			}
		}
		fh.Close()
		f.mu.Unlock()
		if len(rows) == 0 {
			f.mu.Lock()
			f.compactLocked(false)
			f.mu.Unlock()
			return nil
		}
		if err := f.post(ctx, rows); err != nil {
			f.mu.Lock()
			f.fails++
			f.lastErr = err.Error()
			f.mu.Unlock()
			fogC.mark(false)
			return err
		}
		f.mu.Lock()
		if f.pos() == off { // a compaction in between would have reset it
			writeFileAtomic(f.path("fog_outbox.pos"), []byte(strconv.FormatInt(off+used, 10)))
		}
		f.sent += len(rows)
		f.lastErr, f.lastOK = "", time.Now()
		f.mu.Unlock()
		fogC.mark(true)
	}
}

func (f *fogUploader) post(ctx context.Context, rows []json.RawMessage) error {
	body, _ := json.Marshal(map[string]any{"board_id": profStr("board_id"), "site_id": profStr("site_id"), "stream": f.stream, "rows": rows})
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, strings.TrimRight(f.url(), "/")+"/v1/ingest", bytes.NewReader(body))
	if err != nil {
		return err
	}
	req.Header.Set("Content-Type", "application/json")
	if tok := reasonerProfile("fog_token", "SCE_FOG_TOKEN"); tok != "" {
		req.Header.Set("Authorization", "Bearer "+tok)
	}
	resp, err := f.client.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	var out struct {
		OK bool `json:"ok"`
	}
	if resp.StatusCode != http.StatusOK || json.NewDecoder(io.LimitReader(resp.Body, 1<<16)).Decode(&out) != nil || !out.OK {
		return fmt.Errorf("fog ingest: HTTP %d", resp.StatusCode)
	}
	return nil
}

// compactLocked rewrites the outbox without the sent prefix, keeping only the newest version of each unsent incident.
// overCap also drops the oldest rows (health and summaries first) until the file is under 90% of the cap.
func (f *fogUploader) compactLocked(overCap bool) {
	off := f.pos()
	st, err := os.Stat(f.path("fog_outbox.jsonl"))
	if err != nil || (!overCap && off < st.Size() && off < 1<<20) {
		return // little to gain: rewrite only when everything was sent or 1 MB of sent rows piled up
	}
	rows := f.readRows(off, math.MaxInt)
	newest := map[string]int64{}
	for _, r := range rows {
		if r.Kind == "incident" {
			newest[r.Key] = r.Seq
		}
	}
	keep := rows[:0]
	var size int64
	for _, r := range rows {
		if r.Kind == "incident" && newest[r.Key] != r.Seq {
			continue
		}
		keep = append(keep, r)
		size += int64(len(r.Data)) + 100
	}
	for _, pass := range []string{"other", "incident"} {
		for i := 0; overCap && size > f.capBytes*9/10 && i < len(keep); {
			if (pass == "other") == (keep[i].Kind == "incident") {
				i++
				continue
			}
			size -= int64(len(keep[i].Data)) + 100
			keep = append(keep[:i], keep[i+1:]...)
			f.dropped++
		}
	}
	var buf bytes.Buffer
	for _, r := range keep {
		b, _ := json.Marshal(r)
		buf.Write(append(b, '\n'))
	}
	if writeFileAtomic(f.path("fog_outbox.jsonl"), buf.Bytes()) == nil {
		writeFileAtomic(f.path("fog_outbox.pos"), []byte("0"))
	}
	if f.dropped > 0 && overCap {
		log.Printf("fog: outbox over %d MB: %d oldest rows dropped so far", f.capBytes>>20, f.dropped)
	}
}

func (f *fogUploader) Run(stop <-chan struct{}) {
	t := time.NewTicker(f.every)
	defer t.Stop()
	for {
		f.summarise()
		ctx, cancel := context.WithTimeout(context.Background(), 2*time.Minute)
		if err := f.Sync(ctx); err != nil {
			logQuiet("fog-upload", "fog: upload failed (%v); rows stay queued", err)
		}
		cancel()
		select {
		case <-stop:
			return
		case <-t.C:
		}
	}
}

// ---------------------------------------------------------------- fog side

// FogIngestHandler: POST /v1/ingest on the fog. Incidents are upserted into r (so FogHandler's queries see them);
// health and summary rows are appended to state/fog_rows.jsonl. Rows at or below the highest seq applied for their
// (board, stream) are skipped (idempotent retries). Bearer token: SCE_FOG_INGEST_TOKEN when set.
func FogIngestHandler(r *Reasoner, dir string) http.Handler {
	var mu sync.Mutex
	seqFile := filepath.Join(dir, "state", "fog_seq.json")
	rowsFile := filepath.Join(dir, "state", "fog_rows.jsonl")
	applied := map[string]int64{}
	if b, err := os.ReadFile(seqFile); err == nil {
		json.Unmarshal(b, &applied)
	}
	return http.HandlerFunc(func(w http.ResponseWriter, req *http.Request) {
		// fails closed: no token configured = nothing is accepted (a fog box on a LAN must not take rows from anyone)
		tok := profStr("fog_ingest_token")
		if tok == "" {
			http.Error(w, "fog ingest is off: no SCE_FOG_INGEST_TOKEN / fog_ingest_token configured", http.StatusServiceUnavailable)
			return
		}
		if !tokenEq(strings.TrimPrefix(req.Header.Get("Authorization"), "Bearer "), tok) {
			http.Error(w, "unauthorised", http.StatusUnauthorized)
			return
		}
		var in struct {
			Board  string   `json:"board_id"`
			Site   string   `json:"site_id"`
			Stream string   `json:"stream"`
			Rows   []fogRow `json:"rows"`
		}
		if req.Method != http.MethodPost || json.NewDecoder(io.LimitReader(req.Body, 32<<20)).Decode(&in) != nil || in.Stream == "" {
			http.Error(w, "bad request", http.StatusBadRequest)
			return
		}
		mu.Lock()
		defer mu.Unlock()
		k := in.Board + "|" + in.Stream
		n, skipped := 0, 0
		var other bytes.Buffer
		for _, row := range in.Rows {
			if row.Seq <= applied[k] {
				skipped++
				continue
			}
			switch row.Kind {
			case "incident":
				var inc Incident
				if json.Unmarshal(row.Data, &inc) != nil || inc.ID == "" {
					skipped++
					continue
				}
				r.upsertIncident(&inc)
			default:
				b, _ := json.Marshal(map[string]any{"board_id": in.Board, "site_id": in.Site, "kind": row.Kind, "key": row.Key,
					"seq": row.Seq, "ts": row.TS, "data": row.Data})
				other.Write(append(b, '\n'))
			}
			applied[k] = row.Seq
			n++
		}
		if other.Len() > 0 {
			fogMu.Lock()
			err := appendSync(rowsFile, other.Bytes())
			capTail(rowsFile, fogRowsCapBytes)
			fogMu.Unlock()
			if err != nil {
				log.Printf("fog: rows write failed: %v", err)
				http.Error(w, "storage error", http.StatusInsufficientStorage)
				return
			}
		}
		b, _ := json.Marshal(applied)
		os.MkdirAll(filepath.Dir(seqFile), 0o755)
		writeFileAtomic(seqFile, b)
		writeJSON(w, map[string]any{"ok": true, "applied": n, "skipped": skipped, "seq": applied[k]})
	})
}

// upsertIncident replaces (or adds) an incident by ID and persists it (the fog's copy; never runs on the board).
func (r *Reasoner) upsertIncident(inc *Incident) {
	r.mu.Lock()
	found := false
	for i, x := range r.incidents {
		if x.ID == inc.ID {
			r.incidents[i] = inc
			found = true
			break
		}
	}
	if !found {
		r.incidents = append(r.incidents, inc)
	}
	if n := incNum(inc.ID); n > r.seq {
		r.seq = n
	}
	r.mu.Unlock()
	r.persist(inc)
}

// serveFog: the fog side on a laptop / fog box (`edge-agent -fog-addr :8100`): /v1/tool, /v1/status, /v1/ingest.
func serveFog(addr string, r *Reasoner, dir string) {
	mux := http.NewServeMux()
	mux.Handle("/v1/ingest", FogIngestHandler(r, dir))
	mux.Handle("/", FogHandler(r, fogKBCache))
	log.Printf("fog: serving /v1/tool, /v1/status, /v1/ingest on %s", addr)
	srv := &http.Server{Addr: addr, Handler: mux, ReadHeaderTimeout: 10 * time.Second}
	log.Fatal(srv.ListenAndServe())
}
