"""Site model (V3_DESIGN §3): containment tree + equipment + typed links, adaptive grouping windows, roll-up,
suspect-parent rule; synthetic site generator; provisional IIITH campus tree.

API (stable; core/API.md):
  WINDOWS                                  minutes per relation (§3.4)
  gen_site(seed, split="train") -> site    synthetic site (train / dev / test; test adds held-out motifs)
  campus_site() -> site                    provisional IIITH tree from sensors.json + orchestrator causal map
  Index(site)                              lookups: node, parent, children, path, lca, links_of, sensors_under
  Index.path_text(node_id)                 "IIITH > KH building > level 03 > room KH-303"
  Index.relation(a, b) -> (relation, window_min or None, hops)   grouping relation of two sensors (§3.4)
  Index.rollup(status_by_sensor) -> {node: {"status": .., "data_issues": n}}
  Index.suspects(flag_onset_by_sensor) -> [{"node", "why", "flagged": [...]}]
  render_tree(site) -> str, link_table(site) -> [rows]
Node ids: sensors are "<device>/<metric>" (today's node id + metric). Every node / link may carry "inferred": true.
"""
from __future__ import annotations

import json
import random
import string
from collections import defaultdict, deque
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
APPDATA = ROOT / "Code" / "smart-city-edge-agent" / "app" / "device" / "data"

WINDOWS = {"located-in": 15, "sibling": 15, "occupancy-load": 15, "supplies": 15, "serves": 30, "feeds": 30,
           "floor": 30, "building_shared_equipment": 30, "outdoor-for": 60, "outdoor-heatwave": 90, "outdoor-pm": 60,
           "rain-to-tank": 180, "upstream-of": 30, "downstream-of": 30, "campus_no_link": None}
LINK_TYPES = ("serves", "supplies", "feeds", "outdoor-for", "upstream-of", "downstream-of")
ROOM_USES = {"lecture_hall": (60, 240), "office": (2, 12), "lab": (10, 40), "hostel_room": (1, 3), "corridor": (0, 0),
             "plant_room": (0, 0), "library": (40, 150), "canteen": (60, 250), "server_room": (0, 2), "meeting_room": (6, 20)}
IIITH_CODES = {"KH", "VN", "KN", "BN", "PH", "TH", "AN", "BK", "PL", "SB", "NI", "FG", "MG", "SN", "PR", "BB", "KB", "GW",
               "OBH", "NBH", "IIITH"}
HINDI = ["bhavan", "kaksha", "prayogshala", "pustakalay", "bhojanalay", "chhatravas", "karyalay", "sabhagar", "vidyut",
         "jal", "vayu", "tanki", "pump", "chhat", "manzil", "kamra", "galiyara"]
MOTIFS_TEST = ("tank_cascade_3", "district_chiller", "panel_shared_buildings", "mezzanine_wing", "room_two_acs")


