async function quickUpdateCurrentPresetOptions(newOptions){
  const p = PRESETS.find(x => x.id === CURRENT);
  if (!p) {
    setStatus("ERRORE: nessun preset attivo.");
    return;
  }

  const payload = {
    source_id: CURRENT_SOURCE,
    filename: presetFilenameFromPreset(p),
    title: p.title || p.id,
    filters: [...(p.filters || [])],
    rows: [...(p.rows || [])],
    cols: [...(p.cols || [])],
    numeric_fields: [...(p.numeric_fields || [])],
    date_fields: [...(p.date_fields || [])],
    values: [...(p.values || [])],
    options: {
      ...getDefaultPresetOptions(),
      ...(p.options || {}),
      ...newOptions
    }
  };

  try{
    await api("/preset-editor/save", {
      method: "POST",
      body: JSON.stringify(payload)
    });

    await loadPresets();
    await renderFilters();
    await runCurrent();
    setStatus("Preset aggiornato.");
  }catch(e){
    setStatus("ERRORE: " + e.message);
  }
}

async function toggleCurrentPresetOption(optionName){
  const p = PRESETS.find(x => x.id === CURRENT);
  if (!p) {
    setStatus("ERRORE: nessun preset attivo.");
    return;
  }

  const currentOptions = {
    ...getDefaultPresetOptions(),
    ...(p.options || {})
  };

  await quickUpdateCurrentPresetOptions({
    [optionName]: !currentOptions[optionName]
  });
}

async function quickUpdateCurrentPresetOptions(newOptions){
  const p = PRESETS.find(x => x.id === CURRENT);
  if (!p) {
    setStatus("ERRORE: nessun preset attivo.");
    return;
  }

  const payload = {
    source_id: CURRENT_SOURCE,
    filename: presetFilenameFromPreset(p),
    title: p.title || p.id,
    filters: [...(p.filters || [])],
    rows: [...(p.rows || [])],
    cols: [...(p.cols || [])],
    numeric_fields: [...(p.numeric_fields || [])],
    date_fields: [...(p.date_fields || [])],
    values: [...(p.values || [])],
    options: {
      ...getDefaultPresetOptions(),
      ...(p.options || {}),
      ...newOptions
    }
  };

  try{
    await api("/preset-editor/save", {
      method: "POST",
      body: JSON.stringify(payload)
    });

    await loadPresets();
    await renderFilters();
    await runCurrent();
    setStatus("Preset aggiornato.");
  }catch(e){
    setStatus("ERRORE: " + e.message);
  }
}

