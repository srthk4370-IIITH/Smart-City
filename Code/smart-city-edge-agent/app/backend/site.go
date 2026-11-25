package main

// Site model (V3_DESIGN §3): campus tree + typed links + spec cards, stored on the board as versioned JSON
// (state/site.json, every saved version also in state/site_versions/). Built automatically from the campus API node
// registry (/verticals/all/nodes, campus.go) and the sensor bank: building from the node name, floor / room from the node
// code, x,y + lat/lon from the API; links proposed by rules and marked inferred with a reason. The owner edits it in the
// map UI (web/site/); PUT /api/site validates and saves a new version, used at once by the agents (cards), the grouper,
// the roll-up and the site chat tools.
//
// Index mirrors core/sitegraph.py Index (relation, link_path, rollup, suspects) - TestSiteRelationParity /
// TestSiteSuspectParity check it on the Python fixture sites.

import (
	"encoding/json"
	"errors"
	"fmt"
	"log"
	"net/http"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"
)

type SiteNode struct {
	ID       string         `json:"id"`
	Kind     string         `json:"kind"`
	Parent   string         `json:"parent,omitempty"`
	Name     string         `json:"name,omitempty"`
	Etype    string         `json:"etype,omitempty"`
	Use      string         `json:"use,omitempty"`
	Capacity int            `json:"capacity,omitempty"`
	Level    string         `json:"level,omitempty"`
	Code     string         `json:"code,omitempty"`
	Device   string         `json:"device,omitempty"`
	Metric   string         `json:"metric,omitempty"`
	Card     string         `json:"card,omitempty"`
	Location string         `json:"location,omitempty"`
	Place    string         `json:"place,omitempty"` // room text for the agent CARD head ("" = none, as the gate rows)
	XY       []float64      `json:"xy,omitempty"`
	LatLon   []float64      `json:"latlon,omitempty"`
	APIType  string         `json:"api_type,omitempty"`
	Tank     map[string]any `json:"tank,omitempty"`
	Inferred bool           `json:"inferred,omitempty"`
	Why      string         `json:"why,omitempty"`
}

type SiteLink struct {
	From     string `json:"from"`
	To       string `json:"to"`
	Type     string `json:"type"`
	Inferred bool   `json:"inferred,omitempty"`
	Why      string `json:"why,omitempty"`
}

type SiteConfig struct {
	SiteID  string          `json:"site_id"`
	Version int             `json:"version"`
	Saved   string          `json:"saved,omitempty"`
	Source  string          `json:"source,omitempty"` // auto | owner
	Nodes   []SiteNode      `json:"nodes"`
	Links   []SiteLink      `json:"links"`
	Cards   map[string]Card `json:"cards,omitempty"` // owner cards: new sensor types or edited copies of today's cards
	Windows map[string]*int `json:"windows,omitempty"`
}

var siteNodeKinds = []string{"campus", "building", "wing", "floor", "room", "zone", "equipment", "sensor"}
var siteLinkTypes = []string{"serves", "supplies", "feeds", "outdoor-for", "upstream-of", "downstream-of"}
var siteEtypes = []string{"ac_unit", "ahu", "chiller", "panel", "feeder", "pump", "tank", "valve", "meter", "weather_station", "generator", "gateway", "camera"}

func ip(v int) *int { return &v }

// siteWindows mirrors sitegraph.WINDOWS (minutes; nil = never).
func siteWindows() map[string]*int {
	return map[string]*int{"located-in": ip(15), "sibling": ip(15), "occupancy-load": ip(15), "supplies": ip(15), "serves": ip(30),
		"feeds": ip(30), "floor": ip(30), "building_shared_equipment": ip(30), "outdoor-for": ip(60), "outdoor-heatwave": ip(90),
		"outdoor-pm": ip(60), "rain-to-tank": ip(180), "upstream-of": ip(30), "downstream-of": ip(30), "campus_no_link": nil}
}

// ---------------------------------------------------------------- index (sitegraph.Index)

type siteNbr struct{ other, typ, dir string }

type SiteIndex struct {
	cfg      *SiteConfig
	order    []string
	nodes    map[string]*SiteNode
	children map[string][]string
	out, inn map[string][]SiteLink
	win      map[string]*int
}

func NewSiteIndex(cfg *SiteConfig) *SiteIndex {
	ix := &SiteIndex{cfg: cfg, nodes: map[string]*SiteNode{}, children: map[string][]string{}, out: map[string][]SiteLink{}, inn: map[string][]SiteLink{}}
	for i := range cfg.Nodes {
		n := &cfg.Nodes[i]
		if _, dup := ix.nodes[n.ID]; !dup {
			ix.order = append(ix.order, n.ID)
		}
		ix.nodes[n.ID] = n
	}
	for _, id := range ix.order {
		if p := ix.nodes[id].Parent; p != "" {
			ix.children[p] = append(ix.children[p], id)
		}
	}
	for _, l := range cfg.Links {
		ix.out[l.From] = append(ix.out[l.From], l)
		ix.inn[l.To] = append(ix.inn[l.To], l)
	}
	ix.win = siteWindows()
	for k, v := range cfg.Windows {
		ix.win[k] = v
	}
	return ix
}

