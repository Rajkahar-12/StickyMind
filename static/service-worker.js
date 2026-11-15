/* StickyMind Service Worker */
'use strict';

const CACHE_NAME = 'stickymind-v4';   // bump this when app.js/style.css change

const APP_SHELL = [
  '/',
  '/static/css/style.css',
  '/static/js/app.js',
  '/static/manifest.json',
  '/static/icons/icon-192.png',
  '/static/icons/icon-512.png',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(APP_SHELL)).catch(() => {})
  );
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

/* Network-first for navigation, cache-first for assets */
self.addEventListener('fetch', (event) => {
  const req = event.request;

  if (req.method !== 'GET') return;

  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;
  if (url.pathname.startsWith('/api/')) return;   // never cache API

  if (req.mode === 'navigate') {
    event.respondWith(
      fetch(req)
        .then((res) => {
          const copy = res.clone();
          caches.open(CACHE_NAME).then((c) => c.put(req, copy)).catch(() => {});
          return res;
        })
        .catch(() => caches.match(req).then((hit) => hit || caches.match('/')))
    );
    return;
  }

  event.respondWith(
    caches.match(req).then((hit) => {
      if (hit) return hit;
      return fetch(req).then((res) => {
        const copy = res.clone();
        caches.open(CACHE_NAME).then((c) => c.put(req, copy)).catch(() => {});
        return res;
      });
    })
  );
});

/* Push notifications — show + tell every open tab to beep */
self.addEventListener('push', (event) => {
  let payload = { title: 'StickyMind', body: 'You have a reminder', note_id: null };
  if (event.data) {
    try { payload = { ...payload, ...event.data.json() }; } catch { /* ignore */ }
  }

  const tag = payload.note_id ? `note-${payload.note_id}` : 'stickymind-reminder';

  event.waitUntil(
    Promise.all([
      self.registration.showNotification(payload.title, {
        body: payload.body,
        icon: '/static/icons/icon-192.png',
        badge: '/static/icons/icon-192.png',
        tag,
        vibrate: [200, 100, 200],
        data: { note_id: payload.note_id, url: '/' },
      }),
      self.clients.matchAll({ type: 'window', includeUncontrolled: true })
        .then((clients) => clients.forEach((c) => {
          try { c.postMessage({ type: 'PLAY_BEEP' }); } catch { /* ignore */ }
        })),
    ])
  );
});

/* Click on a notification → focus or open the app */
self.addEventListener('notificationclick', (event) => {
  event.notification.close();

  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clients) => {
      for (const client of clients) {
        if (client.url.includes(self.registration.scope) && 'focus' in client) {
          return client.focus();
        }
      }
      if (self.clients.openWindow) return self.clients.openWindow('/');
    })
  );
});
