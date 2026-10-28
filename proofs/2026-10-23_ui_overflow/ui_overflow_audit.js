// UI overflow audit (Node 24, no deps). Drives headless Chrome over CDP against a running backend,
// walks every view/sheet/state at several widths (+130% text zoom emulation), and prints ONLY offenders:
//   PAGE-HSCROLL  document wider than the viewport
//   OUT           element sticks out of the viewport (left<0 or right>vw), root causes only
//   SPILL         element wider than its (overflow:visible) parent, root causes only
//   HSCROLL       a box that scrolls/clips horizontally (scrollWidth > clientWidth) and is not a designed scroller
//   ELLIPSIS      single-line text cut with "..." (reported separately; allowed only when full text is reachable)
// Usage: node ui_overflow_audit.js [base=http://127.0.0.1:18000] [outJson] [shotsDir]
// Stretch mode wraps window.fetch and lengthens display strings (titles, notes, observations, places),
// including an unbroken 60-char token, to force worst-case content without changing the backend.
const fs = require('fs'), path = require('path'), { spawn } = require('child_process');
const BASE = process.argv[2] || 'http://127.0.0.1:18000';
const OUT = process.argv[3] || path.join(__dirname, 'audit_report.json');
const SHOTS = process.argv[4] || '';
const CHROME = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
const port = 9341;
const prof = path.join(process.env.TEMP, 'cdp-ovf-' + port);
const ch = spawn(CHROME, ['--headless=new', '--remote-debugging-port=' + port, '--user-data-dir=' + prof, '--no-first-run', '--hide-scrollbars', '--disable-gpu', 'about:blank'], { stdio: 'ignore' });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const STRETCH = `(() => {
  const LONG = ' and the reading kept drifting upward through the whole window while the neighbouring sensors stayed steady';
  const TOK = ' SR-AQ-KH03-03_metric_window_identifier_without_any_break_0123456789ABCDEF';
  const KEYS = /^(title|rule_title|root_cause|summary|explanation|approval_note|recommendation|rationale|why|location|loc|place|description|desc|note|plain|reason|action_text|cause)$/;
  const grow = (k, v) => (k === 'location' || k === 'loc' || k === 'place') ? v + ' Kohli Research Block level 03 room 312B (north wing)' + TOK : v + LONG + TOK;
  const walk = (o, d) => { if (!o || typeof o !== 'object' || d > 9) return o;
    if (Array.isArray(o)) { o.forEach((x) => walk(x, d + 1)); return o; }
    for (const k of Object.keys(o)) { const v = o[k];
      if (typeof v === 'string' && v && KEYS.test(k)) o[k] = grow(k, v);
      else if (k === 'observations' && Array.isArray(v)) o[k] = v.map((s) => typeof s === 'string' ? s + LONG + TOK : s);
      else walk(v, d + 1); }
    return o; };
  const f0 = window.fetch;
  window.fetch = (...a) => f0(...a).then((r) => { const u = String(a[0]);
    if (!/\\/api\\//.test(u) || !(r.headers.get('content-type') || '').includes('json')) return r;
    return r.clone().json().then((j) => new Response(JSON.stringify(walk(j, 0)), { status: r.status, headers: r.headers })).catch(() => r); });
})();`;

// emulate Android WebView textZoom (system font scale): every px font-size rule x Z, layout untouched
const ZOOM = (z) => `(() => { if (document.getElementById('ovf-zoom')) return 1; const out = [];
  const visit = (rules, wrap) => { for (const r of rules) {
    if (r.cssRules && r.media) { visit(r.cssRules, (s) => '@media ' + r.media.mediaText + '{' + s + '}'); continue; }
    if (!r.style) continue; const fsz = r.style.getPropertyValue('font-size');
    const m = /^([\\d.]+)px$/.exec(fsz.trim()); if (!m) continue;
    const imp = r.style.getPropertyPriority('font-size') ? ' !important' : '';
    out.push(wrap(r.selectorText + '{font-size:' + (+m[1] * ${z}).toFixed(2) + 'px' + imp + '}')); } };
  for (const sh of document.styleSheets) { try { visit(sh.cssRules, (s) => s); } catch (e) {} }
  const st = document.createElement('style'); st.id = 'ovf-zoom'; st.textContent = out.join('\\n'); document.head.appendChild(st);
  /* inline style="font-size:..px" written by app.js */
  const fix = () => document.querySelectorAll('[style*="font-size"]').forEach((e) => { if (e.dataset.ovfz) return; const m = /([\\d.]+)px/.exec(e.style.fontSize); if (m) { e.style.fontSize = (+m[1] * ${z}) + 'px'; e.dataset.ovfz = 1; } });
  fix(); new MutationObserver(fix).observe(document.body, { childList: true, subtree: true }); return out.length; })()`;