func (ix *SiteIndex) Parent(id string) string {
	if n := ix.nodes[id]; n != nil {
		return n.Parent
	}
	return ""
}

func (ix *SiteIndex) Ancestors(id string) []string {
	var out []string
	seen := map[string]bool{id: true}
	for p := ix.Parent(id); p != "" && !seen[p]; p = ix.Parent(p) {
		seen[p] = true
		out = append(out, p)
	}
	return out
}

func (ix *SiteIndex) Path(id string) []string {
	a := ix.Ancestors(id)
	out := make([]string, 0, len(a)+1)
	for i := len(a) - 1; i >= 0; i-- {
		out = append(out, a[i])
	}
	return append(out, id)
}

func (ix *SiteIndex) Name(id string) string {
	if n := ix.nodes[id]; n != nil && n.Name != "" {
		return n.Name
	}
	return id
}

func (ix *SiteIndex) PathText(id string, self bool) string {
	p := ix.Path(id)
	if !self {
		p = p[:len(p)-1]
	}
	names := make([]string, len(p))
	for i, x := range p {
		names[i] = ix.Name(x)
	}
	return strings.Join(names, " > ")
}

func (ix *SiteIndex) LCA(a, b string) string {
	pb := map[string]bool{}
	for _, x := range ix.Path(b) {
		pb[x] = true
	}
	best := ""
	for _, x := range ix.Path(a) {
		if pb[x] {
			best = x
		}
	}
	return best
}

func (ix *SiteIndex) SensorsUnder(id string) []string {
	var out []string
	q := []string{id}
	for len(q) > 0 {
		x := q[0]
		q = q[1:]
		if n := ix.nodes[x]; n != nil && n.Kind == "sensor" {
			out = append(out, x)
		}
		q = append(q, ix.children[x]...)
	}
	return out
}

func (ix *SiteIndex) Neighbours(id string) []siteNbr {
	var out []siteNbr
	for _, l := range ix.out[id] {
		out = append(out, siteNbr{l.To, l.Type, "out"})
	}
	for _, l := range ix.inn[id] {
		out = append(out, siteNbr{l.From, l.Type, "in"})
	}
	return out
}

func (ix *SiteIndex) kind(id string) string {
	if n := ix.nodes[id]; n != nil {
		return n.Kind
	}
	return ""
}

// LinkPath mirrors Index.link_path (nil = no path; [] = same host).
func (ix *SiteIndex) LinkPath(a, b string, maxHops int) []string {
	if a == b {
		return []string{}
	}
	seen := map[string][]string{a: {}}
	q := []string{a}
	for len(q) > 0 {
		x := q[0]
		q = q[1:]
		if len(seen[x]) >= maxHops {
			continue
		}
		nxt := ix.Neighbours(x)
		base := len(nxt)
		for _, nb := range nxt[:base] {
			switch ix.kind(nb.other) {
			case "floor", "building", "wing", "campus":
				for _, r := range ix.children[nb.other] {
					nxt = append(nxt, siteNbr{r, nb.typ, nb.dir})
				}
			}
		}
		for _, anc := range ix.Ancestors(x) {
			for _, nb := range ix.Neighbours(anc) {
				if nb.typ == "outdoor-for" {
					nxt = append(nxt, nb)
				}
			}
		}
		for _, nb := range nxt {
			if _, ok := seen[nb.other]; !ok {
				p := append(append([]string{}, seen[x]...), nb.typ)
				seen[nb.other] = p
				if nb.other == b {
					return p
				}
				q = append(q, nb.other)
			}
		}
	}
	return nil
}

func (ix *SiteIndex) winOf(t string) int {
	if v := ix.win[t]; v != nil {
		return *v
	}
	return 0
}

// Relation mirrors Index.relation for two SENSOR ids: (relation, window minutes, ok window, hops, ok hops).
func (ix *SiteIndex) Relation(a, b string) (string, *int, *int) {
	ha, hb := ix.Parent(a), ix.Parent(b)
	if ha == hb {
		return "located-in", ix.win["located-in"], ip(0)
	}
	if lp := ix.LinkPath(ha, hb, 3); len(lp) > 0 {
		slow := lp[0]
		for _, t := range lp[1:] {
			if ix.winOf(t) > ix.winOf(slow) {
				slow = t
			}
		}
		return slow, ix.win[slow], ip(len(lp))
	}
	l := ix.LCA(a, b)
	k := "campus"
	if l != "" {
		k = ix.kind(l)
	}
	switch k {
	case "floor", "room", "zone":
		return "floor", ix.win["floor"], ip(0)
	case "building", "wing":
		ea := map[string]bool{}
		for _, nb := range ix.Neighbours(ha) {
			ea[nb.other] = true
		}
		for _, nb := range ix.Neighbours(hb) {
			if ea[nb.other] {
				return "building_shared_equipment", ix.win["building_shared_equipment"], ip(2)
			}
		}
	}
	return "campus_no_link", nil, nil
}

