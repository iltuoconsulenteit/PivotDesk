(function () {
  const isDemo = !!window.PIVOTDESK_IS_DEMO;
  const disabled = Array.isArray(window.PIVOTDESK_DISABLED_FEATURES) ? window.PIVOTDESK_DISABLED_FEATURES : [];
  const disabledSet = new Set(disabled);

  const modal = document.getElementById("demoFeatureModal");
  const modalBody = document.getElementById("demoModalBody");
  const closeBtn = document.getElementById("demoModalClose");
  const okBtn = document.getElementById("demoModalOk");

  const labels = {
    subtotals: "Subtotali",
    preview: "Anteprima",
    print: "Stampa"
  };

  function showModal(feature) {
    if (!modal || !modalBody) return false;
    const label = labels[feature] || feature;
    modalBody.textContent = label + " non è disponibile nella versione demo. Installa una licenza completa per sbloccare questa funzionalità.";
    modal.classList.add("active");
    modal.setAttribute("aria-hidden", "false");
    return false;
  }

  function hideModal() {
    if (!modal) return;
    modal.classList.remove("active");
    modal.setAttribute("aria-hidden", "true");
  }

  function checkFeature(feature) {
    if (!isDemo) return true;
    if (!disabledSet.has(feature)) return true;
    showModal(feature);
    return false;
  }

  window.PivotDeskDemoGuard = {
    isDemo,
    disabled,
    checkFeature
  };

  if (!isDemo) return;

  document.addEventListener("click", function (ev) {
    const target = ev.target.closest("[data-feature]");
    if (!target) return;
    const feature = target.getAttribute("data-feature");
    if (!feature) return;
    if (checkFeature(feature)) return;
    ev.preventDefault();
    ev.stopPropagation();
  }, true);

  document.addEventListener("change", function (ev) {
    const target = ev.target.closest("[data-feature]");
    if (!target) return;
    const feature = target.getAttribute("data-feature");
    if (!feature) return;
    if (checkFeature(feature)) return;
    if (target.type === "checkbox") {
      target.checked = false;
    }
    ev.preventDefault();
    ev.stopPropagation();
  }, true);

  if (closeBtn) closeBtn.addEventListener("click", hideModal);
  if (okBtn) okBtn.addEventListener("click", hideModal);
  if (modal) {
    modal.addEventListener("click", function (ev) {
      if (ev.target === modal) hideModal();
    });
  }
  document.addEventListener("keydown", function (ev) {
    if (ev.key === "Escape") hideModal();
  });

  document.querySelectorAll("[data-feature]").forEach(function (el) {
    const feature = el.getAttribute("data-feature");
    if (disabledSet.has(feature)) {
      el.classList.add("demo-disabled");
      if (!el.title) {
        el.title = "Disponibile solo con licenza completa";
      }
    }
  });
})();
