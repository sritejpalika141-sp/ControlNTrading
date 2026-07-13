// SELF-DESTRUCT service worker (kill switch) — controln-trading v7-killswitch
//
// A prior caching service worker (v6.x) served stale HTML / app.js / API responses, which left
// clients showing an old session (admin panel hidden, Fyers "not connected", login appearing to do
// nothing) no matter what the server returned. This replacement caches NOTHING: on activation it
// deletes every cache, unregisters itself, and reloads open windows so all future requests go
// straight to the network. Browsers re-check the SW script on navigation (bypassing the SW's own
// cache), so this version is picked up automatically on the next visit.

self.addEventListener('install', () => {
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    try {
      const keys = await caches.keys();
      await Promise.all(keys.map((k) => caches.delete(k)));
    } catch (e) { /* best-effort */ }
    try {
      await self.registration.unregister();
    } catch (e) { /* best-effort */ }
    try {
      const clients = await self.clients.matchAll({ type: 'window' });
      for (const client of clients) {
        // Force a fresh, network-served reload of each open tab.
        client.navigate(client.url);
      }
    } catch (e) { /* best-effort */ }
  })());
});

// No 'fetch' handler on purpose: the worker never intercepts requests, so the browser performs
// every fetch normally against the network. Combined with the activate handler above, this fully
// removes the PWA cache layer.
