'use strict';
(() => {
  for (const root of document.querySelectorAll('[data-impact-graph]')) {
    let graph;
    try { graph = JSON.parse(root.dataset.impactGraph); } catch (_) { continue; }
    const status = root.querySelector('[data-graph-status]');
    const select = (id, preview = false) => {
      const reached = new Set([id]);
      if (preview) graph.changed.forEach(key => reached.add(key));
      else {
        const queue = [id];
        for (let index = 0; index < queue.length; index++) {
          for (const edge of graph.edges) if (edge.from === queue[index] && !reached.has(edge.to)) { reached.add(edge.to); queue.push(edge.to); }
        }
      }
      for (const node of root.querySelectorAll('[data-node-id]')) {
        const source = node.dataset.nodeId === id;
        node.classList.toggle('graph-source', source);
        node.classList.toggle('graph-cascade', !source && reached.has(node.dataset.nodeId));
        node.setAttribute('aria-pressed', String(source));
      }
      const name = graph.nodes.find(node => node.id === id)?.name || '';
      root.querySelector('[data-graph-cascade-label]').textContent = preview ? 'Conséquence proposée' : 'Dépendant';
      status.textContent = preview ? `Aperçu de ${name} : ${Math.max(0, graph.changed.length - 1)} conséquence(s) proposée(s). Les autres ateliers sont épargnés.` : `${name} : ${Math.max(0, reached.size - 1)} dépendant(s). Un changement ne les modifie que si les règles métier l’exigent.`;
    };
    root.addEventListener('click', event => { const node = event.target.closest('[data-node-id]'); if (node) select(node.dataset.nodeId); });
    root.addEventListener('keydown', event => { if (['Enter', ' '].includes(event.key)) { const node = event.target.closest('[data-node-id]'); if (node) { event.preventDefault(); select(node.dataset.nodeId); } } });
    root.querySelector('[data-graph-reset]')?.addEventListener('click', () => select(graph.source, true));
    if (graph.source) select(graph.source, graph.preview);
  }
})();
