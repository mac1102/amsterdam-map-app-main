import { state, STYLE_BASE, STYLE_DIM, STYLE_SEL } from "./state.js";
import { dom } from "./dom.js";
import { t } from "./i18n.js";
import { setDetails } from "./utils.js";

let filterSelectionHandler = null;

export function setFilterSelectionHandler(fn) {
  filterSelectionHandler = fn;
}

function setLayerInteractivity(layer, enabled) {
  layer.options.interactive = !!enabled;
  const el = layer.getElement?.();
  if (el) el.style.pointerEvents = enabled ? "auto" : "none";
}

export function allLineIds() {
  return Array.from(state.lineIndex.keys());
}

export function isLineVisible(lineId) {
  if (!state.visibleLineIds || state.visibleLineIds.size === 0) return false;
  return state.visibleLineIds.has(lineId);
}

export function applyOverlayStyles() {
  for (const [segId, layer] of state.segmentLayers.entries()) {
    const lineId = layer.featureMeta?.line_id;
    const visible = isLineVisible(lineId);

    if (!visible) {
      layer.setStyle({ opacity: 0, weight: 0 });
      setLayerInteractivity(layer, false);
      continue;
    }

    setLayerInteractivity(layer, true);

    let style = { weight: STYLE_BASE.weight, opacity: STYLE_BASE.opacity };

    // Spotlight mode: one searched/selected line pops out strongly
    if (state.spotlightLineId) {
      style = (lineId === state.spotlightLineId)
        ? { weight: 16, opacity: 1 }
        : { weight: STYLE_DIM.weight, opacity: 0.08 };
    }
    // Normal highlight mode
    else if (state.highlightedLineId) {
      style = (lineId === state.highlightedLineId)
        ? { weight: STYLE_BASE.weight, opacity: STYLE_BASE.opacity }
        : { weight: STYLE_DIM.weight, opacity: STYLE_DIM.opacity };
    }

    if (state.selectedSegmentId && segId === state.selectedSegmentId) {
      style = { ...style, weight: STYLE_SEL.weight, opacity: STYLE_SEL.opacity };
      layer.bringToFront();
    }

    layer.setStyle(style);
  }
}

export function clearHighlights() {
  state.highlightedLineId = "";
  state.spotlightLineId = "";
  state.selectedSegmentId = null;
  applyOverlayStyles();
}

export function setHighlightedLine(lineId) {
  state.highlightedLineId = lineId || "";
  applyOverlayStyles();
}

export function setSelectedSegment(segId) {
  state.selectedSegmentId = segId;
  applyOverlayStyles();
}

export function ensureSelectionVisible() {
  if (!state.currentSelection) return;

  if (state.currentSelection.type === "line") {
    const lineId = state.currentSelection.line_id;
    if (!lineId) return;

    if (!isLineVisible(lineId)) {
      clearHighlights();
      state.currentSelection = null;
      setDetails(`<p>${t("no_selection_yet")}</p>`);
      if (dom.lineSelect) dom.lineSelect.value = "";
    }
  }
}

export function renderFilterList() {
  if (!dom.filterList) return;

  const q = (dom.filterSearch?.value || "").trim().toLowerCase();
  const items = state.lineItems.slice();

  const filtered = q
    ? items.filter(it =>
        it.nameLower.includes(q) ||
        it.idLower.includes(q) ||
        it.display.toLowerCase().includes(q)
      )
    : items;

  dom.filterList.innerHTML = "";

  if (filtered.length === 0) {
    const empty = document.createElement("div");
    empty.className = "filter-empty";
    empty.textContent = t("no_results");
    dom.filterList.appendChild(empty);
    return;
  }

  for (const it of filtered) {
    const row = document.createElement("div");
    row.className = "filter-item";

    const left = document.createElement("div");
    left.className = "filter-left";

    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.className = "filter-checkbox";
    cb.checked = isLineVisible(it.id);

    cb.addEventListener("click", (e) => {
      e.stopPropagation();
    });

    cb.addEventListener("change", () => {
      if (cb.checked) state.visibleLineIds.add(it.id);
      else state.visibleLineIds.delete(it.id);

      applyOverlayStyles();
      ensureSelectionVisible();
      renderFilterList();
    });

    const name = document.createElement("div");
    name.className = "filter-name";
    name.textContent = it.name;

    const rid = document.createElement("div");
    rid.className = "filter-id";
    rid.textContent = it.id;

    row.addEventListener("click", () => {
      if (state.currentSelection?.type === "segment-list") {
        if (!isLineVisible(it.id)) {
          state.visibleLineIds.add(it.id);
          renderFilterList();
          applyOverlayStyles();
        }
        return;
      }

      if (!isLineVisible(it.id)) {
        state.visibleLineIds.add(it.id);
        renderFilterList();
        applyOverlayStyles();
      }

      if (typeof filterSelectionHandler === "function") {
        filterSelectionHandler([it.id]);
      }
    });

    left.appendChild(cb);
    left.appendChild(name);
    row.appendChild(left);
    row.appendChild(rid);
    dom.filterList.appendChild(row);
  }
}

export function setAllLinesVisible() {
  state.visibleLineIds = new Set(allLineIds());
  applyOverlayStyles();
  renderFilterList();
}

export function setAllLinesHidden() {
  state.visibleLineIds = new Set();
  applyOverlayStyles();

  clearHighlights();
  state.currentSelection = null;
  setDetails(`<p>${t("no_selection_yet")}</p>`);
  if (dom.lineSelect) dom.lineSelect.value = "";

  renderFilterList();
}
