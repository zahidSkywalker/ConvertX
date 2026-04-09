/**
 * ConvertX Service Worker
 * 
 * Strategy:
 * - App Shell (HTML, Manifest): Cached on install.
 * - Static Assets (JS/CSS/Images): Network-first, falling back to cache.
 * - API Calls (/api/*): Network-only (don't cache short-lived download UUIDs).
 * - Offline Fallback: Serves offline.html for failed navigation requests.
 */

const CACHE_NAME = 'convertx-v1';
const OFFLINE_URL = '/offline.html';

// Files to precache immediately on SW install
const PRECACHE_URLS = [
  '/',
  '/index.html',
  '/manifest.json',
  '/offline.html'
];

// Install event: Precache core shell
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then((cache) => cache.addAll(PRECACHE_URLS))
      .then(() => self.skipWaiting()) // Activate immediately
  );
});

// Activate event: Clean up old caches
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((cacheNames) => {
      return Promise.all(
        cacheNames
          .filter((name) => name !== CACHE_NAME)
          .map((name) => caches.delete(name))
      );
    }).then(() => self.clients.claim()) // Take control of all pages
  );
});

// Fetch event: Routing logic
self.addEventListener('fetch', (event) => {
  const { request } = event;
  const url = new URL(request.url);

  // 1. API Requests: Network only
  if (url.pathname.startsWith('/api/')) {
    return; // Let the browser handle it naturally
  }

  // 2. Navigation Requests (HTML pages): Network -> Cache -> Offline
  if (request.mode === 'navigate') {
    event.respondWith(
      fetch(request)
        .then((response) => {
          // Cache the latest version of the HTML
          const clone = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(request, clone));
          return response;
        })
        .catch(() => {
          // Network failed, try cache
          return caches.match(request).then((cached) => {
            return cached || caches.match(OFFLINE_URL);
          });
        })
    );
    return;
  }

  // 3. Static Assets (JS, CSS, Images): Network -> Cache (Stale-While-Revalidate logic)
  event.respondWith(
    caches.match(request).then((cached) => {
      const fetchPromise = fetch(request).then((response) => {
        // Update cache with fresh version
        if (response.ok) {
          caches.open(CACHE_NAME).then((cache) => cache.put(request, response));
        }
        return response.clone();
      }).catch(() => {
        // Network failed, return cached if available
        return cached;
      });

      // Return cached immediately if available, otherwise wait for network
      return cached || fetchPromise;
    })
  );
});
