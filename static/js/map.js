import { state } from "./state.js";
import { dom } from "./dom.js";
import { setStatus, setDetails, esc, getJSON, showToast, toISODate } from "./utils.js";
import { t } from "./i18n.js";
import {
  loadWiorLayerForMode,
  reloadWiorLayer,
  applyWiorDateFilter,
  clearWiorDateFilter
} from "./wior.js";
import { updateFavoriteButton } from "./favorites.js";
import {
  renderFilterList,
  applyOverlayStyles,
  clearHighlights,
  setHighlightedLine,
  setSelectedSegment
} from "./filters.js";
import {
  syncClearButton,
  closeCombo,
  setLineInputDisplay
} from "./combo.js";
import { handleHalteClickForTransfer } from "./transfer.js";

const MAP_CENTER = [52.3676, 4.9041];
const MAP_ZOOM = 14;
const MAP_MAX_ZOOM = 19;
const MAP_LAYER_VISIBILITY_KEY = "gvbMapLayerVisibility";
const MAP_LAYER_COLLAPSED_KEY = "gvbMapLayerPanelCollapsed";
const TIMELINE_DAYS_DEFAULT = 84;
const TIMELINE_HIGHLIGHT_STYLE = {
  color: "#e65100",
  weight: 7,
  opacity: 0.95,
  lineCap: "round",
  lineJoin: "round"
};
const TBGN_DEFAULT_COLOR = "#7c3aed";
const TBGN_SUPPORTED_GEOMETRIES = new Set([
  "Point",
  "LineString",
  "MultiLineString",
  "Polygon",
  "MultiPolygon"
]);

let timelineMapDataCache = null;
let timelineDayRequestSeq = 0;

const MAP_LAYER_DEFS = [
  {
    key: "networkFill",
    label: "Network fill / Spoortakken",
    swatch: "network-fill",
    color: "#78909c",
    defaultVisible: true
  },
  {
    key: "kgeModelGauge",
    label: "KGE rail segments",
    swatch: "kge-model-gauge",
    color: "#43a047",
    defaultVisible: true
  },
  {
    key: "switchesJunctions",
    label: "Switches/Junctions",
    swatch: "switches-junctions",
    color: "#f5a623",
    defaultVisible: true
  },
  {
    key: "overheadSections",
    label: "Overhead sections",
    swatch: "overhead-sections",
    color: "#b06bff",
    defaultVisible: true
  },
  {
    key: "activities",
    label: "Activities",
    swatch: "activities",
    color: "#4db6ff",
    defaultVisible: true
  },
  {
    key: "tbgnProjects",
    label: "TBGN Projects",
    swatch: "tbgn-projects",
    color: "#7be495",
    defaultVisible: true
  },
  {
    key: "wiorProjects",
    label: "WIOR Projects",
    swatch: "wior-projects",
    color: "#c97a12",
    defaultVisible: false
  },
  {
    key: "tramStops",
    label: "Tram stops",
    swatch: "tram-stops",
    color: "#47a8ff",
    defaultVisible: true
  },
];

function getPrototypeData(name) {
  if (typeof globalThis !== "undefined" && globalThis[name]) {
    return globalThis[name];
  }

  if (name === "SPOOR_DATA" && typeof SPOOR_DATA !== "undefined") return SPOOR_DATA;
  if (name === "SPOORTAKKEN_DATA" && typeof SPOORTAKKEN_DATA !== "undefined") return SPOORTAKKEN_DATA;
  if (name === "BOVENLEIDING_DATA" && typeof BOVENLEIDING_DATA !== "undefined") return BOVENLEIDING_DATA;
  if (name === "HALTES_DATA" && typeof HALTES_DATA !== "undefined") return HALTES_DATA;

  return null;
}

async function ensurePrototypeDataLoaded() {
  if (
    getPrototypeData("SPOOR_DATA") &&
    getPrototypeData("SPOORTAKKEN_DATA") &&
    getPrototypeData("BOVENLEIDING_DATA") &&
    getPrototypeData("HALTES_DATA")
  ) {
    return;
  }

  const data = await getJSON("/api/map-data");
  globalThis.SPOOR_DATA = data.spoor_data;
  globalThis.SPOORTAKKEN_DATA = data.spoortakken_data;
  globalThis.BOVENLEIDING_DATA = data.bovenleiding_data;
  globalThis.HALTES_DATA = data.haltes_data;
}

function getFeatureSegmentId(feature) {
  const p = feature?.properties || {};
  return String(
    p.k ||
    p.segment_id ||
    p.id ||
    p.SEGMENT_ID ||
    ""
  ).trim();
}

function normalizeTargetType(value) {
  const type = String(value || "rail_segment").trim().toLowerCase();
  if (type === "switch_junction" || type === "overhead_section") return type;
  return "rail_segment";
}

function getTargetKey(target) {
  const type = normalizeTargetType(target?.target_type);
  const id = String(target?.asset_id || target?.segment_id || "").trim();
  return id ? `${type}:${id}` : "";
}

function getSwitchAssetId(properties = {}) {
  return String(properties.w || properties.k || properties.id || "").trim();
}

function getOverheadAssetId(properties = {}) {
  const rawId = String(properties.id || "").trim();
  if (!rawId) return "";
  return rawId.startsWith("BL-") ? rawId : `BL-${rawId}`;
}

function getOverheadColor(feature) {
  const p = feature?.properties || {};
  const rawColor = p.c || p.color || p.kleur || "";
  const color = String(rawColor || "").trim();
  return color || "#7C3AED";
}

function isSwitchJunctionType(value) {
  const type = String(value || "").trim().toUpperCase();
  return type === "WISSEL" ||
    type === "SWITCH" ||
    type === "JUNCTION" ||
    type.includes("KRUISING");
}

function targetTypeLabel(targetOrType) {
  const type = normalizeTargetType(
    typeof targetOrType === "string" ? targetOrType : targetOrType?.target_type
  );
  if (type === "switch_junction") return "Switch/Junction";
  if (type === "overhead_section") return "Overhead";
  return "Rail";
}

function targetTitle(target) {
  const type = normalizeTargetType(target?.target_type);
  const label = String(target?.asset_label || "").trim();
  const assetId = String(target?.asset_id || target?.segment_id || "").trim();

  if (label) return label;
  if (type === "switch_junction") return `Switch/Junction ${assetId || "-"}`;
  if (type === "overhead_section") return `Bovenleiding sectie ${assetId || "-"}`;
  return `Rail segment ${target?.segment_id || assetId || "-"}`;
}

function targetSubtitle(target) {
  const parts = [];
  if (target?.line_name) parts.push(target.line_name);
  if (target?.line_id) parts.push(`(${target.line_id})`);
  if (target?.segment_id && normalizeTargetType(target?.target_type) !== "rail_segment") {
    parts.push(`Segment ${target.segment_id}`);
  }
  return parts.join(" ") || "-";
}

function cloneFeatureWithTargetMeta(feature, target) {
  return {
    ...feature,
    properties: {
      ...(feature?.properties || {}),
      __target_type: normalizeTargetType(target?.target_type),
      __asset_id: String(target?.asset_id || target?.segment_id || "").trim(),
      __asset_label: targetTitle(target)
    }
  };
}

function featureMatchesApplicationTarget(feature, target) {
  const type = normalizeTargetType(target?.target_type);
  const assetId = String(target?.asset_id || target?.segment_id || "").trim();
  const segmentId = String(target?.segment_id || "").trim();
  const p = feature?.properties || {};

  if (type === "overhead_section") {
    return !!assetId && getOverheadAssetId(p) === assetId;
  }

  if (type === "switch_junction") {
    const switchAssetId = getSwitchAssetId(p);
    const switchSegmentId = getFeatureSegmentId(feature);
    return (assetId && switchAssetId === assetId) || (segmentId && switchSegmentId === segmentId);
  }

  return !!(segmentId || assetId) && getFeatureSegmentId(feature) === (segmentId || assetId);
}

function findApplicationTargetFeatures(mapData, targets) {
  const features = [];
  const spoorFeatures =
    mapData?.spoor_data?.features ||
    mapData?.spoor?.features ||
    mapData?.kge?.features ||
    [];
  const overheadFeatures =
    mapData?.bovenleiding_data?.features ||
    mapData?.bovenleiding?.features ||
    [];

  (targets || []).forEach((target) => {
    const type = normalizeTargetType(target?.target_type);
    const source = type === "overhead_section" ? overheadFeatures : spoorFeatures;
    const matched = source.find((feature) => featureMatchesApplicationTarget(feature, target));
    if (matched) {
      features.push(cloneFeatureWithTargetMeta(matched, target));
    }
  });

  return features;
}

async function loadTimelineMapData() {
  if (timelineMapDataCache) return timelineMapDataCache;

  if (typeof globalThis !== "undefined" && globalThis.SPOOR_DATA) {
    timelineMapDataCache = {
      spoor_data: globalThis.SPOOR_DATA,
      bovenleiding_data: globalThis.BOVENLEIDING_DATA
    };
    return timelineMapDataCache;
  }

  timelineMapDataCache = await getJSON("/api/map-data");
  return timelineMapDataCache;
}

function startOfTimelineWeek(dateValue = new Date()) {
  const current = new Date(dateValue);
  current.setHours(0, 0, 0, 0);

  const weekday = current.getDay();
  const diffToMonday = weekday === 0 ? -6 : 1 - weekday;
  current.setDate(current.getDate() + diffToMonday);
  return current;
}

