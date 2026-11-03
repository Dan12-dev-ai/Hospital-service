/* The hospital portal used to install a service worker (a PWA). The
 * developer dashboard does not: this replacement removes itself, clears the
 * old caches and reloads open pages, so browsers that installed the old one
 * stop using it. Kept at the same URL until no browser has the old worker. */
self.addEventListener("install", () => self.skipWaiting());

self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      const keys = await caches.keys();
      await Promise.all(keys.map((key) => caches.delete(key)));
      await self.registration.unregister();
      const clients = await self.clients.matchAll({ type: "window" });
      for (const client of clients) client.navigate(client.url);
    })()
  );
});
