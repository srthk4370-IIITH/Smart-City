"""gen5_domain.py N OUT: per-domain severity contrast quadruples (same window shape, normal/warning/critical/sensor_fault), deciding evidence and card limits in the report.
Domains: CO2/occupancy (big_co2), HVAC thermal (big_temp), water pH + tank level, power factor, weather temp/RH. Scenes dated 2025-01..2025-12-10. family gen5_domain."""
import sys, json, random, collections
BIGB = "/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-20_rsn_big/build"; sys.path.insert(0, BIGB)
import build_big as BB, big_inc as BI, v2_gen as X
B, G, M = BB.B, BB.G, X.M
P, ag, ob, rep, ev_of, S, XX = M.P, M.ag, M.ob, M.rep, M.ev_of, M.S, M.X
_scen = M.scen


def scen(R, i, novel=False, months=None, hours=None):
    sc = _scen(R, i, novel, [m for m in (months or range(1, 12)) if m <= 11] or [5], hours)
    e = sc["end"]
    sc["end"] = e.replace(year=2025, day=min(e.day, 28))
    return sc


M.scen = scen
ADJ = BI.ADJ


def cfgs(R, nd):
    hi = R.uniform(62, 90)
    return {
        "ph": dict(role="water", metric="ph", node=nd["wq"], head=["LIMITS: warning above 8.5, critical above 9.0"], w=8.5, c=9.0, unit="", word="pH", dec=2, nz=0.02,
                   base=lambda r: r.uniform(7.2, 7.6),
                   top={"normal": lambda r: r.uniform(7.8, 8.3), "warning": lambda r: r.uniform(8.6, 8.9), "critical": lambda r: r.uniform(9.1, 9.6)},
                   jump=lambda r: r.uniform(2.4, 4.0), label="water_quality_issue", dom="water", act="inspect_water_system"),
        "tank": dict(role="water", metric="level", node=nd["tank"], head=["TANK: high level above %.1f, overflow risk above %.1f; usual fill up to 90 min" % (hi, hi + 30)],
                     w=round(hi, 1), c=round(hi + 30, 1), unit="", word="Tank level", dec=1, nz=0.4, base=lambda r: r.uniform(hi - 60, hi - 40),
                     top={"normal": lambda r: r.uniform(hi - 12, hi - 2), "warning": lambda r: r.uniform(hi + 4, hi + 24), "critical": lambda r: r.uniform(hi + 34, hi + 60)},
                     jump=lambda r: r.uniform(70, 120), label="water_supply_issue", dom="water", act="inspect_water_system"),
        "pf": dict(role="power", metric="pf", node=(M.SUB_NODE, M.SUB_LOC), head=[M.LIM["pf"]], w=0.85, c=0.7, lo=True, unit="", word="Power factor", dec=2, nz=0.01,
                   base=lambda r: r.uniform(0.93, 0.97),
                   top={"normal": lambda r: r.uniform(0.87, 0.91), "warning": lambda r: r.uniform(0.74, 0.83), "critical": lambda r: r.uniform(0.5, 0.67)},
                   jump=lambda r: -r.uniform(0.3, 0.45), label="power_quality_issue", dom="power", act="inspect_electrical"),
        "wtemp": dict(role="weather", metric="temp", node=(M.WE_NODE, M.WE_LOC), head=[M.LIM["wtemp"]], w=38, c=42, unit="C", word="Outdoor temperature", dec=1, nz=0.15,
                      base=lambda r: r.uniform(26, 31),
                      top={"normal": lambda r: r.uniform(34.2, 37.4), "warning": lambda r: r.uniform(38.6, 41.4), "critical": lambda r: r.uniform(42.6, 45.5)},
                      jump=lambda r: r.uniform(9, 14), label="weather_driven", dom="weather", act="monitor"),
        "wrh": dict(role="weather", metric="rh", node=(M.WE_NODE, M.WE_LOC), head=[M.LIM["wrh"]], w=90, c=97, unit="%", word="Outdoor humidity", dec=1, nz=0.4,
                    base=lambda r: r.uniform(55, 70),
                    top={"normal": lambda r: r.uniform(80, 88.5), "warning": lambda r: r.uniform(91, 96), "critical": lambda r: r.uniform(97.5, 99.5)},
                    jump=lambda r: -r.uniform(30, 45), label="weather_driven", dom="weather", act="monitor"),
    }