# --------------------------------------------------------------------------------------------- index
class Index:
    def __init__(self, site):
        self.site = site
        self.nodes = {n["id"]: n for n in site["nodes"]}
        self.children = defaultdict(list)
        for n in site["nodes"]:
            if n.get("parent"):
                self.children[n["parent"]].append(n["id"])
        self.out = defaultdict(list)
        self.inn = defaultdict(list)
        for l in site["links"]:
            self.out[l["from"]].append(l)
            self.inn[l["to"]].append(l)

    def parent(self, nid):
        return self.nodes[nid].get("parent")

    def ancestors(self, nid):
        out = []
        p = self.parent(nid)
        while p:
            out.append(p)
            p = self.parent(p)
        return out

    def path(self, nid):
        return list(reversed(self.ancestors(nid))) + [nid]

    def name(self, nid):
        n = self.nodes[nid]
        return n.get("name") or nid

    def path_text(self, nid, include_self=False):
        p = self.path(nid)
        if not include_self:
            p = p[:-1]
        return " > ".join(self.name(x) for x in p)

    def lca(self, a, b):
        pa = self.path(a)
        pb = set(self.path(b))
        best = None
        for x in pa:
            if x in pb:
                best = x
        return best

    def sensors_under(self, nid):
        out, q = [], deque([nid])
        while q:
            x = q.popleft()
            if self.nodes[x]["kind"] == "sensor":
                out.append(x)
            q.extend(self.children.get(x, []))
        return out

    def host(self, sid):
        """The room / equipment / zone a sensor sits in (its parent)."""
        return self.parent(sid)

    def neighbours(self, nid):
        """(other, link type, direction) over typed links of nid."""
        for l in self.out.get(nid, []):
            yield l["to"], l["type"], "out"
        for l in self.inn.get(nid, []):
            yield l["from"], l["type"], "in"

    def link_path(self, a_host, b_host, max_hops=3):
        """Shortest typed-link path between two hosts (BFS over links and the 'room is inside floor/building'
        relation for served floors/buildings). Returns list of link types or None."""
        if a_host == b_host:
            return []
        seen = {a_host: []}
        q = deque([a_host])
        while q:
            x = q.popleft()
            if len(seen[x]) >= max_hops:
                continue
            nxt = list(self.neighbours(x))
            # a link to a floor / building also reaches the rooms below it
            for y, t, d in list(nxt):
                if self.nodes[y]["kind"] in ("floor", "building", "wing", "campus"):
                    for r in self.children.get(y, []):
                        nxt.append((r, t, d))
            # equipment and rooms inherit the links of the floor/building they are in (outdoor-for building)
            for anc in self.ancestors(x):
                for y, t, d in self.neighbours(anc):
                    if t == "outdoor-for":
                        nxt.append((y, t, d))
            for y, t, d in nxt:
                if y not in seen:
                    seen[y] = seen[x] + [t]
                    if y == b_host:
                        return seen[y]
                    q.append(y)
        return None

    def relation(self, a, b):
        """Grouping relation of two SENSOR ids -> (relation, window minutes or None, hops)."""
        ha, hb = self.host(a), self.host(b)
        if ha == hb:
            return "located-in", WINDOWS["located-in"], 0
        lp = self.link_path(ha, hb)
        if lp:
            slow = max(lp, key=lambda t: WINDOWS.get(t) or 0)
            return slow, WINDOWS.get(slow), len(lp)
        l = self.lca(a, b)
        k = self.nodes[l]["kind"] if l else "campus"
        if k in ("floor", "room", "zone"):
            return "floor", WINDOWS["floor"], 0
        if k in ("building", "wing"):
            ea = {x for x, _, _ in self.neighbours(ha)}
            eb = {x for x, _, _ in self.neighbours(hb)}
            if ea & eb:
                return "building_shared_equipment", WINDOWS["building_shared_equipment"], 2
        return "campus_no_link", None, None

    def rollup(self, status_by_sensor):
        """Worst process status of children (critical > warning > normal); sensor_fault / stale / maintenance
        roll up separately as data issues."""
        rank = {"normal": 0, "warning": 1, "critical": 2}
        out = {}
        for nid, n in self.nodes.items():
            if n["kind"] == "sensor":
                continue
            ss = self.sensors_under(nid)
            st, di = "normal", 0
            for s in ss:
                v = status_by_sensor.get(s)
                if v in rank:
                    if rank[v] > rank[st]:
                        st = v
                elif v:
                    di += 1
            out[nid] = {"status": st, "data_issues": di}
        return out

    def suspects(self, onset_by_sensor, window_min=None):
        """§3.3: a node is SUSPECT when >= 2 of its sensor-bearing children flag within the node's window (or >= 50 %
        when it has >= 4), or >= 2 nodes it serves/supplies flag within that link's window."""
        out = []
        for nid, n in self.nodes.items():
            if n["kind"] in ("sensor", "campus"):
                continue
            kids = [c for c in self.children.get(nid, []) if self.nodes[c]["kind"] != "sensor" and self.sensors_under(c)]
            w = (window_min or WINDOWS["floor"]) * 60
            fl = [c for c in kids if any(s in onset_by_sensor for s in self.sensors_under(c))]
            if fl:
                ts = sorted(min(onset_by_sensor[s] for s in self.sensors_under(c) if s in onset_by_sensor) for c in fl)
                close = len(ts) >= 2 and ts[-1] - ts[0] <= w
                if close and (len(fl) >= 2 if len(kids) < 4 else len(fl) * 2 >= len(kids)):
                    out.append({"node": nid, "why": f"{len(fl)} of {len(kids)} children flagged", "flagged": fl})
                    continue
            served = [l["to"] for l in self.out.get(nid, []) if l["type"] in ("serves", "supplies")]
            fl2 = []
            for t in served:
                ss = self.sensors_under(t) if self.nodes[t]["kind"] != "sensor" else [t]
                ss += [s for s in self.sensors_under(t)] if False else []
                on = [onset_by_sensor[s] for s in ss if s in onset_by_sensor]
                if on:
                    fl2.append((t, min(on)))
            if len(fl2) >= 2:
                lt = next(l["type"] for l in self.out[nid] if l["type"] in ("serves", "supplies"))
                ts = sorted(t for _, t in fl2)
                if ts[-1] - ts[0] <= (WINDOWS[lt] or 0) * 60:
                    out.append({"node": nid, "why": f"{len(fl2)} of {len(served)} {lt} loads flagged",
                                "flagged": [x for x, _ in fl2]})
        return out


