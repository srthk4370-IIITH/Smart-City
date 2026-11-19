package main

// Chat r5 site tools (fmt_v4.SITE_TOOLS; Python twin rsn/gen_chat_v4.py SiteTools): get_site_tree, nodes_under,
// linked_equipment, site_status. Parity: chat_site_test.go on the Python fixture sites (site_tools_fixtures.json).
// The header (chat_header_r5.txt = r3 header + the 4 tools, == tools_v4.json["chat_r5"]) and system
// (chat_system_r5.txt = r3 + SITE_RULE) are used with chat_prompt=r3 + reasoner_prompt=v4 (Phase 2; OFF in Phase 1).
// The tools themselves always answer (the dashboard's site view and tests use them).

import (
	_ "embed"
	"fmt"
	"sort"
	"strings"
)

//go:embed chat_header_r5.txt
var chatHeaderR5 string

//go:embed chat_system_r5.txt
var chatSystemR5 string

var siteToolNames = []string{"get_site_tree", "nodes_under", "linked_equipment", "site_status"}

type SiteTools struct {
	ix     *SiteIndex
	status map[string]string         // sensor -> warning | critical | data_issue (absent = normal)
	inc    map[string]map[string]any // sensor -> {id, severity, title}
	roll   map[string]RollStatus
	byname map[string]string
}

func NewSiteTools(cfg *SiteConfig, status map[string]string, inc map[string]map[string]any) *SiteTools {
	ix := NewSiteIndex(cfg)
	rs := map[string]string{}
	for k, v := range status {
		if v == "data_issue" {
			v = "sensor_fault"
		}
		rs[k] = v
	}
	t := &SiteTools{ix: ix, status: status, inc: inc, roll: ix.Rollup(rs), byname: map[string]string{}}
	for _, n := range cfg.Nodes {
		t.byname[strings.ToLower(n.ID)] = n.ID
		if n.Name != "" {
			if _, ok := t.byname[strings.ToLower(n.Name)]; !ok {
				t.byname[strings.ToLower(n.Name)] = n.ID
			}
		}
	}
	return t
}

func (t *SiteTools) find(x string) string { return t.byname[strings.ToLower(strings.TrimSpace(x))] }

func (t *SiteTools) st(id string) string {
	if t.ix.kind(id) == "sensor" {
		if v, ok := t.status[id]; ok {
			return v
		}
		return "normal"
	}
	return t.roll[id].Status
}

func (t *SiteTools) name(id string) string {
	if t.ix.kind(id) == "sensor" {
		return id
	}
	return t.ix.Name(id)
}

func (t *SiteTools) openUnder(id string) []map[string]any {
	ss := []string{id}
	if t.ix.kind(id) != "sensor" {
		ss = t.ix.SensorsUnder(id)
	}
	sort.Strings(ss)
	var out []map[string]any
	for _, s := range ss {
		if o, ok := t.inc[s]; ok {
			m := map[string]any{}
			for k, v := range o {
				m[k] = v
			}
			m["node"] = s
			out = append(out, m)
		}
	}
	sort.SliceStable(out, func(i, j int) bool {
		a, b := rollRank[fmt.Sprint(out[i]["severity"])], rollRank[fmt.Sprint(out[j]["severity"])]
		if a != b {
			return a > b
		}
		return fmt.Sprint(out[i]["id"]) < fmt.Sprint(out[j]["id"])
	})
	return out
}

func siteNF(node string) map[string]any {
	return map[string]any{"found": false, "node": node, "note": "no such node in the site map", "source": "device"}
}

func (t *SiteTools) campus() string {
	for _, id := range t.ix.order {
		if t.ix.nodes[id].Kind == "campus" {
			return id
		}
	}
	return ""
}

func (t *SiteTools) walk(x string, d int) []any {
	kids := append([]string{}, t.ix.children[x]...)
	sort.SliceStable(kids, func(i, j int) bool {
		si, sj := t.ix.kind(kids[i]) == "sensor", t.ix.kind(kids[j]) == "sensor"
		if si != sj {
			return !si
		}
		return kids[i] < kids[j]
	})
	items := []any{}
	for i, c := range kids {
		if i >= 15 {
			break
		}
		it := map[string]any{"id": c, "name": t.name(c), "kind": t.ix.kind(c), "status": t.st(c)}
		if t.ix.kind(c) == "sensor" {
			it["metric"] = t.ix.nodes[c].Metric
		}
		if d > 1 && len(t.ix.children[c]) > 0 {
			it["children"] = t.walk(c, d-1)
		}
		items = append(items, it)
	}
	return items
}

func (t *SiteTools) GetSiteTree(node string, depth int) map[string]any {
	nid := t.campus()
	if node != "" {
		if nid = t.find(node); nid == "" {
			return siteNF(node)
		}
	}
	if depth < 1 {
		depth = 1
	}
	if depth > 3 {
		depth = 3
	}
	return map[string]any{"node": nid, "name": t.name(nid), "kind": t.ix.kind(nid), "status": t.st(nid),
		"children_total": len(t.ix.children[nid]), "children": t.walk(nid, depth), "source": "device"}
}

