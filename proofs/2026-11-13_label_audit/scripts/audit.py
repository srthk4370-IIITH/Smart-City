"""Label audit of real_agent incident rows: is the gold severity/label visible in the prompt's evidence lines?
Thresholds are data-driven: per (role, metric) percentiles of the same features on gold-normal rows of the real pool.
Output: ../audit.jsonl, ../summary.json, ../exclusions.jsonl, ../thresholds.json. Deterministic, CPU only."""
import json, re, collections

P = '/mnt/c/Users/hp/Desktop/qidk/proofs/'
OUT = P + '2026-11-13_label_audit/'
NUM = r'([-+]?\d+(?:\.\d+)?)'
SAT = {'pm25': 1000, 'pm10': 1000, 'co2': 5000, 'temp': 60, 'rh': 100, 'room_temp': 45}
NONZERO = {'pm25', 'pm10', 'co2', 'temp', 'rh', 'room_temp', 'pf', 'tds', 'ph'}
ORD = ['normal', 'warning', 'critical']
import sys
sys.path.insert(0, P + '2026-11-13_v3_data/core')
import cards as _cards  # v3 card truth: impossible bounds + max 5-min step
_C = _cards.existing_cards()
CARD_OF = {('air_quality', 'co2'): 'co2_indoor', ('air_quality', 'pm25'): 'pm25_indoor', ('air_quality', 'pm10'): 'pm10_indoor',
           ('air_quality', 'temp'): 'temp_indoor', ('air_quality', 'rh'): 'rh_indoor', ('water', 'level'): 'tank_level',
           ('water', 'flow'): 'water_flow', ('water', 'tds'): 'water_tds', ('water', 'ph'): 'water_ph', ('power', 'power_kw'): 'power_load',
           ('power', 'pf'): 'power_pf', ('weather', 'temp'): 'weather_temp', ('weather', 'rh'): 'weather_rh', ('weather', 'wind'): 'weather_wind',
           ('hvac', 'room_temp'): 'hvac_unit'}


def card(role, metric):
    return _C.get(CARD_OF.get((role, metric), ''), {})


def impossible(role, metric, v):
    b = card(role, metric).get('impossible') or {}
    return v is not None and ((b.get('below') is not None and v < b['below']) or (b.get('above') is not None and v > b['above']))


def f(x):
    return float(x)


def feats_cont(E, n):
    F = {}
    m = re.search(r'last = ' + NUM, E.get('E1', '')); F['last'] = f(m.group(1)) if m else None
    m = re.search(r'max = ' + NUM, E.get('E2', '')); F['max'] = f(m.group(1)) if m else None
    m = re.search(r'min = ' + NUM, E.get('E3', '')); F['min'] = f(m.group(1)) if m else None
    m = re.search(r'trend = ' + NUM + r'.*\(r2 ' + NUM, E.get('E4', ''))
    F['trend'] = abs(f(m.group(1))) if m else 0; F['r2'] = f(m.group(2)) if m else 0
    m = re.search(r'change = ' + NUM, E.get('E5', '')); F['e5'] = abs(f(m.group(1))) if m else 0
    m = re.search(r'mean [\d.]+h = ' + NUM, E.get('E6', '')); F['mean'] = f(m.group(1)) if m else None
    m = re.search(r'crossings (\d+)', E.get('E7', '')); F['cross'] = int(m.group(1)) if m else 0
    m = re.search(r'noise ' + NUM + r', longest flat run (\d+) pts, plateau at max (\d+)', E.get('E8', ''))
    F['noise'], F['flat'], F['plat'] = (f(m.group(1)), int(m.group(2)), int(m.group(3))) if m else (0, 0, 0)
    e9 = E.get('E9', ''); m = re.search(r'(?:r2 [\d.]+, )?' + NUM + r'x normal', e9)
    F['e9x'] = f(m.group(1)) if m else 0
    F['e9kind'] = 'shift' if ('level shift' in e9 and m) else ('drift' if ('drift' in e9 and m) else '')
    m = re.search(r'(\d+) excursions? .*largest ' + NUM + 'x', E.get('E10', ''))
    F['e10n'], F['e10x'] = (int(m.group(1)), f(m.group(2))) if m else (0, 0)
    scale = max(abs(F['mean'] or 0), abs(F['max'] or 0) * 0.5, 1e-3)
    F['noise_rel'] = F['noise'] / scale; F['e5_rel'] = F['e5'] / scale
    F['flat_frac'] = F['flat'] / max(n, 1); F['plat_frac'] = F['plat'] / max(n, 1)
    F['trend_rel'] = F['trend'] * F['r2'] / scale
    return F