# --------------------------------------------------------------------------------------------- naming
def _code(rng, used):
    while True:
        c = rng.choice(string.ascii_uppercase) + rng.choice(string.ascii_uppercase)
        if c not in IIITH_CODES and c not in used:
            used.add(c)
            return c


class Namer:
    """Naming schemes: scrc (SR-AQ-XY03-03), bacnet (B2.F3.AV301_CO2), free ("Lab 3 CO2 sensor"), hindi."""
    PREFIX = {"air": "SR-AQ", "occ": "SR-OC", "em": "SR-EM", "ac": "SR-AC", "tank": "WM-WL", "flow": "WM-WF", "wq": "WM-WD",
              "panel": "EM-PN", "weather": "WE", "outdoor": "AQ", "solar": "SL", "x": "SR-XX"}

    def __init__(self, rng, scheme):
        self.rng, self.scheme, self.used = rng, scheme, set()

    def device(self, kind, bcode, level, idx, room_name=""):
        r = self.rng
        if self.scheme == "scrc":
            p = self.PREFIX.get(kind, "SR-XX")
            name = f"{p}-{bcode}{level:02d}-{idx:02d}" if kind not in ("weather", "outdoor", "solar") else f"{p}-{bcode}{level:02d}-{idx:02d}"
        elif self.scheme == "bacnet":
            obj = {"air": "AV", "occ": "BI", "em": "AI", "ac": "AC", "tank": "LT", "flow": "FT", "wq": "QT", "panel": "PM",
                   "weather": "WX", "outdoor": "OA", "solar": "PV", "x": "AI"}.get(kind, "AI")
            name = f"{bcode}.F{level}.{obj}{100 * level + idx + r.randint(0, 3)}"
        elif self.scheme == "hindi":
            w = {"air": "vayu", "occ": "upasthiti", "em": "vidyut", "ac": "thanda", "tank": "tanki", "flow": "jal-pravah",
                 "wq": "jal-gunvatta", "panel": "vidyut-panel", "weather": "mausam", "outdoor": "bahar-vayu", "solar": "saur",
                 "x": "sensor"}.get(kind, "sensor")
            name = f"{bcode.lower()}-{w}-{level}-{idx}"
        else:
            w = {"air": "air sensor", "occ": "presence sensor", "em": "energy meter", "ac": "AC unit", "tank": "tank level",
                 "flow": "flow meter", "wq": "water quality", "panel": "panel meter", "weather": "weather station",
                 "outdoor": "outdoor air", "solar": "solar inverter", "x": "sensor"}.get(kind, "sensor")
            name = f"{bcode} {room_name or ('L' + str(level))} {w} {idx}".replace("  ", " ")
        while name in self.used:
            name += r.choice("ABCDEFGH")
        self.used.add(name)
        return name


