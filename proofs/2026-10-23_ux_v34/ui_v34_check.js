// UX v34 check (Node 24, no deps): seeds the approval lifecycle on a host --mock backend through the
// real API, then drives headless Chrome over CDP and asserts the new UI at 412x915, 360x780 + 130 %
// text (WebView textZoom emulation) and 1440x900. Saves screenshots and a JSON report.
// Usage: node ui_v34_check.js [base=http://127.0.0.1:18000] [outDir=./]
//   SEED=0 skips seeding (a backend that was already seeded).
const fs = require('fs'), path = require('path'), { spawn } = require('child_process');
const BASE = process.argv[2] || 'http://127.0.0.1:18000';
const OUT = process.argv[3] || __dirname;
const SHOTS = path.join(OUT, 'screens');
fs.mkdirSync(SHOTS, { recursive: true });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const results = []; let fails = 0;
const ok = (cond, name, detail) => { results.push({ ok: !!cond, name, detail: detail === undefined ? '' : String(detail).slice(0, 300) }); if (!cond) { fails++; console.log('FAIL', name, detail || ''); } else console.log('ok  ', name); };

const api = async (p, body) => {
  const r = await fetch(BASE + p, body ? { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) } : {});
  const t = await r.text(); let j = null; try { j = JSON.parse(t); } catch (e) { /* text */ }
  return { code: r.status, j, t };
};
const list = async () => (await api('/api/incidents')).j || [];
async function idle(min, ms = 240000) {
  for (const t0 = Date.now(); Date.now() - t0 < ms; await sleep(2000)) {
    const l = await list();
    if (l.length >= min && !l.some((i) => i.state === 'running')) return l;
  }
  throw new Error('backend did not settle');
}