function capitalizeFirst(value) {
  if (!value) return "";
  return value.charAt(0).toUpperCase() + value.slice(1);
}

function parseTimelineDate(dateStr) {
  if (!dateStr) return null;
  const parsed = new Date(`${dateStr}T00:00:00`);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

function formatTimelineMonthLabel(dateStr) {
  const parsed = parseTimelineDate(dateStr);
  if (!parsed) return "";

  try {
    return capitalizeFirst(
      new Intl.DateTimeFormat("nl-NL", {
        month: "short",
        year: "numeric"
      }).format(parsed).replace(/\./g, "")
    );
  } catch {
    return "";
  }
}

function formatTimelineShortDate(dateStr) {
  const parsed = parseTimelineDate(dateStr);
  if (!parsed) return String(dateStr || "");

  try {
    const day = new Intl.DateTimeFormat("nl-NL", { day: "numeric" }).format(parsed);
    const month = capitalizeFirst(
      new Intl.DateTimeFormat("nl-NL", { month: "short" }).format(parsed).replace(/\./g, "")
    );
    return `${day} ${month}`;
  } catch {
    return String(dateStr || "");
  }
}

function getTimelineWeekKey(item) {
  if (!item?.date) return "";
  const parsed = parseTimelineDate(item.date);
  const year = parsed ? parsed.getFullYear() : String(item.date).slice(0, 4);
  return `${year}-${String(item.week || "")}`;
}

function formatTimelineActiveDate(dateStr) {
  if (!dateStr) return "";

  try {
    const formatted = new Intl.DateTimeFormat("nl-NL", {
      weekday: "long",
      day: "numeric",
      month: "short",
      year: "numeric"
    }).format(new Date(`${dateStr}T00:00:00`));
    return capitalizeFirst(formatted);
  } catch {
    return dateStr;
  }
}

function setTimelineStatusText(text) {
  if (dom.timelineStatus) {
    dom.timelineStatus.textContent = text || "";
  }
}

function updateTimelineWeekNavButtons() {
  if (!dom.timelineScroll || !dom.timelinePrevWeekBtn || !dom.timelineNextWeekBtn) return;

  const weeks = dom.timelineScroll.querySelectorAll(".timeline-week");
  const hasWeeks = weeks.length > 1;
  const maxScrollLeft = Math.max(0, dom.timelineScroll.scrollWidth - dom.timelineScroll.clientWidth);
  const current = dom.timelineScroll.scrollLeft;

  dom.timelinePrevWeekBtn.classList.toggle("is-hidden", !hasWeeks);
  dom.timelineNextWeekBtn.classList.toggle("is-hidden", !hasWeeks);
  dom.timelinePrevWeekBtn.disabled = !hasWeeks || current <= 2;
  dom.timelineNextWeekBtn.disabled = !hasWeeks || current >= maxScrollLeft - 2;
}

function updateTimelineHeaderLabel() {
  const selectedDate = state.timeline.selectedDate;
  const selectedSummary = selectedDate
    ? state.timeline.overview.find((item) => item.date === selectedDate) || null
    : null;

  if (dom.timelineSelectedMeta) {
    if (selectedSummary) {
      const totalCount = selectedSummary.total_count || 0;
      dom.timelineSelectedMeta.classList.remove("is-hidden");
      dom.timelineSelectedMeta.textContent = `Selected: ${formatTimelineActiveDate(selectedDate)} - ${totalCount} work item${totalCount === 1 ? "" : "s"}`;
    } else {
      dom.timelineSelectedMeta.classList.add("is-hidden");
      dom.timelineSelectedMeta.textContent = "";
    }
  }

  if (dom.timelineActiveLabel) {
    if (selectedSummary) {
      const totalCount = selectedSummary.total_count || 0;
      dom.timelineActiveLabel.classList.remove("is-hidden");
      dom.timelineActiveLabel.textContent = `Timeline: ${formatTimelineActiveDate(selectedDate)} - ${totalCount} work item${totalCount === 1 ? "" : "s"}`;
    } else {
      dom.timelineActiveLabel.classList.add("is-hidden");
      dom.timelineActiveLabel.textContent = "";
    }
  }

  if (dom.timelineResetBtn) {
    dom.timelineResetBtn.classList.toggle("is-hidden", !selectedSummary);
  }
}

function clearTimelineHighlightLayer() {
  if (state.timeline.highlightLayer && state.map) {
    try {
      state.map.removeLayer(state.timeline.highlightLayer);
    } catch (_) {
      // Ignore cleanup errors.
    }
  }

  state.timeline.highlightLayer = null;
}

function renderTimelineOverview() {
  if (!dom.timelineBar || !dom.timelineScroll) return;

  if (!state.currentUser || !state.timeline.enabled) {
    dom.timelineBar.classList.add("is-hidden");
    if (dom.timelineActiveLabel) {
      dom.timelineActiveLabel.classList.add("is-hidden");
      dom.timelineActiveLabel.textContent = "";
    }
    return;
  }

  dom.timelineBar.classList.remove("is-hidden");
  dom.timelineScroll.innerHTML = "";
  dom.timelineScroll.scrollLeft = Math.max(0, dom.timelineScroll.scrollLeft);

  if (state.timeline.loading && !state.timeline.overview.length) {
    setTimelineStatusText("Loading timeline...");
  } else if (state.timeline.error) {
    setTimelineStatusText(state.timeline.error);
  } else if (state.timeline.selectedDate) {
    const summary = state.timeline.overview.find((item) => item.date === state.timeline.selectedDate);
    const totalWorks = summary?.total_count || state.timeline.dayItems.length || 0;
    setTimelineStatusText(`${formatTimelineActiveDate(state.timeline.selectedDate)} - ${totalWorks} work item${totalWorks === 1 ? "" : "s"}`);
  } else if (state.timeline.overview.length) {
    setTimelineStatusText(`Showing ${state.timeline.overview.length} days from ${state.timeline.rangeStart}`);
  } else {
    setTimelineStatusText("No timeline data available.");
  }

  updateTimelineHeaderLabel();

  if (!state.timeline.overview.length) {
    updateTimelineWeekNavButtons();
    return;
  }

  const weekGroups = [];
  for (const item of state.timeline.overview) {
    const weekKey = getTimelineWeekKey(item);
    if (!weekGroups.length || weekGroups[weekGroups.length - 1].weekKey !== weekKey) {
      weekGroups.push({
        weekKey,
        week: item.week,
        items: [item]
      });
    } else {
      weekGroups[weekGroups.length - 1].items.push(item);
    }
  }

  let previousMonthKey = "";
  weekGroups.forEach((group) => {
    const weekItems = group.items;
    if (!weekItems.length) return;

    const weekStart = weekItems[0]?.date;
    const weekEnd = weekItems[weekItems.length - 1]?.date;
    const monthLabel = formatTimelineMonthLabel(weekStart);
    const monthKey = monthLabel.toLowerCase();
    const monthChanged = monthKey && monthKey !== previousMonthKey;
    if (monthKey) previousMonthKey = monthKey;

    const weekWrap = document.createElement("section");
    weekWrap.className = "timeline-week";
    if (monthChanged) weekWrap.classList.add("has-month-break");
    if (weekItems.some((item) => item.date === state.timeline.selectedDate)) {
      weekWrap.classList.add("is-selected-week");
    }

    const weekHeader = document.createElement("div");
    weekHeader.className = "timeline-week-header";

    const weekHeaderMain = document.createElement("div");
    weekHeaderMain.className = "timeline-week-main";

    const weekLabel = document.createElement("div");
    weekLabel.className = "timeline-week-label";
    weekLabel.textContent = `Week ${weekItems[0].week}`;

    const weekRange = document.createElement("div");
    weekRange.className = "timeline-week-range";
    weekRange.textContent = `${formatTimelineShortDate(weekStart)} - ${formatTimelineShortDate(weekEnd)}`;

    weekHeaderMain.appendChild(weekLabel);
    weekHeaderMain.appendChild(weekRange);
    weekHeader.appendChild(weekHeaderMain);

    if (monthChanged) {
      const monthChip = document.createElement("span");
      monthChip.className = "timeline-week-month";
      monthChip.textContent = monthLabel;
      weekHeader.appendChild(monthChip);
    }

    weekWrap.appendChild(weekHeader);

    const daysWrap = document.createElement("div");
    daysWrap.className = "timeline-days timeline-week-days";

    weekItems.forEach((item) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "timeline-day-cell";
      btn.dataset.date = item.date;

      if (state.timeline.selectedDate === item.date) {
        btn.classList.add("is-selected");
      }

      if (item.has_warning || item.has_bb) {
        btn.classList.add("has-warning");
      } else if ((item.wior_count || 0) > 0) {
        btn.classList.add("has-wior");
      } else if ((item.internal_count || 0) > 0) {
        btn.classList.add("has-work");
      }
      if ((item.tbgn_count || 0) > 0) {
        btn.classList.add("has-tbgn");
      }

      if (state.timeline.loading) {
        btn.disabled = true;
      }

      const weekday = document.createElement("span");
      weekday.className = "timeline-day-weekday";
      weekday.textContent = capitalizeFirst(String(item.weekday || "").slice(0, 2));

      const dayNumber = document.createElement("span");
      dayNumber.className = "timeline-day-number";
      dayNumber.textContent = String(Number(String(item.date).slice(8, 10)) || String(item.date).slice(8, 10));

      btn.appendChild(weekday);
      btn.appendChild(dayNumber);

      if ((item.total_count || 0) > 0) {
        const count = document.createElement("span");
        count.className = "timeline-day-count";
        count.textContent = String(item.total_count);
        btn.appendChild(count);
      }

      btn.addEventListener("click", async () => {
        await toggleTimelineDay(item.date);
      });

      daysWrap.appendChild(btn);
    });

    weekWrap.appendChild(daysWrap);
    dom.timelineScroll.appendChild(weekWrap);
  });

  if (state.timeline.selectedDate) {
    const selectedCell = dom.timelineScroll.querySelector(`.timeline-day-cell[data-date="${state.timeline.selectedDate}"]`);
    selectedCell?.scrollIntoView({ behavior: "smooth", inline: "center", block: "nearest" });
  }

  updateTimelineWeekNavButtons();
}