# --------------------------------------------------------------------------------------------- synthetic sites
def gen_site(seed, split="train", motifs=None):
    """One synthetic site. split test -> 1-3 held-out motifs (MOTIFS_TEST); train/dev never contain them."""
    rng = random.Random(f"site-{split}-{seed}")
    sid = f"{split[:2]}{seed:05d}"
    scheme = rng.choice(("scrc", "scrc", "bacnet", "free", "hindi"))
    nm = Namer(rng, scheme)
    if motifs is None:
        motifs = set(rng.sample(MOTIFS_TEST, rng.randint(1, 3))) if split.startswith("test") else set()
    nodes, links, used = [], [], set()
    camp = rng.choice(["North campus", "Tech park", "City campus", "Lake campus", "Hill campus", "Vidya parisar", "Gyan kendra"])
    nodes.append({"id": sid, "kind": "campus", "name": camp})
    nb = rng.randint(1, 6) if "district_chiller" not in motifs and "panel_shared_buildings" not in motifs else rng.randint(2, 6)
    bidx = []
    sensor_count = 0

    def add(n):
        nodes.append(n)
        return n["id"]

    def sensor(dev, metric, parent, card, kind_hint, place=None):
        nonlocal sensor_count
        sensor_count += 1
        return add({"id": f"{dev}/{metric}", "kind": "sensor", "parent": parent, "device": dev, "metric": metric,
                    "card": card, "dev_kind": kind_hint})

    weather_ids = []
    for wi in range(rng.randint(1, 3)):
        bc = _code(rng, used)
        dev = nm.device("weather", bc, rng.randint(0, 4), wi)
        ws = add({"id": dev, "kind": "equipment", "etype": "weather_station", "parent": sid, "name": f"weather station {dev}"})
        for m in ("temp", "rh", "wind"):
            sensor(dev, m, ws, f"weather_{m}", "weather")
        weather_ids.append(ws)
    if rng.random() < 0.7:
        bc = _code(rng, used)
        dev = nm.device("outdoor", bc, 0, 0)
        oa = add({"id": dev, "kind": "equipment", "etype": "meter", "parent": sid, "name": f"outdoor air station {dev}"})
        for m in ("pm25", "pm10"):
            sensor(dev, m, oa, f"{m}_outdoor", "outdoor")
        weather_ids.append(oa)
    buildings = []
    all_rooms, all_ac, all_panels = [], [], []
    for b in range(nb):
        bc = _code(rng, used)
        bname = rng.choice([f"{bc} building", f"{bc} block", f"Block {bc}", f"{bc} bhavan", f"{bc} hall"])
        bid = add({"id": f"{sid}-{bc}", "kind": "building", "parent": sid, "name": bname, "code": bc})
        buildings.append(bid)
        bidx.append(bc)
        for w in weather_ids[:1] + ([weather_ids[1]] if len(weather_ids) > 1 and rng.random() < 0.3 else []):
            links.append({"from": w, "to": bid, "type": "outdoor-for"})
        nf = rng.randint(1, 8)
        floors = []
        wing = None
        if "mezzanine_wing" in motifs and b == 0:
            wing = add({"id": f"{bid}-W", "kind": "wing", "parent": bid, "name": f"{bc} east wing"})
        for f in range(nf):
            par = wing if (wing and f % 2 == 1) else bid
            lvl = f
            fname = f"level {lvl:02d}" if rng.random() < 0.8 else f"floor {lvl}"
            fid = add({"id": f"{bid}-{lvl:02d}", "kind": "floor", "parent": par, "name": fname, "level": f"{lvl:02d}"})
            floors.append(fid)
            if "mezzanine_wing" in motifs and b == 0 and f == 0:
                mz = add({"id": f"{bid}-M", "kind": "floor", "parent": bid, "name": "mezzanine", "level": "M"})
                floors.append(mz)
        bpanel = add({"id": nm.device("panel", bc, 0, 0), "kind": "equipment", "etype": "panel", "parent": floors[0],
                      "name": f"main panel {bc}"})
        all_panels.append(bpanel)
        for m, card in (("power_kw", "power_load"), ("pf", "power_pf")):
            sensor(bpanel, m, bpanel, card, "panel")
        for fi, fid in enumerate(floors):
            lvl = fi
            nr = rng.randint(2, 14)
            fpanel = None
            if rng.random() < 0.6:
                fpanel = add({"id": nm.device("panel", bc, lvl, 1), "kind": "equipment", "etype": "panel", "parent": fid,
                              "name": f"panel F{lvl}"})
                links.append({"from": bpanel, "to": fpanel, "type": "supplies"})
                if rng.random() < 0.7:
                    sensor(fpanel, "power_kw", fpanel, "power_load", "panel")
                all_panels.append(fpanel)
            rooms = []
            for r in range(nr):
                use = rng.choices(list(ROOM_USES), weights=[3, 4, 3, 2, 1, 1, 1, 1, 1, 2])[0]
                lo, hi = ROOM_USES[use]
                cap = rng.randint(lo, hi) if hi else 0
                rnum = f"{bc}-{lvl}{r + 1:02d}" if rng.random() < 0.7 else f"{bc}{lvl}.{r + 1}"
                rname = {"lecture_hall": "room", "office": "office", "lab": "lab", "hostel_room": "room", "corridor": "corridor",
                         "plant_room": "plant room", "library": "library", "canteen": "canteen", "server_room": "server room",
                         "meeting_room": "meeting room"}[use] + " " + rnum
                rid = add({"id": f"{fid}-R{r + 1:02d}", "kind": "zone" if use in ("corridor", "outdoor_area") else "room",
                           "parent": fid, "name": rname, "use": use, "capacity": cap})
                rooms.append(rid)
                all_rooms.append(rid)
                if use in ("corridor", "plant_room"):
                    continue
                if rng.random() < 0.85:
                    dev = nm.device("air", bc, lvl, r + 1, rnum)
                    for m, card in (("co2", "co2_indoor"), ("temp", "temp_indoor"), ("rh", "rh_indoor")):
                        if rng.random() < 0.93:
                            sensor(dev, m, rid, card, "air")
                    if rng.random() < 0.2:
                        sensor(dev, "pm25", rid, "pm25_indoor", "air")
                if cap and rng.random() < 0.7:
                    sensor(nm.device("occ", bc, lvl, r + 1, rnum), "occ", rid, "occupancy", "occ")
                if rng.random() < 0.35:
                    em = nm.device("em", bc, lvl, r + 1, rnum)
                    sensor(em, "power_kw", rid, "power_load", "em")
                    if fpanel:
                        links.append({"from": fpanel, "to": rid, "type": "supplies"})
            # AC units: serve 1-4 rooms each
            acr = [x for x in rooms if nodes_by_id(nodes, x)["use"] not in ("corridor", "plant_room")]
            rng.shuffle(acr)
            i = 0
            k = 0
            while i < len(acr):
                if rng.random() < 0.25:
                    i += 1
                    continue
                g = acr[i:i + rng.randint(1, 4)]
                i += len(g)
                k += 1
                acid = add({"id": nm.device("ac", bc, lvl, k), "kind": "equipment", "etype": "ac_unit", "parent": fid,
                            "name": f"AC unit {bc}{lvl}-{k}"})
                all_ac.append(acid)
                sensor(acid, "room_temp", acid, "hvac_unit", "ac")
                for rr in g:
                    links.append({"from": acid, "to": rr, "type": "serves"})
                if "room_two_acs" in motifs and g and rng.random() < 0.5:
                    k += 1
                    ac2 = add({"id": nm.device("ac", bc, lvl, k), "kind": "equipment", "etype": "ac_unit", "parent": fid,
                               "name": f"AC unit {bc}{lvl}-{k}"})
                    all_ac.append(ac2)
                    sensor(ac2, "room_temp", ac2, "hvac_unit", "ac")
                    links.append({"from": ac2, "to": g[0], "type": "serves"})
                links.append({"from": fpanel or bpanel, "to": acid, "type": "supplies"})
            if rng.random() < 0.25:
                ahu = add({"id": f"{fid}-AHU", "kind": "equipment", "etype": "ahu", "parent": fid, "name": f"AHU {bc}-{lvl}"})
                links.append({"from": ahu, "to": fid, "type": "serves"})
                links.append({"from": fpanel or bpanel, "to": ahu, "type": "supplies"})
        # water: sump -> pump -> rooftop tank -> building
        roof = floors[-1]
        nt = 3 if ("tank_cascade_3" in motifs and b == 0) else (2 if rng.random() < 0.3 else 1)
        prev = None
        tanks = []
        for t in range(nt):
            tid = add({"id": nm.device("tank", bc, 99 - t if t else 98, t), "kind": "equipment", "etype": "tank",
                       "tank_kind": "rooftop" if t == nt - 1 else "sump", "parent": roof if t == nt - 1 else floors[0],
                       "name": f"{'rooftop tank' if t == nt - 1 else 'sump' if t == 0 else 'mid tank'} {bc}-{t}",
                       "tank": {"high": 0, "overflow": 0, "fill_min": 0}})
            tanks.append(tid)
            if rng.random() < 0.9:
                sensor(tid, "level", tid, "tank_level", "tank")
            if prev:
                pid = add({"id": f"{tid}-P", "kind": "equipment", "etype": "pump", "parent": floors[0], "name": f"pump {bc}-{t}"})
                links.append({"from": prev, "to": pid, "type": "upstream-of"})
                links.append({"from": pid, "to": tid, "type": "feeds"})
                links.append({"from": bpanel, "to": pid, "type": "supplies"})
                if rng.random() < 0.6:
                    sensor(nm.device("flow", bc, 0, t), "flow", pid, "water_flow", "flow")
            else:
                pid = add({"id": f"{tid}-P", "kind": "equipment", "etype": "pump", "parent": floors[0], "name": f"supply pump {bc}"})
                links.append({"from": pid, "to": tid, "type": "feeds"})
                links.append({"from": bpanel, "to": pid, "type": "supplies"})
                if rng.random() < 0.5:
                    sensor(nm.device("flow", bc, 0, 9), "flow", pid, "water_flow", "flow")
            prev = tid
        links.append({"from": tanks[-1], "to": bid, "type": "supplies"})
        if len(weather_ids) and rng.random() < 0.3:
            links.append({"from": weather_ids[0], "to": tanks[-1], "type": "outdoor-for", "note": "rain-to-tank"})
        if rng.random() < 0.6:
            wq = nm.device("wq", bc, 0, 0)
            for m, card in (("tds", "water_tds"), ("ph", "water_ph")):
                sensor(wq, m, tanks[0], card, "wq")
        if rng.random() < 0.4:
            sl = add({"id": nm.device("solar", bc, 99, 0), "kind": "equipment", "etype": "meter", "parent": roof,
                      "name": f"solar inverter {bc}"})
            sensor(sl, "power_kw", sl, "power_solar", "solar")
            links.append({"from": sl, "to": bpanel, "type": "supplies"})
    if "district_chiller" in motifs and len(buildings) >= 2:
        ch = add({"id": f"{sid}-CH1", "kind": "equipment", "etype": "chiller", "parent": sid, "name": "district chiller 1"})
        for bid in rng.sample(buildings, 2):
            links.append({"from": ch, "to": bid, "type": "serves"})
    if "panel_shared_buildings" in motifs and len(buildings) >= 2:
        sp = add({"id": f"{sid}-SP1", "kind": "equipment", "etype": "feeder", "parent": sid, "name": "shared feeder 1"})
        sensor(sp, "power_kw", sp, "power_load", "panel")
        for bid in rng.sample(buildings, 2):
            mp = next(n["id"] for n in nodes if n.get("etype") == "panel" and n["parent"].startswith(bid))
            links.append({"from": sp, "to": mp, "type": "supplies"})
    elif rng.random() < 0.5 and len(buildings) >= 1 and not split.startswith("test"):
        sub = add({"id": f"{sid}-SUB", "kind": "equipment", "etype": "feeder", "parent": sid, "name": "campus substation"})
        sensor(sub, "power_kw", sub, "power_load", "panel")
        for bid in buildings[:1]:
            mp = next(n["id"] for n in nodes if n.get("etype") == "panel" and n["parent"].startswith(bid))
            links.append({"from": sub, "to": mp, "type": "supplies"})
    return {"site_id": sid, "version": 1, "split": split, "naming": scheme, "motifs": sorted(motifs),
            "nodes": nodes, "links": links, "windows": dict(WINDOWS)}


