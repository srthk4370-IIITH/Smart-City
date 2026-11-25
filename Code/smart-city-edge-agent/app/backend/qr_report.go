package main

// Share an incident as QR code(s): GET /api/incidents/{id}/qr
//
// The incident is reduced to its key parts (title, severity, time, place, what is happening, why it
// matters, checklist with ticks, decision + who, AI vs rules), written as compact JSON with short keys,
// deflated (raw), signed with the board's Ed25519 key and cut into 1-3 URL fragments for the static
// viewer (report-viewer/). Nothing is stored anywhere: the whole report lives in the QR codes.
//
//	full   = base64url(deflate(json)) + "." + base64url(ed25519(key, "QR1" + deflate(json)))
//	QR url = viewer + "#" + gid + "." + k + "." + n + "." + part_k     (gid = first 6 hex of sha256(full))
//
// The key is generated at first start (state/qr_key, hex seed, 0600). The viewer verifies against the
// board's public key from its own trust list (report-viewer/dist/config.js), so a forged code shows
// "NOT verified". The board stays edge-only: no PDF or print here, that happens in the viewer.

import (
	"bytes"
	"compress/flate"
	"crypto/ed25519"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"sync"
)

const (
	qrChunkChars = 470 // payload chars per QR (keeps each code around version 17, easy to scan)
	qrMaxChunks  = 3
	qrSigPrefix  = "QR1"
	qrDefaultURL = "https://qidk-report.pages.dev/"
)

type qrStep struct {
	T string `json:"t"`           // step text
	S int    `json:"s,omitempty"` // 0 open, 1 done, 2 not needed
}

// qrDoc: short keys on purpose, every byte counts.
type qrDoc struct {
	V  int      `json:"v"`            // format version
	B  string   `json:"b,omitempty"`  // board id
	I  string   `json:"i"`            // incident id
	T  string   `json:"t"`            // title
	S  string   `json:"s"`            // severity
	W  int64    `json:"w,omitempty"`  // created, unix s
	P  string   `json:"p,omitempty"`  // place
	D  string   `json:"d,omitempty"`  // what is happening
	M  string   `json:"m,omitempty"`  // why it matters
	C  []qrStep `json:"c,omitempty"`  // checklist
	X  string   `json:"x,omitempty"`  // workflow state
	U  string   `json:"u,omitempty"`  // outcome
	N  string   `json:"n,omitempty"`  // decision note
	O  string   `json:"o,omitempty"`  // who (owner / closed by)
	A  string   `json:"a,omitempty"`  // ai | rules
	K  string   `json:"k,omitempty"`  // report source label
	CF int      `json:"cf,omitempty"` // confidence %
	G  int64    `json:"g,omitempty"`  // generated, unix s
	R  string   `json:"r,omitempty"`  // refine stage
}

func qrCut(s string, n int) string {
	s = strings.Join(strings.Fields(s), " ")
	r := []rune(s)
	if len(r) <= n {
		return s
	}
	if n < 2 {
		return string(r[:n])
	}
	return strings.TrimSpace(string(r[:n-1])) + "…"
}