async function seed() {
  const log = [];
  const say = (m) => { log.push(m); console.log('seed:', m); };
  const full = async (id) => (await api('/api/incidents/' + id)).j;
  const hasFault = (inc) => (inc.sensors || []).some((x) => !x.context && x.rule_finding && x.rule_finding.status === 'sensor_fault');
  // 1. a stuck sensor alone first, so its fault incident is its own (repair memory below)
  say('inject stuck_sensor ' + (await api('/api/inject', { scenario: 'stuck_sensor' })).code);
  let fault = null;
  for (const t0 = Date.now(); Date.now() - t0 < 90000 && !fault; await sleep(2000)) {
    for (const i of (await list()).filter((x) => x.state !== 'running')) { const f = await full(i.id); if (hasFault(f)) { fault = i; break; } }
  }
  say('fault incident ' + (fault && fault.id));
  // 2. the other scenarios
  for (const sc of ['tank_leak', 'power_throttling', 'ventilation_failure']) {
    say('inject ' + sc + ' ' + (await api('/api/inject', { scenario: sc })).code);
    await sleep(1500);
  }
  let l = await idle(3);
  const lead = l.find((i) => !fault || i.id !== fault.id);
  say('rerun ' + lead.id + ' mode 1 -> ' + (await api('/api/incidents/' + lead.id + '/rerun?mode=1', {})).code);
  l = await idle(l.length + 1);
  // one more by hand (Ask the AI to check this sensor) so there is always a fourth to dismiss
  const live0 = (await api('/api/live')).j;
  const wx = (live0.roles.weather || live0.roles.power).sensors[0];
  say('analyze ' + wx.node + ' ' + wx.metric + ' ' + (await api('/api/analyze', { node: wx.node, metric: wx.metric })).code);
  l = await idle(l.length + 1);
  const others = l.filter((i) => i.state !== 'running' && i.state !== 'failed' && (!fault || i.id !== fault.id));
  // A: the most severe one stays abnormal longest (Ravi is on it)
  const rank = { critical: 3, warning: 2, sensor_fault: 1 };
  others.sort((x, y) => (rank[y.severity] || 0) - (rank[x.severity] || 0));
  const D = others.find((i) => i.severity === 'normal' || i.severity === 'info') || others[3];
  const rest = others.filter((i) => i !== D);
  const [A, B, C] = rest;
  if (A) { say('ack A ' + A.id + ' ' + (await api('/api/incidents/' + A.id + '/ack', { operator: 'Ravi' })).code);
    say('step A ' + (await api('/api/incidents/' + A.id + '/steps/s1', { operator: 'Ravi', state: 'done', note: 'valve checked' })).code);
    say('own step A ' + (await api('/api/incidents/' + A.id + '/steps', { operator: 'Ravi', text: 'Tell the hostel warden' })).code); }
  if (C) { say('ack C ' + (await api('/api/incidents/' + C.id + '/ack', { operator: 'Asha' })).code);
    say('close C ' + (await api('/api/incidents/' + C.id + '/close', { operator: 'Asha', outcome: 'fixed_by_action', note: 'load shed' })).code); }
  if (D) say('dismiss D ' + (await api('/api/incidents/' + D.id + '/dismiss', { operator: 'Meena', outcome: 'false_alarm', note: 'test of the pump schedule' })).code);
  // 3. the repair memory: recalibrated and closed as repaired, then the fault comes back (rerun)
  let recur = null;
  if (fault) {
    say('fault ack ' + (await api('/api/incidents/' + fault.id + '/ack', { operator: 'Asha' })).code);
    say('fault step ' + (await api('/api/incidents/' + fault.id + '/steps/s1', { operator: 'Asha', state: 'done', note: 'recalibrated' })).code + ' (404 = the AI judged it fine, no step)');
    say('fault close ' + (await api('/api/incidents/' + fault.id + '/close', { operator: 'Asha', outcome: 'sensor_repaired', note: 'recalibrated on site' })).code);
    const before = new Set((await list()).map((i) => i.id));
    say('fault rerun ' + (await api('/api/incidents/' + fault.id + '/rerun?mode=1', {})).code);
    await idle(before.size + 1);
    recur = (await list()).find((i) => !before.has(i.id));
    recur = recur && recur.id;
  }
  // 4. maintenance: one air sensor out of service for 2 h
  const live = (await api('/api/live')).j;
  const aq = live.roles.air_quality.sensors.find((x) => x.metric === 'pm25') || live.roles.air_quality.sensors[0];
  say('maintenance ' + aq.node + ' ' + aq.metric + ' ' + (await api('/api/maintenance', { node: aq.node, metric: aq.metric, minutes: 120, reason: 'calibration', operator: 'Ravi' })).code);
  // 5. a fresh incident whose re-checks are still ahead: slow polls so the countdown stays visible
  say('poll 10 s ' + (await api('/api/replay', { poll_ms: 10000 })).code);
  const n0 = (await list()).length;
  const pw = live.roles.power.sensors[0];
  say('analyze ' + pw.node + ' ' + pw.metric + ' (re-checks still ahead) ' + (await api('/api/analyze', { node: pw.node, metric: pw.metric })).code);
  await idle(n0 + 1, 300000);
  return { log, A: A && A.id, B: B && B.id, C: C && C.id, D: D && D.id, fault: fault && fault.id, recur, oos: aq.node + ' ' + aq.metric };
}

const ZOOM = (z) => `(() => { if (document.getElementById('ovf-zoom')) return 1; const out = [];
  const visit = (rules, wrap) => { for (const r of rules) {
    if (r.cssRules && r.media) { visit(r.cssRules, (s) => '@media ' + r.media.mediaText + '{' + s + '}'); continue; }
    if (r.cssRules && !r.style) { visit(r.cssRules, wrap); continue; }
    if (!r.style) continue; const fsz = r.style.getPropertyValue('font-size');
    const m = /^([\\d.]+)px$/.exec(fsz.trim()); if (!m) continue;
    const imp = r.style.getPropertyPriority('font-size') ? ' !important' : '';
    out.push(wrap(r.selectorText + '{font-size:' + (+m[1] * ${z}).toFixed(2) + 'px' + imp + '}')); } };
  for (const sh of document.styleSheets) { try { visit(sh.cssRules, (s) => s); } catch (e) {} }
  const st = document.createElement('style'); st.id = 'ovf-zoom'; st.textContent = out.join('\\n'); document.head.appendChild(st); return out.length; })()`;

