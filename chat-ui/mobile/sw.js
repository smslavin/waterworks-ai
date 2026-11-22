// Shell cache only (waterworks-ai#6 Phase 2). API calls and the SSE stream
// are never cached: alerts and reviews must be live or visibly unavailable.
// Bump CACHE when a shell file changes so installed copies pick it up.
'use strict';

const CACHE = 'waterworks-mobile-v4';
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
