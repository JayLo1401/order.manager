// Kuechenmonitor: pollt die Bestellungen und rendert Touch-Kacheln.
(function () {
  "use strict";
  const cfg = window.KITCHEN;
  const POLL_MS = 4000;
  const $ = (sel) => document.querySelector(sel);

  let orders = [];
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

  function tileHtml(o, fresh) {
    const icons = o.ingredients.map((i) => i.icon).filter(Boolean).join("");
    return `
      <button type="button" class="tile tile-${o.status}${fresh ? " fresh" : ""}" data-id="${o.id}">
        <div class="tile-top">
          <span class="tile-number">#${o.number}</span>
          <span class="tile-age" data-created="${esc(o.created_at)}">${minutesSince(o.created_at)}</span>
        </div>
        <div class="tile-guest">${esc(o.guest || "Gast")}</div>
        <div class="tile-item"><span class="emoji">${esc(o.item_icon)}</span> ${esc(o.item_name)}${o.vegetarian ? ' <span class="badge badge-veg">🌱</span>' : ""}</div>
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
    done: [{ status: "in_progress", label: "Wieder öffnen", cls: "" }],
    cancelled: [{ status: "new", label: "Wiederherstellen", cls: "" }],
  };

  function fillModal(o) {
    $("#modal-number").textContent = `Bestellung #${o.number} · ${o.status_label}`;
    $("#modal-title").innerHTML = `<span class="emoji">${esc(o.item_icon)}</span> ${esc(o.item_name)}`;
    $("#modal-guest").textContent = (o.guest || "Gast") + (o.vegetarian ? " · 🌱 vegetarisch" : "");
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
        if (a.confirm && !window.confirm(a.confirm)) return;
        setStatus(o.id, a.status, btn);
      });
    });
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
  document.addEventListener("keydown", (ev) => { if (ev.key === "Escape") closeModal(); });

  $("#done-toggle").addEventListener("click", () => {
    showDone = !showDone;
    $("#done-toggle").textContent = showDone ? "Fertige ausblenden" : "Fertige anzeigen";
    render();
  });
  $("#sound-toggle").addEventListener("click", () => setSound(!soundOn));
  $("#fullscreen-toggle").addEventListener("click", () => {
    if (document.fullscreenElement) document.exitFullscreen();
    else document.documentElement.requestFullscreen?.();
  });
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