const AUDIT = `(() => {
  const vw = document.documentElement.clientWidth, res = [];
  const DESIGNED = '.chips, .sn-pre, .tl, svg, .seg, .tip, .sr-only, [data-ovf-ok]';
  const sel = (e) => { const p = []; for (let x = e; x && x.nodeType === 1 && p.length < 4; x = x.parentElement) {
      let s = x.tagName.toLowerCase(); if (x.id) { s += '#' + x.id; p.unshift(s); break; }
      if (x.classList.length) s += '.' + [...x.classList].slice(0, 2).join('.'); p.unshift(s); } return p.join('>'); };
  const vis = (e) => { for (let x = e; x; x = x.parentElement) { const cs = getComputedStyle(x);
      if (cs.display === 'none' || cs.visibility === 'hidden' || cs.contentVisibility === 'hidden' && x !== e) return false;
      if (x.classList && x.classList.contains('sheet') && !x.classList.contains('open')) return false; } return true; };
  const inDesigned = (e) => !!e.closest(DESIGNED);
  /* ignore boxes whose only overflow is a decorative ::before/::after (e.g. the hero glow) */
  const contentWider = (e, r) => { const g = document.createRange(); g.selectNodeContents(e); const cr = g.getBoundingClientRect(); return cr.right > r.right + 1 || cr.left < r.left - 1 || e.scrollLeft > 0; };
  const txt = (e) => (e.innerText || e.textContent || '').trim().replace(/\\s+/g, ' ').slice(0, 70);
  const pw = document.documentElement.scrollWidth;
  if (pw > vw + 1) res.push({ k: 'PAGE-HSCROLL', sel: 'html', d: pw + ' > ' + vw });
  const all = [...document.body.querySelectorAll('*')].filter((e) => !(e instanceof SVGElement && e.tagName !== 'svg'));
  const visible = new Set(all.filter(vis));
  const off = new Set(), spill = new Set();
  for (const e of visible) { const r = e.getBoundingClientRect(); if (!r.width) continue;
    const cs = getComputedStyle(e);
    if (cs.position === 'fixed' && e.id === 'fs' ) continue;
    if ((r.right > vw + 1 || r.left < -1) && !inDesigned(e)) {
      // ignore things that are scrolled within a horizontally scrolling ancestor that is itself reported
      off.add(e); }
    const p = e.parentElement; if (p && visible.has(p) && cs.position !== 'absolute' && cs.position !== 'fixed') {
      const pr = p.getBoundingClientRect(), pcs = getComputedStyle(p);
      if (pcs.overflowX === 'visible' && r.right > pr.right + 1.5 && !inDesigned(e)) spill.add(e); }
    if (e.clientWidth && e.scrollWidth > e.clientWidth + 1 && cs.overflowX !== 'visible' && !inDesigned(e) && contentWider(e, r)) {
      const ell = cs.textOverflow === 'ellipsis' || (cs.webkitLineClamp && cs.webkitLineClamp !== 'none');
      res.push({ k: ell ? 'ELLIPSIS' : 'HSCROLL', sel: sel(e), d: e.scrollWidth + '>' + e.clientWidth + ' ox=' + cs.overflowX + (e.title ? ' [title]' : ''), t: txt(e) }); }
    /* text that runs out of a box with overflow:visible (overlaps neighbours or the edge) */
    if (cs.overflowX === 'visible' && !inDesigned(e) && [...e.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim())) {
      const g = document.createRange(); let mx = -1e9;
      for (const n of e.childNodes) if (n.nodeType === 3 && n.textContent.trim()) { g.selectNodeContents(n); for (const q of g.getClientRects()) mx = Math.max(mx, q.right); }
      const lim = r.right - (parseFloat(cs.paddingRight) || 0) * 0 + 1;
      if (mx > lim) res.push({ k: 'TEXT-SPILL', sel: sel(e), d: 'text right+' + Math.round(mx - r.right), t: txt(e) }); }
    if (cs.webkitLineClamp && cs.webkitLineClamp !== 'none' && e.scrollHeight > e.clientHeight + 1)
      res.push({ k: 'ELLIPSIS', sel: sel(e), d: 'line-clamp ' + cs.webkitLineClamp + (e.title ? ' [title]' : ''), t: txt(e) });
  }
  for (const e of off) if (!off.has(e.parentElement)) { const r = e.getBoundingClientRect(); res.push({ k: 'OUT', sel: sel(e), d: Math.round(r.left) + '..' + Math.round(r.right) + ' vw=' + vw, t: txt(e) }); }
  for (const e of spill) if (!spill.has(e.parentElement)) { const r = e.getBoundingClientRect(), pr = e.parentElement.getBoundingClientRect(); res.push({ k: 'SPILL', sel: sel(e), d: 'w' + Math.round(r.width) + ' right+' + Math.round(r.right - pr.right), t: txt(e) }); }
  return res; })()`;

