// Journey: static timeline (journey.html); this adds the proof chips and the last step's result from data/today.json.
export default async function mount(ctx) {
  const { root, ui, data, h } = ctx;
  root.querySelector('[data-slot="next"]').append(ui.next('journey', 'today'));

  // proof chips: a link into the Proofs page when the catalog has results from that folder, else the repo path
  const cat = await data.catalog().catch(() => []);
  const files = cat.flatMap((d) => d.source_files || []);
  for (const step of root.querySelectorAll('.jr-step[data-proof]')) {
    const folder = step.dataset.proof;
    const linked = files.some((f) => f === folder || f.startsWith(folder + '/') || f.startsWith(folder + '#'));
    const chip = linked
      ? h('a.chip.chip--source', { href: `#/proofs?file=${encodeURIComponent(folder)}`, title: 'Open the results from this folder' }, h('span', { text: 'Proof' }), h('span.chip__file', { text: folder.replace('proofs/', '') }))
      : h('span.chip.chip--source', { title: 'Folder in the project repository (raw logs, scripts, tables)' }, h('span', { text: 'Proof folder' }), h('span.chip__file', { text: folder }));
    step.append(h('div.jr-proof', null, chip));
  }

  // last step: the final deploy's one-line result, once FINAL_STATUS.md exists
  try {
    const t = await data.json('today.json');
    const f = t.final || {};
    if (f.present && f.result) {
      const dd = root.querySelector('[data-slot="consolidation"]');
      dd.replaceChildren(
        h('span', { text: (f.rolled_back ? 'Rolled back to the known-good state: ' : '') + plain(f.result) + ' ' }),
        h('a', { href: '#/today', text: 'What runs now →' }));
    }
  } catch (e) { /* no today.json in this build: the static line stays */ }
}

function plain(s) {
  return String(s).replace(/`/g, '').replace(/\s+/g, ' ').trim();
}
