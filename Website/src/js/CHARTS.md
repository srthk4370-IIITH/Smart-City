# Chart kit and page contract (for page agents)

Everything a page needs arrives in `ctx`. Do not load scripts, fonts or CSS from anywhere else; do not hard-code colours.
The live demo of every component is the hidden page `#/kit` (`src/pages/kit.html` + `kit.js`): copy from it.

## 1. Where a page lives

| File | Required | Notes |
|---|---|---|
| `src/pages/<page>.html` | yes | Page body, injected into `<main>` inside `<div class="page" id="page-<page>">`. No `<script>` tags (they do not run). |
| `src/pages/<page>.js` | yes | ES module. `export default async function mount(ctx) { ... return cleanup? }` |
| `src/pages/<page>.css` | optional | Page-only styles; injected as a `<style>` in the page. Use the tokens (`var(--accent)` ...). |
| `src/pages/<anything>/<file>` | optional | Images/assets. Load with `await ctx.asset('img/x.png')` -> blob URL. |

`<page>` is one of `route`, `decisions`, `proofs`, `qa` (and `deck`, `kit`, owned by SHELL). All of these files are
encrypted by the build; nothing in `src/pages/` is ever served in plain text. Files starting with `_` (e.g.
`_glossary.json`) are shared data; `*.md` is not published.

The module runs from a `blob:` URL, so **it cannot `import` other files**. Use what `ctx` gives you.

## 2. `ctx`

| Key | What |
|---|---|
| `root` | the page element (your HTML is already inside) |
| `page`, `params`, `query` | route parts. `#/decisions/d12?x=1` -> `page='decisions'`, `params=['d12']`, `query={x:'1'}` |
| `data` | encrypted data loader (below) |
| `charts` | chart kit (below) |
| `ui` | components (below) |
| `h(tag, attrs, ...children)` | DOM helper: `h('div.card', {text:'hi', onclick: fn}, child)` |
| `asset(path)` | decrypts `src/pages/<path>` -> blob URL (for `<img src>`) |
| `nav('#/qa')` | navigate |
| `onCleanup(fn)` | run `fn` when the user leaves the page (timers, listeners) |
| `glossary` | the glossary dict (`src/pages/_glossary.json`) |

## 3. Data (`ctx.data`), all decrypted on demand and cached

```js
const cat  = await ctx.data.catalog();          // array of catalog entries (data/catalog.json .datasets)
const ds   = await ctx.data.dataset('lat_htpd_ab');        // {meta, series, ci?} by catalog id
const ds2  = await ctx.data.dataset('latency/lat_htpd_ab'); // or by path under data/
const dec  = await ctx.data.decisions();        // data/decisions.json
const route= await ctx.data.route();            // data/route.json
const qa   = await ctx.data.qa();               // data/qa.json
const st   = await ctx.data.status();           // data/status.json
const any  = await ctx.data.json('topic/file.json');
await ctx.data.download('packs/latency.json.gz', 'latency.json.gz');   // "download the numbers"
```

## 4. Cards (use these; they make every chart look alike)

```js
// simplest: everything from the dataset (meta.claim, meta.why, meta.chart.type, meta.source_files)
grid.append(ctx.ui.card({ id: 'lat_htpd_ab', span: 6 }));

// explicit
grid.append(ctx.ui.card({
  claim: '47 s -> 21 s for 13 agents',            // one line, the takeaway (<= 12 words)
  why:   'An operator sees the incident report before the next reading.', // one line (<= 20 words)
  chart: { type: 'waterfall', id: 'lat_route_13_agents', opts: { unit: 's' } },
  rejected: [                                        // optional "what we rejected" chips -> open a dialog
    { label: 'GPU path', claim: 'GPU was 3x slower at equal accuracy', id: 'hw_gpu_batched' },
  ],
  span: 12,                                          // 4 | 6 | 8 | 12 inside a .grid
}));
```
- Put cards in `<div class="grid">`. On phones every card is full width.
- `chart.data` instead of `chart.id` takes an inline dataset object (or a Promise of one).
- The source chip is automatic (from `meta.source_files` / `meta.script`) and links to `#/proofs?file=<path>`.
  Override with `source: {files:[...], script}`.
- `body` (node or HTML string) adds extra content under the chart.

Other components:
```js
ctx.ui.anchor({ before: '47 s', after: '21 s', label: 'Incident analysis, 13 agents, on the NPU', meta: 'n = 20 runs' })
ctx.ui.anchors([{...}, {...}])     // a row of big numbers
ctx.ui.chip('kept', 'good')        // kinds: ours | good | warn | bad | rejected | source
ctx.ui.sourceChip(meta)
ctx.ui.modal('Title', node)        // dialog (Esc / backdrop closes)
ctx.ui.startHere()                 // Route -> Decisions -> Q&A
ctx.ui.next('route')               // "Next -> Decisions" footer (default order deck>route>decisions>qa>proofs)
ctx.ui.statusStrip(statusJson)
ctx.ui.term('NPU')                 // glossary term element; or in HTML: <span data-term="NPU">NPU</span>
```
Glossary terms in your HTML (`<span data-term="htpd">htpd</span>` or `<abbr>`) are wired automatically after
`mount`. Add missing definitions to `src/pages/_glossary.json` (one line each, plain words).