async function loadTimelineOverview() {
  if (!state.currentUser || !state.timeline.enabled) return;

  state.timeline.loading = true;
  state.timeline.error = "";
  renderTimelineOverview();

  const start = toISODate(startOfTimelineWeek(new Date()));
  const days = state.timeline.days || TIMELINE_DAYS_DEFAULT;

  try {
    const data = await getJSON(`/api/timeline/overview?start=${encodeURIComponent(start)}&days=${encodeURIComponent(days)}`);
    state.timeline.rangeStart = data?.start || start;
    state.timeline.days = data?.days || days;
    state.timeline.overview = Array.isArray(data?.items) ? data.items : [];
  } catch (err) {
    console.error("Failed to load timeline overview:", err);
    state.timeline.overview = [];
    state.timeline.error = "Could not load timeline overview.";
  } finally {
    state.timeline.loading = false;
    renderTimelineOverview();
  }
}

async function highlightTimelineSegments(dayItems) {
  clearTimelineHighlightLayer();

  const wantedTargets = (dayItems || [])
    .filter((item) => item?.type === "internal")
    .map((item) => ({
      target_type: normalizeTargetType(item.target_type),
      asset_id: String(item.asset_id || item.segment_id || "").trim(),
      asset_label: item.asset_label || "",
      segment_id: String(item.segment_id || "").trim(),
      line_id: item.line_id || "",
      line_name: item.line_name || ""
    }))
    .filter((target) => target.asset_id || target.segment_id);

  const uniqueByKey = new Map();
  wantedTargets.forEach((target) => {
    const key = getTargetKey(target);
    if (key && !uniqueByKey.has(key)) uniqueByKey.set(key, target);
  });

  const resolvedTargets = [...uniqueByKey.values()];

  const wantedIds = [...new Set(
    resolvedTargets
      .filter((target) => normalizeTargetType(target.target_type) === "rail_segment")
      .map((target) => String(target.segment_id || target.asset_id || "").trim())
      .filter(Boolean)
  )];

  const matchedFeatures = [];
  const tbgnTimelineFeatures = (dayItems || [])
    .filter((item) => item?.type === "tbgn")
    .flatMap((item) =>
      tbgnGeometryToFeatures(item, item.geometry).map((feature) => ({
        ...feature,
        properties: {
          ...(feature.properties || {}),
          __timeline_type: "tbgn",
          __tbgnProject: item
        }
      }))
    );
  const unresolvedRailIds = new Set(wantedIds);

  if (state.segmentLayers instanceof Map) {
    wantedIds.forEach((segmentId) => {
      const layer = state.segmentLayers.get(segmentId);
      if (!layer || typeof layer.toGeoJSON !== "function") return;
      const target = resolvedTargets.find((item) => normalizeTargetType(item.target_type) === "rail_segment" && (item.segment_id || item.asset_id) === segmentId);
      matchedFeatures.push(cloneFeatureWithTargetMeta(layer.toGeoJSON(), target || {
        target_type: "rail_segment",
        asset_id: segmentId,
        segment_id: segmentId
      }));
      unresolvedRailIds.delete(segmentId);
    });
  }

  if (state.switchLayers instanceof Map) {
    resolvedTargets
      .filter((target) => normalizeTargetType(target.target_type) === "switch_junction")
      .forEach((target) => {
        const layer = state.switchLayers.get(target.asset_id) || state.switchSegmentLayers?.get(target.segment_id);
        if (!layer || typeof layer.toGeoJSON !== "function") return;
        matchedFeatures.push(cloneFeatureWithTargetMeta(layer.toGeoJSON(), target));
      });
  }

  if (state.overheadLayers instanceof Map) {
    resolvedTargets
      .filter((target) => normalizeTargetType(target.target_type) === "overhead_section")
      .forEach((target) => {
        const layer = state.overheadLayers.get(target.asset_id);
        if (!layer || typeof layer.toGeoJSON !== "function") return;
        matchedFeatures.push(cloneFeatureWithTargetMeta(layer.toGeoJSON(), target));
      });
  }

  const unresolvedTargets = resolvedTargets.filter((target) => {
    const type = normalizeTargetType(target.target_type);
    if (type === "rail_segment") {
      return unresolvedRailIds.has(String(target.segment_id || target.asset_id || "").trim());
    }
    const key = getTargetKey(target);
    return key && !matchedFeatures.some((feature) => {
      const p = feature?.properties || {};
      return `${normalizeTargetType(p.__target_type)}:${String(p.__asset_id || "").trim()}` === key;
    });
  });

  if (unresolvedTargets.length) {
    const mapData = await loadTimelineMapData();
    matchedFeatures.push(...findApplicationTargetFeatures(mapData, unresolvedTargets));
  }

  matchedFeatures.push(...tbgnTimelineFeatures);

  if (!matchedFeatures.length || !state.map || typeof L === "undefined") {
    return null;
  }

  state.timeline.highlightLayer = L.geoJSON(
    {
      type: "FeatureCollection",
      features: matchedFeatures
    },
    {
      pointToLayer: (feature, latlng) => {
        if (feature?.properties?.__timeline_type !== "tbgn") {
          return L.marker(latlng);
        }
        const project = feature?.properties?.__tbgnProject || {};
        const color = normalizeTbgnColor(project.color);
        return L.circleMarker(latlng, {
          radius: 8,
          color,
          weight: 3,
          opacity: 1,
          fillColor: color,
          fillOpacity: 0.9
        });
      },
      style: (feature) => {
        if (feature?.properties?.__timeline_type === "tbgn") {
          const project = feature?.properties?.__tbgnProject || {};
          const color = normalizeTbgnColor(project.color);
          const geometryType = feature?.geometry?.type || "";
          const isPolygon = geometryType === "Polygon" || geometryType === "MultiPolygon";
          return {
            color,
            weight: isPolygon ? 4 : 7,
            opacity: 0.98,
            fillColor: color,
            fillOpacity: isPolygon ? 0.18 : 0,
            dashArray: isPolygon ? "8 5" : null,
            lineCap: "round",
            lineJoin: "round"
          };
        }
        const type = normalizeTargetType(feature?.properties?.__target_type);
        if (type === "overhead_section") {
          return {
            color: "#7c3aed",
            weight: 7,
            opacity: 0.95,
            lineCap: "round",
            lineJoin: "round"
          };
        }
        return TIMELINE_HIGHLIGHT_STYLE;
      },
      onEachFeature: (feature, layer) => {
        const p = feature?.properties || {};
        if (p.__timeline_type === "tbgn") {
          const project = p.__tbgnProject || {};
          layer.bindTooltip(`Timeline TBGN: ${esc(project.name || "project")}`, {
            sticky: true
          });
          return;
        }
        const label = p.__asset_label || p.__asset_id || getFeatureSegmentId(feature);
        layer.bindTooltip(`Timeline target: ${label}`, {
          sticky: true
        });
      }
    }
  ).addTo(state.map);

  state.timeline.highlightLayer.eachLayer((layer) => {
    if (typeof layer.bringToFront === "function") {
      layer.bringToFront();
    }
  });

  return state.timeline.highlightLayer;
}

function fitTimelineBounds() {
  if (!state.map || typeof L === "undefined") return;

  const layers = [];

  if (state.timeline.highlightLayer && typeof state.timeline.highlightLayer.getBounds === "function") {
    const highlightBounds = state.timeline.highlightLayer.getBounds();
    if (highlightBounds?.isValid()) {
      layers.push(state.timeline.highlightLayer);
    }
  }

  if (state.timeline.wiorFilteredLayer && typeof state.timeline.wiorFilteredLayer.getBounds === "function") {
    const wiorBounds = state.timeline.wiorFilteredLayer.getBounds();
    if (wiorBounds?.isValid()) {
      layers.push(state.timeline.wiorFilteredLayer);
    }
  }

  if (!layers.length) return;

  const group = L.featureGroup(layers);
  const bounds = group.getBounds();
  if (!bounds.isValid()) return;

  state.map.fitBounds(bounds, {
    padding: [60, 60],
    maxZoom: 17
  });
}

async function applyTimelineSelection(dateStr, dayItems) {
  state.timeline.selectedDate = dateStr;
  state.timeline.dayItems = Array.isArray(dayItems) ? dayItems : [];
  state.timeline.error = "";

  await highlightTimelineSegments(state.timeline.dayItems);
  await applyWiorDateFilter(state.map, dateStr);
  registerMapLayers();
  renderTimelineOverview();
  fitTimelineBounds();
}