const closeAll = `(document.querySelectorAll('.sheet.open').forEach(x=>{const b=x.querySelector('[data-close]');b&&b.click()}), document.getElementById('fs') && !document.getElementById('fs').hidden && document.getElementById('fs-x').click(), 1)`;
const STATES = [
  { n: 'sensors', hash: 'sensors' },
  { n: 'sensor_drawer', js: `(document.querySelector('#sens .sn-row b, #sens .sn-nm')||{click(){}}).click(), (typeof openSheet==='function' && document.querySelector('#sheet.open'))?1:0` },
  { n: 'live', hash: 'live' },
  { n: 'domain_sheet', js: `(document.querySelector('.dh-tile:not(.calm)')||document.querySelector('.dh-tile')).click(),1` },
  { n: 'domain_sensor_drawer', js: `(document.querySelector('#dsheet .ds-row')||{click(){}}).click(),1`, wait: 1800 },
  { n: 'live_rows', hash: 'live', js: `(document.querySelector('#live-grid .row')||{click(){}}).click(),1`, wait: 1800 },
  { n: 'incidents', hash: 'incidents' },
  { n: 'incident_sheet', js: `(document.querySelector('.icard')||{click(){}}).click(),1`, wait: 2500 },
  { n: 'incident_tech', js: `(()=>{const f=document.querySelector('.tech-wrap .fold-h'); if(f&&f.getAttribute('aria-expanded')==='false') f.click(); document.querySelectorAll('#inc-detail .fold-h[aria-expanded="false"]').forEach(b=>b.click()); document.querySelectorAll('#inc-detail details').forEach(d=>d.open=true); return 1})()`, wait: 1200 },
  { n: 'incident_sensor_fs', js: `(document.querySelector('#inc-detail .schip')||{click(){}}).click(),1`, wait: 1500 },
  { n: 'incident_decided', hash: 'incidents', js: `(()=>{const c=[...document.querySelectorAll('.icard')].find(x=>/approved|dismissed/i.test(x.textContent)); (c||document.querySelector('.icard')||{click(){}}).click(); return !!c})()`, wait: 2500 },
  { n: 'map', hash: 'map' },
  { n: 'about', hash: 'about' },
  { n: 'toast', hash: 'live', js: `(toast('Could not reach the edge device: request to /api/incidents/INC-0042/approve failed with HTTP 409 analysis_still_running_decide_once_the_report_is_ready', true), toast('Saved'), 1)`, wait: 400 },
  { n: 'eng_live', eng: 1, hash: 'live' },
  { n: 'eng_incident', js: `(location.hash='#incidents', setTimeout(()=>(document.querySelector('.icard')||{click(){}}).click(),900), 1)`, wait: 3200 },
  { n: 'eng_incident_tech', js: `(()=>{document.querySelectorAll('#inc-detail .fold-h[aria-expanded="false"]').forEach(b=>b.click()); document.querySelectorAll('#inc-detail details').forEach(d=>d.open=true); return 1})()`, wait: 1200 },
  { n: 'eng_sensor_fs', js: `(document.querySelector('#inc-detail .schip')||{click(){}}).click(),1`, wait: 1500 },
  { n: 'eng_about', hash: 'about' },
];
const CONFIGS = [
  { name: '360', w: 360, h: 780, mobile: true }, { name: '412', w: 412, h: 915, mobile: true },
  { name: '412z130', w: 412, h: 915, mobile: true, zoom: 1.3 }, { name: '360z130', w: 360, h: 780, mobile: true, zoom: 1.3 },
  { name: '412light', w: 412, h: 915, mobile: true, theme: 'light' }, { name: '412stretch', w: 412, h: 915, mobile: true, stretch: 1 },
  { name: '360z130stretch', w: 360, h: 780, mobile: true, zoom: 1.3, stretch: 1 },
  { name: '768', w: 768, h: 1024, mobile: true }, { name: '1440', w: 1440, h: 900 }, { name: '1440stretch', w: 1440, h: 900, stretch: 1 },
];
const only = process.env.OVF_ONLY ? process.env.OVF_ONLY.split(',') : null;
const shotList = process.env.OVF_SHOTS ? process.env.OVF_SHOTS.split(',') : []; // "412stretch:incident_sheet,..."

