'use strict';

(() => {
  const root = document.documentElement;
  const system = matchMedia('(prefers-color-scheme: dark)');
  let saved;
  try { saved = localStorage.getItem('impactflow-theme'); } catch (_) { /* Stockage facultatif. */ }
  root.dataset.theme = ['light', 'dark'].includes(saved) ? saved : system.matches ? 'dark' : 'light';
  document.addEventListener('DOMContentLoaded', () => {
    const button = document.querySelector('#theme-toggle');
    const update = () => {
      button.textContent = root.dataset.theme === 'dark' ? '☀' : '☾';
      button.setAttribute('aria-label', `Passer en mode ${root.dataset.theme === 'dark' ? 'clair' : 'nuit'}`);
    };
    update();
    button.addEventListener('click', () => {
      root.dataset.theme = root.dataset.theme === 'dark' ? 'light' : 'dark';
      saved = root.dataset.theme;
      try { localStorage.setItem('impactflow-theme', saved); } catch (_) { /* Le thème reste utilisable. */ }
      update();
    });
    system.addEventListener('change', () => {
      if (!['light', 'dark'].includes(saved)) {
        root.dataset.theme = system.matches ? 'dark' : 'light';
        update();
      }
    });
  });
})();