export function clearTimelineSelection() {
  timelineDayRequestSeq += 1;
  state.timeline.selectedDate = null;
  state.timeline.dayItems = [];
  state.timeline.loading = false;
  state.timeline.error = "";
  clearTimelineHighlightLayer();
  clearWiorDateFilter(state.map);
  registerMapLayers();
  renderTimelineOverview();
}

async function toggleTimelineDay(dateStr) {
  if (!dateStr || state.timeline.loading) return;

  if (state.timeline.selectedDate === dateStr) {
    clearTimelineSelection();
    return;
  }

  state.timeline.loading = true;
  state.timeline.error = "";
  renderTimelineOverview();
  const requestSeq = ++timelineDayRequestSeq;

  try {
    const data = await getJSON(`/api/timeline/day?date=${encodeURIComponent(dateStr)}`);
    if (requestSeq !== timelineDayRequestSeq) return;
    await applyTimelineSelection(dateStr, data?.items || []);
  } catch (err) {
    if (requestSeq !== timelineDayRequestSeq) return;
    console.error("Failed to load timeline day:", err);
    state.timeline.error = "Could not load the selected timeline day.";
    showToast({
      title: "Timeline",
      message: "Could not load the selected day.",
      durationMs: 4000
    });
    renderTimelineOverview();
  } finally {
    if (requestSeq !== timelineDayRequestSeq) return;
    state.timeline.loading = false;
    renderTimelineOverview();
  }
}

function resetTimelineStateForMapInit() {
  timelineDayRequestSeq += 1;
  clearTimelineHighlightLayer();
  state.timeline.selectedDate = null;
  state.timeline.dayItems = [];
  state.timeline.loading = false;
  state.timeline.error = "";
  state.timeline.wiorBaseLayer = null;
  state.timeline.wiorFilteredLayer = null;
  state.timeline.previousWiorVisible = null;
}

function wireTimelineUi() {
  if (dom.timelineResetBtn) {
    dom.timelineResetBtn.onclick = () => {
      clearTimelineSelection();
    };
  }

  if (dom.timelinePrevWeekBtn) {
    dom.timelinePrevWeekBtn.onclick = () => {
      if (!dom.timelineScroll) return;
      const firstWeek = dom.timelineScroll.querySelector(".timeline-week");
      const style = firstWeek ? window.getComputedStyle(firstWeek) : null;
      const weekWidth = firstWeek ? firstWeek.getBoundingClientRect().width : 320;
      const weekGap = style ? parseFloat(style.marginRight || "0") : 0;
      dom.timelineScroll.scrollBy({
        left: -(weekWidth + weekGap + 10),
        behavior: "smooth"
      });
      window.setTimeout(updateTimelineWeekNavButtons, 240);
    };
  }

  if (dom.timelineNextWeekBtn) {
    dom.timelineNextWeekBtn.onclick = () => {
      if (!dom.timelineScroll) return;
      const firstWeek = dom.timelineScroll.querySelector(".timeline-week");
      const style = firstWeek ? window.getComputedStyle(firstWeek) : null;
      const weekWidth = firstWeek ? firstWeek.getBoundingClientRect().width : 320;
      const weekGap = style ? parseFloat(style.marginRight || "0") : 0;
      dom.timelineScroll.scrollBy({
        left: weekWidth + weekGap + 10,
        behavior: "smooth"
      });
      window.setTimeout(updateTimelineWeekNavButtons, 240);
    };
  }

  if (dom.timelineScroll && dom.timelineScroll.dataset.timelineWeekNavBound !== "1") {
    dom.timelineScroll.addEventListener("scroll", () => {
      window.requestAnimationFrame(updateTimelineWeekNavButtons);
    }, { passive: true });
    dom.timelineScroll.dataset.timelineWeekNavBound = "1";
  }
}

function createEmptyLayerGroup() {
  return L.layerGroup();
}

function getLayerItemCount(layer) {
  if (!layer || typeof layer.getLayers !== "function") return 0;
  return layer.getLayers().length;
}

function readStoredLayerVisibility() {
  try {
    const raw = localStorage.getItem(MAP_LAYER_VISIBILITY_KEY);
    if (!raw) return null;

    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object") return null;
    return parsed;
  } catch {
    return null;
  }
}

function writeStoredLayerVisibility() {
  try {
    localStorage.setItem(MAP_LAYER_VISIBILITY_KEY, JSON.stringify(state.mapLayerVisibility || {}));
  } catch {
    // Ignore storage errors silently
  }
}

function readStoredPanelCollapsed() {
  try {
    const value = localStorage.getItem(MAP_LAYER_COLLAPSED_KEY);
    if (value === "1") return true;
    if (value === "0") return false;
  } catch {
    // Ignore storage errors silently
  }
  return null;
}

function writeStoredPanelCollapsed() {
  try {
    localStorage.setItem(MAP_LAYER_COLLAPSED_KEY, state.mapLayerCollapsed ? "1" : "0");
  } catch {
    // Ignore storage errors silently
  }
}

function getMapLayerEntry(layerKey) {
  if (!state.mapLayers || !(state.mapLayers instanceof Map)) return null;
  return state.mapLayers.get(layerKey) || null;
}

function syncLayerPanelCollapsedUi() {
  if (!dom.mapLayerPanel || !dom.mapLayerPanelHeader || !dom.mapLayerChevron) return;

  dom.mapLayerPanel.classList.toggle("is-collapsed", !!state.mapLayerCollapsed);
  dom.mapLayerPanelHeader.setAttribute("aria-expanded", state.mapLayerCollapsed ? "false" : "true");
  dom.mapLayerChevron.textContent = state.mapLayerCollapsed ? ">" : "v";
}

function getOrderedLayerDefs() {
  const order = Array.isArray(state.mapLayerOrder) && state.mapLayerOrder.length
    ? state.mapLayerOrder
    : MAP_LAYER_DEFS.map((def) => def.key);

  return order
    .map((layerKey) => MAP_LAYER_DEFS.find((def) => def.key === layerKey))
    .filter(Boolean);
}

function renderLayerPanelRows() {
  if (!dom.mapLayerList) return;

  dom.mapLayerList.innerHTML = "";

  const defs = getOrderedLayerDefs();

  for (const def of defs) {
    const entry = getMapLayerEntry(def.key);
    const isAvailable = !!entry?.available;
    const isVisible = !!state.mapLayerVisibility[def.key] && isAvailable;
    const countText = isAvailable ? String(entry?.count ?? 0) : "-";

    const row = document.createElement("div");
    row.className = "map-layer-row";
    row.dataset.layerKey = def.key;
    if (!isAvailable) row.classList.add("is-disabled");
    if (isVisible) row.classList.add("is-active");

    const left = document.createElement("div");
    left.className = "map-layer-left";

    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.className = "map-layer-checkbox";
    checkbox.checked = isVisible;
    checkbox.disabled = !isAvailable;
    checkbox.setAttribute("aria-label", `${def.label} visibility`);
    checkbox.addEventListener("click", (event) => event.stopPropagation());
    checkbox.addEventListener("change", () => {
      setLayerVisibility(def.key, checkbox.checked);
    });

    const swatch = document.createElement("span");
    swatch.className = `map-layer-swatch map-layer-swatch-${def.swatch}`;

    const label = document.createElement("span");
    label.className = "map-layer-label";
    label.textContent = def.label;

    left.appendChild(checkbox);
    left.appendChild(swatch);
    left.appendChild(label);

    const count = document.createElement("span");
    count.className = "map-layer-count";
    count.textContent = countText;

    row.appendChild(left);
    row.appendChild(count);

    row.addEventListener("click", (event) => {
      event.stopPropagation();
      if (!isAvailable) return;
      setLayerVisibility(def.key, !state.mapLayerVisibility[def.key]);
    });

    dom.mapLayerList.appendChild(row);

    if (def.key === "wiorProjects") {
      const subfilters = document.createElement("div");
      subfilters.className = "map-layer-subfilters";
      subfilters.addEventListener("click", (event) => event.stopPropagation());
      subfilters.addEventListener("mousedown", (event) => event.stopPropagation());

      const subfiltersLabel = document.createElement("label");
      subfiltersLabel.className = "map-layer-subfilters-label";
      subfiltersLabel.textContent = "Filter";

      const subfiltersSelect = document.createElement("select");
      subfiltersSelect.className = "map-layer-subfilters-select";
      subfiltersSelect.disabled = !isAvailable;

      const filterOptions = [
        { label: "Active", value: "active" },
        { label: "Next 7 days", value: "next7" },
        { label: "Next 30 days", value: "next30" },
        { label: "Show all", value: "all" }
      ];

      const selectedMode = state.wiorFilterMode || "active";
      for (const optionDef of filterOptions) {
        const option = document.createElement("option");
        option.value = optionDef.value;
        option.textContent = optionDef.label;
        option.selected = optionDef.value === selectedMode;
        subfiltersSelect.appendChild(option);
      }

      subfiltersSelect.addEventListener("click", (event) => event.stopPropagation());
      subfiltersSelect.addEventListener("change", async (event) => {
        event.stopPropagation();
        const newMode = event.target?.value || "active";

        subfiltersSelect.disabled = true;
        try {
          await reloadWiorLayer(state.map, newMode);
          registerMapLayers();
        } catch (err) {
          console.error("Failed to reload WIOR layer:", err);
          subfiltersSelect.disabled = false;
        }
      });

      subfilters.appendChild(subfiltersLabel);
      subfilters.appendChild(subfiltersSelect);
      dom.mapLayerList.appendChild(subfilters);
    }
  }
}

