'use strict';

// Maquettes C1-01 : fixtures en mémoire, sans serveur, authentification ou envoi.
// Les ensembles d’impact ci-dessous sont scénarisés. Le site utilisera le BFS Python.
const icons = {
  flow: '<circle cx="5" cy="12" r="2"/><circle cx="18" cy="5" r="2"/><circle cx="18" cy="19" r="2"/><path d="M7 12h4a4 4 0 0 0 4-4V5h1M11 12a4 4 0 0 1 4 4v3h1"/>',
  grid: '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
  calendar: '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M16 3v4M8 3v4M3 11h18"/>',
  people: '<circle cx="9" cy="8" r="3"/><path d="M3 21v-2a6 6 0 0 1 12 0v2M17 5a3 3 0 0 1 0 6M21 21v-2a6 6 0 0 0-4-5"/>',
  mail: '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="m3 6 9 7 9-7"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  pin: '<path d="M20 10c0 6-8 12-8 12S4 16 4 10a8 8 0 1 1 16 0Z"/><circle cx="12" cy="10" r="2.5"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2M5 5l1.5 1.5M17.5 17.5 19 19M19 5l-1.5 1.5M6.5 17.5 5 19"/>',
  moon: '<path d="M21 13A9 9 0 0 1 11 3a9 9 0 1 0 10 10Z"/>',
  arrow: '<path d="M5 12h14m-6-6 6 6-6 6"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  check: '<path d="m5 12 4 4L19 6"/>',
  close: '<path d="m6 6 12 12M18 6 6 18"/>',
  workshop: '<path d="M4 21V9l8-6 8 6v12M8 21v-8h8v8M2 21h20"/>',
  journal: '<rect x="4" y="3" width="16" height="18" rx="2"/><path d="M8 8h8M8 12h8M8 16h5"/>',
  shield: '<path d="m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6l8-3Z"/><path d="m8 12 3 3 5-6"/>',
};
const icon = (name) => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${icons[name] || icons.workshop}</svg>`;
const escapeHTML = (value) => String(value).replace(/[&<>"']/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[char]);
const workshops = [
  { id: 'w1', name: 'Cuisine de saison', short: 'Cuisine', start: '14:00', end: '15:00', room: 'La Cuisine', capacity: 12, category: 'Création', downstream: ['w1', 'w2', 'w3'] },
  { id: 'w2', name: 'Dégustation partagée', short: 'Dégustation', start: '15:00', end: '16:00', room: 'La Grande Table', capacity: 18, category: 'Découverte', downstream: ['w2', 'w3'] },
  { id: 'w3', name: 'Accords & échanges', short: 'Accords', start: '16:00', end: '17:00', room: 'Le Salon', capacity: 18, category: 'Échange', downstream: ['w3'] },
  { id: 'w4', name: 'Initiation à la poterie', short: 'Poterie', start: '14:00', end: '15:30', room: 'L’Atelier', capacity: 10, category: 'Création', downstream: ['w4', 'w5'] },
  { id: 'w5', name: 'Vernissage des créations', short: 'Vernissage', start: '16:00', end: '17:00', room: 'La Galerie', capacity: 20, category: 'Découverte', downstream: ['w5'] },
  { id: 'w6', name: 'Balade photographique', short: 'Photo', start: '14:00', end: '15:00', room: 'Le Port', capacity: 12, category: 'Exploration', downstream: ['w6'] },
];
const people = [
  { id: 'alice', name: 'Alice Martin', status: 'pending', enrolled: [] },
  { id: 'sofia', name: 'Sofia Bernard', status: 'accepted', enrolled: ['w1'] },
  { id: 'mehdi', name: 'Mehdi Benali', status: 'accepted', enrolled: ['w2'] },
  { id: 'lina', name: 'Lina Moreau', status: 'accepted', enrolled: ['w3'] },
  { id: 'nora', name: 'Nora Petit', status: 'accepted', enrolled: ['w4'] },
  { id: 'hugo', name: 'Hugo Laurent', status: 'accepted', enrolled: ['w5'] },
  { id: 'emma', name: 'Emma Robert', status: 'accepted', enrolled: ['w6'] },
  { id: 'alex', name: 'Alex Dubois', status: 'accepted', enrolled: [] },
  { id: 'bruno', name: 'Bruno Lefèvre', status: 'declined', enrolled: [] },
  { id: 'chloe', name: 'Chloé Garcia', status: 'pending', enrolled: [] },
];
const alice = people[0];
let selectedSource = 'w1';
let journal = [];
let toastTimer;
let lastFocused;
let invitationSelection = new Set(['w1', 'w2']);
const originalTimes = Object.fromEntries(workshops.map((w) => [w.id, w.start]));
const app = document.querySelector('#app');
const dialog = document.querySelector('#change-dialog');
const workshop = (id) => workshops.find((w) => w.id === id);
const confirmed = () => people.filter((p) => p.status === 'accepted');
const impacted = (source) => confirmed().filter((p) => p.enrolled.some((id) => workshop(source).downstream.includes(id)));
const enrolledCount = (id) => confirmed().filter((p) => p.enrolled.includes(id)).length;
const formatTime = (value) => value.replace(':', ' h ');
const initials = (name) => name.split(' ').slice(0, 2).map((part) => part[0]).join('');
const badge = (text, style = '') => `<span class="badge ${style}">${text}</span>`;
const brand = () => `<a class="brand" href="#organisateur" aria-label="ImpactFlow, accueil de la maquette"><span class="brand-mark">${icon('flow')}</span>ImpactFlow</a>`;
const themeButton = () => `<button class="icon-button theme-toggle" type="button" aria-label="Passer en mode ${document.documentElement.dataset.theme === 'dark' ? 'clair' : 'nuit'}">${icon(document.documentElement.dataset.theme === 'dark' ? 'sun' : 'moon')}</button>`;
const meta = () => `<div class="meta"><span>${icon('calendar')}Jeudi 22 octobre 2026</span><span>${icon('clock')}14 h – 18 h</span><span>${icon('pin')}Les Ateliers du Port, Nice</span></div>`;

function toast(message) {
  clearTimeout(toastTimer);
  const element = document.querySelector('#feedback');
  element.textContent = message;
  element.classList.add('visible');
  toastTimer = setTimeout(() => element.classList.remove('visible'), 4500);
}

function renderGraph() {
  const source = workshop(selectedSource);
  const node = (id) => {
    const w = workshop(id);
    const role = id === selectedSource ? 'source' : source.downstream.includes(id) ? 'cascade' : '';
    const label = role === 'source' ? 'source' : role === 'cascade' ? 'en cascade' : 'épargné';
    return `<button class="graph-node ${role}" data-source="${id}" type="button" aria-pressed="${id === selectedSource}" aria-label="${w.short}, ${label} : sélectionner comme source"><strong>${w.short}</strong><small>${enrolledCount(id)} inscrit${enrolledCount(id) > 1 ? 's' : ''} · ${label}</small></button>`;
  };
  return `<div class="graph" aria-label="Dépendances des ateliers, une flèche va de la source à l’atelier dépendant">
    <div class="graph-row">${node('w1')}<span class="graph-arrow" aria-hidden="true">→</span>${node('w2')}<span class="graph-arrow" aria-hidden="true">→</span>${node('w3')}</div>
    <div class="graph-row">${node('w4')}<span class="graph-arrow" aria-hidden="true">→</span>${node('w5')}<span class="graph-arrow" aria-hidden="true">·</span>${node('w6')}</div>
  </div>`;
}

function dashboard() {
  const affected = impacted(selectedSource);
  return `<div class="shell">
    <aside class="sidebar">${brand()}<p class="workspace-label">Espace organisateur</p>
      <div class="nav-label">Votre événement</div>
      <nav class="side-nav" aria-label="Navigation organisateur">
        <a href="#organisateur" class="active">${icon('grid')}Vue d’ensemble</a>
        <a href="#programme">${icon('calendar')}Programme & ateliers</a>
        <a href="#participants">${icon('people')}Participants</a>
        <a href="#journal">${icon('journal')}Journal des changements</a>
      </nav>
      <div class="sidebar-note">${icon('flow')}<strong>Les bonnes personnes.<br>Au bon moment.</strong>Chaque changement a son impact. Chaque message a sa raison.</div>
      <div class="profile"><span class="avatar">TM</span><div><strong>Thomas Mercier</strong><small>Responsable de l’événement</small></div></div>
    </aside>
    <div class="main-wrap"><header class="topbar"><div class="breadcrumb"><span>Mes événements</span><span aria-hidden="true">/</span><span>Rencontres créatives</span></div><div class="top-actions"><small>Événement sur invitation</small>${themeButton()}<span class="avatar" aria-label="Thomas Mercier">TM</span></div></header>
    <main class="main" id="main" tabindex="-1">
      <div class="page-heading"><div><div class="eyebrow">Votre prochain rendez-vous ${badge('Publié')}</div><h1>Les Rencontres créatives</h1>${meta()}</div><button type="button" class="button primary" data-change="${selectedSource}">${icon('plus')}Créer un changement</button></div>
      <div class="stats">
        ${stat('Participants confirmés', confirmed().length, 'Des participations réellement acceptées', 'people')}
        ${stat('Ateliers au programme', workshops.length, 'Deux chaînes et un atelier indépendant', 'calendar')}
        ${stat('Invitations en attente', people.filter((p) => p.status === 'pending').length, 'Aucune inscription active à ce stade', 'mail')}
        ${stat('E-mails envoyés', 0, 'Aucun envoi externe dans cette maquette', 'check')}
      </div>
      <div class="dashboard-grid"><section class="panel" aria-labelledby="graph-title"><div class="panel-head"><div><h2 id="graph-title">Chaque atelier est connecté.</h2><p>Sélectionnez un atelier pour explorer son impact.</p></div>${badge('Aperçu', 'neutral')}</div><div class="legend"><span><i></i>Source</span><span><i class="cascade"></i>En cascade</span><span><i class="spared"></i>Épargné</span></div>${renderGraph()}<div class="panel-foot">${icon('flow')}Une flèche propage l’information vers l’atelier dépendant.</div></section>
      <section class="panel" aria-labelledby="impact-title"><div class="panel-head"><div><h2 id="impact-title">Un impact ciblé</h2><p>Si ${escapeHTML(workshop(selectedSource).short)} change…</p></div>${icon('people')}</div><div class="impact-highlight"><span class="big-number">${affected.length}<span style="font-size:17px;opacity:.6"> / ${confirmed().length}</span></span><small>personnes à prévenir, sans doublon</small></div><div class="impact-line"><span class="muted">Ateliers concernés</span><strong>${workshop(selectedSource).downstream.length} sur 6</strong></div><div class="impact-line"><span class="muted">Participants épargnés</span><strong>${confirmed().length - affected.length}</strong></div><div class="impact-people" aria-label="${escapeHTML(affected.map((p) => p.name).join(', '))}">${affected.map((p) => `<span class="avatar" title="${p.name}">${initials(p.name)}</span>`).join('')}</div><div class="panel-foot">${icon('shield')}Refus et invitations en attente exclus.</div></section></div>
      <section class="panel" id="programme" aria-labelledby="programme-title"><div class="panel-head"><div><h2 id="programme-title">Le programme, en un regard</h2><p>6 ateliers pour apprendre, créer et se rencontrer.</p></div><a class="button small" href="#invitation">Voir l’invitation ${icon('arrow')}</a></div><div class="table-scroll"><table><thead><tr><th scope="col">Atelier</th><th scope="col">Horaire</th><th scope="col">Lieu</th><th scope="col">Inscrits</th><th scope="col"><span class="muted">Action</span></th></tr></thead><tbody>${workshops.map((w) => `<tr><td><div class="workshop-name"><span class="workshop-icon">${icon('workshop')}</span><div><strong>${w.name}</strong><small>${w.category}</small></div></div></td><td>${formatTime(w.start)} – ${formatTime(w.end)}</td><td>${w.room}</td><td>${enrolledCount(w.id)} <span class="muted">/ ${w.capacity}</span></td><td><button type="button" class="table-link" data-change="${w.id}">Modifier<span class="sr-label"> ${w.short}</span></button></td></tr>`).join('')}</tbody></table></div></section>
      <section class="panel" id="participants" style="margin-top:22px" aria-labelledby="people-title"><div class="panel-head"><div><h2 id="people-title">Des réponses, des personnes</h2><p>Une invitation n’est pas encore une inscription.</p></div><a href="#invitation" class="button small">Parcours d’Alice ${icon('arrow')}</a></div><div class="table-scroll"><table><thead><tr><th scope="col">Participant</th><th scope="col">Réponse</th><th scope="col">Ateliers actifs</th></tr></thead><tbody>${people.map((p) => `<tr><td><strong>${p.name}</strong><small>${p.id}@example.test</small></td><td>${badge(p.status === 'accepted' ? 'Acceptée' : p.status === 'pending' ? 'En attente' : 'Refusée', p.status === 'accepted' ? '' : p.status === 'pending' ? 'waiting' : 'neutral')}</td><td>${p.enrolled.map((id) => workshop(id).short).join(', ') || 'Aucun'}</td></tr>`).join('')}</tbody></table></div></section>
      <section class="panel" id="journal" style="margin-top:22px" aria-labelledby="journal-title"><div class="panel-head"><div><h2 id="journal-title">Journal des changements</h2><p>Les actions de cette session de maquette.</p></div>${badge('Session locale', 'neutral')}</div>${journal.length ? `<ul class="activity-list">${journal.map((item) => `<li><strong>${escapeHTML(item.title)}</strong><small>${escapeHTML(item.detail)}</small></li>`).join('')}</ul>` : '<div class="empty-state">Aucun changement pour le moment. Créez-en un pour explorer l’aperçu d’impact.</div>'}</section>
      <footer class="footer-note"><span>ImpactFlow · Moins de bruit, plus de coordination.</span><span>Maquettes C1-01 · Aucune donnée enregistrée sur un serveur</span></footer>
    </main></div></div>`;
}

function stat(label, value, detail, name) {
  return `<section class="stat" aria-label="${label}"><div class="stat-top"><span>${label}</span>${icon(name)}</div><strong>${String(value).padStart(2, '0')}</strong><small>${detail}</small></section>`;
}

function publicHeader(participant = false) {
  return `<header class="public-header">${brand()}<div class="top-actions">${participant ? '<small>Espace participant</small><span class="avatar">AM</span>' : '<a href="#participant" class="button small">Mon espace</a>'}${themeButton()}</div></header>`;
}

function invitation() {
  const answered = alice.status !== 'pending';
  return `${publicHeader()}<main class="public-main" id="main" tabindex="-1"><section class="invitation-hero"><div><div class="eyebrow">Une invitation de Thomas Mercier</div><h1>Une après-midi pour<br>créer des liens.</h1><p>Cuisiner, façonner, échanger. Retrouvez-nous aux Rencontres créatives et composez le programme qui vous ressemble.</p>${meta()}</div><div class="date-stamp" aria-hidden="true"><small>Jeudi</small><strong>22</strong><small>Octobre 2026</small></div></section>
    ${answered ? `<div class="feedback-success"><strong>${alice.status === 'accepted' ? 'Votre participation est confirmée dans la maquette.' : 'Votre refus est enregistré dans la maquette.'}</strong>${alice.status === 'accepted' ? `${alice.enrolled.length} atelier(s) choisi(s). Retrouvez votre programme dans votre espace.` : 'Aucune participation ni place active n’a été créée.'} <a href="#participant" class="table-link">Ouvrir mon espace →</a></div>` : ''}
    <div class="invitation-layout"><section aria-labelledby="choices-title"><div class="section-heading"><h2 id="choices-title">À vous de composer votre après-midi.</h2><p>Choisissez librement vos ateliers, dans la limite des places et des horaires.</p></div><form id="invitation-form"><div class="choices">${workshops.map((w) => `<label class="workshop-choice"><input type="checkbox" name="workshop" value="${w.id}" ${invitationSelection.has(w.id) ? 'checked' : ''} ${answered ? 'disabled' : ''}><span class="choice-body"><strong>${w.name}</strong><span class="meta"><span>${icon('clock')}${formatTime(w.start)} – ${formatTime(w.end)}</span><span>${icon('pin')}${w.room}</span></span></span><span class="choice-places">${w.capacity - enrolledCount(w.id)} places disponibles</span></label>`).join('')}</div></form><p class="muted" style="font-size:11px;margin-top:16px">Les ateliers liés peuvent être choisis séparément. Une dépendance sert à vous prévenir des changements qui vous concernent.</p></section>
      <aside><section class="panel summary-box"><span class="avatar">AM</span><h2>Bonjour Alice.</h2><p>Cette invitation vous est personnellement adressée par Thomas.</p>${badge(answered ? alice.status === 'accepted' ? 'Invitation acceptée' : 'Invitation refusée' : 'En attente de votre réponse', answered ? alice.status === 'accepted' ? '' : 'neutral' : 'waiting')}<hr class="divider"><div class="selection-summary" id="selection-summary"></div><div class="form-error" id="invitation-error" role="alert"></div><button type="submit" form="invitation-form" class="button primary" ${answered ? 'disabled' : ''}>${icon('check')}Accepter l’invitation</button><button type="button" class="button quiet" id="decline" ${answered ? 'disabled' : ''}>Décliner l’invitation</button><p class="privacy-note">Consulter cette page ne change pas votre réponse. Votre choix n’est enregistré qu’après confirmation.</p></section><p class="muted" style="font-size:10px;padding:14px 8px">Prototype : les réponses restent en mémoire jusqu’au rechargement. La création de compte sera reliée au serveur lors du développement.</p></aside>
    </div><footer class="footer-note"><span>ImpactFlow · Chaque invitation ouvre une rencontre.</span><span>Des questions ? Thomas sera votre interlocuteur.</span></footer></main>`;
}

function participant() {
  const accepted = alice.status === 'accepted';
  return `${publicHeader(true)}<main class="public-main" id="main" tabindex="-1"><div class="participant-heading"><div><div class="eyebrow">Votre espace personnel</div><h1>Bonjour Alice<span style="color:var(--accent-text)">.</span></h1><p>Vos rendez-vous, vos ateliers. Juste ce qui vous concerne.</p></div>${badge('Compte de démonstration', 'neutral')}</div>
    <div class="participant-grid"><div><section class="event-ticket">${badge(accepted ? 'Participation confirmée' : alice.status === 'pending' ? 'Invitation en attente' : 'Invitation refusée', accepted ? '' : 'waiting')}<h2>Les Rencontres créatives</h2>${meta()}${!accepted ? `<p class="muted" style="font-size:12px;margin-top:15px">${alice.status === 'pending' ? 'Répondez à votre invitation et choisissez vos ateliers pour retrouver votre programme ici.' : 'Vous n’avez aucune inscription active à cet événement.'}</p><a class="button small" style="margin-top:8px" href="#invitation">Voir mon invitation ${icon('arrow')}</a>` : ''}</section>
    <section class="panel" style="margin-top:22px" aria-labelledby="planning-title"><div class="panel-head"><div><h2 id="planning-title">Votre après-midi prend forme</h2><p>Jeudi 22 octobre · votre planning personnel</p></div>${icon('calendar')}</div>${accepted && alice.enrolled.length ? `<div class="schedule">${alice.enrolled.map(workshop).sort((a, b) => a.start.localeCompare(b.start)).map((w) => `<article class="schedule-item"><div class="schedule-time">${w.start}<small>${w.end}</small></div><div><h3>${w.name}</h3><p>${w.room} · ${w.category}</p></div></article>`).join('')}</div>` : `<div class="empty-state">${icon('calendar')}<strong>Aucun atelier réservé pour le moment.</strong>${accepted ? 'Vous participez à l’événement sans inscription à un atelier.' : 'Votre programme apparaîtra après acceptation de l’invitation.'}</div>`}</section></div>
    <aside><section class="panel" aria-labelledby="inbox-title"><div class="panel-head"><div><h2 id="inbox-title">Vos notifications</h2><p>Un fil réservé à ce qui vous concerne.</p></div>${icon('mail')}</div>${journal.some((item) => item.preview && item.recipients.includes('alice')) ? journal.filter((item) => item.preview && item.recipients.includes('alice')).map((item) => `<article class="inbox-item"><span class="badge neutral">Aperçu · non envoyé</span><h3 style="margin-top:10px">${escapeHTML(item.title)}</h3><p>${escapeHTML(item.detail)}</p><small>Un exemple du contenu à préparer côté serveur.</small></article>`).join('') : `<div class="empty-state">${icon('mail')}<strong>Tout est calme.</strong>Aucune notification envoyée dans cette maquette.</div>`}</section><section class="panel" style="margin-top:20px"><div class="panel-head"><div><h2>Moins de messages.<br>Les bonnes informations.</h2><p>Un changement sur un atelier indépendant ne vous interrompt pas. Et plusieurs corrections rapprochées deviennent une seule information cohérente.</p></div></div></section></aside></div><footer class="footer-note"><span>Les horaires de vos ateliers sont affichés à l’heure de Paris.</span><span>Session fictive · aucune authentification réelle</span></footer></main>`;
}

function updateSelection() {
  const element = document.querySelector('#selection-summary');
  if (!element) return;
  element.innerHTML = `<strong>${invitationSelection.size} atelier${invitationSelection.size > 1 ? 's' : ''} sélectionné${invitationSelection.size > 1 ? 's' : ''}</strong><span>${[...invitationSelection].map((id) => workshop(id).short).join(' · ') || 'Vous pouvez également participer sans atelier.'}</span>`;
}

function render() {
  const hash = location.hash.slice(1);
  const page = hash === 'invitation' ? 'invitation' : hash === 'participant' ? 'participant' : 'organisateur';
  app.innerHTML = page === 'invitation' ? invitation() : page === 'participant' ? participant() : dashboard();
  document.querySelectorAll('.preview-nav a').forEach((link) => {
    if (link.hash === `#${page}`) link.setAttribute('aria-current', 'page');
    else link.removeAttribute('aria-current');
  });
  document.title = `${page === 'invitation' ? 'Votre invitation' : page === 'participant' ? 'Mon espace' : 'Vue d’ensemble'} — ImpactFlow`;
  updateSelection();
  if (['programme', 'participants', 'journal'].includes(hash)) document.getElementById(hash).scrollIntoView({ block: 'start' });
}

