'use strict';
(() => {
  const element = document.querySelector('[data-live-url]');
  if (!element) return;
  const status = document.querySelector('#live-status');
  let busy = false;
  setInterval(async () => {
    if (busy || document.hidden) return;
    busy = true;
    try {
      const response = await fetch(element.dataset.liveUrl, {credentials: 'same-origin', cache: 'no-store', redirect: 'error'});
      if (!response.ok) throw new Error('unavailable');
      const data = await response.json();
      if (data.revision !== element.dataset.liveRevision) location.reload();
      else if (status) status.textContent = 'À jour · vérification toutes les 2 secondes.';
    } catch (_) {
      if (status) status.textContent = 'Actualisation indisponible. Nouvelle vérification dans 2 secondes.';
    } finally { busy = false; }
  }, 2000);
})();