func (t *SiteTools) NodesUnder(node, kind, metric, status string) map[string]any {
	nid := t.find(node)
	if nid == "" {
		return siteNF(node)
	}
	var out []string
	q := append([]string{}, t.ix.children[nid]...)
	for len(q) > 0 {
		x := q[0]
		q = append(q[1:], t.ix.children[x]...)
		n := t.ix.nodes[x]
		if kind != "" && n.Kind != kind || metric != "" && n.Metric != metric {
			continue
		}
		s := t.st(x)
		if status != "" && !(s == status || status == "data_issue" && t.status[x] == "data_issue") {
			continue
		}
		out = append(out, x)
	}
	sort.Strings(out)
	f := map[string]any{}
	if kind != "" {
		f["kind"] = kind
	}
	if metric != "" {
		f["metric"] = metric
	}
	if status != "" {
		f["status"] = status
	}
	items := []any{}
	for i, x := range out {
		if i >= 12 {
			break
		}
		items = append(items, map[string]any{"id": x, "name": t.name(x), "kind": t.ix.kind(x), "status": t.st(x)})
	}
	return map[string]any{"node": nid, "name": t.name(nid), "filters": f, "total": len(out), "items": items, "source": "device"}
}

func (t *SiteTools) LinkedEquipment(node, link, direction string) map[string]any {
	nid := t.find(node)
	if nid == "" {
		return siteNF(node)
	}
	if direction == "" {
		direction = "both"
	}
	type row struct {
		typ, dir, node string
		m              map[string]any
	}
	var res []row
	for _, nb := range t.ix.Neighbours(nid) {
		if link != "" && nb.typ != link || (direction == "out" || direction == "in") && nb.dir != direction {
			continue
		}
		open := []any{}
		for i, o := range t.openUnder(nb.other) {
			if i >= 3 {
				break
			}
			open = append(open, o["id"])
		}
		res = append(res, row{nb.typ, nb.dir, nb.other, map[string]any{"type": nb.typ, "direction": nb.dir, "node": nb.other,
			"name": t.name(nb.other), "status": t.st(nb.other), "open": open}})
	}
	sort.SliceStable(res, func(i, j int) bool {
		a, b := res[i], res[j]
		if a.typ != b.typ {
			return a.typ < b.typ
		}
		if a.dir != b.dir {
			return a.dir < b.dir
		}
		return a.node < b.node
	})
	links := []any{}
	for i, r := range res {
		if i >= 12 {
			break
		}
		links = append(links, r.m)
	}
	return map[string]any{"node": nid, "name": t.name(nid), "links": links, "total": len(res), "source": "device"}
}

func (t *SiteTools) SiteStatus(node string) map[string]any {
	nid := t.find(node)
	if nid == "" {
		return siteNF(node)
	}
	r, ok := t.roll[nid]
	if !ok {
		r = RollStatus{Status: t.st(nid)}
	}
	open := []any{}
	for i, o := range t.openUnder(nid) {
		if i >= 5 {
			break
		}
		open = append(open, map[string]any{"id": o["id"], "severity": o["severity"], "title": o["title"], "sensor": o["node"]})
	}
	return map[string]any{"node": nid, "name": t.name(nid), "status": r.Status, "data_issues": r.DataIssues, "open_incidents": open, "source": "device"}
}

// Call dispatches one site tool (args as the chat parser gives them).
func (t *SiteTools) Call(name string, a map[string]any) (map[string]any, error) {
	s := func(k string) string { v, _ := a[k].(string); return v }
	switch name {
	case "get_site_tree":
		d := 1
		switch v := a["depth"].(type) {
		case float64:
			d = int(v)
		case int:
			d = v
		case string:
			fmt.Sscanf(v, "%d", &d)
		}
		return t.GetSiteTree(s("node"), d), nil
	case "nodes_under":
		return t.NodesUnder(s("node"), s("kind"), s("metric"), s("status")), nil
	case "linked_equipment":
		return t.LinkedEquipment(s("node"), s("link"), s("direction")), nil
	case "site_status":
		return t.SiteStatus(s("node")), nil
	}
	return nil, fmt.Errorf("unknown site tool %q", name)
}

// liveSiteTools: the tools over the board's site config and live state.
func liveSiteTools(r *Reasoner) *SiteTools {
	cfg, _ := siteS.Get()
	if cfg == nil {
		cfg = &SiteConfig{Nodes: []SiteNode{{ID: "iiith", Kind: "campus", Name: "IIITH"}}}
	}
	var eng *Engine
	if r != nil {
		eng = r.eng
	}
	st := map[string]string{}
	for k, v := range siteSensorStatus(eng) {
		if v != "normal" {
			st[k] = v
		}
	}
	return NewSiteTools(cfg, st, siteOpenIncidents(r))
}

func chatSiteV4() bool { return chatPromptR3() && reasonerPromptV4() }
