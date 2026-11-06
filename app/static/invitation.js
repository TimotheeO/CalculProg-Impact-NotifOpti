'use strict';

(() => {
  const page = location.pathname;
  if (!['/activation-organisateur', '/invitations', '/reinitialisation'].includes(page)) return;
  const token = new URLSearchParams(location.hash.slice(1)).get(page === '/reinitialisation' ? 'reset' : 'invitation');
  if (!token) return;
  // Le secret ne doit pas apparaître dans les URL de requête, logs HTTP ou Referer.
  history.replaceState(null, '', location.pathname);
  const feedback = document.querySelector('#invitation-feedback');
  const csrf = document.querySelector('#invitation-csrf');
  if (!feedback || !csrf) return;
  feedback.textContent = 'Ouverture de votre invitation…';
  fetch(`${page}/preparer`, {
    method: 'POST', credentials: 'same-origin', redirect: 'error',
    headers: {'Content-Type': 'application/x-www-form-urlencoded'},
    body: new URLSearchParams({token, csrf_token: csrf.value}),
  }).then((response) => {
    if (response.ok) location.replace(page);
    else {
      feedback.className = 'form-error';
      feedback.textContent = response.status === 410 ? 'Cette invitation est invalide, expirée ou déjà utilisée.' : response.status === 429 ? 'Trop de tentatives. Réessayez dans quinze minutes.' : 'Impossible d’ouvrir cette invitation. Rechargez la page et réessayez avec le lien reçu.';
    }
  }).catch(() => {
    feedback.className = 'form-error';
    feedback.textContent = 'Le serveur est indisponible. Réessayez avec le lien reçu dans votre invitation.';
  });
})();