function openChange(id) {
  selectedSource = id;
  lastFocused = document.activeElement;
  const w = workshop(id);
  dialog.innerHTML = `<form id="change-form"><div class="dialog-head"><div><div class="eyebrow">Un changement, le bon impact</div><h2 id="dialog-title">Modifier ${w.short}</h2></div><button type="button" class="icon-button" id="close-dialog" aria-label="Fermer l’aperçu">${icon('close')}</button></div><p>Vérifiez l’impact avant de confirmer le nouvel horaire.</p><div class="form-grid"><label>Début actuel<input type="text" value="${formatTime(w.start)}" readonly></label><label>Nouveau début<input id="new-start" type="time" value="${w.start}" required min="14:00" max="17:00"></label></div><div id="change-preview"></div><p>Les ateliers dépendants conservent leur horaire. Une notification les informe de l’impact. Les conflits existants seront signalés.</p><div class="dialog-actions"><button type="button" class="button" id="cancel-change">Annuler</button><button type="submit" class="button primary" id="confirm-change">Confirmer le changement ${icon('arrow')}</button></div></form>`;
  dialog.showModal();
  updateChangePreview();
}

function updateChangePreview() {
  const w = workshop(selectedSource);
  const next = document.querySelector('#new-start').value;
  const affected = impacted(w.id);
  const noChange = !next || next === w.start;
  const returnsToStart = next === originalTimes[w.id];
  const recipients = noChange || returnsToStart ? [] : affected;
  const minutes = (time) => Number(time.slice(0, 2)) * 60 + Number(time.slice(3));
  const newEnd = minutes(next) + minutes(w.end) - minutes(w.start);
  const conflicts = noChange ? [] : confirmed().filter((p) => p.enrolled.includes(w.id) && p.enrolled.some((id) => id !== w.id && minutes(next) < minutes(workshop(id).end) && minutes(workshop(id).start) < newEnd));
  document.querySelector('#change-preview').innerHTML = `<div class="preview-box"><h3>${noChange ? 'Aucune modification' : returnsToStart ? 'Retour à l’horaire initial' : `${recipients.length} personne${recipients.length > 1 ? 's' : ''} concernée${recipients.length > 1 ? 's' : ''}`}</h3><p>${noChange ? 'Choisissez un nouvel horaire pour découvrir son impact.' : returnsToStart ? 'Le changement reste dans l’historique. Aucune notification pour ce retour à la valeur initiale avant envoi.' : `${formatTime(w.start)} → ${formatTime(next)} · ${w.downstream.length} atelier(s) dans la propagation · ${confirmed().length - affected.length} participant(s) épargné(s).`}</p>${recipients.length ? `<div class="recipient-list">${recipients.map((p) => `<div><strong>${p.name}</strong><span>${p.enrolled.includes(w.id) ? 'Inscription directe' : 'En cascade'}</span></div>`).join('')}</div>` : ''}${conflicts.length ? `<p><strong>Conflit à vérifier :</strong> ${conflicts.map((p) => p.name).join(', ')} a un autre atelier sur ce créneau. Les inscriptions seront conservées.</p>` : ''}</div>`;
  document.querySelector('#confirm-change').disabled = noChange;
}

