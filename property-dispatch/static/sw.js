// Service worker: makes the site installable and keeps it usable on a weak signal.
//
//   Pages        network first, cached copy when offline
//   /static/*    cache first (URLs carry ?v=<version>, so new deploys bust it)
//   Crew route   network first; the last good copy is kept for offline viewing
//   Other API    always network (bookings and completions must reach the server)
//
// __VERSION__ is replaced by the server with a hash of the static files.

const VERSION = "__VERSION__";
const SHELL = `shell-${VERSION}`;
const ROUTES = "crew-routes";
const PAGES = ["/", "/book", "/crew"];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(SHELL).then((c) => c.addAll(PAGES)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k.startsWith("shell-") && k !== SHELL).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

async function networkFirst(request, cacheName, { markOffline = false } = {}) {
  const cache = await caches.open(cacheName);
  try {
    const response = await fetch(request);
    if (response.ok) cache.put(request, response.clone());
    return response;
  } catch (err) {
    const cached = await cache.match(request, { ignoreSearch: !markOffline });
    if (!cached) throw err;
    if (!markOffline) return cached;
    const headers = new Headers(cached.headers);
    headers.set("X-Offline-Copy", cached.headers.get("Date") || "1");
    return new Response(cached.body, { status: cached.status, headers });
  }
}

async function cacheFirst(request) {
  const cache = await caches.open(SHELL);
  const hit = await cache.match(request);
  if (hit) return hit;
  const response = await fetch(request);
  if (response.ok) cache.put(request, response.clone());
  return response;
}

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  if (url.pathname.startsWith("/api/routes/")) {
    event.respondWith(networkFirst(request, ROUTES, { markOffline: true }));
  } else if (url.pathname.startsWith("/api/") || url.pathname.startsWith("/internal/") || url.pathname.startsWith("/webhooks/")) {
    return; // live data only
  } else if (url.pathname.startsWith("/static/")) {
    event.respondWith(cacheFirst(request));
  } else if (url.pathname.startsWith("/pay/")) {
    return; // private payment pages: never stored on the device
  } else if (request.mode === "navigate") {
    event.respondWith(networkFirst(request, SHELL));
  }
});
