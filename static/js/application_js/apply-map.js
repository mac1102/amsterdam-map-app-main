import { state } from "../state.js";
import { dom } from "../dom.js";
import { showToast, esc, getJSON } from "../utils.js";
import { TRAM_LINE_IDS } from "./apply-wizard.js";

const TARGET_TYPES = Object.freeze(["rail_segment", "switch_junction", "overhead_section"]);

export const APPLY_PREVIEW_MAP_MAX_ZOOM = 18;
export const APPLY_PREVIEW_NL_BOUNDS = L.latLngBounds([50.7, 3.1], [53.7, 7.3]);

let applicationMapDataCache = null;

export function normalizeTargetType(value) {
  const type = String(value || "rail_segment").trim().toLowerCase();
  return TARGET_TYPES.includes(type) ? type : "rail_segment";
}

export function getTargetTypeLabel(targetOrType) {
  const type = normalizeTargetType(
    typeof targetOrType === "string" ? targetOrType : (targetOrType?.targetType || targetOrType?.target_type)
  );
  if (type === "switch_junction") return "Switch/Junction";
  if (type === "overhead_section") return "Overhead";
  return "Rail";
}

export function getTargetReviewLabel(target) {
  const type = normalizeTargetType(target?.targetType || target?.target_type);
  const assetId = String(target?.assetId || target?.asset_id || target?.segmentId || target?.segment_id || "").trim();
  const segmentId = String(target?.segmentId || target?.segment_id || "").trim();
  const label = String(target?.assetLabel || target?.asset_label || "").trim();

  if (type === "switch_junction") return label || `Switch/Junction ${assetId || segmentId || "-"}`;
  if (type === "overhead_section") return label || `Overhead section ${assetId || "-"}`;
  return label || `Rail segment ${segmentId || assetId || "-"}`;
}

export function getTargetSubtitle(target) {
  const lineName = String(target?.lineName || target?.line_name || "").trim();
  const lineId = String(target?.lineId || target?.line_id || "").trim();
  const segmentId = String(target?.segmentId || target?.segment_id || "").trim();
  const type = normalizeTargetType(target?.targetType || target?.target_type);
  const parts = [];

  if (lineName) parts.push(lineName);
  if (lineId) parts.push(`(${lineId})`);
  if (type !== "rail_segment" && segmentId) parts.push(`Segment ${segmentId}`);
  return parts.join(" ") || "-";
}

export function targetSupportsCustomArea(target) {
  const type = normalizeTargetType(target?.targetType || target?.target_type);
  const hasGeometry = Array.isArray(target?.geometry) && target.geometry.length > 0;
  return hasGeometry && (type === "rail_segment" || type === "overhead_section");
}

export function getTargetKey(target) {
  const type = normalizeTargetType(target?.targetType || target?.target_type);
  const id = String(target?.assetId || target?.asset_id || target?.segmentId || target?.segment_id || "").trim();
  return id ? `${type}:${id}` : "";
}

export function getFeatureSegmentId(feature) {
  const p = feature?.properties || {};
  return String(
    p.k ||
    p.segment_id ||
    p.id ||
    p.SEGMENT_ID ||
    ""
  ).trim();
}

export function getSwitchAssetId(properties = {}) {
  return String(properties.w || properties.k || properties.id || "").trim();
}

export function getOverheadAssetId(properties = {}) {
  const rawId = String(properties.id || "").trim();
  if (!rawId) return "";
  return rawId.startsWith("BL-") ? rawId : `BL-${rawId}`;
}

export function featureMatchesTarget(feature, target) {
  const type = normalizeTargetType(target?.target_type || target?.targetType);
  const assetId = String(target?.asset_id || target?.assetId || target?.segment_id || target?.segmentId || "").trim();
  const segmentId = String(target?.segment_id || target?.segmentId || "").trim();
  const p = feature?.properties || {};

  if (type === "overhead_section") {
    return !!assetId && getOverheadAssetId(p) === assetId;
  }

  if (type === "switch_junction") {
    return (assetId && getSwitchAssetId(p) === assetId) ||
      (segmentId && getFeatureSegmentId(feature) === segmentId);
  }

  return !!(segmentId || assetId) && getFeatureSegmentId(feature) === (segmentId || assetId);
}

export function cloneFeatureWithTargetMeta(feature, target) {
  return {
    ...feature,
    properties: {
      ...(feature?.properties || {}),
      __target_type: normalizeTargetType(target?.target_type || target?.targetType),
      __asset_id: String(target?.asset_id || target?.assetId || target?.segment_id || target?.segmentId || "").trim(),
      __asset_label: getTargetReviewLabel(target)
    }
  };
}

