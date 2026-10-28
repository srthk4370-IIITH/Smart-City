// Browser-free check of app.js token handling: seq order, reset, duplicate skip, gap -> /api/streams resync.
const fs = require('fs');
const src = fs.readFileSync(process.argv[2], 'utf8');
const a = src.indexOf('/* ----- token streaming ----- */'), b = src.indexOf('function renderIncFoot');
let fetched = [];
const S = { stream: {}, cardStream: {}, incId: 'INC-1', inc: { id: 'INC-1', state: 'running' } };
const els = {};
const $ = (sel) => { const m = /data-(s|rs|cs)="([^"]+)"/.exec(sel); return m ? (els[m[1] + ':' + m[2]] ||= { textContent: '', scrollTop: 0, scrollHeight: 0, clientHeight: 0 }) : null; };
const h = (t, a, ...k) => ({ textContent: [a && a.text || '', ...k.flat(3).map((x) => (typeof x === 'string' ? x : x ? x.textContent : ''))].join('') });
const fill = () => {}; let raf = [];
const requestAnimationFrame = (f) => { raf.push(f); return 1; };
let server = {};
const api = async (p) => { fetched.push(p); return server; };
const refreshIncDetail = () => {}, renderIncDetail = () => {};
const STAGE_TEXT = {}, roleTitle = {};
eval(src.slice(a, b) + ';globalThis.T={onToken,ST,paintStreams,onBatch}');
const onTok = T.onToken, ST = T.ST;
const flush = () => { const r = raf; raf = []; r.forEach((f) => f()); };
const ok = (c, m) => { if (!c) { console.error('FAIL', m); process.exit(1); } };
onTok({ incident: 'INC-1', ref: 'S1', text: 'ab', seq: 1, reset: true });
onTok({ incident: 'INC-1', ref: 'S2', text: 'xy', seq: 1, reset: true });
onTok({ incident: 'INC-1', ref: 'S1', text: 'cd', seq: 2 });
onTok({ incident: 'INC-1', ref: 'S1', text: 'cd', seq: 2 }); // duplicate
ok(raf.length === 1, 'one paint per frame, got ' + raf.length);
flush();
ok($('[data-s="S1"]').textContent === 'abcd', 'S1 painted ' + $('[data-s="S1"]').textContent);
ok($('[data-s="S2"]').textContent === 'xy', 'S2');
onTok({ incident: 'INC-1', ref: 'S1', text: 'ZZ', seq: 1, reset: true }); // re-run replaces
flush();
ok($('[data-s="S1"]').textContent === 'ZZ', 'reset ' + $('[data-s="S1"]').textContent);
server = { streams: [{ ref: 'S2', text: 'xy-123', seq: 4 }], refine_streams: [] };
onTok({ incident: 'INC-1', ref: 'S2', text: '3', seq: 4 }); // gap (missed 2,3)
setTimeout(() => {
  ok(fetched.length === 1 && S.stream['INC-1:S2'] === 'xy-123', 'resync ' + S.stream['INC-1:S2']);
  onTok({ incident: 'INC-1', ref: 'S2', text: '4', seq: 5 });
  ok(S.stream['INC-1:S2'] === 'xy-1234', 'after resync ' + S.stream['INC-1:S2']);
  onTok({ incident: 'INC-1', ref: 'S3', text: 'r', seq: 1, reset: true }, true);
  ok(S.rstream['INC-1:S3'] === 'r' && !S.stream['INC-1:S3'], 'refine tokens kept apart');
  onTok({ incident: 'INC-1', ref: 'S9', text: 'old' }); // old server without seq: appended
  ok(S.stream['INC-1:S9'] === 'old', 'no-seq compat');
  console.log('ui stream check: OK');
}, 10);
