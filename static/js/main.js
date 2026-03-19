document.addEventListener("DOMContentLoaded", () => {
  setBuilderMode("new");
  initDropZones();
  initMenus();

  Promise.resolve()
    .then(loadSources)
    .then(loadSettings)
    .then(loadFields)
    .then(loadPresets)
    .then(renderBuilder)
    .catch(e => setStatus("ERRORE: " + e.message));
});