function refreshLayerRow(layerKey) {
  if (!dom.mapLayerList) return;

  const row = dom.mapLayerList.querySelector(`[data-layer-key="${layerKey}"]`);
  const entry = getMapLayerEntry(layerKey);

  if (!row || !entry) return;

  const isAvailable = !!entry.available;
  const isVisible = !!state.mapLayerVisibility[layerKey] && isAvailable;

  row.classList.toggle("is-disabled", !isAvailable);
  row.classList.toggle("is-active", isVisible);

  const checkbox = row.querySelector(".map-layer-checkbox");
  if (checkbox) {
    checkbox.disabled = !isAvailable;
    checkbox.checked = isVisible;
  }

  const count = row.querySelector(".map-layer-count");
  if (count) {
    count.textContent = isAvailable ? String(entry.count ?? 0) : "-";
  }
}

function wireLayerPanelUi() {
  if (dom.mapLayerPanelHeader) {
    dom.mapLayerPanelHeader.onclick = () => {
      toggleLayerPanelCollapsed();
    };
  }

  if (dom.mapLayerOrderBtn) {
    dom.mapLayerOrderBtn.onclick = (event) => {
      event.preventDefault();
      event.stopPropagation();
    };
  }

  if (dom.mapLayerPanel && typeof L !== "undefined" && L.DomEvent) {
    L.DomEvent.disableClickPropagation(dom.mapLayerPanel);
    L.DomEvent.disableScrollPropagation(dom.mapLayerPanel);
  }
}

export function toggleLayerPanelCollapsed(forceCollapsed = null) {
  const nextCollapsed =
    typeof forceCollapsed === "boolean"
      ? forceCollapsed
      : !state.mapLayerCollapsed;

  state.mapLayerCollapsed = nextCollapsed;
  syncLayerPanelCollapsedUi();
  writeStoredPanelCollapsed();

  if (state.map) {
    setTimeout(() => state.map.invalidateSize(), 0);
  }
}

export function updateLayerPanelCount() {
  if (!dom.mapLayerActiveCount) return;

  const defs = getOrderedLayerDefs();
  const totalCount = defs.length;

  let activeCount = 0;
  for (const def of defs) {
    const entry = getMapLayerEntry(def.key);
    if (!entry?.available) continue;
    if (state.mapLayerVisibility[def.key]) activeCount += 1;
  }

  dom.mapLayerActiveCount.textContent = `${activeCount} / ${totalCount} active`;
}

export function setLayerVisibility(layerKey, visible) {
  const entry = getMapLayerEntry(layerKey);
  if (!entry) return;

  const nextVisible = !!visible && !!entry.available;
  state.mapLayerVisibility[layerKey] = nextVisible;

  if (state.map && entry.layer) {
    if (nextVisible) {
      if (!state.map.hasLayer(entry.layer)) entry.layer.addTo(state.map);
    } else if (state.map.hasLayer(entry.layer)) {
      state.map.removeLayer(entry.layer);
    }
  }

  refreshLayerRow(layerKey);
  updateLayerPanelCount();
  writeStoredLayerVisibility();
}

function resolveLayerVisibility(layerKey, defaultVisible, isAvailable, storedVisibility) {
  const persisted = storedVisibility && typeof storedVisibility[layerKey] === "boolean"
    ? storedVisibility[layerKey]
    : null;

  const inMemory = typeof state.mapLayerVisibility[layerKey] === "boolean"
    ? state.mapLayerVisibility[layerKey]
    : null;

  const fallback = typeof persisted === "boolean"
    ? persisted
    : (typeof inMemory === "boolean" ? inMemory : !!defaultVisible);

  return !!isAvailable && fallback;
}

function buildLayerRegistry() {
  const byKey = {
    networkFill: {
      layer: state.spoortakkenLayer || createEmptyLayerGroup(),
      available: !!state.spoortakkenLayer,
      count: getLayerItemCount(state.spoortakkenLayer)
    },
    activities: {
      layer: state.activitiesLayer || createEmptyLayerGroup(),
      available: true,
      count: getLayerItemCount(state.activitiesLayer)
    },
    tbgnProjects: {
      layer: state.tbgnProjectsLayer || createEmptyLayerGroup(),
      available: true,
      count: getLayerItemCount(state.tbgnProjectsLayer)
    },
    wiorProjects: {
      layer: state.wiorLayer || createEmptyLayerGroup(),
      available: !!state.wiorLayer,
      count: getLayerItemCount(state.wiorLayer)
    },
    tramStops: {
      layer: state.haltesLayer || createEmptyLayerGroup(),
      available: !!state.haltesLayer,
      count: getLayerItemCount(state.haltesLayer)
    },
    switchesJunctions: {
      layer: state.switchesLayer || createEmptyLayerGroup(),
      available: !!state.switchesLayerHasData,
      count: getLayerItemCount(state.switchesLayer)
    },
    overheadSections: {
      layer: state.bovenleidingLayer || createEmptyLayerGroup(),
      available: !!state.bovenleidingLayer,
      count: getLayerItemCount(state.bovenleidingLayer)
    },
    kgeModelGauge: {
      layer: state.spoorLayer || createEmptyLayerGroup(),
      available: !!state.spoorLayer,
      count: getLayerItemCount(state.spoorLayer)
    }
  };

  return byKey;
}

export function registerMapLayers() {
  if (!state.map) return;

  if (!state.mapLayerPrefsLoaded) {
    const storedCollapsed = readStoredPanelCollapsed();
    if (typeof storedCollapsed === "boolean") {
      state.mapLayerCollapsed = storedCollapsed;
    }
    state.mapLayerPrefsLoaded = true;
  }

  const storedVisibility = readStoredLayerVisibility();
  const layerRegistry = buildLayerRegistry();

  state.mapLayers = new Map();
  state.mapLayerOrder = MAP_LAYER_DEFS.map((def) => def.key);

  for (const def of MAP_LAYER_DEFS) {
    const resolved = layerRegistry[def.key] || {
      layer: createEmptyLayerGroup(),
      available: false,
      count: 0
    };

    const entry = {
      ...def,
      layer: resolved.layer,
      available: !!resolved.available,
      count: resolved.count ?? 0
    };

    state.mapLayers.set(def.key, entry);

    const shouldBeVisible = resolveLayerVisibility(
      def.key,
      def.defaultVisible,
      entry.available,
      storedVisibility
    );
    state.mapLayerVisibility[def.key] = shouldBeVisible;

    if (!entry.layer) continue;

    if (shouldBeVisible) {
      if (!state.map.hasLayer(entry.layer)) entry.layer.addTo(state.map);
    } else if (state.map.hasLayer(entry.layer)) {
      state.map.removeLayer(entry.layer);
    }
  }

  renderLayerPanelRows();
  updateLayerPanelCount();
  syncLayerPanelCollapsedUi();
  wireLayerPanelUi();
  writeStoredLayerVisibility();
}

export function setActionsVisible(visible) {
  if (!dom.projectActions) return;
  dom.projectActions.classList.toggle("is-hidden", !visible);
}

export function setSelection(sel) {
  state.currentSelection = sel;

  if (!sel) {
    setActionsVisible(false);

    if (dom.projectActionsHint) {
      dom.projectActionsHint.textContent = t("actions_hint_default");
    }
    return;
  }

  setActionsVisible(true);
  updateFavoriteButton();

  if (!dom.projectActionsHint) return;

  if (sel.type === "segment-list") {
    const count = sel.segments?.length || 0;

    if (count === 1) {
      const s = sel.segments[0];
      dom.projectActionsHint.textContent =
        `${targetTypeLabel(s)} - ${targetTitle(s)}`;
    } else {
      dom.projectActionsHint.textContent = `${count} targets selected`;
    }
  } else if (sel.type === "line") {
    dom.projectActionsHint.textContent =
      `${sel.line_name} (${sel.line_id})`;
  }
}

function resetUiAfterClear() {
  if (dom.lineSelect) dom.lineSelect.value = "";
  syncClearButton();
  closeCombo();

  clearHighlights();
  state.selectedTargetKeys = new Set();
  applyAssetSelectionStyles();
  restoreFilterState();
  setSelection(null);
  setDetails(`<p>${esc(t("no_selection_yet"))}</p>`);
}

function fitLayerBounds(layerOrLayers) {
  if (!state.map) return;

  if (!layerOrLayers) return;

  if (Array.isArray(layerOrLayers)) {
    const validLayers = layerOrLayers.filter(Boolean);
    if (!validLayers.length) return;

    const group = L.featureGroup(validLayers);
    state.map.fitBounds(group.getBounds(), {
      padding: [40, 40],
      maxZoom: 18
    });
    return;
  }

  if (layerOrLayers.getBounds) {
    state.map.fitBounds(layerOrLayers.getBounds(), {
      padding: [40, 40],
      maxZoom: 18
    });
  }
}

function focusFilterOnLine(lineId) {
  if (!lineId) return;

  if (!state.savedVisibleLineIds) {
    state.savedVisibleLineIds = new Set(state.visibleLineIds);
  }

  state.visibleLineIds = new Set([lineId]);
  renderFilterList();
  applyOverlayStyles();
  setLineInputDisplay(lineId);
}

