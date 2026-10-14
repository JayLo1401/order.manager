// Drag & Drop-Sortierung (Maus und Touch) fuer Listen mit [data-sortable].
// Elemente: [data-sortable-id], Griff: [data-sortable-handle]. Nach dem Loslassen
// wird die neue Reihenfolge als {"ids": [...]} an data-sortable-url geschickt.
(function () {
  "use strict";

  function initSortable(list) {
    const status = document.querySelector("[data-sortable-status]");
    const order = () => Array.from(list.querySelectorAll(":scope > [data-sortable-id]"))
      .map((el) => Number(el.dataset.sortableId));

    list.addEventListener("pointerdown", (ev) => {
      const handle = ev.target.closest("[data-sortable-handle]");
      const item = handle && handle.closest("[data-sortable-id]");
      if (!item || item.parentNode !== list || ev.button > 0) return;
      ev.preventDefault();

      const before = order().join(",");
      item.classList.add("dragging");
      document.body.classList.add("sorting");
      handle.setPointerCapture(ev.pointerId);

      const onMove = (e) => {
        // Auto-Scroll am Rand, damit man auch lange Listen sortieren kann
        if (e.clientY < 70) window.scrollBy(0, -12);
        else if (e.clientY > window.innerHeight - 70) window.scrollBy(0, 12);

        const target = document.elementFromPoint(e.clientX, e.clientY)?.closest("[data-sortable-id]");
        if (!target || target === item || target.parentNode !== list) return;
        const items = Array.from(list.children);
        if (items.indexOf(target) > items.indexOf(item)) target.after(item);
        else target.before(item);
      };

      const onUp = () => {
        handle.removeEventListener("pointermove", onMove);
        handle.removeEventListener("pointerup", onUp);
        handle.removeEventListener("pointercancel", onUp);
        item.classList.remove("dragging");
        document.body.classList.remove("sorting");
        if (order().join(",") !== before) save();
      };

      handle.addEventListener("pointermove", onMove);
      handle.addEventListener("pointerup", onUp);
      handle.addEventListener("pointercancel", onUp);
    });

    async function save() {
      if (status) status.textContent = "Speichere …";
      try {
        const res = await fetch(list.dataset.sortableUrl, {
          method: "POST",
          headers: { "Content-Type": "application/json", "X-CSRF-Token": list.dataset.csrf },
          body: JSON.stringify({ ids: order() }),
        });
        if (!res.ok) throw new Error(res.status);
        if (status) status.textContent = "✓ Reihenfolge gespeichert";
      } catch (e) {
        if (status) status.textContent = "⚠ Speichern fehlgeschlagen – Seite neu laden";
      }
    }
  }

  document.querySelectorAll("[data-sortable]").forEach(initSortable);
})();