def f_dom(name):
    def f(R, sc, nd, nd2=None):
        Rs, var = BI._next(R)
        c = cfgs(R, nd)[name]
        node, loc = c["node"]
        lo = c.get("lo")
        base, dec = c["base"](Rs), c["dec"]
        if var == "sensor_fault":
            hist = M.noise(Rs, 144, base, c["nz"], dec)
            jt, off = Rs.randrange(100, 136), c["jump"](R)
            xs = [M.r1(v + (off if i >= jt else 0), dec) for i, v in enumerate(hist)]
        else:
            xs = M.ramp(Rs, Rs.randrange(4, 24), base, c["top"][var](R), c["nz"], dec, lo=None if lo else 0)
            last = xs[-1]
            past = (lambda lim: last < lim) if lo else (lambda lim: last > lim)
            if ("critical" if past(c["c"]) else "warning" if past(c["w"]) else "normal") != var:
                return None
        st = var if R.random() < 0.6 else R.choice(ADJ[var])
        wrong = st != var
        u = (" " + c["unit"]) if c["unit"] else ""
        s1 = S("S1", c["role"], c["metric"], node, loc, xs, True, head=c["head"],
               agent=lambda s: ag("step_increase" if var == "sensor_fault" else ("gradual_decrease" if lo else "gradual_increase"), st,
                                  "sensor_fault" if st == "sensor_fault" else c["label"], round(R.uniform(0.7, 0.9), 2), ["%s now %s%s [E1]" % (c["word"], P(s)["last"], u)]))
        if c["metric"] == "ph":
            s2 = S("S2", "water", "flow", nd["fout"][0], nd["fout"][1], M.noise(Rs, 48, Rs.uniform(8, 20), 0.3, 1, lo=0), False, "water flow context", agent=M.steady_ag("Flow"))
        elif c["role"] == "weather":
            s2 = S("S2", "air_quality", "temp", nd["aq"][0], nd["aq"][1], M.noise(Rs, 48, Rs.uniform(23, 26), 0.1, 1), False, "indoor temperature context", agent=M.steady_ag("Indoor temperature"))
        elif c["role"] == "power":
            s2 = S("S2", "power", "power_kw", M.SUB_NODE, M.SUB_LOC, M.noise(Rs, 48, Rs.uniform(900, 1300), 6, 2), False, "feeder load context", agent=M.steady_ag("Feeder load"))
        else:
            s2 = S("S2", "water", "flow", nd["fin"][0], nd["fin"][1], M.noise(Rs, 48, Rs.uniform(8, 20), 0.3, 1, lo=0), False, "inflow context", agent=M.steady_ag("Inflow"))
        p1, p2 = P(s1), P(s2)
        t = "S1 (%s)" % node
        W, Cc = c["w"], c["c"]

        def ck(fact, src):
            return [{"ref": "S1", "claim": "status %s" % st, "verdict": "corrected", "fact": fact, "src": src}] if wrong else []
        if var == "sensor_fault":
            obs = [M.o_jump(s1, c["word"]), M.o_now(s1, c["word"]), ob("Context sensor steady at %s" % p2["last"], ["S2.E1", "S2.E4"])]
            j = p1["jump"].lstrip("+-")
            chk = ck("a %s step in one sample that the context sensor does not share" % j, ["S1.E5", "S2.E1"])
            r = rep("%s step that nothing else shows: %s" % (c["word"], nd["place"]), "sensor_fault", "sensor_fault",
                    "%s stepped %s%s in one sample while the context sensor stays steady and nothing physical explains it: a sensor fault, not an event." % (c["word"], j, u),
                    "%s step (S1.E5), context steady (S2.E1) -> sensor fault" % j, obs, chk, [c["dom"]], ["S1"], ev_of(obs), round(R.uniform(0.8, 0.9), 2),
                    [("check_sensor", t, "Reading jumped alone"), ("recalibrate_sensor", t, "Compare with a reference")], "Reading after the sensor check",
                    "A lone step is a sensor fault; the card limit does not apply to it.")
            sevf = "sensor_fault"
        else:
            obs = [M.o_tr(s1, c["word"]), M.o_now(s1, c["word"]), ob("Context sensor steady around %s" % p2["last"], ["S2.E1", "S2.E4"])]
            lim = W if var != "critical" else Cc
            chk = ck("%s%s %s (card limit %s)" % (p1["last"], u, {"normal": "does not pass the warning limit", "warning": "is past the warning limit", "critical": "is past the critical limit"}[var], lim), ["S1.E1", "S2.E1"])
            title = {"normal": "%s %s%s, inside the card limit: %s", "warning": "%s %s%s past the warning limit: %s", "critical": "%s %s%s past the critical limit: %s"}[var] % (c["word"], p1["last"], u, nd["place"])
            cl = [M.cl("monitor", s1, "Watch the trend against the %s limit" % W)] if var == "normal" else [M.cl(c["act"], s1, "Past the card limit")]
            if var == "critical":
                cl.append(M.cl("request_facility_review", s1, "Beyond the critical limit"))
            txt = {"normal": "stays inside the %s warning limit" % W, "warning": "is past the %s warning limit, short of %s" % (W, Cc), "critical": "is past the %s critical limit" % Cc}[var]
            r = rep(title, var, "normal_operation" if var == "normal" else c["label"],
                    "%s %s (%s%s); the context sensor is steady, so the reading is genuine." % (c["word"], txt, p1["last"], u),
                    "%s %s%s (S1.E1) against card limit %s; context steady (S2.E1)" % (c["word"], p1["last"], u, lim), obs, chk, [c["dom"]], [], ev_of(obs), round(R.uniform(0.78, 0.9), 2), cl,
                    "Reading at the next re-check", {"normal": "Inside the card limit: keep watching.", "warning": "Past the warning limit; check it.", "critical": "Past the critical limit; act now."}[var])
            sevf = var
        return XX(sensors=[s1, s2], report=r, root_metric=c["metric"], rtype="pair_relation", hops=1, think=None, fam="gen5dom_%s:%s" % (name, var), outdoor=None,
                  ctx=("%s: %s" % (c["word"], nd["place"]), st if st != sevf else R.choice(ADJ[sevf]), r["title"], sevf))
    return f


N = int(sys.argv[1]); OUT = sys.argv[2]
X.install_r4(); BI.install_big()
FN = {"gen5dom_" + k: f_dom(k) for k in ("ph", "tank", "pf", "wtemp", "wrh")}
for k, f in FN.items():
    M.FAMS.append((k, f, 0.0)); M.RT_OF[k] = "pair_relation"
R = random.Random(52112)
bu, be, bq, seen, qseen = BB.bans_and_seen()
st = collections.Counter()
sink = B.Sink(OUT)
NAMES = list(FN) + ["big_co2", "big_temp", "big_co2", "big_temp"]


def mk():
    i = mk.i
    mk.i += 1
    r = B.run_inc(R, "r4", "train", st, fam_w=X.weights({NAMES[(i // 4) % len(NAMES)]: 1}), agt_p=0.75)
    if r is None:
        return None
    r.update(src_real=False, gen5="domain", block="gen5_domain")
    r["family"] = "gen5_domain:" + r["family"]
    return r


mk.i = 0
B.gen_block("gen5_dom", N, R, mk, sink, st, (bu, be), seen)
sink.close()
print(sink.n, dict(st))
print(collections.Counter(json.loads(l)["family"].split(":", 1)[1] for l in open(OUT)).most_common(40))
