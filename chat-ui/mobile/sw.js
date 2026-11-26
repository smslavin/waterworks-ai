// Shell cache only (waterworks-ai#6 Phase 2). API calls and the SSE stream
// are never cached: alerts and reviews must be live or visibly unavailable.
// Also shows Web Push notifications (gh-80): chat-ui/push.py sends
// {title, body, tag, url}.
// Bump CACHE when a shell file changes so installed copies pick it up.
'use strict';

const CACHE = 'waterworks-mobile-v6';
const SHELL = [
  './',
  'index.html',
  'app.js',
  'style.css',
  'manifest.json',
  'icons/icon-192.png',
  'icons/icon-512.png',
  'icons/apple-touch-icon.png',
];

self.addEventListener('install', (event) => {
  event.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)));
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);
  if (event.request.method !== 'GET' || url.origin !== location.origin) return;
  if (!url.pathname.startsWith('/mobile/')) return; // /api/* goes straight to the network

  // Network first so a running plant always serves the current shell; the
  // cache only answers when the plant can't be reached.
  event.respondWith(
    fetch(event.request)
      .then((resp) => {
        if (resp.ok) {
          const copy = resp.clone();
          caches.open(CACHE).then((c) => c.put(event.request, copy));
        }
        return resp;
      })
      .catch(() => caches.match(event.request, { ignoreSearch: true })),
  );
});

self.addEventListener('push', (event) => {
  let msg = {};
  try { msg = event.data ? event.data.json() : {}; } catch { /* not JSON */ }
  event.waitUntil(self.registration.showNotification(msg.title || 'Waterworks', {
    body: msg.body || '',
    tag: msg.tag,           // a repeat replaces the earlier one
    renotify: Boolean(msg.tag),
    icon: 'icons/icon-192.png',
    badge: 'icons/icon-192.png',
    data: { url: msg.url || './' },
  }));
});

// Tapping a notification brings the page forward, opening it if needed.
self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const target = new URL(event.notification.data?.url || './', self.registration.scope).href;
  event.waitUntil((async () => {
    const open = await clients.matchAll({ type: 'window', includeUncontrolled: true });
    const page = open.find((c) => c.url.startsWith(self.registration.scope));
    if (page) return page.focus();
    return clients.openWindow(target);
  })());
});