def nodes_by_id(nodes, nid):
    for n in reversed(nodes):
        if n["id"] == nid:
            return n
    raise KeyError(nid)


def attach_extra_sensors(site, rng, type_pool, k=None):
    """Add synthetic-metric sensors (unseen types) to suitable hosts of a site. Returns the new sensor ids.
    Card values are drawn later per row (cards.synthetic_card), the node only records the type."""
    ix = Index(site)
    hosts = {"room": [n["id"] for n in site["nodes"] if n["kind"] == "room"],
             "equip": [n["id"] for n in site["nodes"] if n["kind"] == "equipment"],
             "any": [n["id"] for n in site["nodes"] if n["kind"] in ("room", "zone", "equipment")]}
    out = []
    for i in range(k if k is not None else rng.randint(2, 6)):
        t = rng.choice(type_pool)
        h = rng.choice(hosts["room"] or hosts["any"])
        dev = f"X{i}-{t[:4].upper()}-{rng.randrange(100, 999)}"
        nid = f"{dev}/{t}"
        site["nodes"].append({"id": nid, "kind": "sensor", "parent": h, "device": dev, "metric": t,
                              "card": f"synthetic:{t}", "dev_kind": "x"})
        out.append(nid)
    return out


# --------------------------------------------------------------------------------------------- IIITH campus
def campus_site():
    """Provisional IIITH tree from the app's sensors.json + sensors_hvac_v2.json + the orchestrator causal map.
    Every relation not stated in sensors.json (building / level / location text) is marked inferred=True with a
    reason; the owner corrects them in the data review."""
    S = json.loads((APPDATA / "sensors.json").read_text())["sensors"]
    SH = json.loads((APPDATA / "sensors_hvac_v2.json").read_text())
    tl = json.loads((APPDATA / "node_limits_v2.json").read_text())
    nodes = [{"id": "iiith", "kind": "campus", "name": "IIITH"}]
    links = []
    have = {"iiith"}

    def add(n):
        if n["id"] not in have:
            nodes.append(n)
            have.add(n["id"])
        return n["id"]

    def building(code, inferred=False, why=None):
        return add({"id": code, "kind": "building", "parent": "iiith", "name": f"{code} building", "code": code,
                    **({"inferred": True, "why": why} if inferred else {})})

    def floor(code, lvl, inferred=False, why=None):
        building(code)
        name = {"98": "rooftop (level 98)", "95": "gateway level 95"}.get(lvl, f"level {lvl}")
        return add({"id": f"{code}-{lvl}", "kind": "floor", "parent": code, "name": name, "level": lvl,
                    **({"inferred": True, "why": why} if inferred else {})})

    from cards import metric_to_card  # noqa: E402
    for s in S + SH["sensors"]:
        node, role, metric = s["node"], s["role"], s["metric"]
        loc = s.get("location", "")
        b, lvl = s.get("building"), s.get("level")
        if role == "hvac" and metric != "room_temp" and node.startswith("SR-AC"):
            continue  # setpoint / ac_on are channels of the hvac_unit card
        if node.startswith("AC-KH03") and metric == "room_temp":
            continue
        sid = f"{node}/{metric}"
        if node.startswith("SR-AQ"):
            fl = floor(b, lvl)
            host = add({"id": f"{b}-{lvl}-AQ{node[-2:]}", "kind": "room", "parent": fl, "name": f"room of air sensor {node[-2:]}",
                        "use": "lecture_hall", "capacity": 60, "inferred": True,
                        "why": "room, use and capacity unknown; sensors.json says 'indoor air sensor 03'"})
        elif node.startswith("AQ-"):
            bc = node[3:5]
            building(bc, True, "outdoor station code AQ-KN00 -> KN")
            host = add({"id": node, "kind": "equipment", "etype": "meter", "parent": "iiith", "name": f"outdoor air station {node}"})
            links.append({"from": node, "to": bc, "type": "outdoor-for", "inferred": True, "why": "station at KN serves KN"})
            links.append({"from": node, "to": "KH", "type": "outdoor-for", "inferred": True,
                          "why": "causal map: pm25 relates to other station / campus air"})
        elif node.startswith("WM-WL"):
            fl = floor(b, lvl)
            lim = tl.get(node, {})
            host = add({"id": node, "kind": "equipment", "etype": "tank", "tank_kind": "rooftop", "parent": fl,
                        "name": "rooftop tank KH", "tank": {k: lim.get(k) for k in ("high", "overflow", "fill_min")},
                        "inferred": True, "why": "level 98 read as rooftop; tank kind inferred"})
            links.append({"from": node, "to": "KH", "type": "supplies", "inferred": True, "why": "tank on KH roof supplies KH"})
        elif node.startswith("WM-WF"):
            fl = floor(b, lvl)
            host = add({"id": "PUMP-KH98", "kind": "equipment", "etype": "pump", "parent": fl, "name": "supply pump KH (flow meter 40)",
                        "inferred": True, "why": "flow meter assumed on the tank inlet pump line"})
            links.append({"from": "PUMP-KH98", "to": "WM-WL-KH98-00", "type": "feeds", "inferred": True,
                          "why": "causal map: flow explains level changes"})
        elif node.startswith("WM-WD"):
            host = "WM-WL-KH98-00"
            floor(b, lvl)
        elif node.startswith("SR-EM"):
            fl = floor(b, lvl)
            host = add({"id": f"{b}-{lvl}-EM{node[-2:]}", "kind": "room", "parent": fl, "name": f"room of energy meter {node[-2:]}",
                        "use": "office", "capacity": 10, "inferred": True, "why": "room use unknown ('room energy meter 01')"})
        elif node.startswith("EM-CR"):
            host = add({"id": node, "kind": "equipment", "etype": "feeder", "parent": "iiith", "name": "SB00 substation 11 kV feeder"})
            links.append({"from": node, "to": "KH", "type": "supplies", "inferred": True, "why": "feeder assumed to supply KH"})
        elif node.startswith("SR-OC"):
            fl = floor("KH", "03", True, "occupancy gateway KH95 has no level; placed with the KH-03 air sensor room")
            host = "KH-03-AQ03"
            add({"id": host, "kind": "room", "parent": fl, "name": "room of air sensor 03", "use": "lecture_hall", "capacity": 60,
                 "inferred": True, "why": "room unknown"})
        elif node.startswith("WE-"):
            building(b)
            fl = floor(b, lvl)
            host = add({"id": node, "kind": "equipment", "etype": "weather_station", "parent": fl, "name": "rooftop weather station VN"})
            for bb in ("KH", "KN", "VN"):
                building(bb)
                links.append({"from": node, "to": bb, "type": "outdoor-for", "inferred": bb != "VN",
                              **({"why": "one weather station assumed for the whole campus"} if bb != "VN" else {})})
        elif node.startswith("SR-AC"):
            fl = floor(b, lvl)
            host = add({"id": node, "kind": "equipment", "etype": "ac_unit", "parent": fl, "name": f"AC indoor unit {node[-2:]}"})
            if lvl == "03":
                links.append({"from": node, "to": "KH-03-AQ03", "type": "serves", "inferred": True,
                              "why": "same floor as the air sensor room; real served rooms unknown"})
            else:
                rid = add({"id": f"{b}-{lvl}-ROOM{node[-2:]}", "kind": "room", "parent": fl, "name": f"room of AC unit {node[-2:]}",
                           "use": "office", "capacity": 10, "inferred": True, "why": "room implied by an AC unit"})
                links.append({"from": node, "to": rid, "type": "serves", "inferred": True, "why": "one room per AC unit assumed"})
            links.append({"from": "EM-CR-SB00-00", "to": node, "type": "supplies", "inferred": True,
                          "why": "causal map: AC is the main load"})
        elif node.startswith("AC-KH"):
            continue
        else:
            raise KeyError(node)
        card = metric_to_card(role, metric, node, loc)
        add({"id": sid, "kind": "sensor", "parent": host, "device": node, "metric": metric, "card": card, "location": loc})
    # de-duplicate links
    seen, L = set(), []
    for l in links:
        k = (l["from"], l["to"], l["type"])
        if k not in seen and l["from"] in have and l["to"] in have:
            seen.add(k)
            L.append(l)
    return {"site_id": "iiith", "version": 0, "split": "test_campus", "naming": "scrc", "motifs": [], "provisional": True,
            "nodes": nodes, "links": L, "windows": dict(WINDOWS)}


