/* StickyMind frontend — Paper Workspace Edition */
'use strict';

const state = {
  notes: [],
  view: 'all',            // all | today | upcoming | pinned | Study | Work | Personal
  search: '',
  editingId: null,
  selectedColor: 'yellow',
};

const $ = (s) => document.querySelector(s);
const $$ = (s) => Array.from(document.querySelectorAll(s));

const VIEW_TITLES = {
  all: 'All Notes',
  today: 'Today',
  upcoming: 'Upcoming',
  pinned: 'Pinned Notes',
  Study: 'Study',
  Work: 'Work',
  Personal: 'Personal',
};

const EMPTY_STATES = {
  all: { icon: '✎', title: 'Your thoughts go here.', sub: 'Create your first note and make space for your ideas.' },
  today: { icon: '☀️', title: 'Nothing on your list today.', sub: 'Enjoy the clear space.' },
  upcoming: { icon: '⏳', title: 'No upcoming reminders.', sub: 'Your future self will thank you.' },
  pinned: { icon: '📌', title: 'Your important thoughts will live here.', sub: 'Pin a note to keep it close.' },
  search: { icon: '⌕', title: 'No matching notes.', sub: 'Try a different word.' }
};

/* ------------------------------------------------------------------ */
/* API helper                                                          */
/* ------------------------------------------------------------------ */
async function api(url, opts = {}) {
  const res = await fetch(url, {
    headers: { 'Content-Type': 'application/json' },
    ...opts,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ error: `HTTP ${res.status}` }));
    throw new Error(err.error || `HTTP ${res.status}`);
  }
  return res.json();
}

/* ------------------------------------------------------------------ */
/* Toast                                                               */
/* ------------------------------------------------------------------ */
let toastTimer = null;
function toast(msg) {
  const el = $('#toast');
  el.textContent = msg;
  el.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove('show'), 3000);
}

/* ------------------------------------------------------------------ */
/* Helpers                                                             */
/* ------------------------------------------------------------------ */
function escapeHtml(str) {
  const d = document.createElement('div');
  d.textContent = str == null ? '' : String(str);
  return d.innerHTML;
}