function closeDialog() {
  dialog.close();
  if (lastFocused?.isConnected) lastFocused.focus();
}

document.addEventListener('click', (event) => {
  const source = event.target.closest('[data-source]');
  const change = event.target.closest('[data-change]');
  if (source) {
    const scroll = window.scrollY;
    selectedSource = source.dataset.source;
    render();
    window.scrollTo(0, scroll);
    document.querySelector(`[data-source="${selectedSource}"]`).focus({ preventScroll: true });
  }
  if (change) openChange(change.dataset.change);
  if (event.target.closest('.theme-toggle')) {
    const next = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem('impactflow-theme', next); } catch (_) { /* Le thème reste utilisable sans stockage. */ }
    document.querySelectorAll('.theme-toggle').forEach((button) => {
      button.innerHTML = icon(next === 'dark' ? 'sun' : 'moon');
      button.setAttribute('aria-label', `Passer en mode ${next === 'dark' ? 'clair' : 'nuit'}`);
    });
  }
  if (event.target.closest('#reset')) location.reload();
  if (event.target.closest('#close-dialog, #cancel-change')) closeDialog();
  if (event.target.closest('#decline') && alice.status === 'pending') {
    alice.status = 'declined';
    alice.enrolled = [];
    invitationSelection.clear();
    journal.unshift({ title: 'Alice a décliné son invitation', detail: 'Aucune participation ni inscription active créée.' });
    render();
    toast('Refus enregistré dans cette session de maquette.');
  }
});

