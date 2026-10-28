// Final QA: every page at 3 sizes; screenshots + report.json (console errors, overflow, timings).
//   PUPPETEER=<path> node qa_final.js [baseUrl] [pages,comma] [sizes w x h,comma]
const path = require('path'); const fs = require('fs');
const puppeteer = require(process.env.PUPPETEER || 'puppeteer-core');
const BASE = process.argv[2] || 'http://127.0.0.1:8080/';
const PAGES = (process.argv[3] || 'deck,route,decisions,proofs,qa,rawdata,kit').split(',');
const SIZES = (process.argv[4] || '360x780,1440x900,1920x1080').split(',').map((s) => s.split('x').map(Number));
const OUT = process.env.OUT || __dirname; fs.mkdirSync(OUT, { recursive: true }); const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const report = { base: BASE, when: new Date().toISOString(), runs: [] };
(async () => {
  const browser = await puppeteer.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: true, args: ['--no-first-run', '--disable-extensions'] });
  for (const [w, hgt] of SIZES) {
    const bctx = await browser.createBrowserContext(); const page = await bctx.newPage();
    await page.setViewport({ width: w, height: hgt, deviceScaleFactor: 1 });
    let errs = [];
    page.on('console', (m) => { if (['error', 'warning'].includes(m.type())) errs.push(`${m.type()}: ${m.text()}`); });
    page.on('pageerror', (e) => errs.push('pageerror: ' + e.message));
    page.on('requestfailed', (r) => errs.push('requestfailed: ' + r.url().slice(0, 120)));
    await page.goto(BASE, { waitUntil: 'networkidle0' });
    await page.type('#pw', 'test-only-pw'); const t0 = Date.now();
    await page.click('#gate button[type=submit]');
    await page.waitForFunction(() => !document.body.classList.contains('locked') && document.querySelector('#app .page'), { timeout: 20000 });
    const unlockMs = Date.now() - t0;
    for (const p of PAGES) {
      errs = [];
      const t1 = Date.now();
      await page.evaluate((p) => { location.hash = '#/' + p; }, p);
      await page.waitForFunction((p) => document.querySelector('#page-' + p), { timeout: 20000 }, p).catch(() => {});
      const mountMs = Date.now() - t1;
      // scroll through to trigger lazy charts
      await page.evaluate(async () => { for (let y = 0; y < document.body.scrollHeight; y += 400) { window.scrollTo(0, y); await new Promise((r) => setTimeout(r, 90)); } });
      await sleep(900);
      const info = await page.evaluate(() => {
        const over = [...document.querySelectorAll('#app *')].filter((e) => { const r = e.getBoundingClientRect(); return r.width > 0 && r.right > window.innerWidth + 1 && getComputedStyle(e).position !== 'fixed'; })
          .filter((e) => { for (let a = e.parentElement; a && a !== document.body; a = a.parentElement) { const ox = getComputedStyle(a).overflowX; if (ox === 'auto' || ox === 'scroll' || ox === 'hidden') return false; } return !e.closest('[_echarts_instance_], pre, table'); }).slice(0, 5).map((e) => e.tagName + '.' + (e.className && e.className.baseVal == null ? e.className : '') + ' ' + Math.round(e.getBoundingClientRect().right));
        const charts = [...document.querySelectorAll('[_echarts_instance_]')].length;
        const empty = [...document.querySelectorAll('.card__chart')].filter((c) => !c.querySelector('canvas,svg') ).length;
        const navActive = document.querySelector('.nav__item[aria-current=page]')?.dataset.page || null;
        const next = !!document.querySelector('.next__link');
        return { hscroll: document.documentElement.scrollWidth > window.innerWidth + 1, scrollWidth: document.documentElement.scrollWidth, over, charts, emptyChartBoxes: empty, navActive, next, title: document.title, height: document.body.scrollHeight };
      });
      const totalMs = Date.now() - t1;
      await page.evaluate(() => window.scrollTo(0, 0)); await sleep(300);
      await page.screenshot({ path: path.join(OUT, `${p}_${w}x${hgt}.png`), fullPage: !!process.env.FULL });
      const r = { page: p, size: `${w}x${hgt}`, unlockMs, mountMs, totalMs, ...info, console: errs.slice() };
      report.runs.push(r); console.log(JSON.stringify(r));
    }
    await bctx.close();
  }
  fs.writeFileSync(path.join(OUT, process.env.REPORT || 'report.json'), JSON.stringify(report, null, 1));
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
