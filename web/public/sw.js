/* Parlo service worker
 * - app shell & static assets: cache-first (Next.js assets are content-hashed)
 * - TTS audio: cache-first (immutable, keyed by content hash)
 * - lessons, review queue, course map, profile: network-first, cached copy offline
 * - pages: network-first with the last cached copy as the offline fallback
 * - web push: daily reminders
 */
const VERSION = "parlo-v1";
const STATIC = `${VERSION}-static`;
const RUNTIME = `${VERSION}-runtime`;
const AUDIO = `${VERSION}-audio`;

const OFFLINE_API = [
  /^\/api\/v1\/lessons\/\d+$/,
  /^\/api\/v1\/srs\/[a-z]{2}\/(queue|stats|levels|practice)/,
  /^\/api\/v1\/course\/[a-z]{2}$/,
  /^\/api\/v1\/auth\/me$/,
  /^\/api\/v1\/dashboard/,
  /^\/api\/v1\/kanji\//,
  /^\/api\/v1\/meta$/,
];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(STATIC).then((c) => c.addAll(["/manifest.webmanifest", "/icons/icon-192.png"])).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => !k.startsWith(VERSION)).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

async function cacheFirst(request, cacheName) {
  const cache = await caches.open(cacheName);
  const hit = await cache.match(request);
  if (hit) return hit;
  const res = await fetch(request);
  if (res.ok) cache.put(request, res.clone());
  return res;
}

async function networkFirst(request, cacheName, fallbackUrl) {
  const cache = await caches.open(cacheName);
  try {
    const res = await fetch(request);
    // only cache complete, successful responses (202 = lesson still generating)
    if (res.status === 200) cache.put(request, res.clone());
    return res;
  } catch (err) {
    const hit = (await cache.match(request)) || (fallbackUrl && (await cache.match(fallbackUrl)));
    if (hit) return hit;
    throw err;
  }
}

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  if (url.pathname.startsWith("/_next/static/") || url.pathname.startsWith("/icons/")) {
    event.respondWith(cacheFirst(request, STATIC));
  } else if (url.pathname.startsWith("/api/v1/audio/")) {
    event.respondWith(cacheFirst(request, AUDIO));
  } else if (OFFLINE_API.some((re) => re.test(url.pathname))) {
    event.respondWith(networkFirst(request, RUNTIME));
  } else if (request.mode === "navigate") {
    event.respondWith(networkFirst(request, RUNTIME, "/"));
  }
});

self.addEventListener("push", (event) => {
  let data = { title: "Parlo", body: "Time for a little practice!", url: "/" };
  try {
    data = { ...data, ...event.data.json() };
  } catch {
    /* plain-text push */
  }
  event.waitUntil(
    self.registration.showNotification(data.title, {
      body: data.body,
      icon: "/icons/icon-192.png",
      badge: "/icons/icon-192.png",
      data: { url: data.url },
      tag: "parlo-reminder",
    }),
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const target = (event.notification.data && event.notification.data.url) || "/";
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((wins) => {
      for (const w of wins) {
        if ("focus" in w) {
          w.navigate(target);
          return w.focus();
        }
      }
      return self.clients.openWindow(target);
    }),
  );
});
