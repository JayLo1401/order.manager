// Service Worker: macht die Seiten installierbar ("App installieren") und
// zeigt Push-Benachrichtigungen an. Bewusst kein Caching - die Daten muessen
// immer live sein.
self.addEventListener("install", () => { self.skipWaiting(); });
self.addEventListener("activate", (event) => { event.waitUntil(self.clients.claim()); });

self.addEventListener("push", (event) => {
  let data = {};
  try { data = event.data ? event.data.json() : {}; } catch (e) { data = { body: event.data && event.data.text() }; }
  const title = data.title || "Bestellung";
  event.waitUntil(self.registration.showNotification(title, {
    body: data.body || "",
    icon: "/static/img/icon-192.png",
    badge: "/static/img/icon-192.png",
    tag: data.tag,
    renotify: true,
    vibrate: [200, 100, 200, 100, 300],
    data: { url: data.url || "/" },
  }));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = new URL(event.notification.data.url, self.location.origin).href;
  event.waitUntil((async () => {
    const windows = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
    for (const client of windows) {
      if (client.url.startsWith(url) && "focus" in client) return client.focus();
    }
    return self.clients.openWindow(url);
  })());
});