// qrDocOf copies the key parts; scale (0..1) shrinks every free-text limit (used to fit 3 codes).
func qrDocOf(i *Incident, board string, scale float64) qrDoc {
	lim := func(n int) int {
		v := int(float64(n) * scale)
		if v < 12 {
			v = 12
		}
		return v
	}
	r := &i.Mode1
	if i.Final != nil && i.Final.Parsed != nil {
		r = i.Final.Parsed
	}
	d := qrDoc{V: 1, B: board, I: i.ID, T: qrCut(i.Title, lim(90)), S: i.Severity, A: "ai", R: i.RefineStage}
	if d.T == "" {
		d.T = qrCut(r.Title, lim(90))
	}
	if t := wallOf(i); !t.IsZero() {
		d.W = t.Unix()
	}
	places := []string{}
	if i.Scope != "" {
		places = append(places, i.Scope)
	}
	for _, sr := range i.Sensors {
		if !sr.Context && sr.Location != "" {
			dup := false
			for _, p := range places {
				dup = dup || p == sr.Location
			}
			if !dup && len(places) < 3 {
				places = append(places, sr.Location)
			}
		}
	}
	d.P = qrCut(strings.Join(places, "; "), lim(70))
	d.D = qrCut(r.RootCause, lim(220))
	why := r.Explanation
	if why == "" {
		why = r.CausalChain
	}
	d.M = qrCut(why, lim(180))
	if d.M == d.D {
		d.M = ""
	}
	src := strings.ToLower(r.Source)
	if strings.Contains(src, "rules") || (i.Final == nil && r.Source == "") {
		d.A = "rules"
	}
	d.K = qrCut(r.Source, 40)
	if r.Confidence > 0 {
		d.CF = int(r.Confidence*100 + 0.5)
		if r.Confidence > 1 {
			d.CF = int(r.Confidence + 0.5)
		}
	}
	for _, st := range i.Steps {
		if st.State == "withdrawn" || len(d.C) >= 8 {
			continue
		}
		t := st.Text
		if t == "" {
			t = strings.TrimSpace(st.Action + " " + st.Target)
		}
		s := 0
		switch st.State {
		case "done":
			s = 1
		case "not_needed":
			s = 2
		}
		d.C = append(d.C, qrStep{T: qrCut(t, lim(75)), S: s})
	}
	if len(d.C) == 0 {
		for _, c := range r.Checklist {
			if len(d.C) >= 8 {
				break
			}
			d.C = append(d.C, qrStep{T: qrCut(strings.TrimSpace(c.Action+" "+c.Target), lim(75))})
		}
	}
	d.X = wfOf(i)
	d.U = i.Outcome
	d.N = qrCut(i.OutcomeNote, lim(80))
	d.O = i.ClosedBy
	if d.O == "" {
		d.O = i.Owner
	}
	return d
}

func qrB64(b []byte) string { return base64.RawURLEncoding.EncodeToString(b) }

func qrDeflate(b []byte) ([]byte, error) {
	var buf bytes.Buffer
	w, err := flate.NewWriter(&buf, flate.BestCompression)
	if err != nil {
		return nil, err
	}
	if _, err := w.Write(b); err != nil {
		return nil, err
	}
	if err := w.Close(); err != nil {
		return nil, err
	}
	return buf.Bytes(), nil
}

// qrPack builds the signed payload string for a document.
func qrPack(d qrDoc, priv ed25519.PrivateKey) (string, error) {
	js, err := json.Marshal(d)
	if err != nil {
		return "", err
	}
	raw, err := qrDeflate(js)
	if err != nil {
		return "", err
	}
	sig := ed25519.Sign(priv, append([]byte(qrSigPrefix), raw...))
	return qrB64(raw) + "." + qrB64(sig), nil
}

// qrPackFit shrinks the free text until the payload fits qrMaxChunks codes.
func qrPackFit(i *Incident, board string, priv ed25519.PrivateKey) (string, error) {
	var last string
	for _, sc := range []float64{1, 0.8, 0.6, 0.45, 0.3, 0.2} {
		p, err := qrPack(qrDocOf(i, board, sc), priv)
		if err != nil {
			return "", err
		}
		last = p
		if len(p) <= qrChunkChars*qrMaxChunks-60 { // room for the per-part URL fragment prefix
			return p, nil
		}
	}
	return last, fmt.Errorf("report too large for %d codes (%d chars)", qrMaxChunks, len(last))
}

// qrUnpack verifies and decodes a payload. ok is false when the signature does not match pub.
func qrUnpack(full string, pub ed25519.PublicKey) (d qrDoc, ok bool, err error) {
	parts := strings.Split(full, ".")
	if len(parts) != 2 {
		return d, false, errors.New("bad payload")
	}
	raw, err := base64.RawURLEncoding.DecodeString(parts[0])
	if err != nil {
		return d, false, err
	}
	sig, err := base64.RawURLEncoding.DecodeString(parts[1])
	if err != nil {
		return d, false, err
	}
	ok = len(pub) == ed25519.PublicKeySize && ed25519.Verify(pub, append([]byte(qrSigPrefix), raw...), sig)
	js, err := io.ReadAll(io.LimitReader(flate.NewReader(bytes.NewReader(raw)), 1<<20))
	if err != nil {
		return d, ok, err
	}
	err = json.Unmarshal(js, &d)
	return d, ok, err
}

