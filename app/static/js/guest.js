// Gaeste-Seiten: Wunschpizza-Auswahl, Live-Status und Benachrichtigungen.
(function () {
  "use strict";
  const $ = (sel) => document.querySelector(sel);

  // Doppelt-Absenden verhindern (sonst zwei Bestellungen bei Doppeltipp)
  document.addEventListener("submit", (ev) => {
    const msg = ev.target.dataset.confirm;
    if (msg && !window.confirm(msg)) { ev.preventDefault(); return; }
    ev.target.querySelectorAll("[data-once]").forEach((b) => {
      setTimeout(() => { b.disabled = true; b.textContent = "Wird gesendet …"; }, 0);
    });
  });

  // ---------------------------------------------------------------- Wunschpizza
  const customForm = $("#custom-form");
  if (customForm) {
    const max = Number(customForm.dataset.max || 0);
    const boxes = Array.from(customForm.querySelectorAll('input[name="ingredient_ids"]'));
    const update = () => {
      const checked = boxes.filter((b) => b.checked);
      const n = checked.length;
      boxes.forEach((b) => { b.disabled = max > 0 && n >= max && !b.checked; });
      $("#custom-submit").disabled = n === 0;
      $("#custom-summary").textContent = n === 0
        ? "Bitte wähle mindestens eine Zutat"
        : `${n} Zutat${n === 1 ? "" : "en"} gewählt${max ? ` (max. ${max})` : ""}`;
    };
    boxes.forEach((b) => b.addEventListener("change", update));
    update();
  }

  // ---------------------------------------------------------------- Status
  const ordersEl = $("#orders");
  if (!ordersEl) return;

  if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});

  const known = {};
  ordersEl.querySelectorAll("[data-order-id]").forEach((el) => { known[el.dataset.orderId] = el.dataset.status; });

  async function localNotify(order) {
    if (navigator.vibrate) navigator.vibrate([200, 100, 200, 100, 400]);
    try {
      const ctx = new (window.AudioContext || window.webkitAudioContext)();
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.frequency.value = 880;
      gain.gain.value = 0.2;
      osc.connect(gain).connect(ctx.destination);
      osc.start(); osc.stop(ctx.currentTime + 0.4);
    } catch (e) { /* Audio evtl. blockiert */ }
    if ("Notification" in window && Notification.permission === "granted" && navigator.serviceWorker) {
      const reg = await navigator.serviceWorker.ready;
      // Gleicher Tag wie beim Server-Push -> keine doppelte Meldung
      reg.showNotification("Deine Pizza ist fertig! 🍕", {
        body: `${order.item_name} kann abgeholt werden.`,
        icon: "/static/img/icon-192.png",
        tag: `order-${order.id}`,
        data: { url: location.pathname },
      });
    }
  }

  async function poll() {
    try {
      const res = await fetch(ordersEl.dataset.statusUrl, { cache: "no-store", headers: { Accept: "application/json" } });
      if (res.ok) {
        const data = await res.json();
        let changed = false;
        for (const o of data.orders) {
          if (known[o.id] !== o.status) {
            changed = true;
            if (o.status === "done" && known[o.id] !== undefined) await localNotify(o);
          }
        }
        if (changed || data.orders.length !== Object.keys(known).length) {
          location.replace(location.pathname); // ohne ?ok=1
          return;
        }
      } else if (res.status === 410) {
        location.reload();
        return;
      }
    } catch (e) { /* offline - naechster Versuch */ }
    setTimeout(poll, document.visibilityState === "visible" ? 5000 : 15000);
  }
  setTimeout(poll, 5000);
  document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible") poll(); });

  // ---------------------------------------------------------------- Push-Benachrichtigung
  const card = $("#notify-card");
  if (!card) return;
  const btn = $("#notify-btn");
  const hint = $("#notify-hint");
  const isIos = /iphone|ipad|ipod/i.test(navigator.userAgent);
  const standalone = window.matchMedia("(display-mode: standalone)").matches || navigator.standalone;
  const pushSupported = "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;
  const allDone = Object.values(known).every((s) => s === "done" || s === "cancelled");

  function urlBase64ToUint8Array(base64) {
    const padding = "=".repeat((4 - (base64.length % 4)) % 4);
    const raw = atob((base64 + padding).replace(/-/g, "+").replace(/_/g, "/"));
    return Uint8Array.from(raw, (c) => c.charCodeAt(0));
  }

  async function subscribe() {
    btn.disabled = true;
    try {
      const permission = await Notification.requestPermission();
      if (permission !== "granted") {
        hint.textContent = "Benachrichtigungen wurden nicht erlaubt. Lass diese Seite einfach offen – sie aktualisiert sich automatisch.";
        btn.disabled = false;
        return;
      }
      const reg = await navigator.serviceWorker.ready;
      let sub = await reg.pushManager.getSubscription();
      if (!sub) {
        sub = await reg.pushManager.subscribe({
          userVisibleOnly: true,
          applicationServerKey: urlBase64ToUint8Array(card.dataset.vapidKey),
        });
      }
      const res = await fetch(card.dataset.pushUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-CSRF-Token": card.dataset.csrf },
        body: JSON.stringify(sub.toJSON()),
      });
      if (!res.ok) throw new Error(res.status);
      btn.hidden = true;
      hint.textContent = "✓ Aktiv – du bekommst eine Nachricht, sobald deine Pizza fertig ist.";
    } catch (e) {
      hint.textContent = "Benachrichtigung konnte nicht aktiviert werden. Lass diese Seite offen – sie aktualisiert sich automatisch.";
      btn.disabled = false;
    }
  }

  if (allDone) return;
  card.hidden = false;
  if (pushSupported && card.dataset.vapidKey) {
    if (Notification.permission === "granted") {
      // Schon erlaubt: Abo still auffrischen
      subscribe();
    }
    btn.addEventListener("click", subscribe);
  } else if (isIos && !standalone) {
    btn.hidden = true;
    hint.innerHTML = "Am iPhone: Tippe auf <b>Teilen</b> → <b>Zum Home-Bildschirm</b> und öffne die Bestellung von dort – dann kannst du Benachrichtigungen aktivieren. Oder lass diese Seite einfach offen.";
  } else {
    btn.hidden = true;
    hint.textContent = "Dein Browser unterstützt keine Benachrichtigungen. Lass diese Seite offen – sie aktualisiert sich automatisch.";
  }
})();
