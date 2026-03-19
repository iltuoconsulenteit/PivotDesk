let SOURCES = [];
let PRESETS = [];
let CURRENT = null;
let CURRENT_SOURCE = null;
let CURRENT_FIELDS = [];

const BUILDER = {
  filters: [],
  rows: [],
  cols: [],
  values: []
};

function setStatus(t){
  document.getElementById("status").innerText = t || "";
}

async function api(url, options = {}){
  const r = await fetch(url, {
    cache: "no-store",
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {})
    }
  });

  const data = await r.json().catch(() => ({}));

  if (!r.ok) {
    const details = [];
    if (data.error) details.push(data.error);
    if (data.missing_columns) details.push("Colonne mancanti: " + data.missing_columns.join(", "));
    throw new Error(details.join("\n") || ("Errore API: " + url));
  }

  return data;
}

async function loadSources(){
  const j = await api("/sources");
  SOURCES = j.items || [];
  CURRENT_SOURCE = j.default_source || (SOURCES[0]?.id || null);

  const sel = document.getElementById("sourceSelect");
  sel.innerHTML = "";

  SOURCES.forEach(src => {
    const o = document.createElement("option");
    o.value = src.id;
    o.textContent = src.title || src.id;
    if (src.id === CURRENT_SOURCE) o.selected = true;
    sel.appendChild(o);
  });

  sel.onchange = async () => {
    CURRENT_SOURCE = sel.value;
    CURRENT = null;
    clearBuilder();
    await loadFields();
    await loadPresets();
  };
}

async function loadFields(){
  const j = await api("/fields?source_id=" + encodeURIComponent(CURRENT_SOURCE));
  CURRENT_FIELDS = j.fields || [];
  renderFieldsSidebar();
  renderColumnsPanel();
}

async function loadPresets(){
  const j = await api("/pivots?source_id=" + encodeURIComponent(CURRENT_SOURCE));
  PRESETS = j.items || [];
  CURRENT = CURRENT || (PRESETS[0]?.id || null);
  renderTabs();
  await renderFilters();
  await runCurrent();
}

function renderTabs(){
  const tabbar = document.getElementById("tabbar");
  tabbar.innerHTML = "";

  PRESETS.forEach(p => {
    const b = document.createElement("button");
    b.type = "button";
    b.textContent = p.title || p.id;
    if (p.id === CURRENT) b.classList.add("active");
    b.onclick = async () => {
      CURRENT = p.id;
      renderTabs();
      await renderFilters();
      await runCurrent();
    };
    tabbar.appendChild(b);
  });
}

async function renderFilters(){
  const box = document.getElementById("filters");
  box.innerHTML = "";

  const preset = PRESETS.find(x => x.id === CURRENT);
  const filters = preset?.filters || [];

  for (const field of filters) {
    const wrap = document.createElement("div");
    wrap.className = "field";

    const label = document.createElement("label");
    label.textContent = field;

    const select = document.createElement("select");
    select.dataset.field = field;

    const optAll = document.createElement("option");
    optAll.value = "";
    optAll.textContent = "(Tutto)";
    select.appendChild(optAll);

    try {
      const j = await api("/filter-values?source_id=" + encodeURIComponent(CURRENT_SOURCE) + "&field=" + encodeURIComponent(field));
      (j.values || []).forEach(v => {
        const o = document.createElement("option");
        o.value = v;
        o.textContent = v;
        select.appendChild(o);
      });
    } catch (_e) {}

    select.onchange = () => runCurrent();

    wrap.appendChild(label);
    wrap.appendChild(select);
    box.appendChild(wrap);
  }
}

function getFilters(){
  const out = {};
  document.querySelectorAll("#filters select").forEach(sel => {
    if (sel.value) out[sel.dataset.field] = sel.value;
  });
  return out;
}