document.addEventListener('change', (event) => {
  if (event.target.matches('input[name="workshop"]')) {
    if (event.target.checked) invitationSelection.add(event.target.value);
    else invitationSelection.delete(event.target.value);
    updateSelection();
    document.querySelector('#invitation-error').textContent = '';
  }
});
document.addEventListener('input', (event) => {
  if (event.target.id === 'new-start') updateChangePreview();
});

document.addEventListener('submit', (event) => {
  if (event.target.id === 'invitation-form') {
    event.preventDefault();
    if (alice.status !== 'pending') return;
    const chosen = [...invitationSelection].map(workshop);
    for (let a = 0; a < chosen.length; a++) {
      for (let b = a + 1; b < chosen.length; b++) {
        if (chosen[a].start < chosen[b].end && chosen[b].start < chosen[a].end) {
          document.querySelector('#invitation-error').textContent = `${chosen[a].short} et ${chosen[b].short} se chevauchent. Modifiez votre sélection avant de confirmer.`;
          return;
        }
      }
    }
    alice.status = 'accepted';
    alice.enrolled = [...invitationSelection];
    journal.unshift({ title: 'Alice a accepté son invitation', detail: `${chosen.length} atelier(s) choisi(s) · participation active dans la maquette.` });
    render();
    toast('Participation simulée confirmée. Votre programme est prêt dans Mon espace.');
  }
  if (event.target.id === 'change-form') {
    event.preventDefault();
    const w = workshop(selectedSource);
    const next = document.querySelector('#new-start').value;
    if (!next || next === w.start) return;
    const previous = w.start;
    const duration = Number(w.end.slice(0, 2)) * 60 + Number(w.end.slice(3)) - Number(previous.slice(0, 2)) * 60 - Number(previous.slice(3));
    const endMinutes = Number(next.slice(0, 2)) * 60 + Number(next.slice(3)) + duration;
    if (endMinutes > 18 * 60) {
      toast('Cet atelier finirait après la clôture de l’événement à 18 h.');
      return;
    }
    w.start = next;
    w.end = `${String(Math.floor(endMinutes / 60)).padStart(2, '0')}:${String(endMinutes % 60).padStart(2, '0')}`;
    const affected = impacted(w.id);
    const returnsToStart = next === originalTimes[w.id];
    const title = `${w.short} : ${formatTime(previous)} → ${formatTime(next)}`;
    journal = journal.map((item) => item.workshopId === w.id ? { ...item, preview: false } : item);
    journal.unshift({ title, detail: returnsToStart ? 'Retour à l’horaire initial · historique conservé, aucune notification à préparer.' : `${affected.length} personne(s) concernée(s) · aperçu fictif, aucun e-mail envoyé.`, preview: !returnsToStart, recipients: affected.map((p) => p.id), workshopId: w.id });
    closeDialog();
    render();
    document.querySelector(`[data-change="${w.id}"]`)?.focus({ preventScroll: true });
    toast('Changement enregistré dans la maquette uniquement.');
  }
});

dialog.addEventListener('click', (event) => {
  if (event.target === dialog && (event.clientX < dialog.getBoundingClientRect().left || event.clientX > dialog.getBoundingClientRect().right || event.clientY < dialog.getBoundingClientRect().top || event.clientY > dialog.getBoundingClientRect().bottom)) closeDialog();
});
window.addEventListener('hashchange', () => {
  render();
  if (['#organisateur', '#invitation', '#participant'].includes(location.hash)) {
    window.scrollTo(0, 0);
    document.querySelector('#main').focus({ preventScroll: true });
  }
});
render();