(async () => {
  let ws;
  for (let i = 0; i < 50 && !ws; i++) { try { const l = await (await fetch('http://127.0.0.1:' + port + '/json')).json(); const p = l.find((x) => x.type === 'page'); if (p) ws = new WebSocket(p.webSocketDebuggerUrl); } catch (e) {} await sleep(200); }
  if (ws.readyState !== 1) await new Promise((r) => ws.addEventListener('open', r));
  let id = 0; const pend = {}; const errs = [];
  ws.addEventListener('message', (m) => { const d = JSON.parse(m.data); if (d.id && pend[d.id]) { pend[d.id](d); delete pend[d.id]; }
    if (d.method === 'Runtime.exceptionThrown') errs.push(JSON.stringify(d.params.exceptionDetails.exception && d.params.exceptionDetails.exception.description || d.params.exceptionDetails.text).slice(0, 200)); });
  const send = (method, params) => new Promise((r) => { const i = ++id; pend[i] = r; ws.send(JSON.stringify({ id: i, method, params: params || {} })); });
  const ev = async (expr) => { const r = await send('Runtime.evaluate', { expression: expr, awaitPromise: true, returnByValue: true }); return r.result && r.result.result && r.result.result.value; };
  await send('Page.enable'); await send('Runtime.enable');
  const report = {}; let total = 0; let scriptId = null;
  for (const c of CONFIGS) {
    if (only && !only.includes(c.name)) continue;
    await send('Emulation.setDeviceMetricsOverride', { width: c.w, height: c.h, deviceScaleFactor: 1, mobile: !!c.mobile });
    if (scriptId) { await send('Page.removeScriptToEvaluateOnNewDocument', { identifier: scriptId }); scriptId = null; }
    const pre = `try{localStorage.setItem('sce-theme','${c.theme || 'dark'}');localStorage.setItem('sce-eng','0')}catch(e){};` + (c.stretch ? STRETCH : '');
    scriptId = (await send('Page.addScriptToEvaluateOnNewDocument', { source: pre })).result.identifier;
    let eng = 0;
    await send('Page.navigate', { url: BASE + '/#sensors' }); await sleep(3500);
    if (c.zoom) await ev(ZOOM(c.zoom));
    report[c.name] = {};
    for (const s of STATES) {
      if (s.eng && !eng) { await ev(`(localStorage.setItem('sce-eng','1'), 1)`); await send('Page.reload'); await sleep(3500); if (c.zoom) await ev(ZOOM(c.zoom)); eng = 1; }
      if (s.hash) { await ev(closeAll); await sleep(400); await ev(`location.hash='${s.hash}',1`); await sleep(s.js ? 1500 : (s.wait || 1500)); }
      if (s.js) { await ev(s.js); await sleep(s.wait || 1300); }
      const r = (await ev(AUDIT)) || [];
      const key = c.name + ':' + s.n;
      if (shotList.includes(key) && SHOTS) { fs.mkdirSync(SHOTS, { recursive: true }); const p = await send('Page.captureScreenshot', { format: 'png' }); fs.writeFileSync(path.join(SHOTS, s.n + '_' + c.name + '.png'), Buffer.from(p.result.data, 'base64')); }
      // de-duplicate identical findings (e.g. 27 identical rows)
      const seen = new Map(); for (const f of r) { const k = f.k + '|' + f.sel; if (seen.has(k)) seen.get(k).n++; else seen.set(k, Object.assign(f, { n: 1 })); }
      const uniq = [...seen.values()];
      report[c.name][s.n] = uniq;
      const bad = uniq.filter((f) => f.k !== 'ELLIPSIS');
      total += bad.length;
      for (const f of uniq) if (f.k !== 'ELLIPSIS' || process.env.OVF_ELL) console.log(`${key}\t${f.k}\t${f.sel}\t${f.d}${f.n > 1 ? ' x' + f.n : ''}\t${f.t || ''}`);
    }
  }
  fs.writeFileSync(OUT, JSON.stringify({ base: BASE, when: new Date().toISOString(), configs: CONFIGS.map((c) => c.name), states: STATES.map((s) => s.n), page_errors: errs, total_non_ellipsis: total, report }, null, 1));
  const ell = Object.values(report).flatMap((o) => Object.values(o).flat()).filter((f) => f.k === 'ELLIPSIS').length;
  console.log(`TOTAL overflow findings (excluding ELLIPSIS): ${total}; ELLIPSIS: ${ell}; page errors: ${errs.length}`);
  errs.slice(0, 5).forEach((e) => console.log('PAGE ERROR', e));
  ws.close(); ch.kill(); process.exit(0);
})().catch((e) => { console.error(e); ch.kill(); process.exit(1); });