async function runCurrent(){
  const preset = PRESETS.find(x => x.id === CURRENT);
  if (!preset) {
    document.getElementById("report").innerHTML = "<p>Nessun preset disponibile.</p>";
    setStatus("Nessun preset disponibile.");
    return;
  }

  setStatus("Calcolo pivot in corso...");

  const filters = encodeURIComponent(JSON.stringify(getFilters()));
  const url = "/pivot/run?pivot_id=" + encodeURIComponent(preset.id) +
              "&source_id=" + encodeURIComponent(CURRENT_SOURCE || "") +
              "&filters=" + filters;

  try {
    const j = await api(url);
    document.getElementById("report").innerHTML =
      "<h3>" + escapeHtml(preset.title || preset.id) + "</h3>" + (j.html || "");
    setStatus("OK");
  } catch (e) {
    document.getElementById("report").innerHTML = "";
    setStatus("ERRORE: " + e.message);
  }
}

function renderColumnsPanel(){
  document.getElementById("columnsCount").innerText = `${CURRENT_FIELDS.length} colonne`;
  document.getElementById("columnsRaw").innerText = CURRENT_FIELDS.join("\n");
}

function renderFieldsSidebar(){
  const list = document.getElementById("fieldsList");
  const q = (document.getElementById("fieldsSearch").value || "").toLowerCase().trim();
  list.innerHTML = "";

  CURRENT_FIELDS
    .filter(f => !q || f.toLowerCase().includes(q))
    .forEach(field => {
      const item = document.createElement("div");
      item.className = "field-chip";
      item.draggable = true;
      item.dataset.field = field;
      item.textContent = field;

      item.addEventListener("dragstart", (ev) => {
        ev.dataTransfer.setData("text/plain", JSON.stringify({ field, source: "fields" }));
      });

      list.appendChild(item);
    });
}

function clearBuilder(){
  BUILDER.filters = [];
  BUILDER.rows = [];
  BUILDER.cols = [];
  BUILDER.values = [];
  renderBuilder();
}

function addToZone(zone, field){
  if (zone === "values") {
    if (BUILDER.values.find(x => x.field === field)) return;
    BUILDER.values.push({ field, agg: "sum", label: "", numeric: true });
  } else {
    if (BUILDER[zone].includes(field)) return;
    BUILDER[zone].push(field);
  }
  renderBuilder();
}

function removeFromZone(zone, field){
  if (zone === "values") {
    BUILDER.values = BUILDER.values.filter(x => x.field !== field);
  } else {
    BUILDER[zone] = BUILDER[zone].filter(x => x !== field);
  }
  renderBuilder();
}

function renderBuilder(){
  renderSimpleZone("filters");
  renderSimpleZone("rows");
  renderSimpleZone("cols");
  renderValuesZone();
}

function renderSimpleZone(zone){
  const box = document.getElementById("zone-" + zone);
  box.innerHTML = "";

  BUILDER[zone].forEach(field => {
    const row = document.createElement("div");
    row.className = "drop-item";

    const name = document.createElement("span");
    name.textContent = field;

    const btn = document.createElement("button");
    btn.type = "button";
    btn.textContent = "Rimuovi";
    btn.onclick = () => removeFromZone(zone, field);

    row.appendChild(name);
    row.appendChild(btn);
    box.appendChild(row);
  });
}

function renderValuesZone(){
  const box = document.getElementById("zone-values");
  box.innerHTML = "";

  BUILDER.values.forEach(v => {
    const row = document.createElement("div");
    row.className = "drop-item";

    const left = document.createElement("div");
    left.innerHTML = `<div>${escapeHtml(v.field)}</div><div class="meta">Misura</div>`;

    const right = document.createElement("div");
    right.className = "actions-inline";

    const agg = document.createElement("select");
    ["sum","count","avg","min","max"].forEach(a => {
      const o = document.createElement("option");
      o.value = a;
      o.textContent = a;
      if (v.agg === a) o.selected = true;
      agg.appendChild(o);
    });
    agg.onchange = () => v.agg = agg.value;

    const label = document.createElement("input");
    label.placeholder = "Etichetta";
    label.value = v.label || "";
    label.oninput = () => v.label = label.value;

    const btn = document.createElement("button");
    btn.type = "button";
    btn.textContent = "Rimuovi";
    btn.onclick = () => removeFromZone("values", v.field);

    right.appendChild(agg);
    right.appendChild(label);
    right.appendChild(btn);

    row.appendChild(left);
    row.appendChild(right);
    box.appendChild(row);
  });
}