def feats_hvac(E, n):
    F = {}
    m = re.search(r'room now ' + NUM + r' C, setpoint ' + NUM + r' C \(band ' + NUM + '-' + NUM, E.get('E1', ''))
    F['last'], F['sp'], F['blo'], F['bhi'] = (f(m.group(1)), f(m.group(2)), f(m.group(3)), f(m.group(4))) if m else (None,) * 4
    m = re.search(r'max ' + NUM + r' C.*min ' + NUM + ' C', E.get('E2', ''))
    F['max'], F['min'] = (f(m.group(1)), f(m.group(2))) if m else (None, None)
    m = re.search(r'(above|below) band for last (\d+) min', E.get('E3', ''))
    F['outband'] = int(m.group(2)) if m else 0; F['outdir'] = m.group(1) if m else ''
    m = re.search(r'AC on (\d+)/(\d+) samples.*starts (\d+)', E.get('E5', ''))
    F['acon'], F['acn'], F['starts'] = (int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else (0, 1, 0)
    e7 = E.get('E7', ''); m = re.search(r'temp flat (\d+) min max, largest 5-min step ' + NUM, e7)
    F['flatmin'], F['e5'] = (int(m.group(1)), abs(f(m.group(2)))) if m else (0, 0)
    F['whole'] = 'whole-degree' in e7; F['flat_frac'] = F['flatmin'] / 5 / max(n, 1)
    e8 = E.get('E8', ''); m = re.search(r'usually on (\d+)%', e8); F['usual'] = int(m.group(1)) if m else 0
    m = re.search(r'missing (\d+)/(\d+)', e8); F['miss_frac'] = int(m.group(1)) / max(int(m.group(2)), 1) if m else 0
    F['alarm'] = bool(e8) and 'alarm none' not in e8
    F['vacant'] = 'vacant' in e8
    e9 = E.get('E9', ''); m = re.search(r'(?:r2 [\d.]+, )?' + NUM + r'x normal', e9); F['e9x'] = f(m.group(1)) if m else 0
    F['e9kind'] = 'shift' if 'level shift' in e9 else ('drift' if 'drift' in e9 else '')
    m = re.search(r'(\d+) excursions? .*largest ' + NUM + 'x', E.get('E10', ''))
    F['e10n'], F['e10x'] = (int(m.group(1)), f(m.group(2))) if m else (0, 0)
    m = re.search(r'last hour ' + NUM, E.get('E4', '')); F['lasth'] = abs(f(m.group(1))) if m else 0
    return F


def feats_occ(E, n):
    F = {}
    m = re.search(r'state changes = (\d+)', E.get('E3', '')); F['changes'] = int(m.group(1)) if m else 0
    m = re.search(r'fraction = ' + NUM, E.get('E2', '')); F['frac'] = f(m.group(1)) if m else 0
    m = re.search(r'(\d+) occupied periods.*longest ' + NUM, E.get('E10', ''))
    F['periods'], F['longest'] = (int(m.group(1)), f(m.group(2))) if m else (0, 0)
    F['offh'] = 'off-hours' in E.get('E6', ''); F['chg_rate'] = F['changes'] / max(n, 1)
    return F


FEATS = {'continuous': ['noise_rel', 'noise', 'e5_rel', 'flat_frac', 'plat_frac', 'e9x', 'e10x', 'trend_rel'],
         'hvac': ['flat_frac', 'e5', 'miss_frac', 'e9x', 'e10x', 'lasth'], 'occupancy': ['chg_rate', 'changes', 'periods']}
LOWF = {'continuous': ['noise_rel']}


def kind_of(role):
    return 'hvac' if role == 'hvac' else ('occupancy' if role == 'occupancy' else 'continuous')


def feats(role, E, n):
    return {'hvac': feats_hvac, 'occupancy': feats_occ, 'continuous': feats_cont}[kind_of(role)](E, n)


def pct(xs, q):
    xs = sorted(xs)
    if not xs:
        return None
    return xs[min(len(xs) - 1, max(0, int(round(q * (len(xs) - 1)))))]


def build_thresholds(pool):
    by = collections.defaultdict(list)
    for r in pool:
        if r['gold']['status'] != 'normal':
            continue
        by[(r['role'], r['metric'])].append(feats(r['role'], dict(r['ev']), r['n']))
    T = {}
    for k, rows in by.items():
        kk = kind_of(k[0]); t = {}
        for fn in FEATS[kk]:
            v = [x[fn] for x in rows if x.get(fn) is not None]
            t[fn] = (pct(v, 0.975), pct(v, 0.99))
        for fn in LOWF.get(kk, []):
            t[fn + '_lo'] = pct([x[fn] for x in rows if x.get(fn) is not None], 0.025)
        t['n'] = len(rows); T['%s|%s' % k] = t
    return T


def limits_of(head):
    L = {}
    for h in head:
        for d, w in (('above', 'hi'), ('below', 'lo')):
            m = re.search(r'warning %s ' % d + NUM, h); mc = re.search(r'critical %s ' % d + NUM, h)
            if m or mc:
                L[w] = (f(m.group(1)) if m else None, f(mc.group(1)) if mc else None)
        m = re.search(r'high level above ' + NUM + r', overflow risk above ' + NUM, h)
        if m:
            L['tank'] = (f(m.group(1)), f(m.group(2)))
    return L


def fault_signs(role, metric, F, T):
    S = []
    k = kind_of(role)
    t = T.get('%s|%s' % (role, metric), {})
    if k == 'continuous':
        mx, mn = F['max'], F['min']
        if metric in SAT and mx is not None and mx >= SAT[metric] and F['plat'] >= 2:
            S.append(('saturation_at_%g' % SAT[metric], 'abs'))
        if metric in NONZERO and mn is not None and mn == 0:
            S.append(('reading_drops_to_0', 'abs'))
        if impossible(role, metric, mn) or impossible(role, metric, mx):
            S.append(('impossible_value_card', 'abs'))
        ms = card(role, metric).get('max_step')
        if ms and F['e5'] > ms:
            S.append(('5min_step_%g_above_card_max_step_%g' % (F['e5'], ms), 'abs'))
        if mn == 0 and metric in NONZERO | {'level'} and mx and F['e5'] >= 0.8 * mx:
            S.append(('zero_glitch_and_back', 'abs'))
        if F['e9x'] >= 4:
            S.append(('e9_%s_%gx' % (F['e9kind'], F['e9x']), 'p975'))
        if F['noise'] == 0 and F['flat'] >= 6:
            S.append(('zero_noise_flat', 'abs'))
        if F['e10x'] >= 8:
            S.append(('excursion_%gx' % F['e10x'], 'abs'))
        if F['e9x'] >= 8:
            S.append(('e9_%s_%gx' % (F['e9kind'], F['e9x']), 'abs'))
    elif k == 'hvac':
        if F['max'] is not None and F['max'] >= 45:
            S.append(('saturation_45C', 'abs'))
        if F['min'] is not None and F['min'] <= 0:
            S.append(('reading_drops_to_0', 'abs'))
        if F['whole']:
            S.append(('whole_degree_quantised', 'abs'))
        if F['miss_frac'] >= 0.25:
            S.append(('missing_%d%%' % (F['miss_frac'] * 100), 'abs'))
        if F['e10x'] >= 8:
            S.append(('excursion_%gx' % F['e10x'], 'abs'))
        if F['e9x'] >= 8:
            S.append(('e9_%s_%gx' % (F['e9kind'], F['e9x']), 'abs'))
        elif F['e9x'] >= 4:
            S.append(('e9_%s_%gx' % (F['e9kind'], F['e9x']), 'p975'))
        if F['e5'] > 2.0:
            S.append(('5min_step_%g_above_card_max_step_2' % F['e5'], 'abs'))
        if F['outdir'] == 'below' and F['outband'] >= 30 and F['acon'] == 0:
            S.append(('below_band_with_AC_off_%dmin' % F['outband'], 'abs'))
    for fn in FEATS[k]:
        if fn not in t or t[fn][0] is None or F.get(fn) is None:
            continue
        p975, p99 = t[fn]
        if F[fn] > p99 and F[fn] > 0:
            S.append((fn + '>p99(%.3g>%.3g)' % (F[fn], p99), 'p99'))
        elif F[fn] > p975 and F[fn] > 0:
            S.append((fn + '>p97.5(%.3g>%.3g)' % (F[fn], p975), 'p975'))
    for fn in LOWF.get(k, []):
        lo = t.get(fn + '_lo')
        if lo is not None and F.get(fn) is not None and F[fn] < lo * 0.5:
            S.append((fn + '<0.5*p2.5', 'p975'))
    return S


KIND_FEATS = {'stuck': ('flat', 'plat', 'zero_noise', 'noise_rel<', 'saturation'),
              'quantised': ('flat', 'plat', 'whole', 'quant'),
              'noise': ('noise', 'e5', 'excursion', 'e10', 'drops_to_0', 'chg', 'changes', 'periods', 'lasth', '5min_step', 'zero_glitch'),
              'dropout': ('drops_to_0', 'missing', 'e5', 'excursion', 'e10', 'noise', '5min_step', 'zero_glitch'),
              'bias': ('e9', 'e5', 'impossible', 'drops_to_0', '5min_step', 'below_band'),
              'drift': ('e9', 'trend', 'impossible', 'flat', 'below_band'),
              'saturation': ('saturation', 'plat', 'e9', 'flat')}


def judge(role, metric, gold_sev, fk, F, head, n, T, quality, ctx):
    S = fault_signs(role, metric, F, T)
    strong = [s for s, st in S if st in ('abs', 'p99')]
    anyS = [s for s, st in S]
    L = limits_of(head)
    k = kind_of(role)
    if gold_sev == 'sensor_fault':
        if quality and quality not in ('good',):
            return 'y', 'quality line says %s' % quality, anyS
        rel = [s for s in anyS if any(p in s for p in KIND_FEATS.get(fk or '', ()))]
        if rel:
            return 'y', '%s visible: %s' % (fk, '; '.join(rel[:3])), anyS
        if strong:
            return 'y', 'a fault is visible (other signature than %s): %s' % (fk, '; '.join(strong[:3])), anyS
        return 'n', 'no %s signature in the evidence lines (every feature inside the normal range of %s %s)' % (fk, role, metric), anyS
    if gold_sev in ('warning', 'critical'):
        if k == 'continuous':
            if 'hi' in L or 'lo' in L:
                w, c = L.get('hi', (None, None)); wl, cl = L.get('lo', (None, None))
                mx, mn = F['max'], F['min']
                lvl = 'normal'
                if mx is not None and w is not None and mx > w: lvl = 'warning'
                if mn is not None and wl is not None and mn < wl: lvl = 'warning'
                if mx is not None and c is not None and mx > c: lvl = 'critical'
                if mn is not None and cl is not None and mn < cl: lvl = 'critical'
                if lvl == 'normal':
                    return 'n', 'no value beyond the warning limit (max %s, min %s; %s)' % (mx, mn, ' '.join(head)), anyS
                if gold_sev == 'critical' and lvl == 'warning':
                    return 'n', 'evidence reaches warning only (max %s, min %s); gold critical' % (mx, mn), anyS
                return 'y', ('E2/E3 beyond the %s limit' % lvl) if lvl == gold_sev else 'beyond the critical limit; gold warning (under-graded but alert supported)', anyS
            if 'tank' in L and F['max'] is not None and F['max'] > L['tank'][0]:
                return 'y', 'tank level above high %g' % L['tank'][0], anyS
            mx, mn, mean = F['max'] or 0, F['min'] or 0, F['mean'] or 0
            rel = (mx - mn) / max(abs(mean), 1e-3)
            if rel >= 0.35 or F['e9x'] >= 4 or F['e10x'] >= 5 or F['plat_frac'] >= 0.2 or F['trend_rel'] >= 0.1:
                return 'y', 'rate-rule metric; change visible (range/mean %.2f, E9 %gx, E10 %d)' % (rel, F['e9x'], F['e10n']), anyS
            return 'n', 'rate-rule metric with no visible change (range/mean %.2f)' % rel, anyS
        if k == 'hvac':
            if F['max'] is not None and F['max'] > (34 if gold_sev == 'critical' else 30):
                return 'y', 'room temp beyond the %s limit' % gold_sev, anyS
            if F['outband'] >= 30 or F['starts'] >= 4 or (F['usual'] >= 50 and F['acon'] == 0) or (F['acon'] >= F['acn'] * 0.8 and F['outdir'] == 'above') or F['alarm'] or (F['acon'] >= F['acn'] * 0.8 and (F['usual'] <= 35 or F['vacant'])):
                return 'y', 'HVAC evidence: out of band %d min, starts %d, AC on %d/%d (usually %d%%)' % (F['outband'], F['starts'], F['acon'], F['acn'], F['usual']), anyS
            return 'n', 'HVAC: in band, no cycling or AC anomaly visible', anyS
        if F.get('offh') or ctx.get('offday'):
            return 'y', 'presence off-hours / non-workday', anyS
        return ('y', 'presence pattern visible', anyS) if F.get('chg_rate', 0) > 0 else ('n', 'no presence visible', anyS)
    if gold_sev == 'normal':
        if k == 'continuous' and impossible(role, metric, F['last']):
            return 'n', 'gold normal but the current value %s is physically impossible on the v3 card' % F['last'], anyS
        if k == 'continuous' and 'hi' in L and L['hi'][1] is not None and F['last'] is not None and F['last'] > L['hi'][1]:
            return 'n', 'last value %s above the critical limit %s, gold normal' % (F['last'], L['hi'][1]), anyS
        bad = [s for s in strong if s.startswith(('saturation', 'whole', 'missing'))]
        if bad:
            return 'n', 'gold normal but a fault signature is visible: %s' % '; '.join(bad), anyS
        return 'y', 'no limit crossed and no persistent fault signature', anyS
    return 'y', 'n/a', anyS


def parse_prompt(u):
    lines = u.split('\n')
    s1 = []; inS1 = False
    for ln in lines:
        if ln.startswith('S1 ['):
            inS1 = True; s1.append(ln); continue
        if inS1 and re.match(r'(S\d+ \[|[A-Z][A-Z -]+:)', ln):
            break
        if inS1:
            s1.append(ln)
    hdr = s1[0] if s1 else ''
    m = re.match(r'S1 \[[^\]]*\]: (\S+) (\S+) .*\((\w+)\)\s*$', hdr)
    node, metric, role = (m.group(1), m.group(2), m.group(3)) if m else (None, None, None)
    E = {}; head = []; quality = None
    for ln in s1[1:]:
        t = ln.strip()
        mm = re.match(r'S1\.(E\d+) (.*)', t)
        if mm:
            E[mm.group(1)] = mm.group(2); continue
        if t.startswith(('LIMITS:', 'TANK:')):
            head.append(t)
        mq = re.match(r'quality=(\S+)', t)
        if mq:
            quality = mq.group(1).rstrip(',;')
    mh = re.search(r'windows ([\d.]+) h of 5-min', u); n = int(round(float(mh.group(1)) * 12)) if mh else 48
    ctx = {'offday': bool(re.search(r'\| (weekend|holiday)', lines[0]))}
    return node, metric, role, E, head, quality, n, ctx


def gold_of(a):
    i = a.find('{')
    return json.JSONDecoder().raw_decode(a[i:])[0]


FILES = {'r3_train': '2026-11-06_4b_local/data/final/incidents_train.jsonl',
         'test_r2': '2026-11-06_4b_local/data/final/incidents_test_r2.jsonl',
         'dev_r3': '2026-11-06_4b_local/data/final/dev_r3.jsonl',
         'dev60': '2026-11-06_4b_local/data/final/incidents_dev60.jsonl',
         'rwh': '2026-10-25_reasoner_final/data/incidents_rwh.jsonl',
         'rwh2': '2026-10-29_rsn_v3/kaggle/build/r1/heldout/incidents_rwh2.jsonl',
         'dev': '2026-10-25_reasoner_final/data/incidents_dev.jsonl',
         'r1_train': '2026-10-25_reasoner_final/data/incidents_train.jsonl',
         'r4_replay': '2026-11-12_topup_r4/data/final/replay.jsonl'}


def main():
    pool = [json.loads(l) for l in open(P + '2026-10-25_reasoner_final/data/real_pool.jsonl')]
    T = build_thresholds(pool)
    json.dump(T, open(OUT + 'thresholds.json', 'w'), indent=0)
    pidx = {}
    for r in pool:
        E = dict(r['ev']); pidx[(r['node'], r['metric'], E.get('E1'), E.get('E2'), E.get('E8'))] = r
    ctrl = collections.Counter(); pool_out = open(OUT + 'pool_audit.jsonl', 'w')
    for r in pool:
        g = r['gold']; Fx = feats(r['role'], dict(r['ev']), r['n'])
        s, why, sg = judge(r['role'], r['metric'], g['status'], g.get('fault_kind'), Fx,
                           [h for h in r['head'] if h.startswith(('LIMITS', 'TANK'))], r['n'], T, None, {})
        ctrl[(g['status'], s)] += 1
        pool_out.write(json.dumps({'pool_id': r['id'], 'model': r['model'], 'role': r['role'], 'metric': r['metric'], 'gold': g['status'],
                                   'fault_kind': g.get('fault_kind'), 'sub': r['sub'], 'pred_status': (r['pred'] or {}).get('status'),
                                   'supported': s, 'reason': why, 'signatures': sg[:6]}) + '\n')
    out = open(OUT + 'audit.jsonl', 'w'); excl = open(OUT + 'exclusions.jsonl', 'w'); summ = {}
    for name, fn in FILES.items():
        c = collections.Counter(); byk = collections.Counter()
        for l in open(P + fn, encoding='utf-8'):
            if '"real_agent' not in l:
                continue
            r = json.loads(l)
            if not str(r.get('family', '')).startswith('real_agent'):
                continue
            u = next(m['content'] for m in r['messages'] if m['role'] == 'user')
            gold = gold_of(r['messages'][-1]['content']); sev = gold.get('severity')
            node, metric, role, E, head, quality, n, ctx = parse_prompt(u)
            pr = pidx.get((node, metric, E.get('E1'), E.get('E2'), E.get('E8')))
            fk = pr['gold'].get('fault_kind') if pr else None
            if fk is None and sev == 'sensor_fault':
                mm = re.search(r'for this sensor \((\w+)\)', gold.get('root_cause', '')); fk = mm.group(1) if mm else None
            s, why, signs = judge(role, metric, sev, fk, feats(role, E, n), head, n, T, quality, ctx)
            ag = re.search(r'agent: pattern=(\S+) status=(\S+) cause=(\S+)', u)
            rec = {'id': r['id'], 'file': name, 'family': r['family'], 'role': role, 'metric': metric, 'node': node,
                   'gold': sev, 'label': gold.get('label'), 'fault_kind': fk, 'agent_status': ag.group(2) if ag else None,
                   'supported': s, 'reason': why, 'signatures': signs[:6], 'pool_id': pr['id'] if pr else None}
            out.write(json.dumps(rec) + '\n')
            c[(sev, s)] += 1; byk[(role, sev, fk, s)] += 1
            if s == 'n':
                if sev == 'sensor_fault' and rec['agent_status'] == 'normal':
                    act, new = 'relabel', 'normal'      # the agent was right; the evidence shows no fault
                elif sev == 'normal' and 'impossible' in why:
                    act, new = 'drop_r3_replay__relabel_v4', 'sensor_fault'  # v3 card: impossible current value = data fault
                else:
                    act, new = 'drop', None             # gold not visible; agent claim cannot be judged from the prompt
                excl.write(json.dumps({'id': r['id'], 'file': name, 'pool_id': rec['pool_id'], 'gold': sev, 'action': act,
                                       'new_gold': new, 'reason': why}) + '\n')
        summ[name] = {'by_gold': {'%s|%s' % k: v for k, v in sorted(c.items(), key=str)},
                      'by_role_kind': {'|'.join(map(str, k)): v for k, v in sorted(byk.items(), key=str)}}
    summ['pool_control'] = {'%s|%s' % k: v for k, v in sorted(ctrl.items())}
    json.dump(summ, open(OUT + 'summary.json', 'w'), indent=1)
    for k, v in summ.items():
        print(k, v.get('by_gold', v))


if __name__ == '__main__':
    main()