function focusFilterOnSelectedSegments(selectedSegments) {
  if (!selectedSegments?.length) return;

  if (!state.savedVisibleLineIds) {
    state.savedVisibleLineIds = new Set(state.visibleLineIds);
  }

  const selectedLineIds = [...new Set(selectedSegments.map(s => s.line_id).filter(Boolean))];
  if (!selectedLineIds.length) return;
  state.visibleLineIds = new Set(selectedLineIds);

  renderFilterList();
  applyOverlayStyles();
}

function restoreFilterState() {
  if (state.savedVisibleLineIds) {
    state.visibleLineIds = new Set(state.savedVisibleLineIds);
    state.savedVisibleLineIds = null;
  } else {
    state.visibleLineIds = new Set(state.lineIndex.keys());
  }

  renderFilterList();
  applyOverlayStyles();
}

function renderSelectedSegmentsDetails(selectedSegments) {
  if (!selectedSegments?.length) {
    setDetails(`<p>${esc(t("no_selection_yet"))}</p>`);
    return;
  }

  setDetails(`
    <p><strong>Selected targets:</strong></p>
    <ul>
      ${selectedSegments.map(s => `
        <li>
          <strong>${esc(targetTypeLabel(s))}:</strong>
          ${esc(targetTitle(s))}
          <span class="tt-muted">${esc(targetSubtitle(s))}</span>
        </li>
      `).join("")}
    </ul>
  `);
}

export function tooltipHtml(lineId, statusObj) {
  const line = state.lineIndex.get(lineId) || {};
  const name = line.name || lineId;

  let statusHtml = `<span class="tt-muted">...</span>`;

  if (statusObj) {
    if (statusObj.auth_required) {
      statusHtml = `<span class="tt-muted">${esc(t("hover_login_needed"))}</span>`;
    } else if (statusObj.applied) {
      const latest = statusObj.latest || {};
      statusHtml = `<strong>Application:</strong> ${esc(latest.status || "submitted")} (${statusObj.count})`;
    } else {
      statusHtml = `<strong>Application:</strong> None`;
    }
  }

  return `
    <div class="gvb-tt-box">
      <div class="gvb-tt-title">${esc(name)}</div>
      <div class="gvb-tt-status">${statusHtml}</div>
    </div>
  `;
}

export async function fetchLineStatus(lineId) {
  if (state.lineStatusCache.has(lineId)) {
    return state.lineStatusCache.get(lineId);
  }

  const res = await fetch(`/api/line_status?line_id=${encodeURIComponent(lineId)}`, {
    credentials: "same-origin"
  });

  if (!res.ok) {
    throw new Error(`Failed to load line status for ${lineId}`);
  }

  const data = await res.json();
  state.lineStatusCache.set(lineId, data);
  return data;
}

export function attachHoverTooltip(layer, lineId) {
  layer.bindTooltip("", {
    sticky: true,
    direction: "top",
    opacity: 0.98,
    className: "gvb-tt"
  });

  layer.on("mouseover", async () => {
    layer.setTooltipContent(tooltipHtml(lineId, null));

    try {
      const status = await fetchLineStatus(lineId);
      layer.setTooltipContent(tooltipHtml(lineId, status));
    } catch {
      // Ignore tooltip status errors silently
    }
  });
}

function spoorFeatureToSegment(feature) {
  const p = feature.properties || {};
  const geometry = feature.geometry || {};

  return {
    id: p.k,
    segment_id: p.k,
    line_id: p.li || "UNKNOWN",
    line_name: p.s || p.z || p.li || "Unknown",
    name: p.lo || p.k,
    geometry: geometry.coordinates || [],
    feature_type: p.t || "",
    color: p.c || "#43a047"
  };
}

function spoorFeatureToSwitchTarget(feature) {
  const p = feature.properties || {};
  const geometry = feature.geometry || {};
  const assetId = getSwitchAssetId(p);
  const switchName = p.w ? `W-${p.w}` : (p.k || assetId || "-");
  const typeLabel = p.t || "Switch/Junction";
  const streetLabel = p.s || p.lo || p.li || "";
  const lineName = [p.s, p.lo].filter(Boolean).join(" - ") || p.z || p.li || "Unknown";

  return {
    id: assetId,
    target_type: "switch_junction",
    asset_id: assetId,
    asset_label: `${typeLabel} ${switchName}${streetLabel ? ` - ${streetLabel}` : ""}`,
    asset_source: "SPOOR_DATA",
    segment_id: p.k || "",
    line_id: p.li || "UNKNOWN",
    line_name: lineName,
    name: p.lo || switchName,
    geometry: geometry.coordinates || [],
    feature_type: p.t || "",
    color: p.c || "#f5a623"
  };
}

function bovenleidingFeatureToTarget(feature) {
  const p = feature.properties || {};
  const geometry = feature.geometry || {};
  const assetId = getOverheadAssetId(p);
  const schouwroute = String(p.s || "").trim();
  const tekening = String(p.t || "").trim();
  const subtitle = [
    schouwroute ? `Schouwroute ${schouwroute}` : "",
    tekening ? `Tekening ${tekening}` : ""
  ].filter(Boolean).join(" - ");

  return {
    id: assetId,
    target_type: "overhead_section",
    asset_id: assetId,
    asset_label: `Bovenleiding sectie ${p.id || assetId || "-"}`,
    asset_source: "BOVENLEIDING_DATA",
    segment_id: "",
    line_id: schouwroute,
    line_name: subtitle || "Bovenleiding",
    name: subtitle || assetId,
    geometry: geometry.coordinates || [],
    feature_type: "BOVENLEIDING",
    color: getOverheadColor(feature)
  };
}

function setLayerStyleSafe(layer, style) {
  if (layer && typeof layer.setStyle === "function") {
    layer.setStyle(style);
  }
}

function applyAssetSelectionStyles() {
  const selectedKeys = state.selectedTargetKeys || new Set();

  if (state.switchLayers instanceof Map) {
    state.switchLayers.forEach((layer, assetId) => {
      const selected = selectedKeys.has(`switch_junction:${assetId}`);
      setLayerStyleSafe(layer, {
        color: selected ? "#b42318" : "#f5a623",
        weight: selected ? 8 : 4,
        opacity: selected ? 1 : 0.9,
        lineCap: "round",
        lineJoin: "round"
      });
      if (selected && typeof layer.bringToFront === "function") layer.bringToFront();
    });
  }

  if (state.overheadLayers instanceof Map) {
    state.overheadLayers.forEach((layer, assetId) => {
      const selected = selectedKeys.has(`overhead_section:${assetId}`);
      const baseColor = getOverheadColor(layer?.feature);
      setLayerStyleSafe(layer, {
        color: selected ? "#7C3AED" : baseColor,
        weight: selected ? 7 : 4,
        opacity: selected ? 1 : 0.7,
        lineCap: "round",
        lineJoin: "round"
      });
      if (selected && typeof layer.bringToFront === "function") layer.bringToFront();
    });
  }
}

function buildActivitiesLayer() {
  state.activitiesLayer = createEmptyLayerGroup();
}

function normalizeTbgnColor(value) {
  const color = String(value || "").trim();
  return /^#[0-9a-fA-F]{6}$/.test(color) ? color : TBGN_DEFAULT_COLOR;
}

function getTbgnDerivedStatus(project) {
  const today = toISODate(new Date());
  const start = String(project?.start_date || "").trim();
  const end = String(project?.end_date || "").trim();
  if (start && today < start) return "Upcoming";
  if (end && today > end) return "Completed";
  return "Active";
}

function tbgnProjectFeatureProperties(project) {
  return {
    __tbgnProject: project,
    tbgn_id: project.id,
    name: project.name,
    color: normalizeTbgnColor(project.color)
  };
}

function tbgnGeometryToFeatures(project, geometry) {
  if (!geometry || typeof geometry !== "object") return [];

  if (geometry.type === "FeatureCollection") {
    const features = Array.isArray(geometry.features) ? geometry.features : [];
    return features.flatMap((feature) => tbgnGeometryToFeatures(project, feature));
  }

  if (geometry.type === "Feature") {
    if (!geometry.geometry) return [];
    return tbgnGeometryToFeatures(project, geometry.geometry).map((feature) => ({
      ...feature,
      properties: {
        ...(geometry.properties || {}),
        ...feature.properties
      }
    }));
  }

  if (!TBGN_SUPPORTED_GEOMETRIES.has(geometry.type)) return [];

  return [
    {
      type: "Feature",
      properties: tbgnProjectFeatureProperties(project),
      geometry
    }
  ];
}

function tbgnPopupHtml(project) {
  const status = getTbgnDerivedStatus(project);
  const lines = String(project?.affected_lines || "").trim() || "-";
  const notes = String(project?.notes || "").trim();
  return `
    <div class="tbgn-popup">
      <strong>${esc(project?.name || "TBGN project")}</strong>
      <div>${esc(project?.start_date || "-")} - ${esc(project?.end_date || "-")}</div>
      <div><strong>Lines:</strong> ${esc(lines)}</div>
      <div><strong>Status:</strong> ${esc(status)}</div>
      ${notes ? `<div><strong>Notes:</strong> ${esc(notes)}</div>` : ""}
    </div>
  `;
}