export function findTargetFeatures(mapData, targets) {
  const spoorFeatures =
    mapData?.spoor_data?.features ||
    mapData?.spoor?.features ||
    mapData?.kge?.features ||
    [];
  const overheadFeatures =
    mapData?.bovenleiding_data?.features ||
    mapData?.bovenleiding?.features ||
    [];
  const matched = [];

  (targets || []).forEach((target) => {
    const type = normalizeTargetType(target?.target_type || target?.targetType);
    const source = type === "overhead_section" ? overheadFeatures : spoorFeatures;
    const feature = source.find((item) => featureMatchesTarget(item, target));
    if (feature) matched.push(cloneFeatureWithTargetMeta(feature, target));
  });

  return matched;
}

export function uniqueTruthy(values) {
  return [...new Set((values || []).map(v => String(v || "").trim()).filter(Boolean))];
}

export async function loadApplicationMapData() {
  if (applicationMapDataCache) return applicationMapDataCache;

  if (typeof globalThis !== "undefined" && globalThis.SPOOR_DATA) {
    applicationMapDataCache = {
      spoor_data: globalThis.SPOOR_DATA,
      bovenleiding_data: globalThis.BOVENLEIDING_DATA
    };
    return applicationMapDataCache;
  }

  applicationMapDataCache = await getJSON("/api/map-data");
  return applicationMapDataCache;
}

export function focusMainMap() {
  const mapPage = document.getElementById("mapPage");
  mapPage?.scrollIntoView({ behavior: "smooth", block: "start" });

  if (state.map && typeof state.map.invalidateSize === "function") {
    requestAnimationFrame(() => state.map.invalidateSize());
    setTimeout(() => {
      if (state.map) state.map.invalidateSize();
    }, 180);
  }
}

export function clearApplicationTargetHighlight() {
  if (state.applicationTargetHighlightTimeout) {
    clearTimeout(state.applicationTargetHighlightTimeout);
    state.applicationTargetHighlightTimeout = null;
  }

  if (state.applicationTargetHighlightLayer && state.map) {
    try {
      state.map.removeLayer(state.applicationTargetHighlightLayer);
    } catch (_) {}
  }

  state.applicationTargetHighlightLayer = null;
}

export async function zoomToApplicationTargets(application) {
  const targets = Array.isArray(application?.targets) ? application.targets : [];
  const wantedKeys = [...new Set(targets.map(getTargetKey).filter(Boolean))];

  if (!wantedKeys.length) {
    showToast({
      title: "Show on map",
      message: "No target found for this application.",
      durationMs: 4000
    });
    return;
  }

  const map = state.map;
  if (!map || typeof L === "undefined") {
    showToast({
      title: "Show on map",
      message: "Main map is unavailable right now.",
      durationMs: 4000
    });
    return;
  }

  focusMainMap();
  clearApplicationTargetHighlight();

  const matchedFeatures = [];

  targets.forEach((target) => {
    const type = normalizeTargetType(target?.target_type);
    let layer = null;

    if (type === "rail_segment") {
      layer = state.segmentLayers?.get?.(target.segment_id || target.asset_id);
    } else if (type === "switch_junction") {
      layer = state.switchLayers?.get?.(target.asset_id) || state.switchSegmentLayers?.get?.(target.segment_id);
    } else if (type === "overhead_section") {
      layer = state.overheadLayers?.get?.(target.asset_id);
    }

    if (layer && typeof layer.toGeoJSON === "function") {
      matchedFeatures.push(cloneFeatureWithTargetMeta(layer.toGeoJSON(), target));
    }
  });

  const matchedKeys = new Set(
    matchedFeatures
      .map((feature) => {
        const p = feature?.properties || {};
        return `${normalizeTargetType(p.__target_type)}:${String(p.__asset_id || "").trim()}`;
      })
      .filter(Boolean)
  );
  const unresolvedTargets = targets.filter((target) => {
    const key = getTargetKey(target);
    return key && !matchedKeys.has(key);
  });

  if (unresolvedTargets.length) {
    const mapData = await loadApplicationMapData();
    matchedFeatures.push(...findTargetFeatures(mapData, unresolvedTargets));
  }

  if (!matchedFeatures.length) {
    console.warn("No matching target geometry found", wantedKeys);
    showToast({
      title: "Show on map",
      message: "Could not find geometry for this application.",
      durationMs: 4500
    });
    return;
  }

  const highlightLayer = L.geoJSON(
    {
      type: "FeatureCollection",
      features: matchedFeatures
    },
    {
      style: (feature) => {
        const type = normalizeTargetType(feature?.properties?.__target_type);
        return {
          color: type === "overhead_section" ? "#7c3aed" : "#e60012",
          weight: 8,
          opacity: 1,
          lineCap: "round",
          lineJoin: "round"
        };
      },
      onEachFeature: (feature, layer) => {
        const p = feature?.properties || {};
        const label = p.__asset_label || p.__asset_id || getFeatureSegmentId(feature);
        layer.bindTooltip(`Application target: ${label}`, {
          sticky: true
        });
      }
    }
  ).addTo(map);

  highlightLayer.eachLayer((layer) => {
    if (typeof layer.bringToFront === "function") layer.bringToFront();
  });

  state.applicationTargetHighlightLayer = highlightLayer;

  const bounds = highlightLayer.getBounds();
  if (bounds.isValid()) {
    map.fitBounds(bounds, {
      padding: [60, 60],
      maxZoom: 17
    });
  }

  state.applicationTargetHighlightTimeout = setTimeout(() => {
    if (state.applicationTargetHighlightLayer !== highlightLayer || !state.map) return;
    state.map.removeLayer(highlightLayer);
    state.applicationTargetHighlightLayer = null;
    state.applicationTargetHighlightTimeout = null;
  }, 8000);
}

