'use strict';

// Le serveur reçoit toujours YYYY-MM-DDTHH:mm en heure civile de Paris.
// Les valeurs ne sont appliquées qu’après validation explicite du dialogue.
(() => {
  const dialog = document.querySelector('#datetime-picker');
  if (!dialog || typeof dialog.showModal !== 'function') return;
  const byId = (id) => dialog.querySelector('#' + id);
  const dateInput = byId('datetime-date');
  const hourInput = byId('datetime-hours');
  const minuteInput = byId('datetime-minutes');
  const monthSelect = byId('calendar-month');
  const yearSelect = byId('calendar-year');
  const days = byId('calendar-days');
  const dial = byId('clock-dial');
  const error = byId('datetime-error');
  const pad = (number) => String(number).padStart(2, '0');
  const dateKey = (date) => `${date.year}-${pad(date.month + 1)}-${pad(date.day)}`;
  const frenchDate = new Intl.DateTimeFormat('fr-FR', {day: 'numeric', month: 'long', year: 'numeric', timeZone: 'UTC'});
  const fullDate = new Intl.DateTimeFormat('fr-FR', {weekday: 'long', day: 'numeric', month: 'long', year: 'numeric', timeZone: 'UTC'});
  const monthName = new Intl.DateTimeFormat('fr-FR', {month: 'long', timeZone: 'UTC'});
  let active = null;
  let draft = null;
  let visibleMonth = null;
  let mode = 'hours';
  let dragging = false;

  function validDate(year, month, day) {
    const value = new Date(Date.UTC(year, month, day));
    return year >= 1900 && year <= 2100 && value.getUTCFullYear() === year && value.getUTCMonth() === month && value.getUTCDate() === day;
  }

  function readDate(text) {
    const parts = /^(\d{2})\/(\d{2})\/(\d{4})$/.exec(text);
    if (!parts) return null;
    const [, day, month, year] = parts.map(Number);
    return validDate(year, month - 1, day) ? {year, month: month - 1, day} : null;
  }

  function readValue(value) {
    const parts = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})$/.exec(value);
    if (!parts) return null;
    const [, year, month, day, hour, minute] = parts.map(Number);
    return validDate(year, month - 1, day) && hour < 24 && minute < 60 ? {year, month: month - 1, day, hour, minute} : null;
  }

  function parisNow() {
    const parts = Object.fromEntries(new Intl.DateTimeFormat('fr-FR', {
      timeZone: 'Europe/Paris', year: 'numeric', month: 'numeric', day: 'numeric',
      hour: 'numeric', minute: 'numeric', hourCycle: 'h23',
    }).formatToParts(new Date()).filter((part) => part.type !== 'literal').map((part) => [part.type, Number(part.value)]));
    return {year: parts.year, month: parts.month - 1, day: parts.day, hour: parts.hour, minute: parts.minute};
  }

  function showError(message, control) {
    error.textContent = message;
    error.hidden = false;
    if (control) {
      control.setAttribute('aria-invalid', 'true');
      control.focus();
    }
  }

  function clearError() {
    error.hidden = true;
    for (const input of [dateInput, hourInput, minuteInput]) input.removeAttribute('aria-invalid');
  }

  function writeDate() {
    dateInput.value = `${pad(draft.day)}/${pad(draft.month + 1)}/${draft.year}`;
  }

  function setDate(date, focusDay = false) {
    Object.assign(draft, date);
    visibleMonth = {year: date.year, month: date.month};
    writeDate();
    clearError();
    renderCalendar(focusDay ? date.day : null);
  }

  function renderCalendar(focusDay = null) {
    const {year, month} = visibleMonth;
    monthSelect.value = String(month);
    yearSelect.value = String(year);
    const caption = `${monthName.format(new Date(Date.UTC(year, month, 1)))} ${year}`;
    byId('calendar-caption').textContent = caption;
    days.setAttribute('aria-label', caption);
    byId('calendar-previous').disabled = year === 1900 && month === 0;
    byId('calendar-next').disabled = year === 2100 && month === 11;
    const firstWeekday = (new Date(Date.UTC(year, month, 1)).getUTCDay() + 6) % 7;
    const count = new Date(Date.UTC(year, month + 1, 0)).getUTCDate();
    const today = dateKey(parisNow());
    const tabDay = focusDay || (year === draft.year && month === draft.month ? draft.day : 1);
    days.replaceChildren();
    for (let blank = 0; blank < firstWeekday; blank += 1) {
      const spacer = document.createElement('span');
      spacer.setAttribute('aria-hidden', 'true');
      days.append(spacer);
    }
    for (let day = 1; day <= count; day += 1) {
      const button = document.createElement('button');
      const date = {year, month, day};
      button.type = 'button';
      button.textContent = String(day);
      button.dataset.day = String(day);
      button.tabIndex = day === tabDay ? 0 : -1;
      button.setAttribute('aria-label', fullDate.format(new Date(Date.UTC(year, month, day))));
      button.setAttribute('aria-pressed', String(dateKey(date) === dateKey(draft)));
      if (dateKey(date) === today) button.setAttribute('aria-current', 'date');
      button.addEventListener('click', () => setDate(date, true));
      button.addEventListener('keydown', (event) => {
        const delta = {ArrowLeft: -1, ArrowRight: 1, ArrowUp: -7, ArrowDown: 7,
          Home: -((new Date(Date.UTC(year, month, day)).getUTCDay() + 6) % 7),
          End: 6 - ((new Date(Date.UTC(year, month, day)).getUTCDay() + 6) % 7)}[event.key];
        if (delta === undefined) return;
        event.preventDefault();
        const next = new Date(Date.UTC(year, month, day + delta));
        if (validDate(next.getUTCFullYear(), next.getUTCMonth(), next.getUTCDate())) {
          setDate({year: next.getUTCFullYear(), month: next.getUTCMonth(), day: next.getUTCDate()}, true);
        }
      });
      days.append(button);
    }
    if (focusDay !== null) days.querySelector(`[data-day="${focusDay}"]`)?.focus();
  }

  function changeMonth(delta) {
    const next = new Date(Date.UTC(visibleMonth.year, visibleMonth.month + delta, 1));
    if (next.getUTCFullYear() < 1900 || next.getUTCFullYear() > 2100) return;
    visibleMonth = {year: next.getUTCFullYear(), month: next.getUTCMonth()};
    renderCalendar();
  }

  function svgElement(name, attributes, text) {
    const element = document.createElementNS('http://www.w3.org/2000/svg', name);
    for (const [key, value] of Object.entries(attributes)) element.setAttribute(key, String(value));
    if (text !== undefined) element.textContent = text;
    return element;
  }

  function point(slot, radius) {
    const angle = slot * Math.PI / 6;
    return {x: 130 + Math.sin(angle) * radius, y: 130 - Math.cos(angle) * radius};
  }

  function renderClock() {
    const isHours = mode === 'hours';
    const value = isHours ? draft.hour : draft.minute;
    const selected = point(isHours ? value % 12 : value / 5, isHours && (value === 0 || value > 12) ? 68 : 103);
    byId('clock-hours').setAttribute('aria-pressed', String(isHours));
    byId('clock-minutes').setAttribute('aria-pressed', String(!isHours));
    dial.setAttribute('aria-label', isHours ? 'Heures, format 24 heures' : 'Minutes');
    dial.setAttribute('aria-valuemax', isHours ? '23' : '59');
    dial.setAttribute('aria-valuenow', String(value));
    dial.setAttribute('aria-valuetext', `${pad(value)} ${isHours ? 'heures' : 'minutes'}`);
    dial.replaceChildren(svgElement('circle', {cx: 130, cy: 130, r: 124, class: 'clock-face', 'aria-hidden': true}));
    dial.append(svgElement('line', {x1: 130, y1: 130, x2: selected.x, y2: selected.y, class: 'clock-hand', 'aria-hidden': true}));
    dial.append(svgElement('circle', {cx: selected.x, cy: selected.y, r: 17, class: 'clock-selection', 'aria-hidden': true}));
    dial.append(svgElement('circle', {cx: 130, cy: 130, r: 4, class: 'clock-selection', 'aria-hidden': true}));
    for (let index = 0; index < (isHours ? 24 : 12); index += 1) {
      const number = isHours ? index : index * 5;
      const inner = isHours && (number === 0 || number > 12);
      const position = point(index % 12, inner ? 68 : 103);
      dial.append(svgElement('text', {x: position.x, y: position.y, dy: '.35em',
        class: `clock-number${inner ? ' clock-inner' : ''}${number === value ? ' clock-chosen' : ''}`, 'aria-hidden': true}, pad(number)));
    }
  }

  function selectMode(value, focus = false) {
    mode = value;
    renderClock();
    if (focus) dial.focus();
  }

  function selectPoint(event) {
    const bounds = dial.getBoundingClientRect();
    const x = (event.clientX - bounds.left) * 260 / bounds.width - 130;
    const y = (event.clientY - bounds.top) * 260 / bounds.height - 130;
    const distance = Math.hypot(x, y);
    if (distance < 35) return;
    const angle = (Math.atan2(x, -y) + Math.PI * 2) % (Math.PI * 2);
    if (mode === 'hours') {
      const slot = Math.round(angle * 6 / Math.PI) % 12;
      draft.hour = distance < 85 ? (slot === 0 ? 0 : slot + 12) : (slot === 0 ? 12 : slot);
      hourInput.value = pad(draft.hour);
    } else {
      draft.minute = Math.round(angle * 30 / Math.PI) % 60;
      minuteInput.value = pad(draft.minute);
    }
    clearError();
    renderClock();
  }

  function open(input, trigger, missing = false) {
    active = {input, trigger};
    draft = readValue(input.value) || parisNow();
    visibleMonth = {year: draft.year, month: draft.month};
    mode = 'hours';
    clearError();
    writeDate();
    hourInput.value = pad(draft.hour);
    minuteInput.value = pad(draft.minute);
    byId('datetime-context').textContent = trigger.dataset.label;
    renderCalendar();
    renderClock();
    dialog.showModal();
    if (missing) showError('Choisissez une date et une heure, puis validez le créneau.', dateInput);
    else dateInput.focus();
  }

  function updateTrigger(input, trigger) {
    const value = readValue(input.value);
    trigger.querySelector('.datetime-value').textContent = value
      ? `${frenchDate.format(new Date(Date.UTC(value.year, value.month, value.day)))} · ${pad(value.hour)}:${pad(value.minute)}`
      : 'Choisir la date et l’heure';
    trigger.setAttribute('aria-label', `${trigger.dataset.label} : ${trigger.querySelector('.datetime-value').textContent}, heure de Paris`);
    trigger.setAttribute('aria-invalid', String(input.getAttribute('aria-invalid') === 'true'));
  }

  for (let month = 0; month < 12; month += 1) monthSelect.add(new Option(monthName.format(new Date(Date.UTC(2026, month, 1))), String(month)));
  for (let year = 1900; year <= 2100; year += 1) yearSelect.add(new Option(String(year), String(year)));
  byId('calendar-previous').addEventListener('click', () => changeMonth(-1));
  byId('calendar-next').addEventListener('click', () => changeMonth(1));
  for (const control of [monthSelect, yearSelect]) control.addEventListener('change', () => {
    visibleMonth = {year: Number(yearSelect.value), month: Number(monthSelect.value)};
    renderCalendar();
  });
  dateInput.addEventListener('input', () => {
    const date = readDate(dateInput.value);
    if (date) {
      Object.assign(draft, date);
      visibleMonth = {year: date.year, month: date.month};
      clearError();
      renderCalendar();
    }
  });
  for (const [input, part, maximum] of [[hourInput, 'hour', 23], [minuteInput, 'minute', 59]]) {
    input.addEventListener('focus', () => selectMode(part === 'hour' ? 'hours' : 'minutes'));
    input.addEventListener('input', () => {
      if (/^\d{1,2}$/.test(input.value) && Number(input.value) <= maximum) {
        draft[part] = Number(input.value);
        clearError();
        renderClock();
      }
    });
    input.addEventListener('blur', () => {
      if (/^\d{1,2}$/.test(input.value) && Number(input.value) <= maximum) input.value = pad(Number(input.value));
    });
  }
  byId('clock-hours').addEventListener('click', () => selectMode('hours', true));
  byId('clock-minutes').addEventListener('click', () => selectMode('minutes', true));
  dial.addEventListener('pointerdown', (event) => {
    if (event.button !== 0) return;
    dragging = true;
    dial.setPointerCapture(event.pointerId);
    dial.focus();
    selectPoint(event);
  });
  dial.addEventListener('pointermove', (event) => { if (dragging) selectPoint(event); });
  dial.addEventListener('pointerup', (event) => {
    if (!dragging) return;
    selectPoint(event);
    dragging = false;
    if (dial.hasPointerCapture(event.pointerId)) dial.releasePointerCapture(event.pointerId);
    if (mode === 'hours') selectMode('minutes');
  });
  dial.addEventListener('pointercancel', () => { dragging = false; });
  dial.addEventListener('keydown', (event) => {
    const maximum = mode === 'hours' ? 23 : 59;
    const part = mode === 'hours' ? 'hour' : 'minute';
    const delta = {ArrowUp: 1, ArrowRight: 1, ArrowDown: -1, ArrowLeft: -1}[event.key];
    if (delta === undefined && !['Home', 'End', 'Enter'].includes(event.key)) return;
    event.preventDefault();
    if (event.key === 'Enter') { selectMode('minutes'); return; }
    draft[part] = event.key === 'Home' ? 0 : event.key === 'End' ? maximum : (draft[part] + delta + maximum + 1) % (maximum + 1);
    (part === 'hour' ? hourInput : minuteInput).value = pad(draft[part]);
    clearError();
    renderClock();
  });

  function apply() {
    const date = readDate(dateInput.value);
    if (!date) { showError('Renseignez une date valide au format JJ/MM/AAAA, entre 1900 et 2100.', dateInput); return; }
    if (!/^\d{1,2}$/.test(hourInput.value) || Number(hourInput.value) > 23) { showError('Choisissez une heure entre 00 et 23.', hourInput); return; }
    if (!/^\d{1,2}$/.test(minuteInput.value) || Number(minuteInput.value) > 59) { showError('Choisissez des minutes entre 00 et 59.', minuteInput); return; }
    const value = `${dateKey(date)}T${pad(Number(hourInput.value))}:${pad(Number(minuteInput.value))}`;
    const {input, trigger} = active;
    if ((input.min && value < input.min) || (input.max && value > input.max)) { showError('Choisissez un créneau compris dans la période autorisée.', dateInput); return; }
    input.value = value;
    input.removeAttribute('aria-invalid');
    updateTrigger(input, trigger);
    input.dispatchEvent(new Event('change', {bubbles: true}));
    dialog.close();
  }
  byId('datetime-apply').addEventListener('click', apply);
  for (const input of [dateInput, hourInput, minuteInput]) input.addEventListener('keydown', (event) => {
    if (event.key === 'Enter') { event.preventDefault(); apply(); }
  });
  for (const button of dialog.querySelectorAll('[data-datetime-close]')) button.addEventListener('click', () => dialog.close());
  dialog.addEventListener('close', () => { dragging = false; active?.trigger.focus(); });

  const forms = new Map();
  for (const input of document.querySelectorAll('input[type="datetime-local"][data-french-datetime]')) {
    const label = document.querySelector(`label[for="${input.id}"]`);
    const trigger = document.createElement('button');
    trigger.type = 'button';
    trigger.id = input.id + '-picker';
    trigger.className = 'datetime-trigger';
    trigger.dataset.label = label?.textContent.trim() || 'Date et heure';
    trigger.setAttribute('aria-haspopup', 'dialog');
    trigger.setAttribute('aria-controls', dialog.id);
    if (input.hasAttribute('aria-describedby')) trigger.setAttribute('aria-describedby', input.getAttribute('aria-describedby'));
    const icon = document.createElement('span');
    icon.className = 'datetime-icon';
    icon.textContent = '◷';
    icon.setAttribute('aria-hidden', 'true');
    const text = document.createElement('span');
    text.className = 'datetime-value';
    trigger.append(text, icon);
    input.type = 'hidden';
    input.after(trigger);
    if (label) label.htmlFor = trigger.id;
    updateTrigger(input, trigger);
    input.addEventListener('change', () => updateTrigger(input, trigger));
    trigger.addEventListener('click', () => open(input, trigger));
    const entries = forms.get(input.form) || [];
    entries.push({input, trigger});
    forms.set(input.form, entries);
  }
  for (const [form, entries] of forms) form.addEventListener('submit', (event) => {
    const invalid = entries.find(({input}) => !readValue(input.value) || (input.min && input.value < input.min) || (input.max && input.value > input.max));
    if (invalid) {
      event.preventDefault();
      invalid.trigger.setAttribute('aria-invalid', 'true');
      open(invalid.input, invalid.trigger, true);
    }
  });
})();