# --------------------------------------------------------------------------------------------- rendering
def render_tree(site, mark_inferred=True):
    ix = Index(site)
    root = next(n["id"] for n in site["nodes"] if n["kind"] == "campus")
    lines = []

    def walk(x, depth):
        n = ix.nodes[x]
        tag = n["kind"]
        extra = []
        if n.get("use"):
            extra.append(f"{n['use']}, cap {n.get('capacity', 0)}")
        if n.get("etype"):
            extra.append(n["etype"])
        if n["kind"] == "sensor":
            extra.append(f"card {n['card']}")
        s = "  " * depth + f"- {ix.name(x) if n['kind'] != 'sensor' else x} [{tag}{'; ' + '; '.join(extra) if extra else ''}]"
        if mark_inferred and n.get("inferred"):
            s += f"  (INFERRED: {n.get('why', '')})"
        lines.append(s)
        for c in sorted(ix.children.get(x, []), key=lambda c: (ix.nodes[c]["kind"] == "sensor", c)):
            walk(c, depth + 1)

    walk(root, 0)
    return "\n".join(lines)


def link_table(site):
    return [{"from": l["from"], "type": l["type"], "to": l["to"], "inferred": bool(l.get("inferred")), "why": l.get("why", "")}
            for l in site["links"]]


if __name__ == "__main__":
    import sys
    s = gen_site(1, "train")
    ix = Index(s)
    print(s["site_id"], s["naming"], len(s["nodes"]), "nodes", len(s["links"]), "links")
    sens = [n["id"] for n in s["nodes"] if n["kind"] == "sensor"]
    print(sens[:5], ix.path_text(sens[-1]))
    t = gen_site(3, "test")
    print("test motifs", t["motifs"], len(t["nodes"]))
    c = campus_site()
    print(render_tree(c))
    for r in link_table(c):
        print(r)
    cx = Index(c)
    print(cx.relation("SR-AQ-KH03-03/co2", "SR-OC-GW-KH95-01/occ"), cx.relation("SR-AQ-KH03-03/co2", "WE-VN04-00/temp"),
          cx.relation("WM-WL-KH98-00/level", "WM-WF-KH98-40/flow"), cx.relation("AQ-KN00-00/pm25", "SR-EM-KH04-01/power_kw"))