function initDropZones(){
  document.querySelectorAll(".drop-zone").forEach(zone => {
    zone.addEventListener("dragover", (ev) => {
      ev.preventDefault();
      zone.classList.add("active");
    });

    zone.addEventListener("dragleave", () => {
      zone.classList.remove("active");
    });

    zone.addEventListener("drop", (ev) => {
      ev.preventDefault();
      zone.classList.remove("active");
      try {
        const payload = JSON.parse(ev.dataTransfer.getData("text/plain"));
        addToZone(zone.dataset.zone, payload.field);
      } catch (_e) {}
    });
  });
}

function loadCurrentPresetIntoBuilder(){
  const preset = PRESETS.find(x => x.id === CURRENT);
  if (!preset) return;

  BUILDER.filters = [...(preset.filters || [])];
  BUILDER.rows = [...(preset.rows || [])];
  BUILDER.cols = [...(preset.cols || [])];
  BUILDER.values = (preset.values || []).map(v => ({
    field: v.field,
    agg: v.agg || "sum",
    label: v.label || "",
    numeric: true
  }));

  document.getElementById("presetFilename").value =
    ((preset._filename || (preset.id + ".json")).split("/").pop());

  document.getElementById("presetTitle").value = preset.title || "";
  renderBuilder();
}

async function saveBuilderPreset(){
  const filename = document.getElementById("presetFilename").value.trim();
  const title = document.getElementById("presetTitle").value.trim();

  if (!filename) throw new Error("Inserisci il nome file JSON");
  if (!BUILDER.values.length) throw new Error("Inserisci almeno una misura");
  if (!BUILDER.rows.length && !BUILDER.cols.length) {
    throw new Error("Inserisci almeno una riga o una colonna");
  }

  const numericFields = BUILDER.values
    .filter(v => ["sum","avg","min","max"].includes(v.agg))
    .map(v => v.field);

  const payload = {
    source_id: CURRENT_SOURCE,
    filename,
    title: title || filename.replace(/\.json$/i, ""),
    filters: [...BUILDER.filters],
    rows: [...BUILDER.rows],
    cols: [...BUILDER.cols],
    numeric_fields: [...new Set(numericFields)],
    date_fields: BUILDER.filters.filter(x => x.includes("DATA")),
    values: BUILDER.values.map(v => ({
      field: v.field,
      agg: v.agg,
      label: v.label || ""
    }))
  };

  setStatus("Salvataggio preset in corso...");

  const j = await api("/preset-editor/save", {
    method: "POST",
    body: JSON.stringify(payload)
  });

  CURRENT = payload.filename.replace(/\.json$/i, "");
  await loadPresets();
  await renderFilters();
  await runCurrent();
  setStatus("Preset salvato: " + (j.filename || payload.filename));
}

function escapeHtml(v){
  return String(v ?? "")
    .replaceAll("&","&amp;")
    .replaceAll("<","&lt;")
    .replaceAll(">","&gt;")
    .replaceAll('"',"&quot;")
    .replaceAll("'","&#39;");
}

function bindEvents(){
  document.getElementById("fieldsSearch").addEventListener("input", renderFieldsSidebar);

  document.getElementById("btnReload").onclick = () =>
    Promise.resolve()
      .then(loadFields)
      .then(loadPresets)
      .catch(e => setStatus("ERRORE: " + e.message));

  document.getElementById("btnPrint").onclick = () => window.print();

  document.getElementById("btnToggleColumns").onclick = () => {
    const panel = document.getElementById("columnsPanel");
    panel.classList.toggle("hidden");
    document.getElementById("btnToggleColumns").innerText =
      panel.classList.contains("hidden") ? "Mostra colonne" : "Nascondi colonne";
  };

  document.getElementById("btnBuilderClear").onclick = clearBuilder;
  document.getElementById("btnBuilderLoadCurrent").onclick = loadCurrentPresetIntoBuilder;
  document.getElementById("btnBuilderSave").onclick = async () => {
    try {
      await saveBuilderPreset();
    } catch (e) {
      setStatus("ERRORE: " + e.message);
    }
  };
}

async function boot(){
  try {
    bindEvents();
    initDropZones();
    await loadSources();
    await loadFields();
    await loadPresets();
    renderBuilder();
  } catch (e) {
    setStatus("ERRORE: " + e.message);
  }
}

document.addEventListener("DOMContentLoaded", boot);