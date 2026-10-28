// Drives headless Chrome over CDP (no deps) against the local mock backend and saves screenshots.
import { spawn } from 'node:child_process';
import fs from 'node:fs';
const OUT = process.argv[2];
const BASE = 'http://localhost:8766/';
fs.mkdirSync(OUT, { recursive: true });
const chrome = spawn('C:/Program Files/Google/Chrome/Application/chrome.exe', ['--headless=new', '--remote-debugging-port=9334',
  '--user-data-dir=C:/Users/hp/AppData/Local/Temp/claude/C--Users-hp-Desktop-qidk/125df7ac-c9eb-46de-b63b-ce87f4c7e8ce/scratchpad/chrome_prof2', '--no-first-run', '--disable-gpu', 'about:blank'], { stdio: 'ignore' });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let ws, id = 0; const pend = new Map(); const logs = [];
async function connect() {
  for (let i = 0; i < 40; i++) {
    try { const l = await (await fetch('http://127.0.0.1:9334/json')).json(); const p = l.find((x) => x.type === 'page'); if (p) return p.webSocketDebuggerUrl; } catch (e) { }
    await sleep(250);
  }
  throw new Error('no chrome');
}
const send = (method, params = {}) => new Promise((res, rej) => { const i = ++id; pend.set(i, { res, rej }); ws.send(JSON.stringify({ id: i, method, params })); });
const ev = async (expr) => { const r = await send('Runtime.evaluate', { expression: expr, awaitPromise: true, returnByValue: true }); if (r.exceptionDetails) throw new Error(JSON.stringify(r.exceptionDetails).slice(0, 400)); return r.result.value; };
async function shot(name, h) {
  if (h) await send('Emulation.setDeviceMetricsOverride', { width: 360, height: h, deviceScaleFactor: 2, mobile: true });
  await sleep(500);
  const r = await send('Page.captureScreenshot', { format: 'png' });
  fs.writeFileSync(OUT + '/' + name + '.png', Buffer.from(r.data, 'base64'));
  console.log('saved', name);
}
const hscroll = (what) => ev(`(() => { const d = document.documentElement; const over = [...document.querySelectorAll('#inc-detail *, #fs *, #inc-list *')].filter(e => { const r = e.getBoundingClientRect(); return r.width && r.right > innerWidth + 1 && getComputedStyle(e).position !== 'fixed'; }).slice(0, 5).map(e => e.className + ':' + Math.round(e.getBoundingClientRect().right)); return { what: ${JSON.stringify(what)}, scrollW: d.scrollWidth, innerW: innerWidth, sheetBdScrollW: (document.querySelector('#inc-detail')||{}).scrollWidth, fsScrollW: (document.querySelector('#fs-bd')||{}).scrollWidth, overflowing: over }; })()`);

// Fetch interceptor installed before the app loads: optional per-scenario rewrite of API JSON.
const INTERCEPT = `(() => {
  const of = window.fetch;
  window.__rw = null;
  window.fetch = async (u, o) => {
    const r = await of(u, o);
    if (!window.__rw || typeof u !== 'string' || !u.startsWith('/api/incidents')) return r;
    const j = await r.clone().json().catch(() => null); if (j == null) return r;
    const out = window.__rw(u, j);
    return new Response(JSON.stringify(out), { status: 200, headers: { 'Content-Type': 'application/json' } });
  };
})();`;

const api = async (p, body) => { const r = await fetch('http://localhost:8766' + p, body ? { method: 'POST', body: JSON.stringify(body) } : {}); return r.json(); };
const until = async (what, fn, ms = 150000) => { const t0 = Date.now(); for (;;) { const v = await fn(); if (v) return v; if (Date.now() - t0 > ms) throw new Error('timeout: ' + what); await sleep(500); } };
const W = (hh) => send('Emulation.setDeviceMetricsOverride', { width: 360, height: hh || 780, deviceScaleFactor: 2, mobile: true });