(async () => {
  const seeded = process.env.SEED === '0' ? JSON.parse(fs.readFileSync(path.join(OUT, 'seed.json'), 'utf8')) : await seed();
  fs.writeFileSync(path.join(OUT, 'seed.json'), JSON.stringify(seeded, null, 1));
  // backend-level checks on the seeded data
  const l = await list();
  const byId = Object.fromEntries(l.map((i) => [i.id, i]));
  ok(seeded.A && ['in_progress', 'resolved'].includes(byId[seeded.A].workflow) && byId[seeded.A].owner === 'Ravi', 'API: acknowledged incident is in progress (or back to normal), owner Ravi', JSON.stringify(byId[seeded.A] || {}).slice(0, 200));
  ok(seeded.C && byId[seeded.C].outcome === 'fixed_by_action' && byId[seeded.C].workflow === 'closed', 'API: closed with an outcome');
  ok(seeded.D && byId[seeded.D].outcome === 'false_alarm' && byId[seeded.D].approval === 'dismissed', 'API: dismiss = closed as false alarm, approval dismissed (old field kept)');
  ok(l.some((i) => i.group_size > 1), 'API: a repeat incident is grouped (group_size > 1)', l.map((i) => i.id + ':' + i.group + '/' + i.group_size).join(' '));
  if (seeded.fault) {
    const nf = seeded.recur && byId[seeded.recur];
    const full = nf && (await api('/api/incidents/' + nf.id)).j;
    ok(full && (full.steps || []).some((s) => s.action === 'replace_sensor'), 'API: fault after a repair gets "Replace the sensor" (30-day rule)', full ? JSON.stringify(full.steps).slice(0, 300) : 'no recurrence incident');
    const hist = nf && (await api('/api/incidents/' + nf.id + '/history')).j;
    ok(hist && hist.sensors[0].incidents.some((x) => x.id === seeded.fault && x.outcome === 'sensor_repaired'), 'API: History of this sensor lists the repair');
  }
  const ev = (await api('/api/incidents/' + seeded.A + '/events')).j;
  ok(ev && ev.events.map((e) => e.event).join(',').includes('ack,step_done,step_added'), 'API: event log ack, step_done, step_added', ev && ev.events.map((e) => e.actor + ':' + e.event).join(','));

  const CHROME = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe', port = 9351;
  const prof = path.join(process.env.TEMP, 'cdp-v34-' + port);
  const ch = spawn(CHROME, ['--headless=new', '--remote-debugging-port=' + port, '--user-data-dir=' + prof, '--no-first-run', '--hide-scrollbars', '--disable-gpu', 'about:blank'], { stdio: 'ignore' });
  let ws;
  for (let i = 0; i < 50 && !ws; i++) { try { const j = await (await fetch('http://127.0.0.1:' + port + '/json')).json(); const p = j.find((x) => x.type === 'page'); if (p) ws = new WebSocket(p.webSocketDebuggerUrl); } catch (e) {} await sleep(200); }
  if (ws.readyState !== 1) await new Promise((r) => ws.addEventListener('open', r));
  let id = 0; const pend = {}; const errs = [];
  ws.addEventListener('message', (m) => { const d = JSON.parse(m.data); if (d.id && pend[d.id]) { pend[d.id](d); delete pend[d.id]; }
    if (d.method === 'Runtime.exceptionThrown') errs.push(JSON.stringify(d.params.exceptionDetails.exception && d.params.exceptionDetails.exception.description || d.params.exceptionDetails.text).slice(0, 300)); });
  const send = (method, params) => new Promise((r) => { const i = ++id; pend[i] = r; ws.send(JSON.stringify({ id: i, method, params: params || {} })); });
  const ev2 = async (expr) => { const r = await send('Runtime.evaluate', { expression: expr, awaitPromise: true, returnByValue: true }); if (r.result && r.result.exceptionDetails) return { __err: JSON.stringify(r.result.exceptionDetails).slice(0, 300) }; return r.result && r.result.result && r.result.result.value; };
  await send('Page.enable'); await send('Runtime.enable');
  const shot = async (name) => { const p = await send('Page.captureScreenshot', { format: 'png' }); fs.writeFileSync(path.join(SHOTS, name + '.png'), Buffer.from(p.result.data, 'base64')); };
  const CONFIGS = [{ name: '412x915', w: 412, h: 915, mobile: true }, { name: '360x780_z130', w: 360, h: 780, mobile: true, zoom: 1.3 }, { name: '1440x900', w: 1440, h: 900 }];
  let scriptId = null;
  for (const c of CONFIGS) {
    await send('Emulation.setDeviceMetricsOverride', { width: c.w, height: c.h, deviceScaleFactor: 1, mobile: !!c.mobile });
    if (scriptId) await send('Page.removeScriptToEvaluateOnNewDocument', { identifier: scriptId });
    const pre = `try{localStorage.setItem('sce-theme','dark');localStorage.setItem('sce-eng','0');localStorage.setItem('sce-ops',JSON.stringify(['Ravi','Asha','Meena']));` +
      `localStorage.setItem('sce-op',JSON.stringify({name:'Ravi',at:Date.now()}));if(!sessionStorage.getItem('v34seen')){localStorage.setItem('sce-last-visit',String(Date.now()-2*3600e3));sessionStorage.setItem('v34seen','1')}}catch(e){}`;
    scriptId = (await send('Page.addScriptToEvaluateOnNewDocument', { source: pre })).result.identifier;
    await ev2(`(sessionStorage.removeItem('v34seen'),1)`);
    await send('Page.navigate', { url: 'about:blank' }); await sleep(300); // a hash-only navigation would keep the old page
    await send('Page.navigate', { url: BASE + '/#live' }); await sleep(4000);
    if (c.zoom) { await ev2(ZOOM(c.zoom)); await sleep(500); }
    const P = c.name + ' ';
    // shift summary
    const sh = await ev2(`(()=>{const b=document.getElementById('shift');return b&&!b.hidden?b.textContent:''})()`);
    ok(/^Since \d\d:\d\d: \d+ new · \d+ got worse · \d+ resolved/.test(sh || ''), P + 'shift summary on opening', sh);
    // tab labels are not cut (360 px + 130 %: "INCIDEN…")
    const cut = await ev2(`[...document.querySelectorAll('#rail a span:not(.cnt)')].filter(s=>s.scrollWidth>s.clientWidth+1).map(s=>s.textContent)`);
    ok(Array.isArray(cut) && cut.length === 0, P + 'tab labels not truncated', JSON.stringify(cut));
    // operator button
    ok(/Ravi/.test(await ev2(`document.getElementById('op').textContent`) || ''), P + 'operator shown in the header');
    // health tiles: workflow summary + data quality
    const tiles = await ev2(`[...document.querySelectorAll('.dh-tile')].map(t=>t.textContent).join(' | ')`);
    ok(/needs decision|in progress \(Ravi\)|back to normal \(Ravi\)/.test(tiles || ''), P + 'tile shows "N needs decision · N in progress (name)"', (tiles || '').slice(0, 300));
    ok(/Data: .*out of service/i.test(tiles || '') || /out of service/i.test(tiles || ''), P + 'tile shows the out-of-service sensor', '');
    await shot(c.name + '_01_live');
    await ev2(`window.scrollTo(0, (document.getElementById('live-grid')||document.body).offsetTop - 80), 1`); await sleep(600);
    const oos = await ev2(`[...document.querySelectorAll('#live-grid .row')].some(r=>/Out of service/.test(r.textContent))`);
    ok(oos, P + 'live row shows ⊘ Out of service');
    await shot(c.name + '_02_live_rows');
    // incidents list
    await ev2(`location.hash='#incidents',1`); await sleep(1800);
    const cards = await ev2(`[...document.querySelectorAll('#inc-list .icard')].filter(x=>x.offsetParent).map(x=>x.textContent)`);
    ok(cards && cards.some((t) => /(In progress|Resolved) · Ravi/.test(t)), P + 'card shows the owner (In progress · Ravi)');
    ok(cards && cards.some((t) => /Closed · (Fixed by action|False alarm)/.test(t)), P + 'card shows Closed · outcome');
    const rel = await ev2(`(document.querySelector('.irel')||{}).textContent||''`);
    ok(/\d+ related/.test(rel), P + 'grouped card shows "N related"', rel);
    await shot(c.name + '_03_incidents');
    await ev2(`(document.querySelector('.irel')||{click(){}}).click(),1`); await sleep(600);
    ok(await ev2(`!!document.querySelector('.irel-list .icard')`), P + 'related incidents expand');
    await shot(c.name + '_04_group_open');
    await ev2(`(()=>{const q=document.getElementById('inc-q');q.value='ravi';q.dispatchEvent(new Event('input'));return 1})()`); await sleep(500);
    const nq = await ev2(`[...document.querySelectorAll('#inc-list .icard')].filter(x=>x.offsetParent).length`);
    ok(nq >= 1 && nq < (cards || []).length, P + 'text search narrows the list', nq + ' of ' + (cards || []).length);
    await shot(c.name + '_05_search');
    await ev2(`(()=>{const q=document.getElementById('inc-q');q.value='';q.dispatchEvent(new Event('input'));const b=[...document.querySelectorAll('#inc-chips .fchip')].find(x=>x.dataset.k==='closed');b.click();return 1})()`); await sleep(500);
    const closedOnly = await ev2(`[...document.querySelectorAll('#inc-list .icard')].filter(x=>x.offsetParent).every(x=>/Closed/.test(x.textContent))`);
    ok(closedOnly, P + 'state filter "Closed" shows only closed incidents');
    await ev2(`[...document.querySelectorAll('#inc-chips .fchip')].find(x=>x.dataset.k==='all').click(),1`); await sleep(400);
    const eta = await ev2(`[...document.querySelectorAll('#inc-list .eta')].map(e=>e.textContent)`);
    ok(eta && eta.some((t) => /^Next check at (1\.5|3) h · (in ~?\d|in \d|due now)/.test(t)), P + 're-check countdown on an open incident card', JSON.stringify(eta));
    await ev2(`[...document.querySelectorAll('#inc-chips .fchip')].find(x=>x.dataset.k==='all').click(),1`); await sleep(400);
    // incident sheet: in progress (checklist, timeline, history, countdown)
    await ev2(`selectIncidentById=(id)=>{location.hash='#incident/'+id}; selectIncidentById(${JSON.stringify(seeded.A)}),1`); await sleep(2500);
    const det = await ev2(`document.getElementById('inc-detail').textContent`);
    ok(/What to do · \d+ of \d+ ticked/.test(det || ''), P + 'checklist with ticked count', (det || '').slice(0, 200));
    ok(/Done · Ravi/.test(det || ''), P + 'step shows who did it');
    ok(/Activity \(\d+\)/.test(det || ''), P + 'activity timeline');
    ok(/History of this sensor/.test(det || ''), P + 'History of this sensor section');
    const small = await ev2(`[...document.querySelectorAll('#inc-detail .ck-act .btn, #inc-foot .btn, .irel, #inc-detail button.qchip, .ck-add .btn')].filter(b=>b.offsetParent&&b.getBoundingClientRect().height<43.5).map(b=>b.textContent+':'+Math.round(b.getBoundingClientRect().height))`);
    ok(Array.isArray(small) && small.length === 0, P + 'action buttons are at least 44 px tall', JSON.stringify(small));
    const foot = await ev2(`document.getElementById('inc-foot').textContent`);
    ok(/Close…/.test(foot || '') && /Ravi is on it/.test(foot || ''), P + 'footer: owner + Close…', foot);
    await shot(c.name + '_06_incident_in_progress');
    await ev2(`(()=>{const s=document.querySelector('#inc-detail .ck-sec');s&&s.scrollIntoView();return 1})()`); await sleep(400);
    await shot(c.name + '_07_checklist');
    await ev2(`(()=>{const b=[...document.querySelectorAll('#inc-detail .op-sec h3')].find(h=>/Activity/.test(h.textContent));b&&b.scrollIntoView();return 1})()`); await sleep(400);
    await shot(c.name + '_08_activity_history');
    // close form, pre-filled
    await ev2(`[...document.querySelectorAll('#inc-foot .btn')].find(b=>/Close…/.test(b.textContent)).click(),1`); await sleep(500);
    const radios = await ev2(`[...document.querySelectorAll('#inc-foot [role=radio]')].map(r=>r.textContent+'='+r.getAttribute('aria-checked'))`);
    ok(radios && radios.length === 6, P + 'close asks for one of 6 outcomes', JSON.stringify(radios));
    await shot(c.name + '_09_close_form');
    await ev2(`[...document.querySelectorAll('#inc-foot .btn')].find(b=>b.textContent==='Cancel').click(),1`); await sleep(300);
    // needs decision: I'm on it / Dismiss…
    await ev2(`location.hash='#incident/${seeded.B}',1`); await sleep(2500);
    const fb = await ev2(`document.getElementById('inc-foot').textContent`);
    ok(/I'm on it/.test(fb || '') && /Dismiss…/.test(fb || ''), P + 'needs decision: I\'m on it + Dismiss…', fb);
    await shot(c.name + '_10_incident_needs_decision');
    // repair rule incident
    if (seeded.recur) { await ev2(`location.hash='#incident/${seeded.recur}',1`); await sleep(2500);
      ok(/Replace the .* sensor/.test((await ev2(`document.getElementById('inc-detail').textContent`)) || ''), P + 'repair rule step shown'); await shot(c.name + '_11_repair_rule'); }
    await ev2(`document.querySelectorAll('.sheet.open [data-close]').forEach(b=>b.click()),1`); await sleep(400);
    // operator picker
    await ev2(`document.getElementById('op').click(),1`); await sleep(500);
    ok(await ev2(`document.querySelectorAll('#opsheet .op-pick').length===3`), P + 'operator picker lists the device names');
    await shot(c.name + '_12_operator_picker');
    await ev2(`document.querySelector('#opsheet [data-close]').click(),1`); await sleep(300);
    // sensor sheet: out of service + maintenance
    const [n, m] = seeded.oos.split(' ');
    await ev2(`location.hash='#live',1`); await sleep(1200);
    await ev2(`(()=>{const r=[...document.querySelectorAll('#live-grid .row')].find(r=>/Out of service/.test(r.textContent));r&&r.click();return 1})()`); await sleep(2200);
    const dr = await ev2(`document.getElementById('sheet-bd').textContent`);
    ok(/Maintenance/.test(dr || '') && /Out of service until/.test(dr || '') && /Back in service/.test(dr || ''), P + 'sensor sheet: out of service until + Back in service', (dr || '').slice(0, 200));
    await ev2(`(()=>{const s=document.querySelector('.msec');s&&s.scrollIntoView();return 1})()`); await sleep(300);
    await shot(c.name + '_13_sensor_maintenance');
    await ev2(`document.querySelectorAll('.sheet.open [data-close]').forEach(b=>b.click()),1`); await sleep(300);
    const pw = await ev2(`document.documentElement.scrollWidth - document.documentElement.clientWidth`);
    ok(pw <= 1, P + 'no horizontal page scroll', pw);
  }
  ok(errs.length === 0, 'no page errors', errs.join(' | '));
  fs.writeFileSync(path.join(OUT, 'ui_v34_check.json'), JSON.stringify({ base: BASE, when: new Date().toISOString(), seeded, fails, results, page_errors: errs }, null, 1));
  console.log(`ui v34 check: ${results.length - fails}/${results.length} ok`);
  ws.close(); ch.kill(); process.exit(fails ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(2); });
function incNum(id) { return +String(id).slice(4) || 0; }
