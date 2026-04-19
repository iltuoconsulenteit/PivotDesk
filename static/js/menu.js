(function () {
  function closeAllMenus() {
    document.querySelectorAll(".menu-dropdown").forEach(el => {
      el.classList.add("hidden");
    });
  }

  function toggleMenuById(menuId) {
    const target = document.getElementById(menuId);
    if (!target) return;

    const shouldOpen = target.classList.contains("hidden");
    closeAllMenus();
    if (shouldOpen) target.classList.remove("hidden");
  }

  function safeCall(fnName, ...args) {
    const fn = window[fnName];
    if (typeof fn === "function") {
      return fn(...args);
    }
  }

  window.initMenus = function initMenus() {
    document.querySelectorAll(".menu-btn").forEach(btn => {
      btn.addEventListener("click", function (ev) {
        ev.stopPropagation();
        const targetId = btn.getAttribute("data-menu-target");
        toggleMenuById(targetId);
      });
    });

    document.addEventListener("click", function () {
      closeAllMenus();
    });

    const bind = (id, handler) => {
      const el = document.getElementById(id);
      if (!el) return;
      el.addEventListener("click", async function (ev) {
        ev.stopPropagation();
        closeAllMenus();
        try {
          await handler();
        } catch (e) {
          safeCall("setStatus", "ERRORE: " + (e && e.message ? e.message : e));
        }
      });
    };

    bind("menuReload", async function () {
      if (typeof window.loadFields === "function") await window.loadFields();
      if (typeof window.loadPresets === "function") await window.loadPresets();
    });

    bind("menuOpenSources", async function () {
      safeCall("resetSourceForm");
      safeCall("renderSourcesManager");
      safeCall("openSourcesScreen");
    });

    bind("menuToggleColumns", async function () {
      const panel = document.getElementById("columnsPanel");
      if (panel) panel.classList.toggle("hidden");
    });

    bind("menuOpenBuilder", async function () {
      safeCall("openBuilderForNew");
    });

    bind("menuEditCurrentPreset", async function () {
      safeCall("openBuilderForCurrentPreset");
    });

    bind("menuDeleteCurrentPreset", async function () {
      await safeCall("deleteCurrentPreset");
    });

    bind("menuSetVerticalLayout", async function () {
      safeCall("setCurrentViewOptions", { measures_layout: "vertical" });
      safeCall("refreshQuickbarFromPreset");
      await safeCall("runCurrent");
    });

    bind("menuSetHorizontalLayout", async function () {
      safeCall("setCurrentViewOptions", { measures_layout: "horizontal" });
      safeCall("refreshQuickbarFromPreset");
      await safeCall("runCurrent");
    });

    bind("menuToggleRowTotals", async function () {
      const opts = safeCall("getEffectiveViewOptions") || {};
      safeCall("setCurrentViewOptions", {
        show_row_totals: !opts.show_row_totals
      });
      safeCall("refreshQuickbarFromPreset");
      await safeCall("runCurrent");
    });

    bind("menuToggleColTotals", async function () {
      const opts = safeCall("getEffectiveViewOptions") || {};
      safeCall("setCurrentViewOptions", {
        show_col_totals: !opts.show_col_totals
      });
      safeCall("refreshQuickbarFromPreset");
      await safeCall("runCurrent");
    });

    bind("menuToggleSubtotals", async function () {
      const opts = safeCall("getEffectiveViewOptions") || {};
      safeCall("setCurrentViewOptions", {
        show_subtotals: !opts.show_subtotals
      });
      safeCall("refreshQuickbarFromPreset");
      await safeCall("runCurrent");
    });

    bind("menuPrint", async function () {
      safeCall("printPivotOnly");
    });

    bind("menuOpenSettings", async function () {
      safeCall("openSettingsScreen");
    });

    bind("menuExportBackup", async function () {
      await safeCall("exportBackupPackage");
    });

    bind("menuRestoreBackup", async function () {
      const input = document.getElementById("backupRestoreFile");
      if (!input) return;
      input.value = "";
      input.click();
    });

    bind("menuOpenMergeModule", async function () {
      await safeCall("openMergeModuleFromMenu");
    });

    bind("menuOpenApiSchedulerModule", async function () {
      await safeCall("openApiSchedulerModuleFromMenu");
    });

    bind("menuOpenXmlBatchModule", async function () {
      await safeCall("openXmlBatchImportModuleFromMenu");
    });
  };

  document.addEventListener("DOMContentLoaded", function () {
    if (typeof window.initMenus === "function") {
      window.initMenus();
    }
  });
})();