type RollStatus struct {
	Status     string `json:"status"`
	DataIssues int    `json:"data_issues"`
}

var rollRank = map[string]int{"normal": 0, "warning": 1, "critical": 2}

// Rollup mirrors Index.rollup: worst process status of the sensors under each non-sensor node; anything else
// (sensor_fault, stale, maintenance) counts as a data issue.
func (ix *SiteIndex) Rollup(status map[string]string) map[string]RollStatus {
	out := map[string]RollStatus{}
	for _, id := range ix.order {
		if ix.nodes[id].Kind == "sensor" {
			continue
		}
		st, di := "normal", 0
		for _, s := range ix.SensorsUnder(id) {
			v := status[s]
			if r, ok := rollRank[v]; ok {
				if r > rollRank[st] {
					st = v
				}
			} else if v != "" {
				di++
			}
		}
		out[id] = RollStatus{st, di}
	}
	return out
}

type SiteSuspect struct {
	Node    string   `json:"node"`
	Why     string   `json:"why"`
	Flagged []string `json:"flagged"`
}

// Suspects mirrors Index.suspects (§3.3). onsets: sensor id -> onset (unix s).
func (ix *SiteIndex) Suspects(onsets map[string]int64) []SiteSuspect {
	out := []SiteSuspect{}
	w := int64(ix.winOf("floor")) * 60
	for _, id := range ix.order {
		n := ix.nodes[id]
		if n.Kind == "sensor" || n.Kind == "campus" {
			continue
		}
		var kids []string
		for _, c := range ix.children[id] {
			if ix.kind(c) != "sensor" && len(ix.SensorsUnder(c)) > 0 {
				kids = append(kids, c)
			}
		}
		var fl []string
		var ts []int64
		for _, c := range kids {
			first, ok := int64(0), false
			for _, s := range ix.SensorsUnder(c) {
				if t, has := onsets[s]; has && (!ok || t < first) {
					first, ok = t, true
				}
			}
			if ok {
				fl = append(fl, c)
				ts = append(ts, first)
			}
		}
		if len(fl) > 0 {
			sort.Slice(ts, func(i, j int) bool { return ts[i] < ts[j] })
			close := len(ts) >= 2 && ts[len(ts)-1]-ts[0] <= w
			enough := len(fl) >= 2
			if len(kids) >= 4 {
				enough = len(fl)*2 >= len(kids)
			}
			if close && enough {
				out = append(out, SiteSuspect{id, fmt.Sprintf("%d of %d children flagged", len(fl), len(kids)), fl})
				continue
			}
		}
		var served []string
		lt := ""
		for _, l := range ix.out[id] {
			if l.Type == "serves" || l.Type == "supplies" {
				served = append(served, l.To)
				if lt == "" {
					lt = l.Type
				}
			}
		}
		var fl2 []string
		var t2 []int64
		for _, t := range served {
			ss := []string{t}
			if ix.kind(t) != "sensor" {
				ss = ix.SensorsUnder(t)
			}
			first, ok := int64(0), false
			for _, s := range ss {
				if v, has := onsets[s]; has && (!ok || v < first) {
					first, ok = v, true
				}
			}
			if ok {
				fl2 = append(fl2, t)
				t2 = append(t2, first)
			}
		}
		if len(fl2) >= 2 {
			sort.Slice(t2, func(i, j int) bool { return t2[i] < t2[j] })
			if t2[len(t2)-1]-t2[0] <= int64(ix.winOf(lt))*60 {
				out = append(out, SiteSuspect{id, fmt.Sprintf("%d of %d %s loads flagged", len(fl2), len(served), lt), fl2})
			}
		}
	}
	return out
}

// ---------------------------------------------------------------- validation

func ValidateSite(cfg *SiteConfig) []string {
	var bad []string
	ids := map[string]bool{}
	campus := 0
	for _, n := range cfg.Nodes {
		if n.ID == "" {
			bad = append(bad, "node without id")
			continue
		}
		if ids[n.ID] {
			bad = append(bad, "duplicate node "+n.ID)
		}
		ids[n.ID] = true
		if !contains(siteNodeKinds, n.Kind) {
			bad = append(bad, n.ID+": kind '"+n.Kind+"'")
		}
		if n.Kind == "campus" {
			campus++
		}
		if n.Kind == "equipment" && n.Etype != "" && !contains(siteEtypes, n.Etype) {
			bad = append(bad, n.ID+": equipment type '"+n.Etype+"'")
		}
	}
	if campus != 1 {
		bad = append(bad, "exactly one campus node needed")
	}
	for _, n := range cfg.Nodes {
		if n.Kind != "campus" && !ids[n.Parent] {
			bad = append(bad, n.ID+": parent '"+n.Parent+"' not in the site")
		}
		if n.Kind == "sensor" {
			if n.Card == "" {
				bad = append(bad, n.ID+": sensor without a card")
			} else if _, ok := cfg.Cards[n.Card]; !ok {
				if _, ok := existingCards[n.Card]; !ok {
					bad = append(bad, n.ID+": unknown card '"+n.Card+"'")
				}
			}
		}
	}
	// parent cycles
	ix := NewSiteIndex(cfg)
	for _, n := range cfg.Nodes {
		seen := map[string]bool{n.ID: true}
		for p := n.Parent; p != ""; p = ix.Parent(p) {
			if seen[p] {
				bad = append(bad, n.ID+": parent cycle")
				break
			}
			seen[p] = true
		}
	}
	for _, l := range cfg.Links {
		if !contains(siteLinkTypes, l.Type) {
			bad = append(bad, fmt.Sprintf("link %s->%s: type '%s'", l.From, l.To, l.Type))
		}
		if !ids[l.From] || !ids[l.To] {
			bad = append(bad, fmt.Sprintf("link %s->%s: unknown node", l.From, l.To))
		}
	}
	for id, c := range cfg.Cards {
		if c.CardID != id {
			bad = append(bad, "card "+id+": card_id differs")
		}
		for _, e := range ValidateCard(c) {
			bad = append(bad, "card "+id+": "+e)
		}
	}
	return bad
}

