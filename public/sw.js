"use strict";
// GHAZI RADAR service worker: installable app, readable offline, never stale while online.
//
// Shell (page, script, styles, icons) and the published bot-state JSON are
// fetched network-first; the last good copy is kept and served only when the
// network fails, marked with x-ghazi-cached-at so the page says "offline · saved
// at …". TradingView widgets, fonts and any other host pass straight through:
// no price or chart is stored. Bump VERSION with every shell change.
const VERSION = "2026-10-28-3";
const SHELL = "ghazi-shell-" + VERSION;
const DATA = "ghazi-data-v1";
const SHELL_FILES = ["./", "./radar.js", "./radar.css", "./tv-intelligence.js", "./manifest.webmanifest",
  "./icons/icon.svg", "./icons/icon-192.png", "./icons/icon-512.png"];
const DATA_RE = /^https:\/\/raw\.githubusercontent\.com\/GHAZMOTIEBIPRO\/GHAZIBOT\/bot-state\/runtime\/public\/data\/[a-z0-9_]+\.json$/;

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(SHELL).then((c) => Promise.allSettled(SHELL_FILES.map((f) => c.add(new Request(f, { cache: "reload" })))))
    .then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((k) => k.startsWith("ghazi-shell-") && k !== SHELL)
    .map((k) => caches.delete(k)))).then(() => self.clients.claim()));
});

async function networkFirst(request, cacheName, stamp) {
  const cache = await caches.open(cacheName);
  try {
    const response = await fetch(request, { cache: "no-store" });
    if (response.ok) {
      const headers = new Headers(response.headers);
      headers.set("x-ghazi-saved-at", new Date().toISOString());
      const body = await response.clone().blob();
      await cache.put(request.url.split("?")[0], new Response(body, { status: 200, headers }));
    }
    return response;
  } catch (error) {
    const saved = await cache.match(request.url.split("?")[0]);
    if (!saved) throw error;
    if (!stamp) return saved;
    const headers = new Headers(saved.headers);
    const savedAt = saved.headers.get("x-ghazi-saved-at") || "";
    headers.set("x-ghazi-cached-at", savedAt);
    // Cross-origin (CORS) responses hide custom headers from the page; the status text is kept.
    return new Response(await saved.blob(), { status: 200, statusText: "ghazi-cached " + savedAt, headers });
  }
}

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (DATA_RE.test(url.origin + url.pathname)) {
    event.respondWith(networkFirst(request, DATA, true));
  } else if (url.origin === self.location.origin) {
    const home = request.mode === "navigate" && (url.pathname === "/" || url.pathname === "/index.html");
    // Other pages (classic, catalyst desk, …) are not part of this app shell: straight to the network.
    if (!home && !/\/(radar\.js|radar\.css|tv-intelligence\.js|manifest\.webmanifest|icons\/[\w.-]+)$/.test(url.pathname)) return;
    const key = home ? new Request(self.registration.scope) : request;
    event.respondWith(networkFirst(key, SHELL, false).catch(() => caches.match(self.registration.scope)));
  }
});