async function buildTbgnProjectsLayer() {
  state.tbgnProjectsLayer = createEmptyLayerGroup();

  try {
    const data = await getJSON("/api/tbgn/projects");
    const projects = Array.isArray(data?.projects) ? data.projects : [];
    const features = [];

    projects.forEach((project) => {
      features.push(...tbgnGeometryToFeatures(project, project.geometry));
    });

    if (!features.length) return;

    state.tbgnProjectsLayer = L.geoJSON(
      {
        type: "FeatureCollection",
        features
      },
      {
        pointToLayer: (feature, latlng) => {
          const project = feature?.properties?.__tbgnProject || {};
          const color = normalizeTbgnColor(project.color);
          return L.circleMarker(latlng, {
            radius: 7,
            color,
            weight: 2,
            opacity: 0.95,
            fillColor: color,
            fillOpacity: 0.82
          });
        },
        style: (feature) => {
          const project = feature?.properties?.__tbgnProject || {};
          const color = normalizeTbgnColor(project.color);
          const geometryType = feature?.geometry?.type || "";
          const isPolygon = geometryType === "Polygon" || geometryType === "MultiPolygon";
          return {
            color,
            weight: isPolygon ? 3 : 5,
            opacity: 0.9,
            fillColor: color,
            fillOpacity: isPolygon ? 0.14 : 0,
            lineCap: "round",
            lineJoin: "round"
          };
        },
        onEachFeature: (feature, layer) => {
          const project = feature?.properties?.__tbgnProject || {};
          layer.bindPopup(tbgnPopupHtml(project));
          layer.bindTooltip(`TBGN: ${esc(project.name || "project")}`, {
            sticky: true,
            className: "gvb-tt"
          });
        }
      }
    );
  } catch (err) {
    console.error("Failed to load TBGN projects:", err);
    state.tbgnProjectsLayer = createEmptyLayerGroup();
  }
}

function buildSwitchesJunctionsLayer() {
  state.switchesLayer = createEmptyLayerGroup();
  state.switchesLayerHasData = false;
  state.switchLayers = new Map();
  state.switchSegmentLayers = new Map();

  const spoorData = getPrototypeData("SPOOR_DATA");
  const allFeatures = Array.isArray(spoorData?.features) ? spoorData.features : [];

  const switchFeatures = allFeatures.filter((feature) => {
    return isSwitchJunctionType(feature?.properties?.t);
  });

  if (!switchFeatures.length) return;

  state.switchesLayer = L.geoJSON({
    type: "FeatureCollection",
    features: switchFeatures
  }, {
    style: () => ({
      color: "#f5a623",
      weight: 4,
      opacity: 0.9,
      lineCap: "round",
      lineJoin: "round"
    }),
    onEachFeature: (feature, layer) => {
      const target = spoorFeatureToSwitchTarget(feature);
      const lineLabel = target.line_id ? `Line ${esc(target.line_id)}` : "Unknown line";
      const segmentLabel = target.segment_id ? `Segment ${esc(target.segment_id)}` : "Segment -";
      const featureLabel = esc(target.asset_label || "Switch/Junction");

      if (target.asset_id) {
        state.switchLayers.set(target.asset_id, layer);
      }
      if (target.segment_id) {
        state.switchSegmentLayers.set(target.segment_id, layer);
      }

      layer.bindTooltip(
        `<b>${featureLabel}</b><br>${lineLabel}<br>${segmentLabel}`,
        { sticky: true, className: "gvb-tt" }
      );

      layer.on("click", (e) => {
        if (e.originalEvent) {
          e.originalEvent.preventDefault?.();
          e.originalEvent.stopPropagation?.();

          if (typeof L !== "undefined" && L.DomEvent) {
            L.DomEvent.stop(e.originalEvent);
          }
        }

        state.suppressNextMapClear = true;
        selectAssetTarget(target);
      });
    }
  });

  state.switchesLayerHasData = true;
}

function buildSpoortakkenLayer() {
  state.spoortakkenLayer = null;

  const data = getPrototypeData("SPOORTAKKEN_DATA");
  if (!data) return;

  state.spoortakkenLayer = L.geoJSON(data, {
    style: () => ({
      color: "#78909c",
      weight: 2,
      opacity: 0.35,
      interactive: true
    }),
    onEachFeature: (feature, layer) => {
      const p = feature.properties || {};
      layer.bindTooltip(
        `<b>Base network section</b><br>${esc(p.id || p.n || "-")}<br><span class="tt-muted">Visual only - not bookable</span>`,
        { sticky: true, className: "gvb-tt" }
      );
    }
  });
}

function buildSpoorLayer() {
  state.spoorLayer = null;

  const data = getPrototypeData("SPOOR_DATA");
  if (!data) return;
  const railData = {
    type: "FeatureCollection",
    features: (Array.isArray(data.features) ? data.features : [])
      .filter((feature) => !isSwitchJunctionType(feature?.properties?.t))
  };

  state.segmentLayers = new Map();
  state.lineIndex = new Map();
  state.segmentsByLine = new Map();
  state.allSegments = [];
  state.lineStatusCache.clear();

  state.spoorLayer = L.geoJSON(railData, {
    style: (feature) => {
      const p = feature.properties || {};

      return {
        color: p.c || "#43a047",
        weight: p.t === "WISSEL" ? 4 : p.t === "KRUISING" ? 3.5 : 2,
        opacity: 0.8,
        dashArray: p.t === "ISOLATIELAS" ? "4,4" : null,
        lineCap: "round",
        lineJoin: "round"
      };
    },
    onEachFeature: (feature, layer) => {
      const seg = spoorFeatureToSegment(feature);

      if (!seg.segment_id) return;

      if (!state.lineIndex.has(seg.line_id)) {
        state.lineIndex.set(seg.line_id, {
          line_id: seg.line_id,
          name: seg.line_name,
          color: seg.color
        });
      }

      if (!state.segmentsByLine.has(seg.line_id)) {
        state.segmentsByLine.set(seg.line_id, []);
      }

      state.segmentsByLine.get(seg.line_id).push(seg);
      state.allSegments.push(seg);
      state.segmentLayers.set(seg.segment_id, layer);

      layer.featureMeta = {
        id: seg.segment_id,
        line_id: seg.line_id,
        name: seg.name
      };

      attachHoverTooltip(layer, seg.line_id);

      layer.on("click", (e) => {
        if (e.originalEvent) {
          e.originalEvent.preventDefault?.();
          e.originalEvent.stopPropagation?.();

          if (typeof L !== "undefined" && L.DomEvent) {
            L.DomEvent.stop(e.originalEvent);
          }
        }

        state.suppressNextMapClear = true;
        selectSegment(seg);
      });
    }
  });

  state.lineItems = Array.from(state.lineIndex.entries())
    .map(([id, l]) => ({
      id,
      name: l.name || id,
      display: `${l.name || id} (${id})`,
      nameLower: (l.name || id).toLowerCase(),
      idLower: id.toLowerCase()
    }))
    .sort((a, b) => a.nameLower.localeCompare(b.nameLower));

  if (!state.visibleLineIds || state.visibleLineIds.size === 0) {
    state.visibleLineIds = new Set(Array.from(state.lineIndex.keys()));
  }

  renderFilterList();
  applyOverlayStyles();
}

function buildBovenleidingLayer() {
  state.bovenleidingLayer = null;
  state.overheadLayers = new Map();

  const data = getPrototypeData("BOVENLEIDING_DATA");
  if (!data) return;

  state.bovenleidingLayer = L.geoJSON(data, {
    style: (feature) => {
      return {
        color: getOverheadColor(feature),
        weight: 4,
        opacity: 0.7,
        lineCap: "round",
        lineJoin: "round"
      };
    },
    onEachFeature: (feature, layer) => {
      const target = bovenleidingFeatureToTarget(feature);
      if (target.asset_id) {
        state.overheadLayers.set(target.asset_id, layer);
      }

      layer.bindTooltip(
        `<b>${esc(target.asset_label)}</b><br>${esc(target.line_name || "-")}`,
        { sticky: true, className: "gvb-tt" }
      );

      layer.on("click", (e) => {
        if (e.originalEvent) {
          e.originalEvent.preventDefault?.();
          e.originalEvent.stopPropagation?.();

          if (typeof L !== "undefined" && L.DomEvent) {
            L.DomEvent.stop(e.originalEvent);
          }
        }

        state.suppressNextMapClear = true;
        selectAssetTarget(target);
      });
    }
  });
}

function buildHaltesLayer() {
  if (typeof HALTES_DATA === "undefined") return;

  state.haltesLayer = L.geoJSON(HALTES_DATA, {
    pointToLayer: (feature, latlng) =>
      L.circleMarker(latlng, {
        radius: feature.properties?.RADIUS || 5,
        fillColor: "#0863B5",
        fillOpacity: 0.9,
        color: "#024B8C",
        weight: 1.5
      }),
    onEachFeature: (feature, layer) => {
      const p = feature.properties || {};

      layer.on("click", (event) => {
        if (state.transferTrip && state.transferTrip.active) {
          const handled = handleHalteClickForTransfer(feature, event);
          if (handled) {
            state.suppressNextMapClear = true;
          }
        }
      });

      layer.bindTooltip(
        `<b>${esc(p.Naam || "Halte")}</b><br>Lijnen: ${esc(p.Lijn || "-")}`,
        { sticky: true, className: "gvb-tt" }
      );
    }
  });

}