CSS classes you can use in page HTML: `section`, `label` (mono small caps), `statement` (one big line),
`lead`, `muted`, `grid` + `span-4|6|8|12`, `card`, `chip`, `btn`, `btn--solid`.

## 5. Charts directly

```js
const h = ctx.charts.bar(el, dataset, opts);   // also: stackedBar line waterfall scatter boxplot heatmap ciDot sankey funnel timeline
const h = ctx.charts.render(el, 'auto', ctx.data.dataset('id'), opts);  // 'auto' = meta.chart.type (fallback bar)
h.ready.then(echartsInstance => ...); h.drawNow(); h.update(newDataset, newOpts); h.dispose();
```
`dataset` may be an object or a Promise. Charts draw when scrolled into view (IntersectionObserver) and resize with
their box. The router disposes charts when the page changes.

### Dataset shape (the data contract; DATA agent writes it)
```js
{ meta: { id, title, unit, n, source_files:[...], script, claim?, why?,
          chart?: { type, x?, y?, highlight_x?, log_y? } },
  series: [ { name, role: 'ours'|'alt'|'ref', points: [ { x, y, n?, k?, lo?, hi?, label?, note? } ] } ],
  ci?: [ { series?, x, lo, hi } ] }
```
- `role:'ours'` (series or point) -> accent blue. Everything else -> greys. `ref` -> dashed/muted.
- `lo/hi` (or `ci:[lo,hi]`) -> 95 % CI whiskers / bands and in the tooltip. `k` + `n` -> "k / n" in the tooltip.
- `unit: 'fraction'` is shown as percent (x100). Pass `opts.fraction = 'raw'` to keep 0-1.
- `meta.chart.x` naming a point field (e.g. `"agents"`) uses that field as x; otherwise it is the x-axis title.
- `meta.chart.highlight_x: '4 h'` marks that x as the chosen option (accent bar / point / vertical line).
- `data` may be used instead of `points`; `[x, y]` pairs are accepted.

Per type:
| type | points | notes |
|---|---|---|
| `bar` | `{x, y, n?, lo?, hi?}` per series | grouped when several series; auto-horizontal on phones when > 4 bars; `opts.horizontal` forces |
| `stackedBar` | same; one series per stack part | `opts.percent` -> 100 % stacks |
| `line` | `{x, y, lo?, hi?}` | x numeric -> value axis, `YYYY-MM-DD...` -> time axis, else category; CI as band; `opts.area`, `opts.step` |
| `waterfall` | **levels**: `{x, y}` = value after each step (first and last are totals) **or** explicit `{x, y, kind:'total'|'delta'}` | lower-is-better by default (`opts.higherIsBetter`, auto for %) ; several series fall back to a line |
| `scatter` | `{x, y, label?, size?}` | `opts.diagonal: [[0,0],[40,40]]`; string x -> category axis |
| `boxplot` | `{x, min, q1, median, q3, max, n?}` (`y` = median and missing quartiles are tolerated) | |
| `heatmap` | `{x, y:row, v}` **or** contract `{x, y:value, <meta.chart.y field>:row}` **or** one row per series | `opts.diverging`, `opts.reverse`, `opts.xOrder/yOrder` |
| `ciDot` | `{x:label, y, lo, hi, n}` | point + 95 % CI, one row per label; `opts.ref: 0, refLabel` |
| `sankey` | series[0] = `{nodes:[{name, ours?}], links:[{source, target, value}]}` | |
| `funnel` | `{x:stage, y}` | |
| `timeline` | `{date|x, label?, outcome?: kept|dropped|pending|replaced, severity?, y?}` | lane = series name (or y if y is a string); numeric y sizes the dot |

Common `opts`: `unit`, `xName`, `yName`, `yMin`, `yMax`, `logY`, `decimals`, `format(v)`, `labels` (bool),
`legend` (bool), `order` (category order), `markLine: [{y, label}]`, `height` (px), `horizontal`, `eager`
(draw now), `onClick(point)`.

## 6. Rules (SPEC.md)
- Ours = accent, alternatives = grey, always shown **next to** a baseline.
- One claim above, one "why it matters" below, source chip on every chart. n and CI on the chart.
- Motion: fades only (already handled). No extra animation libraries.
- No raw sensor values, prompts or windows anywhere in pages.
