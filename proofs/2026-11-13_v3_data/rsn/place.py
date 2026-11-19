"""Place one incident scenario on a site (synthetic train/dev/test site or the IIITH campus tree).

Place(site, rng) picks a building / floor / room and the equipment around it, and returns names in the shape the r4
family generators expect (nodes(sc): aq, occ, em, ac, out, tank, fin, fout, pump, wq, place, wplace + weather station and
feeder). Devices the site lacks are added to a private copy of the site (equipment / sensor nodes + typed links), so the
SITE / LINKS / SIBLINGS blocks always describe a consistent tree. Deterministic for a given (site, rng state)."""
import copy
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "core"))
import sitegraph as SG  # noqa: E402

UNITS = {"co2": "ppm", "temp": "C", "rh": "%", "pm25": "ug/m3", "pm10": "ug/m3", "power_kw": "kW", "occ": "state", "room_temp": "C"}
SIB_VAL = {"temp": (23.0, 27.5, 1), "rh": (42.0, 62.0, 1), "co2": (450, 820, 0), "pm25": (12.0, 38.0, 1), "power_kw": (0.8, 3.5, 2)}


class Place:
    def __init__(self, site, rng, need_tank=False):
        self.site = copy.deepcopy(site)
        self.rng = rng
        self.ix = SG.Index(self.site)
        self.nm = SG.Namer(rng, self.site.get("naming", "scrc"))
        self.nm.used |= {n["id"] for n in self.site["nodes"]}
        self.host = {}          # device id -> host node id
        self.campus = next(n["id"] for n in self.site["nodes"] if n["kind"] == "campus")
        rooms = self._rooms_with(("co2", "occ"))
        if not rooms:
            rooms = [n["id"] for n in self.site["nodes"] if n["kind"] == "room"]
        self.room = rng.choice(sorted(rooms))
        self.floor = self.ix.parent(self.room)
        self.bld = next(a for a in [self.room] + self.ix.ancestors(self.room) if self.ix.nodes[a]["kind"] == "building")
        others = sorted({b for b in (self._bld_of(r) for r in self._rooms_with(("co2",))) if b != self.bld})
        self.room2 = None
        if others:
            b2 = rng.choice(others)
            self.room2 = rng.choice(sorted(r for r in self._rooms_with(("co2",)) if self._bld_of(r) == b2))

    # ---------------------------------------------------------------- helpers
    def _bld_of(self, nid):
        return next((a for a in [nid] + self.ix.ancestors(nid) if self.ix.nodes[a]["kind"] == "building"), None)

    def _sensors(self, host):
        return [c for c in self.ix.children.get(host, []) if self.ix.nodes[c]["kind"] == "sensor"]

    def _rooms_with(self, metrics):
        out = []
        for n in self.site["nodes"]:
            if n["kind"] in ("room", "zone"):
                ms = {self.ix.nodes[s]["metric"] for s in self._sensors(n["id"])}
                if all(m in ms for m in metrics):
                    out.append(n["id"])
        return out

    def _refresh(self):
        self.ix = SG.Index(self.site)

    def _add_node(self, n):
        self.site["nodes"].append(n)
        self._refresh()
        return n["id"]

    def _add_link(self, a, b, t):
        if not any(l["from"] == a and l["to"] == b and l["type"] == t for l in self.site["links"]):
            self.site["links"].append({"from": a, "to": b, "type": t})
            self._refresh()

    def _code_level(self, nid):
        b = self.ix.nodes[self._bld_of(nid)] if self._bld_of(nid) else {"code": "XX"}
        fl = next((self.ix.nodes[a] for a in [nid] + self.ix.ancestors(nid) if self.ix.nodes[a]["kind"] == "floor"), None)
        lv = int(fl.get("level", "0")) if fl and str(fl.get("level", "0")).isdigit() else 0
        return b.get("code", "XX"), lv

    def _sensor_dev(self, host, metric, kind):
        """device id of a sensor with this metric in host; added when missing"""
        for s in self._sensors(host):
            if self.ix.nodes[s]["metric"] == metric:
                return self.ix.nodes[s]["device"]
        code, lv = self._code_level(host)
        dev = next((self.ix.nodes[s]["device"] for s in self._sensors(host) if self.ix.nodes[s].get("dev_kind") == kind), None)
        if dev is None:
            dev = self.nm.device(kind, code, lv, self.rng.randint(1, 30), self.ix.name(host))
        self._add_node({"id": "%s/%s" % (dev, metric), "kind": "sensor", "parent": host, "device": dev, "metric": metric,
                        "card": "", "dev_kind": kind})
        return dev

    def loc(self, host):
        """'<building>, <floor>, <host>' (campus dropped), as the S# header 'at ...' text"""
        p = [x for x in self.ix.path(host) if self.ix.nodes[x]["kind"] != "campus"]
        return ", ".join(self.ix.name(x) for x in p) or self.ix.name(host)

    def place_text(self, nid):
        p = [x for x in self.ix.path(nid) if self.ix.nodes[x]["kind"] in ("building", "wing", "floor")]
        return ", ".join(self.ix.name(x) for x in p) or self.ix.name(nid)

    def _equip(self, etype, near, name_kind, name_word, link=None):
        """equipment of etype on the floor/building of `near` (linked to `link` target when given); added when missing"""
        cands = []
        for n in self.site["nodes"]:
            if n["kind"] == "equipment" and n.get("etype") == etype:
                if link:
                    t, to = link
                    if any(l["from"] == n["id"] and l["to"] == to and l["type"] == t for l in self.site["links"]):
                        cands.append(n["id"])
                elif self._bld_of(n["id"]) == self._bld_of(near):
                    cands.append(n["id"])
        if cands:
            return sorted(cands)[0]
        code, lv = self._code_level(near)
        dev = self.nm.device(name_kind, code, lv, self.rng.randint(1, 9))
        par = self.ix.parent(near) if self.ix.nodes[near]["kind"] in ("room", "zone") else near
        eid = self._add_node({"id": dev, "kind": "equipment", "etype": etype, "parent": par, "name": "%s %s" % (name_word, dev)})
        if link:
            self._add_link(eid, link[1], link[0])
        return eid

    # ---------------------------------------------------------------- old (building, level, k) -> site host
    def bld_for(self, b):
        """old building code -> site building (first code = the scenario's building, next = another building)"""
        if not hasattr(self, "bmap"):
            self.bmap = {}
        if b not in self.bmap:
            used = set(self.bmap.values())
            if not self.bmap:
                self.bmap[b] = self.bld
            else:
                rest = sorted({self._bld_of(r) for r in self._rooms_with(("co2",))} - used - {None})
                self.bmap[b] = rest[0] if rest else self.bld
        return self.bmap[b]

    def room_for(self, b, fl, k=None):
        """(old building, level, k) -> a room; the first key is the scenario room, same old level -> same floor"""
        if not hasattr(self, "rmap"):
            self.rmap = {}
        key = (b, fl, k)
        if key in self.rmap:
            return self.rmap[key]
        bld = self.bld_for(b)
        same_b = [(kk, r) for kk, r in self.rmap.items() if kk[0] == b]
        rooms = sorted(r for r in self._rooms_with(("co2",)) if self._bld_of(r) == bld) or [self.room]
        if bld == self.bld and not same_b:
            r = self.room
        elif same_b and any(kk[1] == fl for kk, _ in same_b):
            fl_node = self.ix.parent(next(r for kk, r in same_b if kk[1] == fl))
            cand = [x for x in rooms if self.ix.parent(x) == fl_node and x not in self.rmap.values()]
            r = cand[0] if cand else next(r for kk, r in same_b if kk[1] == fl)
        else:
            used_fl = {self.ix.parent(r) for kk, r in same_b}
            cand = [x for x in rooms if self.ix.parent(x) not in used_fl] or rooms
            r = self.rng.choice(cand)
        self.rmap[key] = r
        return r

    def resolve(self, kind, b, fl=None, k=None):
        """(device id, loc) for an old node_* call"""
        if kind in ("aq", "em", "ac", "aq_temp"):
            room = self.room_for(b, fl, k if kind != "em" else None)
            if kind == "ac":
                dev = self._equip("ac_unit", room, "ac", "AC unit", link=("serves", room))
                self.host[dev] = dev
                pan = self._equip("panel", dev, "panel", "panel", link=("supplies", dev))
                self.panel = pan
                return dev, self.loc(dev)
            dev = self._sensor_dev(room, "co2" if kind == "aq" else "power_kw", "air" if kind == "aq" else "em")
            self.host[dev] = room
            return dev, self.loc(room)
        bld = self.bld_for(b)
        if kind == "occ":
            room = next((r for kk, r in getattr(self, "rmap", {}).items() if kk[0] == b), None) or self.room_for(b, fl, k)
            dev = self._sensor_dev(room, "occ", "occ")
            self.host[dev] = room
            return dev, self.loc(room)
        if kind == "out":
            out = next((n["id"] for n in self.site["nodes"] if n["kind"] == "equipment" and any(
                self.ix.nodes[s]["metric"] == "pm25" for s in self._sensors(n["id"]))), None)
            if out is None:
                out = self._add_node({"id": self.nm.device("outdoor", self.ix.nodes[bld].get("code", "XX"), 0, 0), "kind": "equipment",
                                      "etype": "meter", "parent": self.campus, "name": "outdoor air station"})
            self._add_link(out, bld, "outdoor-for")
            self.host[out] = out
            return out, self.loc(out)
        tank = self._equip("tank", bld, "tank", "rooftop tank")
        if self._bld_of(tank) != bld:
            tank = self._add_node({"id": self.nm.device("tank", self.ix.nodes[bld].get("code", "XX"), 9, 0), "kind": "equipment",
                                   "etype": "tank", "parent": bld, "name": "rooftop tank %s" % self.ix.nodes[bld].get("code", "")})
        self._add_link(tank, bld, "supplies")
        if kind == "tank":
            dev = self._sensor_dev(tank, "level", "tank")
        elif kind == "wq":
            dev = self._sensor_dev(tank, "ph", "wq")
        elif kind in ("flow", "pump"):
            pump = self._equip("pump", tank, "flow", "supply pump", link=("feeds", tank))
            if kind == "pump":
                ppan = self._equip("panel", pump, "panel", "pump panel", link=("supplies", pump))
                dev = self._sensor_dev(ppan, "power_kw", "panel")
                self.host[dev] = ppan
                return dev, self.loc(ppan)
            dev = self._sensor_dev(pump, "flow", "flow")
            self.host[dev] = pump
            return dev, self.loc(pump)
        elif kind == "fout":
            fo = [self.ix.nodes[s]["device"] for s in self._sensors(tank) if self.ix.nodes[s]["metric"] == "flow"]
            if fo:
                dev = fo[0]
            else:
                dev = self.nm.device("flow", self.ix.nodes[bld].get("code", "XX"), 0, 40)
                self._add_node({"id": dev + "/flow", "kind": "sensor", "parent": tank, "device": dev, "metric": "flow",
                                "card": "water_flow", "dev_kind": "flow"})
            self.host[dev] = tank
            return dev, self.loc(tank) + ", building outflow"
        self.host[dev] = tank
        return dev, self.loc(tank)

    def place_for(self, b, fl=None):
        if fl is None or b not in getattr(self, "bmap", {}):
            return self.ix.name(self.bld_for(b))
        rs = [r for kk, r in getattr(self, "rmap", {}).items() if kk[0] == b and kk[1] == fl]
        return self.place_text(rs[0]) if rs else self.ix.name(self.bld_for(b))

    # ---------------------------------------------------------------- r4 nodes()
    def nodes(self, second=False):
        room = self.room2 if (second and self.room2) else self.room
        R = {}
        R["aq"] = (self._sensor_dev(room, "co2", "air"), self.loc(room))
        self.host[R["aq"][0]] = room
        R["occ"] = (self._sensor_dev(room, "occ", "occ"), self.loc(room))
        self.host[R["occ"][0]] = room
        em = self._sensor_dev(room, "power_kw", "em")
        R["em"] = (em, self.loc(room))
        self.host[em] = room
        ac = self._equip("ac_unit", room, "ac", "AC unit", link=("serves", room))
        R["ac"] = (ac, self.loc(ac))
        self.host[ac] = ac
        pan = self._equip("panel", ac, "panel", "panel", link=("supplies", ac))
        self.panel = pan
        bld = self._bld_of(room)
        out = next((n["id"] for n in self.site["nodes"] if n["kind"] == "equipment" and any(
            self.ix.nodes[s]["metric"] == "pm25" for s in self._sensors(n["id"]))), None)
        if out is None:
            out = self._add_node({"id": self.nm.device("outdoor", self.ix.nodes[bld].get("code", "XX"), 0, 0), "kind": "equipment",
                                  "etype": "meter", "parent": self.campus, "name": "outdoor air station"})
        R["out"] = (out, self.loc(out))
        self.host[out] = out
        self._add_link(out, bld, "outdoor-for")
        tank = self._equip("tank", bld, "tank", "rooftop tank", link=None)
        if self._bld_of(tank) != bld:
            tank = self._equip("tank", bld, "tank", "rooftop tank")
        R["tank"] = (self._sensor_dev(tank, "level", "tank"), self.loc(tank))
        self.host[R["tank"][0]] = tank
        pump = self._equip("pump", tank, "flow", "supply pump", link=("feeds", tank))
        R["fin"] = (self._sensor_dev(pump, "flow", "flow"), self.loc(pump))
        self.host[R["fin"][0]] = pump
        self._add_link(tank, bld, "supplies")
        fo = self.nm.device("flow", self.ix.nodes[bld].get("code", "XX"), 0, 40)
        self._add_node({"id": fo + "/flow", "kind": "sensor", "parent": tank, "device": fo, "metric": "flow", "card": "water_flow",
                        "dev_kind": "flow"})
        R["fout"] = (fo, self.loc(tank) + ", building outflow")
        self.host[fo] = tank
        ppan = self._equip("panel", pump, "panel", "pump panel", link=("supplies", pump))
        pm = self._sensor_dev(ppan, "power_kw", "panel")
        R["pump"] = (pm, self.loc(ppan))
        self.host[pm] = ppan
        R["wq"] = (self._sensor_dev(tank, "ph", "wq"), self.loc(tank))
        self.host[R["wq"][0]] = tank
        R["place"] = self.place_text(room)
        R["wplace"] = self.place_text(tank)
        R["room_name"] = self.ix.name(room)
        R["_room"] = room
        return R

    def weather(self):
        ws = [n["id"] for n in self.site["nodes"] if n.get("etype") == "weather_station"]
        bld = self._bld_of(self.room)
        lk = [w for w in ws if any(l["from"] == w and l["to"] == bld for l in self.site["links"])]
        w = sorted(lk or ws)[0] if (lk or ws) else self._add_node(
            {"id": self.nm.device("weather", self.ix.nodes[bld].get("code", "XX"), 4, 0), "kind": "equipment",
             "etype": "weather_station", "parent": self.campus, "name": "weather station"})
        self._add_link(w, bld, "outdoor-for")
        dev = self._sensor_dev(w, "temp", "weather")
        self.host[dev] = w
        return dev, self.loc(w)

    def feeder(self):
        """building feeder meter (power_kw + pf); supplies the room panel"""
        bld = self._bld_of(self.room)
        f = next((n["id"] for n in self.site["nodes"] if n.get("etype") in ("feeder",) and self._bld_of(n["id"]) == bld), None)
        if f is None:
            f = self._add_node({"id": self.nm.device("panel", self.ix.nodes[bld].get("code", "XX"), 0, 0) + "-F", "kind": "equipment",
                                "etype": "feeder", "parent": bld, "name": "main feeder %s" % self.ix.nodes[bld].get("code", "")})
        if not hasattr(self, "panel"):
            ac = self._equip("ac_unit", self.room, "ac", "AC unit", link=("serves", self.room))
            self.panel = self._equip("panel", ac, "panel", "panel", link=("supplies", ac))
        self._add_link(f, self.panel, "supplies")
        dev = self._sensor_dev(f, "pf", "panel")
        self._sensor_dev(f, "power_kw", "panel")
        self.host[dev] = f
        return dev, self.loc(f), self.ix.name(f)

    # ---------------------------------------------------------------- v4 context blocks
    def sensor_id(self, dev, metric):
        sid = "%s/%s" % (dev, metric)
        if sid not in self.ix.nodes:
            self._add_node({"id": sid, "kind": "sensor", "parent": self.host.get(dev, self.room), "device": dev, "metric": metric,
                            "card": "", "dev_kind": "x"})
        return sid

    def link_of(self, a_dev, a_metric, b_dev, b_metric):
        sa = self.sensor_id(a_dev, a_metric)
        sb = self.sensor_id(b_dev, b_metric)
        rel, win, hops = self.ix.relation(sa, sb)
        return {"located-in": "located-in", "floor": "same floor", "building_shared_equipment": "same building",
                "campus_no_link": "no site link"}.get(rel, rel)

    def scope_name(self, devs):
        hs = [self.host.get(d, self.room) for d in devs]
        l = hs[0]
        for h in hs[1:]:
            l = self.ix.lca(l, h) or self.campus
        return self.ix.name(l), l

    def site_line(self, host):
        p = " > ".join(self.ix.name(x) for x in self.ix.path(host))
        n = self.ix.nodes[host]
        if n.get("use"):
            p += " (%s, capacity %d)" % (n["use"].replace("_", " "), n.get("capacity", 0))
        elif n.get("etype"):
            p += " (%s)" % n["etype"].replace("_", " ")
        return p

    def links_line(self, refs_devs):
        """refs_devs: [(ref, dev)] -> 'S1 located-in <room>; <AC> serves <room>; ...'"""
        parts, hosts = [], []
        for ref, dev in refs_devs:
            h = self.host.get(dev, self.room)
            hosts.append(h)
            k = self.ix.nodes[h]["kind"]
            parts.append("%s %s %s" % (ref, "located-in" if k in ("room", "zone") else "on", self.ix.name(h)))
        hs = set(hosts)
        for h in list(hs):
            hs |= set(self.ix.ancestors(h))
        seen, direct, other = set(), [], []
        hd = set(hosts)
        for l in self.site["links"]:
            if l["from"] in hs and l["to"] in hs:
                tgt = direct
            elif l["to"] in hd and l["type"] in ("serves", "supplies", "feeds"):
                tgt = direct           # equipment that serves / supplies / feeds a host in the prompt
            else:
                continue
            s = "%s %s %s" % (self.ix.name(l["from"]), l["type"], self.ix.name(l["to"]))
            if s not in seen:
                seen.add(s)
                tgt.append(s)
        return "; ".join((parts + direct + other)[:14])

    def siblings(self, host, in_prompt, rng):
        out = []
        for s in sorted(self._sensors(host)):
            n = self.ix.nodes[s]
            if n["device"] in in_prompt and (n["device"], n["metric"]) in in_prompt[n["device"]]:
                continue
            m = n["metric"]
            if m in SIB_VAL:
                lo, hi, d = SIB_VAL[m]
                v = round(rng.uniform(lo, hi), d)
                v = int(v) if d == 0 else v
                out.append("%s %s %s %s normal" % (n["device"], m, v, UNITS.get(m, "")))
            elif m == "occ":
                out.append("%s occ %d normal" % (n["device"], rng.choice([0, 1])))
            if len(out) >= 3:
                break
        return self.ix.name(host), out
