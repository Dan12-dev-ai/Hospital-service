/* Hospital portal service worker.
 *
 * The portal is authenticated: every page depends on a live session, so we
 * never serve a cached page or API response. The service worker exists to make
 * the app installable as a PWA and to keep the shell's static assets fast.
 * Navigations and API calls always go to the network so an expired session is
 * detected and the visitor is sent to /login.
 */
const CACHE_NAME = "hospital-portal-static-v1";
const STATIC_ASSETS = ["/manifest.json", "/icons/icon-192.png", "/icons/icon-512.png"];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(CACHE_NAME)
      .then((cache) => cache.addAll(STATIC_ASSETS).catch(() => undefined))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      const keys = await caches.keys();
      await Promise.all(
        keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))
      );
      await self.clients.claim();
    })()
  );
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  const url = new URL(request.url);

  // Only handle same-origin requests.
  if (url.origin !== self.location.origin) return;

  // Never intercept API calls or navigations: they must reach the network so a
  // stale/expired session is handled by the portal (redirect to /login).
  if (url.pathname.startsWith("/api/")) return;
  if (request.mode === "navigate") return;

  // Cache-first for immutable static assets.
  if (
    url.pathname.startsWith("/_next/static/") ||
    url.pathname.startsWith("/icons/") ||
    url.pathname === "/manifest.json"
  ) {
    event.respondWith(
      caches.match(request).then((cached) => {
        if (cached) return cached;
        return fetch(request).then((response) => {
          if (response.ok) {
            const copy = response.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(request, copy));
          }
          return response;
        });
      })
    );
  }
});
