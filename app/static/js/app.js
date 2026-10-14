// Allgemeine Helfer fuer die Verwaltungsseiten.
(function () {
  "use strict";

  document.addEventListener("click", (ev) => {
    const navToggle = ev.target.closest("[data-nav-toggle]");
    if (navToggle) {
      document.querySelector(".site-header nav")?.classList.toggle("open");
      return;
    }

    // Symbolbibliothek: Klick setzt das Symbol ins zugehoerige Eingabefeld
    const symbolBtn = ev.target.closest("[data-symbol]");
    if (symbolBtn) {
      const input = document.getElementById(symbolBtn.dataset.symbolTarget);
      if (input) input.value = symbolBtn.dataset.symbol;
      symbolBtn.closest(".symbol-picker")?.querySelectorAll("button.selected")
        .forEach((b) => b.classList.remove("selected"));
      symbolBtn.classList.add("selected");
      symbolBtn.closest("details")?.removeAttribute("open");
      return;
    }

    const copyBtn = ev.target.closest("[data-copy]");
    if (copyBtn) {
      const input = document.querySelector(copyBtn.dataset.copy);
      if (!input) return;
      const done = () => {
        const old = copyBtn.textContent;
        copyBtn.textContent = "✓ Kopiert";
        setTimeout(() => { copyBtn.textContent = old; }, 1500);
      };
      if (navigator.clipboard) {
        navigator.clipboard.writeText(input.value).then(done, () => { input.select(); document.execCommand("copy"); done(); });
      } else {
        input.select(); document.execCommand("copy"); done();
      }
      return;
    }

    const shareBtn = ev.target.closest("[data-share]");
    if (shareBtn && navigator.share) {
      navigator.share({ text: shareBtn.dataset.shareText, url: shareBtn.dataset.shareUrl }).catch(() => {});
    }
  });

  document.addEventListener("submit", (ev) => {
    const msg = ev.target.dataset.confirm;
    if (msg && !window.confirm(msg)) ev.preventDefault();
  });

  document.querySelectorAll("[data-share]").forEach((b) => { b.hidden = !navigator.share; });

  // Neue Zutat: "vegetarisch" passend zur Kategorie vorbelegen (aenderbar)
  document.querySelectorAll("select[data-veg-target]").forEach((select) => {
    select.addEventListener("change", () => {
      const box = document.querySelector(select.dataset.vegTarget);
      if (box) box.checked = !["meat", "fish"].includes(select.value);
    });
  });

  // ---------------------------------------------------------------- PWA
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("/sw.js").catch(() => {});
  }
  let installPrompt = null;
  const installBtn = document.getElementById("pwa-install");
  window.addEventListener("beforeinstallprompt", (ev) => {
    ev.preventDefault();
    installPrompt = ev;
    if (installBtn) installBtn.hidden = false;
  });
  installBtn?.addEventListener("click", async () => {
    if (!installPrompt) return;
    installPrompt.prompt();
    await installPrompt.userChoice;
    installPrompt = null;
    installBtn.hidden = true;
  });
})();
