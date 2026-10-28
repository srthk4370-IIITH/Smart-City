// Renders EVERY dataset in data/catalog.json through the chart kit ('auto' type) and reports failures.
//   PUPPETEER=<path to puppeteer-core> node qa_realdata.js [baseUrl]
const path = require('path');
const fs = require('fs');
const puppeteer = require(process.env.PUPPETEER || 'puppeteer-core');
const BASE = process.argv[2] || 'http://127.0.0.1:8080/';

(async () => {
  const browser = await puppeteer.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: true, protocolTimeout: 600000 });
  const page = await browser.newPage();
  await page.setViewport({ width: 1440, height: 900 });
  const errs = [];
  page.on('console', (m) => { if (m.type() === 'error') errs.push(m.text()); });
  page.on('pageerror', (e) => errs.push(e.message));
  await page.goto(BASE, { waitUntil: 'networkidle0' });
  await page.type('#pw', 'test-only-pw');
  await page.click('#gate button[type=submit]');
  await page.waitForFunction(() => window.SITE && document.querySelector('#app .page'));
  const res = await page.evaluate(async () => {
    const { charts, data, ui } = window.SITE;
    const cat = await data.catalog();
    const page = document.querySelector('#app .page');
    const grid = ui.h('div.grid');
    page.replaceChildren(grid);
    const out = [];
    for (const e of cat) {
      const card = ui.card({ span: 6, id: e.id });
      grid.append(card);
      const h = card._chart;
      h.drawNow(); // draw now, not on scroll
      try {
        const ch = await Promise.race([h.ready, new Promise((_, rej) => setTimeout(() => rej(new Error('timeout')), 8000))]);
        out.push({ id: e.id, type: h.el.dataset.chartType, ok: !!ch });
      } catch (err) { out.push({ id: e.id, ok: false, err: err.message }); }
    }
    return { n: cat.length, out };
  });
  await page.evaluate(async () => { for (let y = 0; y < document.body.scrollHeight; y += 700) { window.scrollTo(0, y); await new Promise((r) => setTimeout(r, 60)); } window.scrollTo(0, 0); });
  await new Promise((r) => setTimeout(r, 1500));
  await page.screenshot({ path: path.join(__dirname, '50_realdata_gallery_1440.png'), fullPage: true });
  const bad = res.out.filter((o) => !o.ok);
  const byType = res.out.reduce((a, o) => ((a[o.type] = (a[o.type] || 0) + 1), a), {});
  fs.writeFileSync(path.join(__dirname, 'realdata_results.json'), JSON.stringify({ when: new Date().toISOString(), ...res, byType, console_errors: errs }, null, 1));
  console.log(`${res.n - bad.length}/${res.n} datasets rendered`, byType, bad.slice(0, 20), errs.slice(0, 10));
  await browser.close();
})();