(async () => {
  ws = new WebSocket(await connect());
  await new Promise((r) => ws.addEventListener('open', r));
  ws.addEventListener('message', (m) => { const d = JSON.parse(m.data); if (d.id && pend.has(d.id)) { const p = pend.get(d.id); pend.delete(d.id); d.error ? p.rej(new Error(d.error.message)) : p.res(d.result); } else if (d.method === 'Runtime.exceptionThrown') logs.push('EXC ' + JSON.stringify(d.params.exceptionDetails).slice(0, 300)); else if (d.method === 'Runtime.consoleAPICalled' && d.params.type === 'error') logs.push('ERR ' + JSON.stringify(d.params.args).slice(0, 300)); });
  await send('Page.enable'); await send('Runtime.enable');
  await W();
  await send('Page.addScriptToEvaluateOnNewDocument', { source: INTERCEPT });
  await send('Page.navigate', { url: BASE + '#incidents' }); await sleep(2500);
  const report = [], timeline = [];
  const mark = (m) => { const s = new Date().toISOString().slice(11, 19) + 'Z ' + m; timeline.push(s); console.log(s); };
  let ID = '';
  // the app lives in an IIFE: open an incident the way a person does, by tapping its row
  const openInc = async () => {
    await ev(`(() => { const x = document.querySelector('#isheet.open [data-close=isheet]'); if (x) x.click(); return true; })()`); await sleep(500);
    await ev(`[...document.querySelectorAll('#inc-list .icard')].find(e => e.textContent.includes(${JSON.stringify(ID)})).click(); true`); await sleep(1500);
  };
  const hdr = () => ev(`(() => { const q = (s) => (document.querySelector(s) || {}).textContent || null; const hb = [...document.querySelectorAll('.fold-h')].find(b => /History/.test(b.textContent));
    return { stage: q('#inc-detail .ltitle .stagetag'), next: q('#inc-detail .ltitle .refnext'), sev: q('#inc-detail .ltitle .sevtag'), title: q('#inc-detail .inc-title'), history: hb ? hb.textContent : null }; })()`);

  // drive a fresh incident through the Sensors API (the user is the sensor): PM2.5 to its maximum
  await api('/api/replay', { poll_ms: 1000 });
  const before = new Set((await api('/api/incidents')).map((i) => i.id));
  const sens = (await api('/api/sensors')).sensors.find((s) => s.metric === 'pm25');
  await api('/api/sensors', { node: sens.node, metric: 'pm25', value: sens.max });
  mark('poll 1 s; PM2.5 ' + sens.node + ' set to ' + sens.max);
  const inc = await until('early incident', async () => (await api('/api/incidents')).find((i) => !before.has(i.id) && i.refine_stage === 'early'));
  ID = inc.id; mark(ID + ' early analysis done: severity ' + inc.severity + ', created ' + inc.created_sim_ist + ', next refinement sim ' + inc.next_refine_sim);
  // the event ends; the refinements re-read the sensor anyway (a stuck sensor may look quiet too)
  await api('/api/sensors', { node: sens.node, metric: 'pm25', value: sens.value });
  await openInc();
  await shot('01_early_detail_top', 780); report.push(await hscroll('early-detail'), { early: await hdr() });

  // the page stays open: it must update by itself (SSE "incident" event) when each refinement lands
  await until('1.5 h on the open page', async () => /1\.5/.test((await hdr()).stage || ''));
  mark(ID + ' open page shows REFINED 1.5 h (no reload)');
  await sleep(500);
  await shot('02_refined_1_5h_detail_top', 780); report.push(await hscroll('r15-detail'), { r15: await hdr() });
  await until('3 h on the open page', async () => /3 h/.test((await hdr()).stage || ''));
  mark(ID + ' open page shows REFINED 3 h (no reload)');
  await sleep(500);
  await shot('03_refined_3h_detail_top', 780); report.push({ r3: await hdr() });
  await ev(`[...document.querySelectorAll('.fold-h')].find(b => /History/.test(b.textContent)).click(); true`); await sleep(300);
  await ev(`[...document.querySelectorAll('.fold-h')].find(b => /History/.test(b.textContent)).scrollIntoView(); true`); await sleep(300);
  await shot('04_history_real'); report.push(await hscroll('history-real'));
  report.push({ historyReal: await ev(`[...document.querySelectorAll('.hist li')].map(li => li.innerText.replace(/\\n+/g, ' | '))`) });
  const full = await ev(`document.querySelector('#inc-detail').scrollHeight`);
  await shot('05_refined_detail_full', Math.min(4200, full + 260));
  await W();
  await ev(`document.querySelector('#inc-detail').scrollTop = 0; document.querySelector('#inc-detail .schip').click(); true`); await sleep(900);
  await shot('06_sensor_sheet_real'); report.push(await hscroll('sheet-real'));
  report.push({ sheetReal: await ev(`({ cap: document.querySelector('.fs-cap').textContent, note: (document.querySelector('#fs .refnext')||{}).textContent || null })`) });
  await ev(`document.querySelector('#fs-x').click(); true`); await sleep(300);
  await ev(`document.querySelector('[data-close=isheet]').click(); true`); await sleep(600);
  await shot('07_list_refined_marker'); report.push(await hscroll('list'));
  report.push({ listRow: await ev(`(() => { const c = [...document.querySelectorAll('#inc-list .icard')].find(e => e.textContent.includes(${JSON.stringify(ID)})); return { cls: c.className, sev: c.querySelector('.sevtag').textContent, stage: (c.querySelector('.stagetag')||{}).textContent || null }; })()`) });
  fs.writeFileSync(OUT + '/incident_' + ID + '_api.json', JSON.stringify(await api('/api/incidents/' + ID), null, 1));
  fs.writeFileSync(OUT + '/incident_list_api.json', JSON.stringify(await api('/api/incidents'), null, 1));

  // SYNTHETIC (labelled): the mock agents always answer stable/normal, so they cannot produce a change.
  // The fetch interceptor rewrites this incident as: early spike/critical -> 1.5 h kept (event over)
  // -> 3 h step increase/warning, which is what the backend tests drive through the real pipeline.
  const rw = `window.__rw = (u, j) => { const ID = ${JSON.stringify(ID)};
    if (Array.isArray(j)) return j.map(x => x.id !== ID ? x : window.__stage === '1.5h' ? Object.assign({}, x, { severity: 'critical', refine_stage: '1.5h', title: 'PM2.5 spike: ' + x.title.split(': ').pop() }) : Object.assign({}, x, { severity: 'warning', title: 'PM2.5 step increase: ' + x.title.split(': ').pop() }));
    if (j.id !== ID) return j; const n = JSON.parse(JSON.stringify(j)); const s1 = n.sensors.find(s => !s.context), loc = s1.location;
    const sv = (p, st, extra) => [Object.assign({ ref: s1.ref, metric: s1.metric, pattern: p, status: st }, extra || {})];
    Object.assign(n.revisions[0], { severity: 'critical', title: 'PM2.5 spike: ' + loc, sensors: sv('spike', 'critical') });
    Object.assign(n.revisions[1], { severity: 'critical', title: 'PM2.5 spike: ' + loc, sensors: sv('spike', 'critical', { kept: true, note: 'kept early spike: event over (refined view: stable)' }) });
    if (window.__stage === '1.5h') { n.revisions = n.revisions.slice(0, 2); n.refine_stage = '1.5h'; n.severity = 'critical'; n.title = 'PM2.5 spike: ' + loc; n.next_refine_sim = n.revisions[1].sim_end + 18 * 300; }
    else { Object.assign(n.revisions[2], { severity: 'warning', title: 'PM2.5 step increase: ' + loc, sensors: sv('step_increase', 'warning') }); n.severity = 'warning'; n.title = 'PM2.5 step increase: ' + loc; }
    const a = n.agents.find(x => x.ref === s1.ref), last = n.revisions[n.revisions.length - 1].sensors[0];
    if (a && a.parsed) { a.parsed.pattern = last.pattern; a.parsed.status = last.status; a.valid = true; }
    return n; }; true`;
  await ev(`window.__stage = '3h'; ` + rw);
  await ev(`window.dispatchEvent(new HashChangeEvent('hashchange')); true`); await sleep(1500);
  await shot('08_list_synthetic_changed');
  await openInc();
  await ev(`(() => { const b = [...document.querySelectorAll('.fold-h')].find(b => /History/.test(b.textContent)); if (b.getAttribute('aria-expanded') !== 'true') b.click(); b.scrollIntoView(); return true; })()`); await sleep(400);
  await shot('09_history_synthetic_spike_kept_then_step'); report.push(await hscroll('history-synth'));
  report.push({ historySynthetic: await ev(`[...document.querySelectorAll('.hist li')].map(li => li.innerText.replace(/\\n+/g, ' | '))`) });
  await ev(`document.querySelector('#inc-detail').scrollTop = 0; document.querySelector('#inc-detail .schip').click(); true`); await sleep(900);
  await shot('10_sensor_sheet_synthetic_was_early'); report.push({ sheetWas: await ev(`(document.querySelector('#fs .refnext')||{}).textContent || null`) });
  await ev(`document.querySelector('#fs-x').click(); true`); await sleep(300);
  await ev(`window.__stage = '1.5h'; ` + rw); await openInc();
  await shot('11_detail_synthetic_1_5h_kept_top'); report.push({ kept15: await hdr() });
  await ev(`document.querySelector('#inc-detail .schip').click(); true`); await sleep(900);
  await shot('12_sensor_sheet_synthetic_kept'); report.push({ sheetKept: await ev(`(document.querySelector('#fs .refnext')||{}).textContent || null`) }, await hscroll('sheet-kept'));
  await ev(`document.querySelector('#fs-x').click(); document.documentElement.setAttribute('data-theme','light'); window.__stage = '3h'; ` + rw); await openInc();
  await shot('13_light_synthetic_detail_top');
  await ev(`window.__rw = null; true`);

  report.push({ timeline, consoleErrors: logs });
  fs.writeFileSync(OUT + '/checks.json', JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report, null, 1));
  ws.close(); chrome.kill();
  process.exit(0);
})().catch((e) => { console.error(e); chrome.kill(); process.exit(1); });
