// Browser-free check of the incident sheet's plain "What is happening" text (app.js happening(),
// sensorPhrase(), joinSentences(), plainTitle()) on the board's real incident shape.
// Usage: node ui_incident_summary_check.js <path to app.js>
const fs = require('fs');
const src = fs.readFileSync(process.argv[2], 'utf8');
const region = (a, b) => { const i = src.indexOf(a), j = src.indexOf(b); if (i < 0 || j < 0) throw new Error('marker ' + a); return src.slice(i, j); };
const fn = (name) => {
  const m = new RegExp('^function ' + name + '\\(', 'm').exec(src); if (!m) throw new Error('no fn ' + name);
  const rest = src.slice(m.index + 1), n = /^(?:async function |function |const |let |\/\*)/m.exec(rest.slice(10));
  return src.slice(m.index, m.index + 1 + 10 + n.index);
};
const nice = (s) => (s == null || s === '' ? '-' : String(s).replace(/_/g, ' '));
const STATUS_LABEL = { normal: 'Normal', warning: 'Warning', critical: 'Critical', sensor_fault: 'Sensor fault', insufficient_data: 'Not enough data' };
const isCtxAgent = (a) => /context agent/i.test((a && a.model) || '');
eval(region('/* ----- plain language ----- */', '/* ----- end plain language ----- */') + fn('sensorVerdict') + fn('findingOf') + fn('sensorPhrase') + fn('happening') +
  ';globalThis.T={happening,joinSentences,plainTitle}');
const ok = (c, m) => { if (!c) { console.error('FAIL', m); process.exit(1); } };

// INC-0053 as seen on the board: CO2 throttling, context sensors incl. AC units (backend text lost that name)
const inc = { state: 'done', mode: 3, sensors: [
  { ref: 'S1', node: 'SR-AQ-KH03-03', metric: 'co2', location: 'KH building, level 03, indoor air sensor 03', context: false, rule_finding: { pattern: 'spike', status: 'warning' } },
  { ref: 'S2', node: 'AC-KH03', metric: 'ac_units_on', location: 'KH building, level 03, AC units', context: true, rule_finding: { pattern: 'stable', status: 'normal' } },
  { ref: 'S3', node: 'SR-OC-GW-KH95-01', metric: 'occ', location: 'KH building, room occupancy sensor 01 (gateway KH95)', context: true, rule_finding: { pattern: 'vacant', status: 'normal' } },
  { ref: 'S4', node: 'SR-EM-KH04-01', metric: 'power_kw', location: 'KH building, level 04, room energy meter 01', context: true, rule_finding: { pattern: 'stable', status: 'normal' } }],
  agents: [{ ref: 'S1', valid: true, model: 'llama', parsed: { pattern: 'throttling', status: 'critical', likely_cause: 'ventilation_insufficient',
    observations: ['CO2 flattened at its maximum 1757 ppm [E2,E8]', 'Reading 1757 ppm breaks the critical limit 1500 ppm [E1]'] } }] };
const r = T.happening(inc, inc.sensors.filter((s) => !s.context), inc.sensors.filter((s) => s.context));
ok(r.lead === 'CO2 at KH-03 flattened at a cap (critical).', 'lead: ' + r.lead);
ok(r.obs === 'CO2 flattened at its maximum 1757 ppm. Reading 1757 ppm breaks the critical limit 1500 ppm.', 'obs: ' + r.obs);
ok(r.related === 'Checked nearby and normal: AC units on at KH-03 AC steady; Occupancy at KH room 01 empty; Power at KH-04 room 01 steady. So the cause looks local.', 'related: ' + r.related);
ok(!/\[|E\d|throttling|vacant|stable/.test(r.lead + r.obs + r.related), 'no jargon / evidence ids');
ok(T.joinSentences(['a reading [E1]', 'Done.', '', 'why? [S1.E2]']) === 'A reading. Done. Why?', 'joinSentences ' + T.joinSentences(['a reading [E1]', 'Done.', '', 'why? [S1.E2]']));
ok(T.plainTitle('Tank level slow drift (12 h view): KH building, level 98, water tank level sensor 00') === 'Tank level drifting slowly (12 h view) · KH-98 tank', 'drift title ' + T.plainTitle('Tank level slow drift (12 h view): KH building, level 98, water tank level sensor 00'));
ok(T.plainTitle('CO2 throttling: KH building, level 03, indoor air sensor 03') === 'CO2 flattened at a cap · KH-03', 'co2 title');
// all flagged judged normal by the AI
inc.agents[0].parsed = { pattern: 'stable', status: 'normal', observations: [] };
const r2 = T.happening(inc, inc.sensors.filter((s) => !s.context), []);
ok(r2.lead === 'Nothing abnormal confirmed: CO2 at KH-03 steady.', 'all normal: ' + r2.lead);
// steady shape but abnormal status reads as the status (title.go what())
inc.agents[0].parsed = { pattern: 'stable', status: 'warning', observations: ['mock'] };
const r3 = T.happening(inc, inc.sensors.filter((s) => !s.context), []);
ok(r3.lead === 'CO2 at KH-03 above normal (warning).', 'steady+warning: ' + r3.lead);
console.log('ui incident summary check: OK');
