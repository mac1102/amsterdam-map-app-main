import { state } from "./state.js";
import { esc } from "./utils.js";

const WIOR_FILTER_MODES = new Set(["active", "next7", "next30", "all"]);
const wiorFeatureCache = new Map();

function formatValue(value) {
  if (value === null || value === undefined || value === "") return "-";
  return esc(String(value));
}

function wiorPopupHtml(props = {}) {
  return `
    <div class="wior-popup">
      <div><strong>WIOR</strong></div>
      <div><strong>ID:</strong> ${formatValue(props.wior_id)}</div>
      <div><strong>Code:</strong> ${formatValue(props.project_code)}</div>
      <div><strong>Name:</strong> ${formatValue(props.project_name)}</div>
      <div><strong>Description:</strong> ${formatValue(props.description)}</div>
      <div><strong>Status:</strong> ${formatValue(props.status)}</div>
      <div><strong>Type:</strong> ${formatValue(props.work_type)}</div>
      <div><strong>Start:</strong> ${formatValue(props.start_date)}</div>
      <div><strong>End:</strong> ${formatValue(props.end_date)}</div>
    </div>
  `;
}

function wiorStyle() {
  return {
    color: "#c97a12",
    weight: 1.5,
    opacity: 0.55,
    fillColor: "#d89a44",
    fillOpacity: 0.16
  };
}

function wiorPointToLayer(feature, latlng) {
  return L.circleMarker(latlng, {
    radius: 4,
    color: "#c97a12",
    weight: 1.5,
    opacity: 0.7,
    fillColor: "#d89a44",
    fillOpacity: 0.45
  });
}

function onEachWiorFeature(feature, layer) {
  const props = feature?.properties || {};
  layer.bindPopup(wiorPopupHtml(props));
}

function normalizeWiorMode(mode) {
  const normalized = typeof mode === "string" ? mode.trim().toLowerCase() : "";
  return WIOR_FILTER_MODES.has(normalized) ? normalized : "active";
}

function normalizeDateOnly(value) {
  if (!value) return "";
  return String(value).slice(0, 10);
}

function isWiorFeatureActiveOnDate(feature, selectedDate) {
  const props = feature?.properties || {};
  const startDate = normalizeDateOnly(props.start_date);
  const endDate = normalizeDateOnly(props.end_date);
  return !!(startDate && endDate && startDate <= selectedDate && selectedDate <= endDate);
}

function buildWiorLayer(featureCollection) {
  if (!featureCollection) return null;

  return L.geoJSON(featureCollection, {
    style: wiorStyle,
    pointToLayer: wiorPointToLayer,
    onEachFeature: onEachWiorFeature
  });
}

async function loadWiorFeatureCollection(mode = "active") {
  const resolvedMode = normalizeWiorMode(mode);

  if (wiorFeatureCache.has(resolvedMode)) {
    return wiorFeatureCache.get(resolvedMode);
  }

  try {
    const res = await fetch(`/api/wior/features?mode=${encodeURIComponent(resolvedMode)}`);
    if (!res.ok) {
      throw new Error(`WIOR backend returned ${res.status} ${res.statusText}`);
    }

    const data = await res.json();
    wiorFeatureCache.set(resolvedMode, data);
    return data;
  } catch (err) {
    console.error("Failed to load WIOR layer:", err);
    return null;
  }
}

function removeLayerIfPresent(map, layer) {
  if (!map || !layer) return;
  if (map.hasLayer(layer)) {
    map.removeLayer(layer);
  }
}

export async function loadWiorLayerForMode(mode = "active") {
  const data = await loadWiorFeatureCollection(mode);
  return buildWiorLayer(data);
}

export async function reloadWiorLayer(map, mode = "active") {
  const resolvedMode = normalizeWiorMode(mode);
  const existingDisplayLayer = state.timeline?.wiorFilteredLayer || state.wiorLayer || null;
  const wasVisible = !!(map && existingDisplayLayer && map.hasLayer(existingDisplayLayer));

  removeLayerIfPresent(map, existingDisplayLayer);

  if (state.timeline?.wiorBaseLayer && state.timeline.wiorBaseLayer !== existingDisplayLayer) {
    removeLayerIfPresent(map, state.timeline.wiorBaseLayer);
  }

  const nextBaseLayer = await loadWiorLayerForMode(resolvedMode);
  state.wiorFilterMode = resolvedMode;

  if (state.timeline?.selectedDate) {
    state.timeline.wiorBaseLayer = nextBaseLayer;
    state.wiorLayer = nextBaseLayer;
    await applyWiorDateFilter(map, state.timeline.selectedDate);
    return state.wiorLayer;
  }

  state.wiorLayer = nextBaseLayer;

  if (wasVisible && map && nextBaseLayer) {
    nextBaseLayer.addTo(map);
  }

  return nextBaseLayer;
}

export async function applyWiorDateFilter(map, selectedDate) {
  const resolvedDate = normalizeDateOnly(selectedDate);
  if (!resolvedDate) return null;

  if (!state.timeline.wiorBaseLayer) {
    state.timeline.wiorBaseLayer = state.wiorLayer || await loadWiorLayerForMode(state.wiorFilterMode || "active");
  }

  if (state.timeline.previousWiorVisible === null) {
    state.timeline.previousWiorVisible = !!state.mapLayerVisibility?.wiorProjects;
  }

  removeLayerIfPresent(map, state.timeline.wiorFilteredLayer);
  removeLayerIfPresent(map, state.timeline.wiorBaseLayer);

  const fullFeatureCollection = await loadWiorFeatureCollection("all");
  const filteredFeatures = Array.isArray(fullFeatureCollection?.features)
    ? fullFeatureCollection.features.filter((feature) => isWiorFeatureActiveOnDate(feature, resolvedDate))
    : [];

  state.timeline.wiorFilteredLayer = buildWiorLayer({
    type: "FeatureCollection",
    features: filteredFeatures
  });
  state.wiorLayer = state.timeline.wiorFilteredLayer;
  state.mapLayerVisibility.wiorProjects = true;

  if (map && state.timeline.wiorFilteredLayer) {
    state.timeline.wiorFilteredLayer.addTo(map);
  }

  return state.timeline.wiorFilteredLayer;
}

export function clearWiorDateFilter(map) {
  const restoredLayer = state.timeline.wiorBaseLayer || state.wiorLayer || null;

  removeLayerIfPresent(map, state.timeline.wiorFilteredLayer);

  if (typeof state.timeline.previousWiorVisible === "boolean") {
    state.mapLayerVisibility.wiorProjects = state.timeline.previousWiorVisible;
  }

  state.timeline.wiorFilteredLayer = null;
  state.timeline.wiorBaseLayer = null;
  state.timeline.previousWiorVisible = null;
  state.wiorLayer = restoredLayer;

  if (map && restoredLayer) {
    if (state.mapLayerVisibility.wiorProjects) {
      restoredLayer.addTo(map);
    } else {
      removeLayerIfPresent(map, restoredLayer);
    }
  }

  return restoredLayer;
}

export function addWiorLayerToMap(map) {
  if (!map || !state.wiorLayer) return;
  if (!map.hasLayer(state.wiorLayer)) {
    state.wiorLayer.addTo(map);
  }
}

export function removeWiorLayerFromMap(map) {
  if (!map || !state.wiorLayer) return;
  if (map.hasLayer(state.wiorLayer)) {
    map.removeLayer(state.wiorLayer);
  }
}

export function getWiorLayer() {
  return state.wiorLayer;
}
