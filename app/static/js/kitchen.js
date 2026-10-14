// Kuechenmonitor: pollt die Bestellungen und rendert Touch-Kacheln.
(function () {
  "use strict";
  const cfg = window.KITCHEN;
  const POLL_MS = 4000;
  const $ = (sel) => document.querySelector(sel);

  let orders = [];
  let eventInfo = {};
  let knownIds = null; // null = erster Ladevorgang, dann kein Ton
  let showDone = false;
  let soundOn = false;
  let openOrderId = null;
  let audioCtx = null;
  let pollTimer = null;

  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));

  function minutesSince(iso) {
    if (!iso) return "";
    const min = Math.max(0, Math.floor((Date.now() - new Date(iso).getTime()) / 60000));
    return min < 60 ? `${min} min` : `${Math.floor(min / 60)} h ${min % 60} min`;
  }

  const optionsText = (o) => (o.options || []).map((x) => `${x.icon} ${x.name}`.trim()).join(" · ");

  function tileHtml(o, fresh) {
    const icons = o.ingredients.map((i) => i.icon).filter(Boolean).join("");
    return `
      <button type="button" class="tile tile-${o.status}${fresh ? " fresh" : ""}" data-id="${o.id}">
        <div class="tile-top">
          <span class="tile-number">#${o.number}</span>
          <span class="tile-age" data-created="${esc(o.created_at)}">${minutesSince(o.created_at)}</span>
        </div>
        <div class="tile-guest">${esc(o.guest || "Gast")}${o.guest_extra_orders ? ` <span title="Nachschlag freigegeben">🎁${o.guest_extra_orders > 1 ? o.guest_extra_orders : ""}</span>` : ""}</div>
        <div class="tile-item"><span class="emoji">${esc(o.item_icon)}</span> ${esc(o.item_name)}${o.vegetarian ? ' <span class="badge badge-veg">🌱</span>' : ""}</div>
        ${optionsText(o) ? `<div class="tile-options">${esc(optionsText(o))}</div>` : ""}
        <div class="tile-icons emoji">${esc(icons)}</div>
        ${o.note ? `<div class="tile-note">💬 ${esc(o.note)}</div>` : ""}
        ${o.status === "in_progress" ? '<span class="tile-status badge badge-warn">In Arbeit</span>' : ""}
      </button>`;
  }

  function render() {
    const open = orders.filter((o) => o.status === "new" || o.status === "in_progress");
    const closed = orders.filter((o) => o.status === "done" || o.status === "cancelled").reverse();
    const fresh = new Set();
    if (knownIds !== null) {
      orders.forEach((o) => { if (!knownIds.has(o.id)) fresh.add(o.id); });
    }
    if (fresh.size && soundOn) beep();
    knownIds = new Set(orders.map((o) => o.id));

    $("#tiles-open").innerHTML = open.map((o) => tileHtml(o, fresh.has(o.id))).join("");
    $("#empty-open").hidden = open.length > 0;
    $("#tiles-done").innerHTML = closed.map((o) => tileHtml(o, false)).join("");
    $("#tiles-done").hidden = !showDone;
    $("#count-new").textContent = orders.filter((o) => o.status === "new").length;
    $("#count-progress").textContent = orders.filter((o) => o.status === "in_progress").length;
    $("#count-done").textContent = orders.filter((o) => o.status === "done").length;

    if (openOrderId !== null) {
      const o = orders.find((x) => x.id === openOrderId);
      if (o) fillModal(o); else closeModal();
    }
  }

  async function load() {
    clearTimeout(pollTimer);
    try {
      const res = await fetch(cfg.apiUrl, { headers: { Accept: "application/json" }, cache: "no-store" });
      if (res.status === 401) { window.location.href = "/login?next=/kitchen"; return; }
      if (!res.ok) throw new Error(res.status);
      const data = await res.json();
      orders = data.orders;
      eventInfo = data.event || {};
      updateSoldOutBadge(eventInfo.sold_out_count || 0);
      $("#conn").classList.remove("offline");
      render();
    } catch (e) {
      $("#conn").classList.add("offline");
    }
    pollTimer = setTimeout(load, POLL_MS);
  }

  // ---------------------------------------------------------------- Modal
  const ACTIONS = {
    new: [
      { status: "in_progress", label: "👨‍🍳 Bestellung bearbeiten", cls: "btn-warn btn-lg" },
      { status: "done", label: "✓ Direkt abschließen", cls: "" },
      { status: "cancelled", label: "Stornieren", cls: "btn-danger btn-sm", confirm: "Bestellung wirklich stornieren?" },
    ],
    in_progress: [
      { status: "done", label: "✓ Bestellung abgeschlossen", cls: "btn-ok btn-lg" },
      { status: "new", label: "Zurück auf „Eingegangen“", cls: "btn-sm" },
      { status: "cancelled", label: "Stornieren", cls: "btn-danger btn-sm", confirm: "Bestellung wirklich stornieren?" },
    ],
    done: [
      { status: "in_progress", label: "Wieder öffnen", cls: "" },
      { deleteGuest: true, label: "🗑️ Gast endgültig löschen", cls: "btn-danger btn-sm" },
    ],
    cancelled: [
      { status: "new", label: "Wiederherstellen", cls: "" },
      { deleteGuest: true, label: "🗑️ Gast endgültig löschen", cls: "btn-danger btn-sm" },
    ],
  };

  function fillModal(o) {
    $("#modal-number").textContent = `Bestellung #${o.number} · ${o.status_label}`;
    $("#modal-title").innerHTML = `<span class="emoji">${esc(o.item_icon)}</span> ${esc(o.item_name)}`;
    $("#modal-guest").textContent = (o.guest || "Gast") + (o.vegetarian ? " · 🌱 vegetarisch" : "");
    $("#modal-options").hidden = !optionsText(o);
    $("#modal-options").textContent = optionsText(o);
    $("#modal-ingredients").innerHTML = o.ingredients
      .map((i) => `<div><span class="emoji">${esc(i.icon)}</span> ${esc(i.name)}</div>`).join("");
    $("#modal-note").hidden = !o.note;
    $("#modal-note").textContent = o.note ? `💬 ${o.note}` : "";
    $("#modal-meta").textContent = `Bestellt um ${o.created_time} Uhr (vor ${minutesSince(o.created_at)})`;
    const actions = cfg.readOnly ? [] : (ACTIONS[o.status] || []);
    $("#modal-actions").innerHTML = actions
      .map((a, idx) => `<button type="button" class="btn btn-block ${a.cls}" data-action="${idx}">${a.label}</button>`)
      .join("");
    $("#modal-actions").querySelectorAll("[data-action]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const a = actions[Number(btn.dataset.action)];
        if (a.deleteGuest) { deleteGuest(o, btn); return; }
        if (a.confirm && !window.confirm(a.confirm)) return;
        setStatus(o.id, a.status, btn);
      });
    });

    // Nachschlag: nur sinnvoll, wenn es ein Bestell-Limit gibt
    const showExtra = !cfg.readOnly && eventInfo.order_limit > 0;
    $("#modal-extra").hidden = !showExtra;
    if (showExtra) {
      const extra = o.guest_extra_orders || 0;
      $("#modal-extra-info").textContent = extra
        ? `Nachschlag für ${o.guest || "diesen Gast"}: ${extra} zusätzliche Pizza${extra > 1 ? "s" : ""} freigegeben.`
        : `Pizza übrig? ${o.guest || "Dieser Gast"} darf dann noch eine bestellen.`;
      $("#extra-revoke").hidden = extra === 0;
      $("#extra-grant").onclick = (ev) => setExtra(o.guest_id, 1, ev.currentTarget);
      $("#extra-revoke").onclick = (ev) => setExtra(o.guest_id, -1, ev.currentTarget);
    }
  }

  async function deleteGuest(o, btn) {
    const theirs = orders.filter((x) => x.guest_id === o.guest_id);
    const list = theirs.map((x) => `#${x.number} ${x.item_name}`).join(", ");
    const msg = `${o.guest || "Gast"} und ${theirs.length === 1 ? "die Bestellung" : `alle ${theirs.length} Bestellungen`} `
      + `(${list}) endgültig löschen?\n\nDas kann nicht rückgängig gemacht werden.`;
    if (!window.confirm(msg)) return;
    btn.disabled = true;
    try {
      const res = await fetch(`/kitchen/api/guests/${o.guest_id}`, {
        method: "DELETE",
        headers: { "X-CSRF-Token": cfg.csrf },
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        alert(data.detail || "Löschen fehlgeschlagen.");
      }
    } catch (e) {
      alert("Keine Verbindung zum Server.");
    }
    closeModal();
    load();
  }

  async function setExtra(guestId, delta, btn) {
    btn.disabled = true;
    try {
      const res = await fetch(`/kitchen/api/guests/${guestId}/extra`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-CSRF-Token": cfg.csrf },
        body: JSON.stringify({ delta }),
      });
      if (!res.ok) alert("Aktion fehlgeschlagen.");
    } catch (e) {
      alert("Keine Verbindung zum Server.");
    }
    btn.disabled = false;
    load(); // Modal bleibt offen und zeigt den neuen Stand
  }

  function openModal(id) {
    const o = orders.find((x) => x.id === id);
    if (!o) return;
    openOrderId = id;
    fillModal(o);
    $("#modal").hidden = false;
  }

  function closeModal() {
    openOrderId = null;
    $("#modal").hidden = true;
  }

  async function setStatus(id, status, btn) {
    btn.disabled = true;
    try {
      const res = await fetch(`/kitchen/api/orders/${id}/status`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-CSRF-Token": cfg.csrf },
        body: JSON.stringify({ status }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        alert(data.detail || "Aktion fehlgeschlagen.");
      }
    } catch (e) {
      alert("Keine Verbindung zum Server.");
    }
    closeModal();
    load();
  }

  // ---------------------------------------------------------------- Zutaten "heute aus"
  const stockModal = $("#stock-modal");

  function updateSoldOutBadge(count) {
    const badge = $("#soldout-count");
    if (!badge) return;
    badge.hidden = !count;
    badge.textContent = `${count} aus`;
  }

  async function openStock() {
    stockModal.hidden = false;
    try {
      const res = await fetch("/kitchen/api/ingredients", { cache: "no-store" });
      const data = await res.json();
      $("#stock-groups").innerHTML = data.groups.map((g) => `
        <h3 class="section-title">${esc(g.label)}</h3>
        <div class="stock-grid">
          ${g.items.map((i) => `
            <button type="button" class="stock-tile${i.sold_out ? " is-out" : ""}" data-ingredient="${i.id}"
                    aria-pressed="${i.sold_out}">
              <span class="emoji">${esc(i.icon)}</span>
              <span class="stock-name">${esc(i.name)}</span>
              <span class="stock-state">${i.sold_out ? "heute aus" : "da"}</span>
            </button>`).join("")}
        </div>`).join("") || '<p class="muted">Keine aktiven Zutaten.</p>';
    } catch (e) {
      $("#stock-groups").innerHTML = '<p class="muted">Konnte die Zutaten nicht laden.</p>';
    }
  }

  async function toggleStock(tile) {
    const soldOut = !tile.classList.contains("is-out");
    tile.disabled = true;
    try {
      const res = await fetch(`/kitchen/api/ingredients/${tile.dataset.ingredient}/sold-out`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-CSRF-Token": cfg.csrf },
        body: JSON.stringify({ sold_out: soldOut }),
      });
      if (!res.ok) throw new Error(res.status);
      const data = await res.json();
      tile.classList.toggle("is-out", soldOut);
      tile.setAttribute("aria-pressed", String(soldOut));
      tile.querySelector(".stock-state").textContent = soldOut ? "heute aus" : "da";
      updateSoldOutBadge(data.sold_out_count);
    } catch (e) {
      alert("Konnte nicht gespeichert werden.");
    }
    tile.disabled = false;
  }

  if (stockModal) {
    $("#stock-open")?.addEventListener("click", openStock);
    stockModal.addEventListener("click", (ev) => {
      const tile = ev.target.closest("[data-ingredient]");
      if (tile) { toggleStock(tile); return; }
      if (ev.target === stockModal || ev.target.closest("[data-close-stock]")) stockModal.hidden = true;
    });
  }

  // ---------------------------------------------------------------- Ton
  function beep() {
    if (!audioCtx) return;
    const now = audioCtx.currentTime;
    [0, 0.18].forEach((offset, i) => {
      const osc = audioCtx.createOscillator();
      const gain = audioCtx.createGain();
      osc.frequency.value = i ? 1046 : 784;
      gain.gain.setValueAtTime(0.0001, now + offset);
      gain.gain.exponentialRampToValueAtTime(0.4, now + offset + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.0001, now + offset + 0.16);
      osc.connect(gain).connect(audioCtx.destination);
      osc.start(now + offset);
      osc.stop(now + offset + 0.17);
    });
  }

  function setSound(on) {
    soundOn = on;
    // Browser erlauben Audio erst nach einer Nutzer-Interaktion -> Kontext hier anlegen.
    if (on && !audioCtx) audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    if (on) { audioCtx.resume(); beep(); }
    $("#sound-toggle").textContent = on ? "🔔 Ton an" : "🔕 Ton aus";
    try { localStorage.setItem("kitchen-sound", on ? "1" : "0"); } catch (e) { /* egal */ }
  }

  // ---------------------------------------------------------------- Bildschirm wach halten
  let wakeLock = null;
  async function keepAwake() {
    try {
      if ("wakeLock" in navigator && document.visibilityState === "visible") {
        wakeLock = await navigator.wakeLock.request("screen");
      }
    } catch (e) { /* nicht unterstuetzt */ }
  }

  // ---------------------------------------------------------------- Events
  document.addEventListener("click", (ev) => {
    const tile = ev.target.closest(".tile");
    if (tile) { openModal(Number(tile.dataset.id)); return; }
    if (ev.target.closest("[data-close]") || ev.target === $("#modal")) closeModal();
  });
  document.addEventListener("keydown", (ev) => {
    if (ev.key !== "Escape") return;
    closeModal();
    if (stockModal) stockModal.hidden = true;
  });

  $("#done-toggle").addEventListener("click", () => {
    showDone = !showDone;
    $("#done-toggle").textContent = showDone ? "Fertige ausblenden" : "Fertige anzeigen";
    render();
  });
  $("#sound-toggle").addEventListener("click", () => setSound(!soundOn));
  // Vollbild: Kopfzeile ausblenden, damit mehr Platz fuer die Kacheln bleibt.
  // webkit-Varianten fuer Safari auf dem iPad.
  const fullscreenElement = () => document.fullscreenElement || document.webkitFullscreenElement;
  $("#fullscreen-toggle").addEventListener("click", () => {
    const root = document.documentElement;
    if (fullscreenElement()) {
      (document.exitFullscreen || document.webkitExitFullscreen)?.call(document);
    } else {
      (root.requestFullscreen || root.webkitRequestFullscreen)?.call(root);
    }
  });
  const onFullscreenChange = () => {
    const on = !!fullscreenElement();
    document.body.classList.toggle("is-fullscreen", on);
    $("#fullscreen-toggle").textContent = on ? "⤢ Vollbild beenden" : "⛶";
  };
  document.addEventListener("fullscreenchange", onFullscreenChange);
  document.addEventListener("webkitfullscreenchange", onFullscreenChange);
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") { keepAwake(); load(); }
  });

  function tick() {
    $("#clock").textContent = new Date().toLocaleTimeString("de-AT", { hour: "2-digit", minute: "2-digit" });
    document.querySelectorAll(".tile-age[data-created]").forEach((el) => {
      el.textContent = minutesSince(el.dataset.created);
    });
  }

  try {
    // Gespeicherte Einstellung nur anzeigen - echter Ton braucht trotzdem einen Tipp.
    if (localStorage.getItem("kitchen-sound") === "1") {
      $("#sound-toggle").textContent = "🔕 Ton aus (antippen)";
    }
  } catch (e) { /* egal */ }

  tick();
  setInterval(tick, 15000);
  keepAwake();
  load();
})();