// qrSplit cuts the payload into viewer URLs.
func qrSplit(full, viewer string) (urls []string, gid string) {
	sum := sha256.Sum256([]byte(full))
	gid = hex.EncodeToString(sum[:3])
	n := (len(full) + qrChunkChars - 1) / qrChunkChars
	size := (len(full) + n - 1) / n // even parts
	for k := 0; k < n; k++ {
		a, b := k*size, (k+1)*size
		if b > len(full) {
			b = len(full)
		}
		urls = append(urls, fmt.Sprintf("%s#%s.%d.%d.%s", viewer, gid, k+1, n, full[a:b]))
	}
	return urls, gid
}

var (
	qrKeyMu  sync.Mutex
	qrKeyMap = map[string]ed25519.PrivateKey{}
)

// qrLoadKey returns the board's signing key, creating state/qr_key (hex seed, 0600) at first use.
func qrLoadKey(dir string) (ed25519.PrivateKey, error) {
	qrKeyMu.Lock()
	defer qrKeyMu.Unlock()
	if k, ok := qrKeyMap[dir]; ok {
		return k, nil
	}
	path := filepath.Join(dir, "state", "qr_key")
	var seed []byte
	if b, err := os.ReadFile(path); err == nil {
		if s, err := hex.DecodeString(strings.TrimSpace(string(b))); err == nil && len(s) == ed25519.SeedSize {
			seed = s
		}
	}
	if seed == nil {
		seed = make([]byte, ed25519.SeedSize)
		if _, err := rand.Read(seed); err != nil {
			return nil, err
		}
		if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
			return nil, err
		}
		tmp := path + ".part"
		if err := os.WriteFile(tmp, []byte(hex.EncodeToString(seed)+"\n"), 0o600); err != nil {
			return nil, err
		}
		if err := os.Rename(tmp, path); err != nil {
			return nil, err
		}
	}
	k := ed25519.NewKeyFromSeed(seed)
	qrKeyMap[dir] = k
	return k, nil
}

func qrBoardID() string {
	if b := profStr("board_id"); b != "" {
		return b
	}
	return "board"
}

func qrViewerURL() string {
	u := profStr("qr_viewer")
	if u == "" {
		u = qrDefaultURL
	}
	if i := strings.Index(u, "#"); i >= 0 {
		u = u[:i]
	}
	return u
}

// qrResponse builds the JSON answer for one incident (also used by tests).
func qrResponse(i *Incident, dir string) (map[string]any, error) {
	priv, err := qrLoadKey(dir)
	if err != nil {
		return nil, err
	}
	board := qrBoardID()
	full, err := qrPackFit(i, board, priv)
	if err != nil {
		return nil, err
	}
	urls, gid := qrSplit(full, qrViewerURL())
	svgs := make([]string, 0, len(urls))
	versions := make([]int, 0, len(urls))
	for _, u := range urls {
		mod, ver, err := qrEncode([]byte(u))
		if err != nil {
			return nil, err
		}
		svgs = append(svgs, qrSVG(mod))
		versions = append(versions, ver)
	}
	pub := priv.Public().(ed25519.PublicKey)
	return map[string]any{"payload": full, "payload_chars": len(full), "url": urls[0], "urls": urls, "chunks": len(urls),
		"svg": svgs[0], "svgs": svgs, "versions": versions, "gid": gid, "board": board, "pubkey": hex.EncodeToString(pub),
		"viewer": qrViewerURL(), "id": i.ID}, nil
}

func (s *Server) serveIncidentQR(w http.ResponseWriter, inc *Incident) {
	s.rsn.mu.RLock()
	cp := *inc // the doc is built from a shallow copy; slices are only read
	resp, err := qrResponse(&cp, s.dir)
	s.rsn.mu.RUnlock()
	if err != nil {
		http.Error(w, "qr: "+err.Error(), 500)
		return
	}
	writeJSON(w, resp)
}