async function buildPrototypeLayers() {
  buildActivitiesLayer();
  await buildTbgnProjectsLayer();
  buildSpoortakkenLayer();
  buildSpoorLayer();
  buildSwitchesJunctionsLayer();
  buildBovenleidingLayer();
  buildHaltesLayer();
}

export function selectAssetTarget(target) {
  if (!target) return;

  state.spotlightLineId = "";
  applyOverlayStyles();

  const normalizedTarget = {
    target_type: normalizeTargetType(target.target_type),
    asset_id: String(target.asset_id || target.segment_id || "").trim(),
    asset_label: target.asset_label || targetTitle(target),
    asset_source: target.asset_source || (normalizeTargetType(target.target_type) === "overhead_section" ? "BOVENLEIDING_DATA" : "SPOOR_DATA"),
    segment_id: String(target.segment_id || "").trim(),
    line_id: String(target.line_id || "").trim(),
    line_name: target.line_name || "",
    geometry: Array.isArray(target.geometry) ? target.geometry : [],
    name: target.name || target.asset_label || target.segment_id || target.asset_id || ""
  };

  if (!normalizedTarget.asset_id) return;

  const existing =
    state.currentSelection?.type === "segment-list"
      ? (state.currentSelection.segments || [])
      : [];

  const targetKey = getTargetKey(normalizedTarget);
  const alreadySelected = existing.find((item) => getTargetKey(item) === targetKey);

  let selectedTargets = [];

  if (alreadySelected) {
    selectedTargets = existing.filter((item) => getTargetKey(item) !== targetKey);
  } else {
    if (existing.length >= 3) {
      setDetails(`<p><strong>Maximum 3 targets allowed.</strong></p>`);
      return;
    }
    selectedTargets = [...existing, normalizedTarget];
  }

  if (selectedTargets.length === 0) {
    resetUiAfterClear();
    return;
  }

  state.selectedTargetKeys = new Set(selectedTargets.map(getTargetKey).filter(Boolean));
  applyAssetSelectionStyles();

  focusFilterOnSelectedSegments(selectedTargets);
  renderSelectedSegmentsDetails(selectedTargets);

  const activeTarget = selectedTargets[selectedTargets.length - 1];
  const activeType = normalizeTargetType(activeTarget.target_type);

  if (activeType === "rail_segment") {
    setSelectedSegment(activeTarget.segment_id);
    setHighlightedLine(activeTarget.line_id);
    setLineInputDisplay(activeTarget.line_id);
  } else {
    setSelectedSegment(null);
    setHighlightedLine(activeTarget.line_id || "");
    if (activeTarget.line_id) setLineInputDisplay(activeTarget.line_id);
  }

  setSelection({
    type: "segment-list",
    segments: selectedTargets
  });

  let layer = null;
  if (activeType === "rail_segment") {
    layer = state.segmentLayers.get(activeTarget.segment_id);
  } else if (activeType === "switch_junction") {
    layer = state.switchLayers.get(activeTarget.asset_id) || state.switchSegmentLayers.get(activeTarget.segment_id);
  } else if (activeType === "overhead_section") {
    layer = state.overheadLayers.get(activeTarget.asset_id);
  }

  fitLayerBounds(layer);
}

export function selectSegment(seg) {
  const line = state.lineIndex.get(seg.line_id) || {};
  const lineName = line.name || seg.line_id;
  selectAssetTarget({
    target_type: "rail_segment",
    asset_id: seg.segment_id,
    asset_label: `Rail segment ${seg.segment_id}`,
    asset_source: "SPOOR_DATA",
    segment_id: seg.segment_id,
    line_id: seg.line_id,
    line_name: lineName,
    geometry: seg.geometry,
    name: seg.name
  });
}

export function selectSegmentById(segmentId) {
  const seg = state.allSegments.find(s => s.segment_id === segmentId);
  if (!seg) return false;

  const target = {
    ...seg,
    target_type: "rail_segment",
    asset_id: seg.segment_id,
    asset_label: `Rail segment ${seg.segment_id}`,
    asset_source: "SPOOR_DATA"
  };

  focusFilterOnSelectedSegments([seg]);
  state.selectedTargetKeys = new Set([getTargetKey(target)].filter(Boolean));
  applyAssetSelectionStyles();

  setSelection({
    type: "segment-list",
    segments: [target]
  });

  setHighlightedLine(seg.line_id);
  setSelectedSegment(seg.segment_id);
  setLineInputDisplay(seg.line_id);

  setDetails(`
    <p><strong>${esc(seg.line_name)}</strong> (${esc(seg.line_id)})</p>
    <p><strong>Segment:</strong> ${esc(seg.segment_id)}</p>
  `);

  const layer = state.segmentLayers.get(seg.segment_id);
  fitLayerBounds(layer);

  return true;
}

export function selectLineById(lineId) {
  if (!lineId) {
    resetUiAfterClear();
    return;
  }

  const line = state.lineIndex.get(lineId);
  const lineName = line?.name || lineId;

  state.selectedSegmentId = null;
  state.selectedTargetKeys = new Set();
  applyAssetSelectionStyles();
  state.highlightedLineId = "";
  state.spotlightLineId = lineId;

  focusFilterOnLine(lineId);

  setDetails(`<p><strong>${esc(lineName)}</strong> (${esc(lineId)})</p>`);
  setSelection({
    type: "line",
    line_id: lineId,
    line_name: lineName
  });

  const segs = state.segmentsByLine.get(lineId) || [];
  const layers = segs
    .map(seg => state.segmentLayers.get(seg.segment_id))
    .filter(Boolean);

  fitLayerBounds(layers);
  applyOverlayStyles();
}

export function selectLinesFromMenu(lineIds) {
  const ids = [...new Set(lineIds)].filter(Boolean);
  const collectedSegments = [];

  if (ids.length === 0) {
    resetUiAfterClear();
    return;
  }

  if (!state.savedVisibleLineIds) {
    state.savedVisibleLineIds = new Set(state.visibleLineIds);
  }

  state.visibleLineIds = new Set(ids);
  renderFilterList();
  applyOverlayStyles();

  for (const lineId of ids) {
    const segs = state.segmentsByLine.get(lineId) || [];
    for (const seg of segs) {
      collectedSegments.push(seg);
    }
  }

  if (collectedSegments.length === 0) {
    setDetails(`<p><strong>No segments found for selected line(s).</strong></p>`);
    setSelection(null);
    return;
  }

  setDetails(`
    <p><strong>Selected from menu:</strong></p>
    <ul>
      ${ids.map(id => {
        const lineName = state.lineIndex.get(id)?.name || id;
        const segCount = (state.segmentsByLine.get(id) || []).length;
        return `<li>${esc(lineName)} (${esc(id)}) - ${segCount} segment(s)</li>`;
      }).join("")}
    </ul>
  `);

  setSelection({
    type: "segment-list",
    segments: collectedSegments
  });
}

export function applyRouteSelectionFromUrl() {
  const params = new URLSearchParams(window.location.search);
  const segmentId = params.get("segment_id");
  const lineId = params.get("line_id");

  if (segmentId) {
    const ok = selectSegmentById(segmentId);
    if (ok) return;
  }

  if (lineId) {
    selectLineById(lineId);
  }
}

export function fixMapSizeSoon() {
  if (state.map) {
    setTimeout(() => state.map.invalidateSize(), 80);
  }
}
export async function initMap() {
  if (!state.currentUser) {
    setStatus("Login to load map data");
    renderTimelineOverview();
    return;
  }

  setStatus("Loading protected map data...");
  await ensurePrototypeDataLoaded();

  const spoorData = getPrototypeData("SPOOR_DATA");
  const spoortakkenData = getPrototypeData("SPOORTAKKEN_DATA");

  if (!spoorData || !spoortakkenData) {
    setStatus("Prototype map data not loaded");
    throw new Error(
      "Protected map data could not be loaded."
    );
  }

  if (state.map) {
    state.map.remove();
    state.map = null;
  }

  resetTimelineStateForMapInit();
  wireTimelineUi();
  renderTimelineOverview();

  setStatus("Initializing map...");

  const nlBounds = L.latLngBounds(
    [50.7, 3.1],
    [53.7, 7.3]
  );

  state.map = L.map("map", {
    center: [52.3676, 4.9041],
    zoom: 11,
    minZoom: 7,
    maxZoom: MAP_MAX_ZOOM,
    zoomControl: true,
    attributionControl: false,
    preferCanvas: true,
    worldCopyJump: false,
    maxBounds: nlBounds,
    maxBoundsViscosity: 1.0
  });

  L.tileLayer("https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png", {
    attribution: "&copy; OpenStreetMap &copy; CARTO",
    maxZoom: MAP_MAX_ZOOM,
    noWrap: true
  }).addTo(state.map);

  await buildPrototypeLayers();

  const wiorLayer = await loadWiorLayerForMode(state.wiorFilterMode || "active");
  if (wiorLayer) {
    state.wiorLayer = wiorLayer;
  }

  registerMapLayers();

  state.map.on("click", () => {
    if (state.transferTrip?.active) {
      return;
    }

    if (state.suppressNextMapClear) {
      state.suppressNextMapClear = false;
      return;
    }

    resetUiAfterClear();
  });

  window.addEventListener("hashchange", fixMapSizeSoon);
  window.addEventListener("resize", fixMapSizeSoon);

  applyRouteSelectionFromUrl();
  await loadTimelineOverview();
  setStatus("Ready");
}