export function toFiniteNumber(value) {
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

export function normalizeSegmentGeometryPaths(geometry) {
  if (!Array.isArray(geometry) || geometry.length === 0) return [];

  const asLatLngPath = (path) => {
    if (!Array.isArray(path)) return [];

    return path
      .map((point) => {
        if (!Array.isArray(point) || point.length < 2) return null;
        const lng = toFiniteNumber(point[0]);
        const lat = toFiniteNumber(point[1]);
        if (lng === null || lat === null) return null;
        return [lat, lng];
      })
      .filter(Boolean);
  };

  const first = geometry[0];
  if (Array.isArray(first) && typeof first[0] === "number") {
    const single = asLatLngPath(geometry);
    return single.length >= 2 ? [single] : [];
  }

  if (Array.isArray(first) && Array.isArray(first[0])) {
    return geometry
      .map(asLatLngPath)
      .filter((path) => path.length >= 2);
  }

  return [];
}

export function previewPointToLatLng(map, point) {
  const x = toFiniteNumber(point?.x);
  const y = toFiniteNumber(point?.y);
  if (x === null || y === null) return null;

  // Support both current preview points (projected x/y) and legacy lng/lat payloads.
  if (Math.abs(x) <= 180 && Math.abs(y) <= 90) {
    return L.latLng(y, x);
  }
  return map.unproject([x, y], state.maxZoom);
}

export function createPreviewMap(containerId, seg, index) {
  const el = document.getElementById(containerId);
  if (!el || !seg.geometry?.length) return;

  const paths = normalizeSegmentGeometryPaths(seg.geometry);
  if (!paths.length) return;

  const map = L.map(el, {
    zoomControl: true,
    attributionControl: false,
    dragging: true,
    scrollWheelZoom: true,
    doubleClickZoom: true,
    boxZoom: false,
    keyboard: false,
    preferCanvas: true,
    minZoom: 7,
    maxZoom: APPLY_PREVIEW_MAP_MAX_ZOOM,
  });

  L.tileLayer("https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png", {
    attribution: "&copy; OpenStreetMap &copy; CARTO",
    maxZoom: APPLY_PREVIEW_MAP_MAX_ZOOM,
    noWrap: true,
  }).addTo(map);

  const targetType = normalizeTargetType(seg.targetType);
  const previewColor = targetType === "overhead_section"
    ? "#7c3aed"
    : targetType === "switch_junction"
      ? "#f5a623"
      : "#cc4b12";

  const lineLayer = L.featureGroup(
    paths.map((latLngPath) => L.polyline(latLngPath, {
      color: previewColor,
      weight: 8,
      opacity: 0.95,
      lineCap: "round",
      lineJoin: "round",
    }))
  ).addTo(map);

  const bounds = lineLayer.getBounds();
  if (bounds.isValid()) {
    map.fitBounds(bounds, { padding: [16, 16] });
  } else {
    map.setView([52.3676, 4.9041], 12);
  }
  map.setMaxBounds(APPLY_PREVIEW_NL_BOUNDS);

  const previewState = {
    map,
    lineLayer,
    startMarker: null,
    endMarker: null,
    clickMode: null,
  };

  state.segmentPreviews[index] = previewState;

  // Restore existing markers if already set.
  if (seg.workStartPoint) {
    const ll = previewPointToLatLng(map, seg.workStartPoint);
    if (ll) previewState.startMarker = L.marker(ll, { title: "Start pin" }).addTo(map);
  }

  if (seg.workEndPoint) {
    const ll = previewPointToLatLng(map, seg.workEndPoint);
    if (ll) previewState.endMarker = L.marker(ll, { title: "End pin" }).addTo(map);
  }

  map.on("click", (e) => {
    if (seg.workMode !== "custom-area") return;
    if (!previewState.clickMode) return;

    // Keep x/y payload shape used by the apply API.
    const point = map.project(e.latlng, state.maxZoom);
    const x = Math.round(point.x);
    const y = Math.round(point.y);

    if (previewState.clickMode === "start") {
      seg.workStartPoint = { x, y };
      if (previewState.startMarker) {
        previewState.startMarker.setLatLng(e.latlng);
      } else {
        previewState.startMarker = L.marker(e.latlng, { title: "Start pin" }).addTo(map);
      }
    }

    if (previewState.clickMode === "end") {
      seg.workEndPoint = { x, y };
      if (previewState.endMarker) {
        previewState.endMarker.setLatLng(e.latlng);
      } else {
        previewState.endMarker = L.marker(e.latlng, { title: "End pin" }).addTo(map);
      }
    }

    updatePinStatus(index);
  });

  setTimeout(() => map.invalidateSize(), 50);
}

export function updatePinStatus(index) {
  const seg = state.applyWizard.segments[index];
  const preview = state.segmentPreviews[index];
  const host = document.getElementById(`pinStatus_${index}`);
  if (!host) return;

  if (seg.workMode === "whole-segment") {
    host.textContent = "Whole target selected.";
    return;
  }

  const start = seg.workStartPoint
    ? `Start pin: ${seg.workStartPoint.x}, ${seg.workStartPoint.y}`
    : "Start pin not set";

  const end = seg.workEndPoint
    ? `End pin: ${seg.workEndPoint.x}, ${seg.workEndPoint.y}`
    : "End pin not set";

  const mode = preview?.clickMode
    ? `Active mode: ${preview.clickMode}`
    : "Active mode: none";

  host.textContent = `${start} | ${end} | ${mode}`;
}

export function wireSegmentCardControls(index) {
  const seg = state.applyWizard.segments[index];

  const radios = document.querySelectorAll(`input[name="workMode_${index}"]`);
  radios.forEach(r => {
    r.addEventListener("change", () => {
      seg.workMode = r.value;

      const preview = state.segmentPreviews[index];
      if (seg.workMode === "whole-segment" && preview) {
        preview.clickMode = null;
      }

      updatePinStatus(index);
    });
  });

  const startBtn = document.querySelector(`[data-pin-start="${index}"]`);
  const endBtn = document.querySelector(`[data-pin-end="${index}"]`);
  const clearBtn = document.querySelector(`[data-pin-clear="${index}"]`);

  if (startBtn) {
    startBtn.addEventListener("click", () => {
      const preview = state.segmentPreviews[index];
      if (!preview) return;

      seg.workMode = "custom-area";
      const customRadio = document.querySelector(`input[name="workMode_${index}"][value="custom-area"]`);
      if (customRadio) customRadio.checked = true;

      preview.clickMode = preview.clickMode === "start" ? null : "start";
      updatePinStatus(index);
    });
  }

  if (endBtn) {
    endBtn.addEventListener("click", () => {
      const preview = state.segmentPreviews[index];
      if (!preview) return;

      seg.workMode = "custom-area";
      const customRadio = document.querySelector(`input[name="workMode_${index}"][value="custom-area"]`);
      if (customRadio) customRadio.checked = true;

      preview.clickMode = preview.clickMode === "end" ? null : "end";
      updatePinStatus(index);
    });
  }

  if (clearBtn) {
    clearBtn.addEventListener("click", () => {
      seg.workStartPoint = null;
      seg.workEndPoint = null;

      const preview = state.segmentPreviews[index];
      if (preview?.startMarker) {
        preview.map.removeLayer(preview.startMarker);
        preview.startMarker = null;
      }
      if (preview?.endMarker) {
        preview.map.removeLayer(preview.endMarker);
        preview.endMarker = null;
      }
      if (preview) {
        preview.clickMode = null;
      }

      updatePinStatus(index);
    });
  }
}

export function renderLocationSummaryStep1() {
  if (!dom.applyLocationSummary) return;

  const segments = state.applyWizard.segments || [];
  const lineIds = uniqueTruthy(segments.map(seg => seg.lineId).filter((id) => TRAM_LINE_IDS.includes(String(id))));
  const linePairs = uniqueTruthy(segments.map((seg) => {
    const name = String(seg.lineName || "").trim();
    const id = String(seg.lineId || "").trim();
    if (name && id) return `${name} (${id})`;
    return name || id;
  }));
  const assetLabels = uniqueTruthy(segments.map(getTargetReviewLabel));
  const typeCounts = segments.reduce((acc, seg) => {
    const label = getTargetTypeLabel(seg);
    acc[label] = (acc[label] || 0) + 1;
    return acc;
  }, {});
  const typeText = Object.entries(typeCounts)
    .map(([label, count]) => `${label}: ${count}`)
    .join(", ") || "-";

  const lineText = linePairs.join(", ") || lineIds.join(", ") || "-";

  dom.applyLocationSummary.innerHTML = `
    <div class="apply-summary-card">
      <span class="apply-summary-label">Target type</span>
      <strong>${esc(typeText)}</strong>
    </div>
    <div class="apply-summary-card">
      <span class="apply-summary-label">Selected targets</span>
      <strong>${segments.length}</strong>
    </div>
    <div class="apply-summary-card apply-summary-card-wide">
      <span class="apply-summary-label">Lines</span>
      <strong>${esc(lineText)}</strong>
    </div>
    <div class="apply-summary-card apply-summary-card-wide">
      <span class="apply-summary-label">Assets</span>
      <strong>${esc(assetLabels.join(", ") || "-")}</strong>
    </div>
  `;
}

export function renderSegmentCardsStep1() {
  const host = document.getElementById("multiSegmentStep1List");
  if (!host) return;

  renderLocationSummaryStep1();

  host.innerHTML = "";
  state.segmentPreviews.forEach(p => {
    if (p?.map) p.map.remove();
  });
  state.segmentPreviews = [];

  state.applyWizard.segments.forEach((seg, index) => {
    const hasGeometry = Array.isArray(seg.geometry) && seg.geometry.length > 0;
    const canUseCustomArea = targetSupportsCustomArea(seg);
    if (!canUseCustomArea && seg.workMode === "custom-area") {
      seg.workMode = "whole-segment";
      seg.workStartPoint = null;
      seg.workEndPoint = null;
    }

    const card = document.createElement("div");
    card.className = "review-card";
    card.innerHTML = `
      <div class="target-card-heading">
        <h4>Target ${index + 1}</h4>
        <span class="target-type-badge">${esc(getTargetTypeLabel(seg))}</span>
      </div>
      <p><strong>${esc(getTargetReviewLabel(seg))}</strong></p>
      <p class="hint">${esc(getTargetSubtitle(seg))}</p>

      <label class="wizard-radio">
        <input type="radio" name="workMode_${index}" value="whole-segment" ${seg.workMode === "whole-segment" ? "checked" : ""}>
        <span>${normalizeTargetType(seg.targetType) === "overhead_section" ? "Use whole overhead section" : "Use whole target"}</span>
      </label>

      <label class="wizard-radio ${canUseCustomArea ? "" : "is-hidden"}">
        <input
          type="radio"
          name="workMode_${index}"
          value="custom-area"
          ${seg.workMode === "custom-area" ? "checked" : ""}
          ${canUseCustomArea ? "" : "disabled"}
        >
        <span>Choose specific work area</span>
      </label>

      ${
        hasGeometry
          ? `
            <div class="segment-preview-caption">Current map preview</div>
            <div id="segmentPreview_${index}" class="segment-preview-map segment-preview-map-current"></div>
            ${
              canUseCustomArea
                ? `
                  <div class="pin-toolbar">
                    <button type="button" class="btn" data-pin-start="${index}">Set start pin</button>
                    <button type="button" class="btn" data-pin-end="${index}">Set end pin</button>
                    <button type="button" class="btn" data-pin-clear="${index}">Clear pins</button>
                  </div>
                  <div id="pinStatus_${index}" class="form-result"></div>
                `
                : `<div class="form-result">Pins are not used for this target type.</div>`
            }
          `
          : `
            <div class="segment-preview-placeholder" style="margin-top:10px;">
              No exact segment geometry available for this target.
            </div>
          `
      }
    `;
    host.appendChild(card);
  });

  state.applyWizard.segments.forEach((seg, index) => {
    const hasGeometry = Array.isArray(seg.geometry) && seg.geometry.length > 0;

    if (hasGeometry) {
      createPreviewMap(`segmentPreview_${index}`, seg, index);
      wireSegmentCardControls(index);
      updatePinStatus(index);
    } else {
      seg.workMode = "whole-segment";
    }
  });
}
