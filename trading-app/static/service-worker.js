const CACHE_NAME = 'controln-trading-v6.2';

// Static assets to precache
const PRECACHE_ASSETS = [
  '/',
  '/static/index.html',
  '/static/admin.html',
  '/static/app.js',
  '/static/styles.css',
  '/static/logo.png',
  '/static/logo-192.png',
  '/static/logo-512.png',
  '/static/lightweight-charts.js',
  '/static/manifest.json'
];

// Install event - precache static assets
self.addEventListener('install', event => {
  self.skipWaiting(); // Force new SW to become active immediately (auto-cache-busting part 1)
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then(cache => {
        return cache.addAll(PRECACHE_ASSETS);
      })
  );
});

// Activate event - clean up old caches
self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(cacheNames => {
      return Promise.all(
        cacheNames.filter(name => name !== CACHE_NAME)
          .map(name => caches.delete(name))
      );
    }).then(() => self.clients.claim()) // Claim clients immediately (auto-cache-busting part 2)
  );
});

// Fetch event - Stale-While-Revalidate for static, Network First for API
self.addEventListener('fetch', event => {
  // Ignore non-GET requests (like POST for APIs) and WebSockets
  if (event.request.method !== 'GET' || !event.request.url.startsWith('http')) {
    return;
  }

  const url = new URL(event.request.url);
  const isApi = url.pathname.startsWith('/api/');

  // D3: sensitive financial/account API paths must NEVER be written to or served from Cache
  // Storage — cached responses persist on-disk on the client and could be read by anything with
  // local device/devtools access, and stale data must never be served offline for these. These
  // paths are network-only (no cache read, no cache write).
  const SENSITIVE_API_PREFIXES = [
    '/api/funds', '/api/positions', '/api/orders',
    '/api/admin/', '/api/user/settings'
  ];
  const isSensitiveApi = isApi && SENSITIVE_API_PREFIXES.some(p => url.pathname.startsWith(p));

  if (isSensitiveApi) {
    // Network-only: bypass the cache entirely for sensitive paths.
    event.respondWith(fetch(event.request));
    return;
  }

  if (isApi) {
    // Network First Strategy for (non-sensitive) API calls
    event.respondWith(
      fetch(event.request)
        .then(networkResponse => {
          if (networkResponse && networkResponse.status === 200 && networkResponse.type === 'basic') {
            const responseToCache = networkResponse.clone();
            caches.open(CACHE_NAME).then(cache => {
              cache.put(event.request, responseToCache);
            });
          }
          return networkResponse;
        })
        .catch(() => {
          return caches.match(event.request);
        })
    );
  } else {
    // Stale-While-Revalidate Strategy for static assets (instant load)
    event.respondWith(
      caches.match(event.request).then(cachedResponse => {
        const fetchPromise = fetch(event.request).then(networkResponse => {
          if (networkResponse && networkResponse.status === 200 && networkResponse.type === 'basic') {
            caches.open(CACHE_NAME).then(cache => {
              cache.put(event.request, networkResponse.clone());
            });
          }
          return networkResponse;
        }).catch(() => {
          // Ignore network failure on background sync
        });

        return cachedResponse || fetchPromise;
      })
    );
  }
});