function todayLocal() {
  const d = new Date();
  const p = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

function formatDate(iso) {
  if (!iso) return '';
  try {
    return new Date(iso).toLocaleDateString(undefined, {
      month: 'short', day: 'numeric', year: 'numeric',
    });
  } catch {
    return iso.slice(0, 10);
  }
}

function formatDateTime(iso) {
  if (!iso) return '';
  try {
    return new Date(iso).toLocaleString(undefined, {
      month: 'short', day: 'numeric',
      hour: 'numeric', minute: '2-digit',
    });
  } catch {
    return iso;
  }
}

function toLocalInput(iso) {
  const d = new Date(iso);
  const p = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`;
}

/* ------------------------------------------------------------------ */
/* Load + render                                                       */
/* ------------------------------------------------------------------ */
async function loadNotes() {
  try {
    state.notes = await api('/api/notes');
  } catch (e) {
    console.error(e);
    toast('Could not load notes');
    state.notes = [];
  }
  renderNotes();
  updateCounters();
}

function filteredNotes() {
  let list = [...state.notes];
  const now = new Date();
  const today = todayLocal();

  if (state.view === 'pinned') {
    list = list.filter((n) => n.pinned);
  } else if (state.view === 'today') {
    list = list.filter(
      (n) =>
        (n.created_at && n.created_at.slice(0, 10) === today) ||
        (n.reminder_at && n.reminder_at.slice(0, 10) === today)
    );
  } else if (state.view === 'upcoming') {
    list = list.filter((n) => n.reminder_at && new Date(n.reminder_at) > now);
  } else if (['Study', 'Work', 'Personal'].includes(state.view)) {
    list = list.filter((n) => n.category === state.view);
  }

  if (state.search) {
    const q = state.search.toLowerCase();
    list = list.filter(
      (n) =>
        (n.title || '').toLowerCase().includes(q) ||
        (n.content || '').toLowerCase().includes(q)
    );
  }
  return list;
}

function noteCard(note) {
  const title = escapeHtml(note.title) || 'Untitled';
  const content = escapeHtml(note.content);
  return `
    <div class="note-card color-${note.color}" data-id="${note.id}">
      <button class="pin-btn ${note.pinned ? 'pinned' : ''}" data-action="pin"
              title="${note.pinned ? 'Unpin' : 'Pin'}">📌</button>
      <div class="note-title">${title}</div>
      <div class="note-content">${content || '<em style="opacity:.5">No content</em>'}</div>
      <div class="note-meta">
        <span class="category-badge">${escapeHtml(note.category)}</span>
        ${note.reminder_at
          ? `<span class="reminder-badge">⏰ ${escapeHtml(formatDateTime(note.reminder_at))}</span>`
          : ''}
      </div>
      <div class="note-footer">
        <span>${escapeHtml(formatDate(note.created_at))}</span>
        <div class="actions">
          <button data-action="edit" title="Edit">✏️</button>
          <button data-action="delete" title="Delete">🗑️</button>
        </div>
      </div>
    </div>`;
}

function renderNotes() {
  const grid = $('#notesGrid');
  const list = filteredNotes();

  // Update headers
  $('#viewTitle').textContent = VIEW_TITLES[state.view] || 'Notes';
  $('#viewCount').textContent = list.length
    ? `${list.length} thought${list.length !== 1 ? 's' : ''}`
    : '';

  if (!list.length) {
    const empty = state.search ? EMPTY_STATES.search : (EMPTY_STATES[state.view] || EMPTY_STATES.all);
    grid.innerHTML = `
      <div class="empty-state">
        <div class="empty-icon">${empty.icon}</div>
        <div class="empty-title">${empty.title}</div>
        <div class="empty-sub">${empty.sub}</div>
      </div>`;
    return;
  }

  grid.innerHTML = list.map(noteCard).join('');
}

function updateCounters() {
  $('#totalCount').textContent = state.notes.length;
}

/* ------------------------------------------------------------------ */
/* Modal                                                               */
/* ------------------------------------------------------------------ */
function openModal(note = null) {
  state.editingId = note ? note.id : null;
  $('#modalTitle').textContent = note ? 'Edit Note' : 'New Note';
  $('#noteTitle').value = note?.title || '';
  $('#noteContent').value = note?.content || '';
  $('#noteCategory').value = note?.category || 'Personal';
  $('#noteReminder').value = note?.reminder_at ? toLocalInput(note.reminder_at) : '';
  setColor(note?.color || 'yellow');
  $('#noteModal').classList.add('open');
  setTimeout(() => $('#noteTitle').focus(), 100);
}

function closeModal() {
  $('#noteModal').classList.remove('open');
  state.editingId = null;
}

function setColor(color) {
  state.selectedColor = color;
  $$('#colorPicker .swatch').forEach((s) =>
    s.classList.toggle('selected', s.dataset.color === color)
  );
}

/* ------------------------------------------------------------------ */
/* Actions                                                             */
/* ------------------------------------------------------------------ */
async function saveNote() {
  const payload = {
    title: $('#noteTitle').value.trim(),
    content: $('#noteContent').value.trim(),
    category: $('#noteCategory').value,
    color: state.selectedColor,
    reminder_at: $('#noteReminder').value
      ? new Date($('#noteReminder').value).toISOString()
      : null,
  };

  if (!payload.title && !payload.content) {
    toast('Add a title or some content');
    return;
  }

  try {
    if (state.editingId) {
      await api(`/api/notes/${state.editingId}`, {
        method: 'PUT',
        body: JSON.stringify(payload),
      });
    } else {
      await api('/api/notes', {
        method: 'POST',
        body: JSON.stringify(payload),
      });
    }
    closeModal();
    await loadNotes();
    toast('Saved ✓');
  } catch (e) {
    toast(e.message || 'Save failed');
  }
}

async function deleteNote(id) {
  if (!confirm('Delete this note?')) return;
  try {
    await api(`/api/notes/${id}`, { method: 'DELETE' });
    await loadNotes();
    toast('Deleted');
  } catch (e) {
    toast(e.message || 'Delete failed');
  }
}

async function togglePin(id) {
  const note = state.notes.find((n) => n.id === id);
  if (!note) return;
  try {
    await api(`/api/notes/${id}`, {
      method: 'PUT',
      body: JSON.stringify({ pinned: !note.pinned }),
    });
    await loadNotes();
  } catch (e) {
    toast(e.message || 'Pin failed');
  }
}

/* ------------------------------------------------------------------ */
/* Events                                                              */
/* ------------------------------------------------------------------ */
function bindEvents() {
  // Grid interactions
  $('#notesGrid').addEventListener('click', (e) => {
    const card = e.target.closest('.note-card');
    if (!card) return;
    const id = parseInt(card.dataset.id, 10);
    const action = e.target.closest('[data-action]')?.dataset.action;

    if (action === 'pin') {
      e.stopPropagation();
      togglePin(id);
    } else if (action === 'edit') {
      e.stopPropagation();
      openModal(state.notes.find((n) => n.id === id));
    } else if (action === 'delete') {
      e.stopPropagation();
      deleteNote(id);
    } else {
      openModal(state.notes.find((n) => n.id === id));
    }
  });

  // Navigation (Desktop Sidebar & Mobile Bottom Nav)
  const navItems = $$('.nav-item, .chip, .bottom-nav-item');
  navItems.forEach((btn) => {
    if (!btn.dataset.view) return;
    btn.addEventListener('click', () => {
      state.view = btn.dataset.view;
      
      // Update active states
      $$('.nav-item').forEach((b) => b.classList.toggle('active', b.dataset.view === state.view));
      $$('.chip').forEach((b) => b.classList.toggle('active', b.dataset.view === state.view));
      $$('.bottom-nav-item').forEach((b) => b.classList.toggle('active', b.dataset.view === state.view));
      
      renderNotes();
      closeSidebarMobile();
    });
  });

  // Search
  $('#searchInput').addEventListener('input', (e) => {
    state.search = e.target.value.trim();
    renderNotes();
  });

  // New Note Triggers
  $('#newNoteBtn').addEventListener('click', () => openModal());
  if ($('#mobileNewBtn')) $('#mobileNewBtn').addEventListener('click', () => openModal());

  // Mobile Settings/Menu toggle
  if ($('#mobileSettings')) {
    $('#mobileSettings').addEventListener('click', () => {
      $('#sidebar').classList.add('open');
      $('#overlay').classList.add('show');
    });
  }

  // Modal
  $('#modalClose').addEventListener('click', closeModal);
  $('#cancelBtn').addEventListener('click', closeModal);
  $('#saveBtn').addEventListener('click', saveNote);
  $('#noteModal').addEventListener('click', (e) => {
    if (e.target.id === 'noteModal') closeModal();
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') closeModal();
  });

  // Color swatches
  $$('#colorPicker .swatch').forEach((s) => {
    s.addEventListener('click', () => setColor(s.dataset.color));
  });

  // Theme toggle
  $('#themeToggle').addEventListener('click', () => {
    const current = document.documentElement.dataset.theme || 'light';
    const next = current === 'light' ? 'dark' : 'light';
    applyTheme(next);
    localStorage.setItem('sm-theme', next);
  });

  // Mobile overlay close
  $('#overlay').addEventListener('click', closeSidebarMobile);
}

function closeSidebarMobile() {
  $('#sidebar').classList.remove('open');
  $('#overlay').classList.remove('show');
}

function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  $('#themeIcon').textContent = theme === 'dark' ? '☀️' : '🌙';
  $('#themeLabel').textContent = theme === 'dark' ? 'Light mode' : 'Dark mode';
}

/* ------------------------------------------------------------------ */
/* Push notifications                                                  */
/* ------------------------------------------------------------------ */
function urlBase64ToUint8Array(base64String) {
  const padding = '='.repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/');
  const raw = atob(base64);
  const arr = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) arr[i] = raw.charCodeAt(i);
  return arr;
}

function swReady(timeoutMs = 5000) {
  return Promise.race([
    navigator.serviceWorker.ready,
    new Promise((_, rej) =>
      setTimeout(() => rej(new Error('Service worker timeout')), timeoutMs)
    ),
  ]);
}

async function registerServiceWorker() {
  if (!('serviceWorker' in navigator)) return null;
  try {
    return await navigator.serviceWorker.register('/service-worker.js');
  } catch (e) {
    console.warn('SW registration failed:', e);
    return null;
  }
}

async function subscribeToPush() {
  const reg = await swReady();
  const { publicKey } = await api('/api/vapid-public-key');

  let sub = await reg.pushManager.getSubscription();
  if (!sub) {
    sub = await reg.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlBase64ToUint8Array(publicKey),
    });
  }

  await api('/api/push/subscribe', {
    method: 'POST',
    body: JSON.stringify({ subscription: sub }),
  });
  return sub;
}

async function unsubscribeFromPush() {
  const reg = await swReady();
  const sub = await reg.pushManager.getSubscription();
  if (!sub) return;
  try {
    await api('/api/push/unsubscribe', {
      method: 'POST',
      body: JSON.stringify({ subscription: sub }),
    });
  } catch (e) {
    console.warn('unsubscribe notify failed:', e);
  }
  await sub.unsubscribe();
}

async function handleNotifToggle() {
  const btn = $('#notifBtn');
  try {
    if (Notification.permission === 'denied') {
      toast('Notifications blocked. Enable in browser settings.');
      return;
    }

    const reg = await registerServiceWorker();
    if (!reg) {
      toast('Service worker unavailable');
      return;
    }

    const readyReg = await swReady();
    const existing = await readyReg.pushManager.getSubscription();

    if (existing) {
      await unsubscribeFromPush();
      btn.textContent = '🔔';
      toast('Notifications disabled');
      return;
    }

    const perm = Notification.permission === 'granted'
      ? 'granted'
      : await Notification.requestPermission();

    if (perm !== 'granted') {
      toast('Permission denied');
      return;
    }

    await subscribeToPush();
    btn.textContent = '🔕';
    toast('Notifications enabled ✓');
  } catch (e) {
    console.error(e);
    toast(e.message || 'Could not enable notifications');
  }
}

async function initNotifications() {
  const btn = $('#notifBtn');

  if (!('Notification' in window) || !('PushManager' in window)) {
    btn.textContent = '🔕';
    btn.disabled = true;
    return;
  }

  btn.addEventListener('click', handleNotifToggle);

  (async () => {
    try {
      const reg = await registerServiceWorker();
      if (!reg) return;
      const readyReg = await swReady(2500);
      const sub = await readyReg.pushManager.getSubscription();
      if (sub && Notification.permission === 'granted') {
        btn.textContent = '🔕';
      }
    } catch { /* ignore */ }
  })();
}

/* ------------------------------------------------------------------ */
/* Dynamic Header Setup                                                */
/* ------------------------------------------------------------------ */
function setupHeader() {
  const now = new Date();
  const hour = now.getHours();
  
  let greeting = 'Good evening';
  if (hour < 12) greeting = 'Good morning';
  else if (hour < 18) greeting = 'Good afternoon';

  $('#greetingText').textContent = greeting;
  $('#currentDate').textContent = now.toLocaleDateString(undefined, { 
    weekday: 'long', month: 'long', day: 'numeric' 
  });
}

/* ------------------------------------------------------------------ */
/* Client-side reminders + sound                                       */
/* ------------------------------------------------------------------ */

let _audioCtx = null;
let _audioUnlocked = false;

function getAudioCtx() {
  if (!_audioCtx) {
    _audioCtx = new (window.AudioContext || window.webkitAudioContext)();
  }
  if (_audioCtx.state === 'suspended') _audioCtx.resume().catch(() => {});
  return _audioCtx;
}

function playBeep() {
  try {
    const ctx = getAudioCtx();
    [0, 0.25].forEach((offset, i) => {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = 'sine';
      osc.frequency.value = i === 0 ? 880 : 1320;
      gain.gain.setValueAtTime(0.0001, ctx.currentTime + offset);
      gain.gain.exponentialRampToValueAtTime(0.35, ctx.currentTime + offset + 0.01);
      gain.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + offset + 0.2);
      osc.connect(gain).connect(ctx.destination);
      osc.start(ctx.currentTime + offset);
      osc.stop(ctx.currentTime + offset + 0.22);
    });
  } catch (err) {
    console.warn('Beep failed:', err);
  }
}

// Browsers require a user gesture before audio can play.
function unlockAudioOnce() {
  if (_audioUnlocked) return;
  try {
    const ctx = getAudioCtx();
    const o = ctx.createOscillator();
    const g = ctx.createGain();
    g.gain.value = 0;
    o.connect(g).connect(ctx.destination);
    o.start(); o.stop(ctx.currentTime + 0.01);
    _audioUnlocked = true;
  } catch { /* ignore */ }
}
document.addEventListener('click', unlockAudioOnce, { once: true });
document.addEventListener('keydown', unlockAudioOnce, { once: true });

// Dedup across reloads: key is note-id + reminder_at, so editing a reminder
// (which changes reminder_at) allows it to fire again.
const FIRED_KEY = 'sm-fired-reminders';
const firedReminders = new Set(JSON.parse(localStorage.getItem(FIRED_KEY) || '[]'));
function saveFired() {
  localStorage.setItem(FIRED_KEY, JSON.stringify([...firedReminders]));
}

async function checkLocalReminders() {
  // Ask for notification permission once (non-blocking).
  if ('Notification' in window && Notification.permission === 'default') {
    try { await Notification.requestPermission(); } catch { /* ignore */ }
  }

  // Refresh from server so we see reminders the server may have marked.
  let notes = state.notes;
  try {
    notes = await api('/api/notes');
    state.notes = notes;
  } catch { /* offline — fall back to cache */ }

  const now = Date.now();
  let anyFired = false;

  for (const note of notes) {
    if (!note.reminder_at || note.reminder_sent) continue;

    const due = new Date(note.reminder_at).getTime();
    if (isNaN(due) || due > now) continue;

    const dedupKey = `note-${note.id}@${note.reminder_at}`;
    if (firedReminders.has(dedupKey)) continue;

    const title = note.title || 'StickyMind Reminder';
    const body  = (note.content || '').slice(0, 140) || 'You have a reminder';

    // 1) System notification
    if ('Notification' in window && Notification.permission === 'granted') {
      try {
        const reg = await navigator.serviceWorker?.getRegistration();
        if (reg) {
          await reg.showNotification(title, {
            body,
            icon: '/static/icons/icon-192.png',
            badge: '/static/icons/icon-192.png',
            tag: dedupKey,
            vibrate: [200, 100, 200],
          });
        } else {
          new Notification(title, {
            body, icon: '/static/icons/icon-192.png', tag: dedupKey,
          });
        }
      } catch (err) {
        console.warn('Notification failed:', err);
      }
    }

    // 2) Sound (always — even if notifications are blocked)
    playBeep();

    // 3) In-app toast as fallback
    toast(`⏰ ${title}`);

    // 4) Remember locally so we don't fire twice on next poll
    firedReminders.add(dedupKey);
    saveFired();
    anyFired = true;

    // 5) Tell the server so other tabs / future polls skip it
    try {
      await api(`/api/notes/${note.id}`, {
        method: 'PUT',
        body: JSON.stringify({ reminder_sent: true }),
      });
    } catch (err) {
      console.warn('Could not mark reminder as sent:', err);
    }
  }

  if (anyFired) await loadNotes();
}

// Poll every 30 s while the tab is open
setInterval(checkLocalReminders, 30_000);

// Listen for beep requests from the service worker (push path)
if ('serviceWorker' in navigator) {
  navigator.serviceWorker.addEventListener('message', (event) => {
    if (event.data?.type === 'PLAY_BEEP') playBeep();
  });
}

/* ------------------------------------------------------------------ */
/* Boot                                                                */
/* ------------------------------------------------------------------ */
async function boot() {
  applyTheme(localStorage.getItem('sm-theme') || 'light');
  setColor('yellow');
  setupHeader();
  bindEvents();
  await loadNotes();

  // Kick off reminder polling shortly after notes load
  setTimeout(checkLocalReminders, 2_000);

  if (typeof initNotifications === 'function') {
    initNotifications().catch((err) => console.warn('notif init:', err));
  }
}

document.addEventListener('DOMContentLoaded', boot);