// ---------------------------------------------------------------- store

type siteStore struct {
	mu  sync.RWMutex
	dir string
	cfg *SiteConfig
	ix  *SiteIndex
}

var siteS = &siteStore{}

func (s *siteStore) Get() (*SiteConfig, *SiteIndex) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	return s.cfg, s.ix
}

func (s *siteStore) path() string { return filepath.Join(s.dir, "state", "site.json") }

func (s *siteStore) Load(dir string) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.dir = dir
	b, err := os.ReadFile(s.path())
	if err != nil {
		return
	}
	var c SiteConfig
	if err := json.Unmarshal(b, &c); err != nil {
		log.Printf("site: %s unreadable (%v): rebuilt from the API", s.path(), err)
		return
	}
	s.cfg, s.ix = &c, NewSiteIndex(&c)
}

// Save validates c and stores it as the next version. Writes state/site.json via .part + rename.
func (s *siteStore) Save(c *SiteConfig, source string) error {
	if bad := ValidateSite(c); len(bad) > 0 {
		if len(bad) > 12 {
			bad = append(bad[:12], fmt.Sprintf("... %d more", len(bad)-12))
		}
		return errors.New(strings.Join(bad, "; "))
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.cfg != nil {
		c.Version = s.cfg.Version + 1
	} else if c.Version < 1 {
		c.Version = 1
	}
	c.Source = source
	c.Saved = nowTime().UTC().Format(time.RFC3339)
	if c.SiteID == "" {
		c.SiteID = "iiith"
	}
	b, _ := json.MarshalIndent(c, "", " ")
	if s.dir != "" {
		_ = os.MkdirAll(filepath.Join(s.dir, "state", "site_versions"), 0o755)
		if err := atomicWrite(s.path(), b, 0o644); err != nil {
			return err
		}
		_ = atomicWrite(filepath.Join(s.dir, "state", "site_versions", fmt.Sprintf("site.v%d.json", c.Version)), b, 0o644)
	}
	s.cfg, s.ix = c, NewSiteIndex(c)
	return nil
}

// siteCardFor: an owner card for a sensor (site config), and its place text. false = use today's card.
func siteCardFor(node, metric string) (Card, string, bool) {
	cfg, ix := siteS.Get()
	if cfg == nil || len(cfg.Cards) == 0 {
		return Card{}, "", false
	}
	n := ix.nodes[node+"/"+metric]
	if n == nil {
		return Card{}, "", false
	}
	c, ok := cfg.Cards[n.Card]
	if !ok {
		return Card{}, "", false
	}
	place := ""
	if h := ix.nodes[n.Parent]; h != nil {
		place = h.Place
	}
	return c, place, true
}

// ---------------------------------------------------------------- auto-build from the API registry

// APINode is one /verticals/all/nodes entry.
type APINode struct {
	NodeID  string  `json:"node_id"`
	Name    string  `json:"name"`
	Lat     float64 `json:"latitude"`
	Lon     float64 `json:"longitude"`
	X       float64 `json:"xcor"`
	Y       float64 `json:"ycor"`
	Type    string  `json:"type"`
	Visible *bool   `json:"visibility"`
}

var reNodeCode = regexp.MustCompile(`([A-Z]{2,3})(\d\d)-(\d\d)$`)
var reGenericName = regexp.MustCompile(`^(Air Quality|Water (Level|Flow|Quality)|Energy Meter|Room (AC|AQ|Occupancy)|Crowd Monitor|Solar)\b`)

func nodeCode(id string) (bld, lvl, idx string, ok bool) {
	m := reNodeCode.FindStringSubmatch(id)
	if m == nil {
		return "", "", "", false
	}
	return m[1], m[2], m[3], true
}

func floorName(lvl string) string {
	switch lvl {
	case "98":
		return "rooftop (level 98)"
	case "95":
		return "gateway level 95"
	case "96":
		return "water plant level 96"
	case "90":
		return "library level 90"
	case "99":
		return "gate level 99"
	}
	return "level " + lvl
}

func apiXY(n APINode) []float64 {
	if n.X == 0 && n.Y == 0 || n.X < 100 && n.Y > 70 { // lat/lon pasted into xcor/ycor (seen: AQ-PH00-00)
		return nil
	}
	return []float64{n.X, n.Y}
}

// BuildSiteFromAPI: the provisional site tree (inferred relations carry a reason). bank: the engine's sensors.
func BuildSiteFromAPI(nodes []APINode, bank []SimSensor) *SiteConfig {
	c := &SiteConfig{SiteID: "iiith", Nodes: []SiteNode{{ID: "iiith", Kind: "campus", Name: "IIITH"}}}
	have := map[string]int{"iiith": 0}
	add := func(n SiteNode) string {
		if _, ok := have[n.ID]; !ok {
			have[n.ID] = len(c.Nodes)
			c.Nodes = append(c.Nodes, n)
		}
		return n.ID
	}
	link := func(from, to, t, why string) {
		for _, l := range c.Links {
			if l.From == from && l.To == to && l.Type == t {
				return
			}
		}
		c.Links = append(c.Links, SiteLink{From: from, To: to, Type: t, Inferred: true, Why: why})
	}
	// building names: the most frequent specific API name per code
	votes := map[string]map[string]int{}
	for _, n := range nodes {
		b, _, _, ok := nodeCode(n.NodeID)
		nm := strings.TrimSpace(n.Name)
		if !ok || nm == "" || reGenericName.MatchString(nm) || strings.HasPrefix(n.NodeID, "WN-") {
			continue
		}
		if votes[b] == nil {
			votes[b] = map[string]int{}
		}
		votes[b][nm]++
	}
	bname := func(code string) string {
		best, bn := "", 0
		for nm, k := range votes[code] {
			if k > bn || k == bn && nm < best {
				best, bn = nm, k
			}
		}
		if best == "" {
			return code + " building"
		}
		return best + " (" + code + ")"
	}
	building := func(code string) string {
		return add(SiteNode{ID: code, Kind: "building", Parent: "iiith", Name: bname(code), Code: code})
	}
	floor := func(code, lvl string) string {
		building(code)
		return add(SiteNode{ID: code + "-" + lvl, Kind: "floor", Parent: code, Name: floorName(lvl), Level: lvl})
	}
	bankBy := map[string][]SimSensor{}
	for _, s := range bank {
		bankBy[s.Node] = append(bankBy[s.Node], s)
	}
	devHost := map[string]string{} // API / bank device -> host node id
	byID := map[string]APINode{}
	ordered := append([]APINode{}, nodes...)
	sort.SliceStable(ordered, func(i, j int) bool { return ordered[i].NodeID < ordered[j].NodeID })
	for _, n := range ordered {
		byID[n.NodeID] = n
	}
	// bank devices not in the registry still get a host (from their code)
	for _, s := range bank {
		if _, ok := byID[s.Node]; !ok && !strings.HasPrefix(s.Node, "AC-") && !strings.HasPrefix(s.Node, "SR-OC-GW-") {
			ordered = append(ordered, APINode{NodeID: s.Node, Name: "", Type: "(not in the campus registry)"})
		}
	}
	aqRooms := map[string][]string{}  // floor -> AQ rooms
	var tanks = map[string][]string{} // building -> tanks
	type pend struct{ from, bld, fl string }
	var acs []pend
	for _, n := range ordered {
		id := n.NodeID
		if strings.HasPrefix(id, "WN-") {
			continue // Wi-SUN network poles: network infrastructure, not site equipment
		}
		b, lvl, idx, ok := nodeCode(id)
		if !ok {
			continue
		}
		xy := apiXY(n)
		var ll []float64
		if n.Lat != 0 {
			ll = []float64{n.Lat, n.Lon}
		}
		dev := func(kind, etype, parent, name string, inferred bool, why string) string {
			h := add(SiteNode{ID: id, Kind: kind, Etype: etype, Parent: parent, Name: name, Device: id, XY: xy, LatLon: ll,
				APIType: n.Type, Inferred: inferred, Why: why})
			devHost[id] = h
			return h
		}
		missing := n.Type == "(not in the campus registry)"
		why := ""
		if missing {
			why = "device of the sensor bank, not in the campus API registry: placed from its code"
		}
		switch {
		case strings.HasPrefix(id, "SR-AQ-"):
			fl := floor(b, lvl)
			h := add(SiteNode{ID: b + "-" + lvl + "-AQ" + idx, Kind: "room", Parent: fl, Name: "room of air sensor " + b + lvl + "-" + idx,
				Device: id, XY: xy, LatLon: ll, APIType: n.Type, Inferred: true, Why: "room, use and capacity unknown; one room per indoor air sensor"})
			devHost[id] = h
			aqRooms[fl] = append(aqRooms[fl], h)
		case strings.HasPrefix(id, "AQ-"):
			building(b)
			dev("equipment", "meter", b, "outdoor air station "+id, false, why)
			link(id, b, "outdoor-for", "outdoor station "+id+" stands at "+b)
		case strings.HasPrefix(id, "SR-AC-"):
			fl := floor(b, lvl)
			dev("equipment", "ac_unit", fl, "AC indoor unit "+b+lvl+"-"+idx, false, why)
			acs = append(acs, pend{id, b, fl})
		case strings.HasPrefix(id, "SR-EM-"):
			fl := floor(b, lvl)
			dev("equipment", "meter", fl, "room energy meter "+b+lvl+"-"+idx, false, why)
			link(id, fl, "supplies", "room energy meter assumed to meter the loads of its floor")
		case strings.HasPrefix(id, "SR-OC-"):
			fl := floor(b, lvl)
			dev("equipment", "gateway", fl, "occupancy gateway "+id, false, why)
		case strings.HasPrefix(id, "EM-"):
			building(b)
			dev("equipment", "feeder", b, "energy meter "+b+lvl+"-"+idx, false, why)
			to := b
			if b == "SB" {
				to = "KH"
				building("KH")
			}
			link(id, to, "supplies", "feeder assumed to supply "+to)
		case strings.HasPrefix(id, "SL-"):
			building(b)
			dev("equipment", "generator", b, "solar plant "+b+lvl+"-"+idx, false, why)
			link(id, b, "supplies", "rooftop solar assumed to supply its building")
		case strings.HasPrefix(id, "WM-WL-"):
			fl := floor(b, lvl)
			h := dev("equipment", "tank", fl, "water tank "+b+lvl+"-"+idx, true, "tank kind inferred from the level code")
			if tl, ok := NodeLimitsV2[id]; ok {
				c.Nodes[have[h]].Tank = map[string]any{"high": tl.High, "overflow": tl.Overflow, "fill_min": tl.FillMin}
			}
			tanks[b] = append(tanks[b], h)
			link(h, b, "supplies", "tank assumed to supply its building")
		case strings.HasPrefix(id, "WM-WF-"):
			fl := floor(b, lvl)
			w := why
			if w == "" {
				w = "flow meter treated as the pump line"
			}
			dev("equipment", "pump", fl, "water flow line "+b+lvl+"-"+idx, true, w)
		case strings.HasPrefix(id, "WM-WD-"):
			fl := floor(b, lvl)
			dev("equipment", "meter", fl, "water quality sensor "+b+lvl+"-"+idx, false, why)
		case strings.HasPrefix(id, "CM-"):
			fl := floor(b, lvl)
			dev("equipment", "camera", fl, "crowd monitor "+b+lvl+"-"+idx, false, why)
		case strings.HasPrefix(id, "WE-"):
			fl := floor(b, lvl)
			dev("equipment", "weather_station", fl, "weather station "+id, false, why)
		}
	}
	for _, a := range acs {
		if rs := aqRooms[a.fl]; len(rs) > 0 {
			for _, r := range rs {
				link(a.from, r, "serves", "same floor as the air sensor room; real served rooms unknown")
			}
		} else {
			link(a.from, a.fl, "serves", "served rooms unknown: the unit serves its floor")
		}
	}
	for _, n := range c.Nodes {
		if n.Etype == "pump" {
			b, _, _, _ := nodeCode(n.ID)
			for _, t := range tanks[b] {
				link(n.ID, t, "feeds", "flow line assumed to feed the tanks of its building")
			}
		}
		if n.Etype == "weather_station" {
			for _, m := range c.Nodes {
				if m.Kind == "building" {
					link(n.ID, m.ID, "outdoor-for", "one weather station for the whole campus")
				}
			}
		}
	}
	// the sensor bank: one sensor leaf per node/metric (hvac unit channels setpoint / ac_on belong to its card)
	for _, s := range bank {
		if s.Role == "hvac" && s.Metric != "room_temp" && strings.HasPrefix(s.Node, "SR-AC") {
			continue
		}
		host := devHost[s.Node]
		switch {
		case strings.HasPrefix(s.Node, "AC-"): // per-floor AC aggregate (ac_units_on, room_temp)
			code := strings.TrimPrefix(s.Node, "AC-")
			if len(code) == 4 {
				fl := floor(code[:2], code[2:])
				host = add(SiteNode{ID: s.Node, Kind: "equipment", Etype: "ac_unit", Parent: fl, Name: "AC units " + code[:2] + " level " + code[2:],
					Inferred: true, Why: "all AC indoor units of the floor, counted together"})
				if rs := aqRooms[fl]; len(rs) > 0 {
					for _, r := range rs {
						link(s.Node, r, "serves", "same floor as the air sensor room")
					}
				} else {
					link(s.Node, fl, "serves", "the floor's AC units")
				}
			}
		case strings.HasPrefix(s.Node, "SR-OC-GW-"): // occupancy channel of a gateway: the building's monitored air room
			b, lvl, _, _ := nodeCode(s.Node)
			host = ""
			for _, s2 := range bank {
				if strings.HasPrefix(s2.Node, "SR-AQ-"+b) && devHost[s2.Node] != "" {
					host = devHost[s2.Node]
					break
				}
			}
			if host == "" {
				fl := floor(b, lvl)
				host = add(SiteNode{ID: fl + "-OC", Kind: "room", Parent: fl, Name: "room of occupancy sensor " + s.Node, Inferred: true, Why: "room unknown"})
			}
		}
		if host == "" {
			continue
		}
		sid := s.Node + "/" + s.Metric
		cid := MetricToCard(s.Role, s.Metric, s.Node, s.Location)
		w := ""
		if strings.HasPrefix(s.Node, "SR-OC-GW-") {
			w = "occupancy gateway has no room: placed in the building's indoor air sensor room (edit if wrong)"
		}
		add(SiteNode{ID: sid, Kind: "sensor", Parent: host, Device: s.Node, Metric: s.Metric, Card: cid, Location: s.Location,
			Inferred: w != "", Why: w})
	}
	c.Windows = siteWindows()
	return c
}

// ---------------------------------------------------------------- live status (roll-up input) + routes

// siteSensorStatus: sensor id -> status for the roll-up: the live process status (normal | warning | critical),
// or data_issue for a sensor fault / stale / maintenance / missing data.
func siteSensorStatus(eng *Engine) map[string]string {
	out := map[string]string{}
	if eng == nil {
		return out
	}
	_, states, _ := eng.Snapshot()
	for _, st := range states {
		k := st.Node + "/" + st.Metric
		switch {
		case st.Status == "sensor_fault" || !st.DataOK || st.MaintUntil > 0:
			out[k] = "data_issue"
		case st.Status == "warning" || st.Status == "critical":
			out[k] = st.Status
		default:
			out[k] = "normal"
		}
	}
	return out
}

// siteOpenIncidents: sensor id -> the worst open incident on it (id, severity, title).
func siteOpenIncidents(r *Reasoner) map[string]map[string]any {
	out := map[string]map[string]any{}
	if r == nil {
		return out
	}
	for _, inc := range r.List() {
		if inc == nil || incClosed(inc) {
			continue
		}
		sev := incSeverity(inc)
		for _, s := range inc.Sensors {
			if s.Context {
				continue
			}
			k := s.Node + "/" + s.Metric
			if o, ok := out[k]; ok && rollRank[o["severity"].(string)] >= rollRank[sev] {
				continue
			}
			out[k] = map[string]any{"id": inc.ID, "severity": sev, "title": incTitle(inc)}
		}
	}
	return out
}

func (s *Server) siteEnsure() (*SiteConfig, *SiteIndex) {
	cfg, ix := siteS.Get()
	if cfg != nil {
		return cfg, ix
	}
	nodes := campusRegistry()
	c := BuildSiteFromAPI(nodes, s.eng.Sensors())
	if len(nodes) == 0 {
		c.Source = "auto"
		return c, NewSiteIndex(c) // not saved until the registry is known
	}
	if err := siteS.Save(c, "auto"); err != nil {
		log.Printf("site: auto-built tree invalid: %v", err)
		return c, NewSiteIndex(c)
	}
	return siteS.Get()
}

func (s *Server) siteRoutes(mux *http.ServeMux) {
	siteS.Load(s.dir)
	mux.HandleFunc("/api/site", func(w http.ResponseWriter, r *http.Request) {
		switch r.Method {
		case http.MethodGet:
			cfg, _ := s.siteEnsure()
			writeJSON(w, cfg)
		case http.MethodPut, http.MethodPost:
			var c SiteConfig
			if err := json.NewDecoder(http.MaxBytesReader(w, r.Body, 4<<20)).Decode(&c); err != nil {
				http.Error(w, "bad site JSON: "+err.Error(), 400)
				return
			}
			if err := siteS.Save(&c, "owner"); err != nil {
				http.Error(w, "site not saved: "+err.Error(), 422)
				return
			}
			s.hub.Publish("site", map[string]any{"version": c.Version})
			writeJSON(w, map[string]any{"ok": true, "version": c.Version})
		default:
			http.Error(w, "GET or PUT", 405)
		}
	})
	mux.HandleFunc("/api/site/rebuild", func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			http.Error(w, "POST", 405)
			return
		}
		c := BuildSiteFromAPI(campusRegistry(), s.eng.Sensors())
		if old, _ := siteS.Get(); old != nil {
			c.Cards = old.Cards // owner cards survive a rebuild
		}
		if err := siteS.Save(c, "auto"); err != nil {
			http.Error(w, err.Error(), 422)
			return
		}
		writeJSON(w, map[string]any{"ok": true, "version": c.Version})
	})
	mux.HandleFunc("/api/site/validate", func(w http.ResponseWriter, r *http.Request) {
		var c SiteConfig
		if err := json.NewDecoder(http.MaxBytesReader(w, r.Body, 4<<20)).Decode(&c); err != nil {
			http.Error(w, err.Error(), 400)
			return
		}
		writeJSON(w, map[string]any{"problems": ValidateSite(&c)})
	})
	mux.HandleFunc("/api/site/versions", func(w http.ResponseWriter, r *http.Request) {
		ents, _ := os.ReadDir(filepath.Join(s.dir, "state", "site_versions"))
		var vs []int
		for _, e := range ents {
			if n, err := strconv.Atoi(strings.TrimSuffix(strings.TrimPrefix(e.Name(), "site.v"), ".json")); err == nil {
				vs = append(vs, n)
			}
		}
		sort.Ints(vs)
		writeJSON(w, map[string]any{"versions": vs})
	})
	mux.HandleFunc("/api/site/status", func(w http.ResponseWriter, r *http.Request) {
		_, ix := s.siteEnsure()
		st := siteSensorStatus(s.eng)
		roll := ix.Rollup(st)
		node := r.URL.Query().Get("node")
		onsets := siteOnsets(s.rsn)
		sus := ix.Suspects(onsets)
		if node != "" {
			if ix.nodes[node] == nil {
				http.Error(w, "no such node", 404)
				return
			}
			out := map[string]any{"node": node, "sensors": map[string]string{}}
			if rs, ok := roll[node]; ok {
				out["status"], out["data_issues"] = rs.Status, rs.DataIssues
			} else {
				out["status"] = st[node]
			}
			for _, x := range ix.SensorsUnder(node) {
				out["sensors"].(map[string]string)[x] = st[x]
			}
			writeJSON(w, out)
			return
		}
		writeJSON(w, map[string]any{"rollup": roll, "sensors": st, "suspects": sus, "open": siteOpenIncidents(s.rsn)})
	})
	mux.HandleFunc("/api/cards", func(w http.ResponseWriter, r *http.Request) {
		cfg, _ := s.siteEnsure()
		writeJSON(w, map[string]any{"existing": existingCards, "site": cfg.Cards, "kinds": cardKinds, "domains": cardDomainNames,
			"actions": cardBaseActions, "faults": cardFaultsAll})
	})
	mux.HandleFunc("/api/cards/validate", func(w http.ResponseWriter, r *http.Request) {
		var m map[string]any
		if err := json.NewDecoder(http.MaxBytesReader(w, r.Body, 1<<20)).Decode(&m); err != nil {
			http.Error(w, err.Error(), 400)
			return
		}
		writeJSON(w, map[string]any{"problems": ValidateCardRaw(m)})
	})
	// PUT /api/site/card {"card":{...}, "sensors":["NODE/metric",...]}: save an owner card (validated) and assign it
	mux.HandleFunc("/api/site/card", func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPut && r.Method != http.MethodPost {
			http.Error(w, "PUT", 405)
			return
		}
		var body struct {
			Card    json.RawMessage `json:"card"`
			Sensors []string        `json:"sensors"`
		}
		if err := json.NewDecoder(http.MaxBytesReader(w, r.Body, 1<<20)).Decode(&body); err != nil {
			http.Error(w, err.Error(), 400)
			return
		}
		var raw map[string]any
		_ = json.Unmarshal(body.Card, &raw)
		if p := ValidateCardRaw(raw); len(p) > 0 {
			writeJSONStatus(w, 422, map[string]any{"problems": p})
			return
		}
		var cd Card
		if err := json.Unmarshal(body.Card, &cd); err != nil {
			http.Error(w, err.Error(), 400)
			return
		}
		if p := cardLimitProblems(cd); len(p) > 0 {
			writeJSONStatus(w, 422, map[string]any{"problems": p})
			return
		}
		cfg, _ := s.siteEnsure()
		nc := cloneSite(cfg)
		if nc.Cards == nil {
			nc.Cards = map[string]Card{}
		}
		nc.Cards[cd.CardID] = cd
		for _, sid := range body.Sensors {
			for i := range nc.Nodes {
				if nc.Nodes[i].ID == sid && nc.Nodes[i].Kind == "sensor" {
					nc.Nodes[i].Card = cd.CardID
				}
			}
		}
		if err := siteS.Save(nc, "owner"); err != nil {
			http.Error(w, err.Error(), 422)
			return
		}
		writeJSON(w, map[string]any{"ok": true, "version": nc.Version})
	})
}

func cloneSite(c *SiteConfig) *SiteConfig {
	b, _ := json.Marshal(c)
	var n SiteConfig
	_ = json.Unmarshal(b, &n)
	return &n
}

func writeJSONStatus(w http.ResponseWriter, code int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(code)
	_ = json.NewEncoder(w).Encode(v)
}

// siteOnsets: sensor id -> created sensor time of the open incidents flagging it (suspect-parent input).
func siteOnsets(r *Reasoner) map[string]int64 {
	out := map[string]int64{}
	if r == nil {
		return out
	}
	for _, inc := range r.List() {
		if inc == nil || incClosed(inc) {
			continue
		}
		for _, s := range inc.Sensors {
			if s.Context {
				continue
			}
			k := s.Node + "/" + s.Metric
			if t, ok := out[k]; !ok || inc.CreatedSim < t {
				out[k] = inc.CreatedSim
			}
		}
	}
	return out
}
