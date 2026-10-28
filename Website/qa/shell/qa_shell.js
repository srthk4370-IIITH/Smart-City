// Shell QA: drives the built site in headless Chrome (puppeteer-core + the installed Chrome).
//   PUPPETEER=<path to node_modules/puppeteer-core> node qa_shell.js [baseUrl]
// Saves screenshots + results.json next to this file. Password: the throwaway test-only-pw.
const path = require('path');
const fs = require('fs');
const puppeteer = require(process.env.PUPPETEER || 'puppeteer-core');

const BASE = process.argv[2] || 'http://127.0.0.1:8080/';
const OUT = __dirname;
const PW = 'test-only-pw';
const FIX = path.join(OUT, 'fixtures');
const VIEWPORTS = [[360, 780], [1440, 900], [1920, 1080]];
const results = { base: BASE, when: new Date().toISOString(), checks: [], console: [] };
const check = (name, ok, detail) => { results.checks.push({ name, ok: !!ok, detail }); console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail != null ? '  ' + JSON.stringify(detail) : ''}`); };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function newPage(browser, w, h) {
  const ctx = await browser.createBrowserContext();
  const page = await ctx.newPage();
  await page.setViewport({ width: w, height: h, deviceScaleFactor: 1 });
  page.on('console', (m) => { if (['error', 'warning'].includes(m.type())) results.console.push(`[${w}] ${m.type()}: ${m.text()}`); });
  page.on('pageerror', (e) => results.console.push(`[${w}] pageerror: ${e.message}`));
  return { ctx, page };
}
async function unlock(page) {
  await page.goto(BASE, { waitUntil: 'networkidle0' });
  await page.type('#pw', PW);
  const t0 = Date.now();
  await page.click('#gate button[type=submit]');
  await page.waitForFunction(() => !document.body.classList.contains('locked') && document.querySelector('#app .page'), { timeout: 15000 });
  return Date.now() - t0;
}
async function noHScroll(page) {
  return page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1);
}
async function scrollThrough(page) {
  await page.evaluate(async () => {
    for (let y = 0; y < document.body.scrollHeight; y += 500) { window.scrollTo(0, y); await new Promise((r) => setTimeout(r, 120)); }
    window.scrollTo(0, 0);
  });
  await sleep(700);
}
const shot = (page, name, full = false) => page.screenshot({ path: path.join(OUT, name), fullPage: full });

(async () => {
  const browser = await puppeteer.launch({
    executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe',
    headless: true, args: ['--no-first-run', '--disable-extensions'],
  });

  // ---- encrypted files are not readable
  for (const f of ['data/catalog.json.enc', 'data/status.json.enc', 'pages/deck.html.enc']) {
    const r = await fetch(BASE + f).catch(() => null);
    if (!r || !r.ok) { check(`fetch ${f}`, false, r && r.status); continue; }
    const b = Buffer.from(await r.arrayBuffer());
    const txt = b.toString('latin1');
    const printable = [...b].filter((c) => c >= 32 && c < 127).length / b.length;
    check(`${f} is ciphertext (no JSON/HTML, printable ratio ${printable.toFixed(2)})`, !/"meta"|"series"|<section|"training"/.test(txt) && printable < 0.6);
  }
  const auth = await (await fetch(BASE + 'auth.json')).json();
  check('auth.json has bcrypt cost 12 + PBKDF2 600000', /^\$2[aby]\$12\$/.test(auth.bcrypt) && auth.pbkdf2.iterations === 600000, { iterations: auth.pbkdf2.iterations });

  for (const [w, h] of VIEWPORTS) {
    const tag = `${w}x${h}`;
    const { ctx, page } = await newPage(browser, w, h);
    await page.goto(BASE, { waitUntil: 'networkidle0' });
    await shot(page, `01_gate_${tag}.png`);
    check(`[${tag}] gate: no horizontal scroll`, await noHScroll(page));

    if (w === 1440) {
      // wrong password
      await page.type('#pw', 'wrong-password');
      const t0 = Date.now();
      await page.click('#gate button[type=submit]');
      await page.waitForFunction(() => document.querySelector('.gate__msg').classList.contains('is-error'), { timeout: 15000 });
      const msg = await page.$eval('.gate__msg', (e) => e.textContent);
      check('wrong password rejected with a friendly message', /not right/.test(msg), { msg, ms: Date.now() - t0 });
      await shot(page, `02_gate_wrong_${tag}.png`);
      // rate limit after 3 failures
      for (let i = 0; i < 2; i++) {
        await page.$eval('#pw', (e) => { e.value = ''; });
        await page.type('#pw', 'wrong-again-' + i);
        await page.click('#gate button[type=submit]');
        await sleep(100);
        await page.waitForFunction(() => !document.querySelector('#gate button').disabled, { timeout: 15000 });
        await sleep(100);
      }
      await page.$eval('#pw', (e) => { e.value = ''; });
      await page.type('#pw', PW);
      await page.click('#gate button[type=submit]');
      await sleep(300);
      const msg2 = await page.$eval('.gate__msg', (e) => e.textContent);
      check('rate limit: after 3 wrong tries even the right password waits', /Wait|again in/.test(msg2) && await page.evaluate(() => document.body.classList.contains('locked')), { msg2 });
      await shot(page, `03_gate_ratelimit_${tag}.png`);
      await ctx.close();
      continue_unlock: {
        const { ctx: c2, page: p2 } = await newPage(browser, w, h);
        await runUnlocked(p2, tag, w, h);
        await c2.close();
      }
    } else {
      await runUnlocked(page, tag, w, h);
      await ctx.close();
    }
  }

  async function runUnlocked(page, tag, w, h) {
    const ms = await unlock(page);
    check(`[${tag}] unlock with the right password (${ms} ms, target < 3000)`, ms < 3000, { ms });
    await page.waitForSelector('.status .status__item, .path', { timeout: 8000 }).catch(() => {});
    await sleep(500);
    await shot(page, `10_home_${tag}.png`);
    await shot(page, `10_home_full_${tag}.png`, true);
    check(`[${tag}] home: no horizontal scroll`, await noHScroll(page));
    const hasPath = await page.$$eval('.path__step', (els) => els.map((e) => e.querySelector('.path__title').textContent));
    check(`[${tag}] home: Start here path Route -> Decisions -> Q&A`, hasPath.join('>') === 'Route>Decisions>Q&A', hasPath);
    const [key, lkeys] = await page.evaluate(() => [Object.keys(sessionStorage), Object.keys(localStorage)]);
    check(`[${tag}] key in sessionStorage only`, key.includes('site.key.v1') && !lkeys.length, { key, lkeys });

    // reload keeps the session (same tab)
    await page.reload({ waitUntil: 'networkidle0' });
    await page.waitForSelector('#app .page', { timeout: 8000 });
    check(`[${tag}] reload stays unlocked (sessionStorage)`, await page.evaluate(() => !document.body.classList.contains('locked')));

    // ---- deck: PDF
    const input = await page.$('#deck-file');
    await input.uploadFile(path.join(FIX, 'test_deck.pdf'));
    await page.waitForSelector('.show__stage canvas', { timeout: 15000 });
    await sleep(600);
    const c1 = await page.$eval('.show__counter', (e) => e.textContent);
    await shot(page, `20_deck_pdf_${tag}.png`);
    await page.keyboard.press('ArrowRight'); await sleep(400);
    await page.keyboard.press('ArrowRight'); await sleep(400);
    const c2 = await page.$eval('.show__counter', (e) => e.textContent);
    await page.keyboard.press('End'); await sleep(400);
    const c3 = await page.$eval('.show__counter', (e) => e.textContent);
    await page.keyboard.press('Home'); await sleep(300);
    await page.keyboard.press(' '); await sleep(400);
    const c4 = await page.$eval('.show__counter', (e) => e.textContent);
    check(`[${tag}] PDF deck: counter + keys (→ → End Home space)`, c1 === '1 / 6' && c2 === '3 / 6' && c3 === '6 / 6' && c4 === '2 / 6', [c1, c2, c3, c4]);
    // click right part of the stage -> next
    const box = await (await page.$('.show__stage')).boundingBox();
    await page.mouse.click(box.x + box.width * 0.8, box.y + box.height / 2); await sleep(400);
    const c5 = await page.$eval('.show__counter', (e) => e.textContent);
    await page.mouse.click(box.x + box.width * 0.1, box.y + box.height / 2); await sleep(400);
    const c6 = await page.$eval('.show__counter', (e) => e.textContent);
    check(`[${tag}] PDF deck: click right = next, left = back`, c5 === '3 / 6' && c6 === '2 / 6', [c5, c6]);
    // swipe left (touch-like pointer drag)
    await page.mouse.move(box.x + box.width * 0.7, box.y + box.height / 2);
    await page.mouse.down(); await page.mouse.move(box.x + box.width * 0.3, box.y + box.height / 2, { steps: 5 }); await page.mouse.up();
    await sleep(400);
    const c7 = await page.$eval('.show__counter', (e) => e.textContent);
    check(`[${tag}] PDF deck: swipe left = next`, c7 === '3 / 6', c7);
    await page.keyboard.press('t'); await sleep(1200);
    await shot(page, `21_deck_pdf_thumbs_${tag}.png`);
    const nThumbs = await page.$$eval('.thumbs button canvas', (e) => e.length);
    check(`[${tag}] PDF deck: thumbnails strip`, nThumbs === 6, nThumbs);
    await page.keyboard.press('t'); await sleep(200);
    await page.keyboard.press('f'); await sleep(900);
    await shot(page, `22_deck_pdf_fullscreen_${tag}.png`);
    const full = await page.evaluate(() => document.querySelector('.show').classList.contains('is-full'));
    await page.keyboard.press('Escape'); await sleep(500);
    const notFull = await page.evaluate(() => !document.querySelector('.show').classList.contains('is-full'));
    check(`[${tag}] PDF deck: F full screen, Esc exits`, full && notFull);
    check(`[${tag}] deck view: no horizontal scroll`, await noHScroll(page));

    // navigate away and back: deck stays in memory
    await page.goto(BASE + '#/route'); await page.waitForSelector('#page-route'); await sleep(300);
    await shot(page, `30_route_placeholder_${tag}.png`);
    await page.goto(BASE + '#/deck'); await page.waitForSelector('.show__stage canvas', { timeout: 8000 });
    check(`[${tag}] deck kept in memory across pages`, true);

    // ---- deck: PPTX (close PDF first)
    await page.$$eval('.deckbar .btn', (bs) => bs.find((b) => b.textContent === 'Close deck').click());
    await page.waitForSelector('#deck-file');
    await (await page.$('#deck-file')).uploadFile(path.join(FIX, 'test_deck.pptx'));
    await page.waitForSelector('.show__stage .pptx-slide-host', { timeout: 30000 });
    await sleep(800);
    const p1 = await page.$eval('.show__counter', (e) => e.textContent);
    await shot(page, `23_deck_pptx_${tag}.png`);
    await page.keyboard.press('ArrowRight'); await sleep(400);
    const p2 = await page.$eval('.show__counter', (e) => e.textContent);
    const ptxt = await page.$eval('.show__stage', (e) => e.innerText.slice(0, 80));
    check(`[${tag}] PPTX deck renders + navigates`, p1 === '1 / 4' && p2 === '2 / 4' && /PPTX test slide 2/.test(ptxt), [p1, p2, ptxt]);
    await shot(page, `24_deck_pptx_slide2_${tag}.png`);

    // reload forgets the deck
    await page.reload({ waitUntil: 'networkidle0' });
    await page.waitForSelector('#app .page');
    await sleep(300);
    check(`[${tag}] reload forgets the deck`, !!(await page.$('#deck-file')) && !(await page.$('.show')));

    // ---- kit
    await page.goto(BASE + '#/kit'); await page.waitForSelector('#page-kit .card');
    await scrollThrough(page);
    const drawn = await page.$$eval('.card__chart', (els) => els.map((e) => [e.dataset.chartType, !!e.querySelector('canvas'), e.classList.contains('is-pending')]));
    const types = new Set(drawn.filter((d) => d[1]).map((d) => d[0]));
    check(`[${tag}] kit: every chart type drawn`, ['bar', 'stackedBar', 'line', 'waterfall', 'scatter', 'boxplot', 'heatmap', 'ciDot', 'sankey', 'funnel', 'timeline'].every((t) => types.has(t)), [...types]);
    await shot(page, `40_kit_full_${tag}.png`, true);
    check(`[${tag}] kit: no horizontal scroll`, await noHScroll(page));
    if (w === 1440) {
      // tooltip on the first bar chart
      const first = await page.$('.card__chart');
      await first.scrollIntoView(); await sleep(400);
      const b = await first.boundingBox();
      // hover over the third bar (ours)
      for (const fx of [0.82, 0.78, 0.86, 0.75]) {
        await page.mouse.move(b.x + b.width * fx, b.y + b.height * 0.6); await sleep(350);
        if (await page.$('.ct-tip')) break;
      }
      const tipTxt = await page.evaluate(() => { const t = [...document.querySelectorAll('.ct-tip')].find((e) => e.offsetParent); return t ? t.innerText : ''; });
      check('tooltip shows value, 95% CI, n and source', /95% CI/.test(tipTxt) && /\bn\b/i.test(tipTxt) && /source/.test(tipTxt), tipTxt.replace(/\s+/g, ' '));
      await shot(page, `41_kit_tooltip_${tag}.png`);
      // glossary tooltip
      const term = await page.$('[data-term="NPU"]');
      await term.hover(); await sleep(300);
      check('glossary tooltip on hover', !!(await page.$('.tip')));
      await shot(page, `42_kit_glossary_${tag}.png`);
      // rejected chip opens a dialog with the alternative's chart
      await page.mouse.move(5, 5);
      await page.$eval('.chip--rejected', (e) => e.click()); await sleep(900);
      const dlg = await page.$eval('dialog.modal', (d) => [d.open, !!d.querySelector('canvas')]).catch(() => [false, false]);
      check('rejected chip opens the alternative chart', dlg[0] && dlg[1], dlg);
      await shot(page, `43_kit_rejected_${tag}.png`);
      await page.keyboard.press('Escape'); await sleep(300);
      // keyboard: Tab reaches the nav with a visible focus ring
      await page.goto(BASE + '#/deck'); await page.reload({ waitUntil: 'networkidle0' }); await page.waitForSelector('#page-deck');
      await page.keyboard.press('Tab'); await page.keyboard.press('Tab'); await page.keyboard.press('Tab');
      const focused = await page.evaluate(() => document.activeElement && (document.activeElement.className + ' ' + document.activeElement.textContent.trim()).slice(0, 60));
      await shot(page, `44_keyboard_focus_${tag}.png`);
      check('keyboard focus reaches the nav', /nav__/.test(focused), focused);
      // lock button clears the key
      await page.click('#lock');
      await page.waitForFunction(() => document.body.classList.contains('locked'), { timeout: 8000 });
      const keys = await page.evaluate(() => Object.keys(sessionStorage));
      check('lock button clears the key and shows the gate', !keys.includes('site.key.v1'), keys);
      await shot(page, `45_locked_again_${tag}.png`);
    }
  }

  // reduced motion honoured
  {
    const { ctx, page } = await newPage(browser, 1440, 900);
    await page.emulateMediaFeatures([{ name: 'prefers-reduced-motion', value: 'reduce' }]);
    await page.goto(BASE, { waitUntil: 'networkidle0' });
    const fade = await page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue('--fade').trim());
    const anim = await page.evaluate(() => getComputedStyle(document.querySelector('.gate__box')).animationDuration);
    check('prefers-reduced-motion: no fades', /^0m?s/.test(fade) && (anim === '0s' || anim === '0ms'), { fade, anim });
    await ctx.close();
  }

  const errors = results.console.filter((l) => !/favicon|DevTools|Download the React/.test(l));
  check('no console errors', errors.length === 0, errors.slice(0, 10));
  const failed = results.checks.filter((c) => !c.ok).length;
  results.summary = { total: results.checks.length, failed };
  fs.writeFileSync(path.join(OUT, 'results.json'), JSON.stringify(results, null, 1));
  console.log(`\n${results.checks.length - failed}/${results.checks.length} checks passed`);
  await browser.close();
  process.exit(failed ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(2); });
