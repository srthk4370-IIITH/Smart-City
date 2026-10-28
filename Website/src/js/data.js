// Encrypted data loader. Every path is relative to Website/data/ (plain at build time, *.enc in dist/data/).
import { decryptBytes, decryptJSON } from './crypto.js';

export function createData() {
  const cache = new Map();
  const once = (key, fn) => { if (!cache.has(key)) cache.set(key, fn().catch((e) => { cache.delete(key); throw e; })); return cache.get(key); };

  const data = {
    /** Any JSON file under data/, e.g. json('latency/htpd_route.json') */
    json: (path) => once('j:' + path, () => decryptJSON('data/' + path)),
    /** Raw bytes (already un-gzipped once: a packs/*.json.gz comes back as the .gz bytes) */
    bytes: (path) => decryptBytes('data/' + path),
    catalog: () => data.json('catalog.json').then((c) => (Array.isArray(c) ? c : c.datasets || [])),
    decisions: () => data.json('decisions.json'),
    route: () => data.json('route.json'),
    qa: () => data.json('qa.json'),
    status: () => data.json('status.json'),
    /** Catalog entry for an id (or undefined). */
    entry: async (id) => (await data.catalog()).find((e) => e.id === id),
    /**
     * Dataset by catalog id ('htpd_route') or by path ('latency/htpd_route' / 'latency/htpd_route.json').
     * Resolves to {meta, series, ci?}.
     */
    dataset: async (id) => {
      if (id.includes('/')) return data.json(id.endsWith('.json') ? id : id + '.json');
      const e = await data.entry(id);
      if (!e) throw new Error(`dataset "${id}" is not in data/catalog.json`);
      const ds = await data.json(`${e.topic}/${e.id}.json`);
      ds.meta = { ...e, ...(ds.meta || {}) };
      return ds;
    },
    /** Decrypt a data file and hand it to the visitor as a download (e.g. a data pack). */
    download: async (path, filename) => {
      const bytes = await data.bytes(path);
      const url = URL.createObjectURL(new Blob([bytes], { type: path.endsWith('.json') ? 'application/json' : 'application/octet-stream' }));
      const a = document.createElement('a');
      a.href = url; a.download = filename || path.split('/').pop();
      document.body.append(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 5000);
    },
  };
  return data;
}
