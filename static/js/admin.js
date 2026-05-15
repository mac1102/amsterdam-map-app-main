async function getJSON(url, options = {}) {
  const res = await fetch(url, {
    credentials: "same-origin",
    ...options
  });

  if (!res.ok) {
    let message = `${res.status} ${res.statusText}`;
    try {
      const data = await res.json();
      if (data?.detail) message = data.detail;
    } catch (_) {}
    throw new Error(message);
  }

  return res.json();
}

const els = {
  appList: document.getElementById("appList"),
  recentList: document.getElementById("recentActivityList"),
  detailRoot: document.getElementById("detailRoot"),
  statusFilter: document.getElementById("statusFilter"),
  emailFilter: document.getElementById("emailFilter"),
  refreshBtn: document.getElementById("refreshBtn"),
  
  // Tabs & Views
  tabDashboard: document.getElementById("tabDashboard"),
  tabApplications: document.getElementById("tabApplications"),
  tabTbgn: document.getElementById("tabTbgn"),
  sidebarDashboard: document.getElementById("sidebarDashboard"),
  sidebarApplications: document.getElementById("sidebarApplications"),
  sidebarTbgn: document.getElementById("sidebarTbgn"),
  viewDashboard: document.getElementById("viewDashboard"),
  viewDetail: document.getElementById("viewDetail"),
  viewTbgn: document.getElementById("viewTbgn"),
  newTbgnBtn: document.getElementById("newTbgnBtn"),
  refreshTbgnBtn: document.getElementById("refreshTbgnBtn"),
  tbgnAddTopBtn: document.getElementById("tbgnAddTopBtn"),
  tbgnRefreshTopBtn: document.getElementById("tbgnRefreshTopBtn"),
  tbgnMessage: document.getElementById("tbgnMessage"),
  tbgnTableBody: document.getElementById("tbgnTableBody"),
  tbgnFormCard: document.getElementById("tbgnFormCard"),
  tbgnForm: document.getElementById("tbgnForm"),
  tbgnFormTitle: document.getElementById("tbgnFormTitle"),
  tbgnCancelBtn: document.getElementById("tbgnCancelBtn"),
  tbgnResetBtn: document.getElementById("tbgnResetBtn"),
  tbgnId: document.getElementById("tbgnId"),
  tbgnName: document.getElementById("tbgnName"),
  tbgnStartDate: document.getElementById("tbgnStartDate"),
  tbgnEndDate: document.getElementById("tbgnEndDate"),
  tbgnAffectedLines: document.getElementById("tbgnAffectedLines"),
  tbgnColor: document.getElementById("tbgnColor"),
  tbgnStatus: document.getElementById("tbgnStatus"),
  tbgnNotes: document.getElementById("tbgnNotes"),
  tbgnGeometry: document.getElementById("tbgnGeometry"),
  tbgnDrawMap: document.getElementById("tbgnDrawMap"),
  tbgnDrawStatus: document.getElementById("tbgnDrawStatus"),
  tbgnClearDrawingBtn: document.getElementById("tbgnClearDrawingBtn"),
  
  // Stats
  statPending: document.getElementById("statPending"),
  statApproved: document.getElementById("statApproved"),
  statZones: document.getElementById("statZones"),
  statRejected: document.getElementById("statRejected"),
  activeZonesSidebar: document.getElementById("activeZonesSidebar")
};

const state = {
  applications: [],
  tbgnProjects: [],
  selectedId: null,
  selectedItemType: null,
  tbgnLoaded: false,
  tbgnEditingId: "",
  activeTab: 'dashboard'
};

const DEBUG_ADMIN_LIST_LOGS = false;

let adminMapDataCache = null;
const adminMiniMaps = new Map();
let tbgnDrawMap = null;
let tbgnDrawnItems = null;
let tbgnDrawControl = null;

function logAdminListDebug(label, payload) {
  if (DEBUG_ADMIN_LIST_LOGS) {
    console.log(label, payload);
  }
}

function cleanupAdminMiniMaps() {
  adminMiniMaps.forEach((map) => {
    try {
      map.remove();
    } catch (_) {}
  });
  adminMiniMaps.clear();
}

async function loadAdminMapData() {
  if (adminMapDataCache) return adminMapDataCache;

  const res = await fetch("/api/map-data", {
    credentials: "same-origin"
  });

  if (!res.ok) {
    throw new Error(`Failed to load map data (${res.status})`);
  }

  adminMapDataCache = await res.json();
  return adminMapDataCache;
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

function getTargetTypeLabel(targetOrType) {
  const type = normalizeTargetType(
    typeof targetOrType === "string" ? targetOrType : targetOrType?.target_type
  );
  if (type === "switch_junction") return "Switch/Junction";
  if (type === "overhead_section") return "Overhead";
  return "Rail";
}

function getTargetReviewLabel(target) {
  const type = normalizeTargetType(target?.target_type);
  const assetId = String(target?.asset_id || target?.segment_id || "").trim();
  const segmentId = String(target?.segment_id || "").trim();
  const label = String(target?.asset_label || "").trim();

  if (type === "switch_junction") return label || `Switch/Junction ${assetId || segmentId || "-"}`;
  if (type === "overhead_section") return label || `Overhead section ${assetId || "-"}`;
  return label || `Rail segment ${segmentId || assetId || "-"}`;
}

function getTargetSubtitle(target) {
  const lineName = String(target?.line_name || "").trim();
  const lineId = String(target?.line_id || "").trim();
  const segmentId = String(target?.segment_id || "").trim();
  const parts = [];

  if (lineName) parts.push(lineName);
  if (lineId) parts.push(`(${lineId})`);
  if (normalizeTargetType(target?.target_type) !== "rail_segment" && segmentId) {
    parts.push(`Segment ${segmentId}`);
  }
  return parts.join(" ") || "-";
}

function getSwitchAssetId(properties = {}) {
  return String(properties.w || properties.k || properties.id || "").trim();
}

function getOverheadAssetId(properties = {}) {
  const rawId = String(properties.id || "").trim();
  if (!rawId) return "";
  return rawId.startsWith("BL-") ? rawId : `BL-${rawId}`;
}

function featureMatchesTarget(feature, target) {
  const type = normalizeTargetType(target?.target_type);
  const assetId = String(target?.asset_id || target?.segment_id || "").trim();
  const segmentId = String(target?.segment_id || "").trim();
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

function cloneFeatureWithTargetMeta(feature, target) {
  return {
    ...feature,
    properties: {
      ...(feature?.properties || {}),
      __target_type: normalizeTargetType(target?.target_type),
      __asset_id: String(target?.asset_id || target?.segment_id || "").trim(),
      __asset_label: getTargetReviewLabel(target)
    }
  };
}

function findTargetFeatures(mapData, targets) {
  const features =
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
    const type = normalizeTargetType(target?.target_type);
    const source = type === "overhead_section" ? overheadFeatures : features;
    const feature = source.find((item) => featureMatchesTarget(item, target));
    if (feature) matched.push(cloneFeatureWithTargetMeta(feature, target));
  });

  return matched;
}

function adminPointToLatLng(point) {
  const x = Number(point?.x);
  const y = Number(point?.y);
  if (!Number.isFinite(x) || !Number.isFinite(y)) return null;
  if (Math.abs(x) > 180 || Math.abs(y) > 90) return null;
  return [y, x];
}

async function renderAdminTargetMiniMap(application) {
  const container = document.getElementById("adminTargetMiniMap");
  const status = document.getElementById("adminTargetMiniMapStatus");
  if (!container || typeof L === "undefined") {
    if (status) status.textContent = "Map preview is unavailable.";
    return;
  }

  cleanupAdminMiniMaps();

  try {
    const mapData = await loadAdminMapData();
    if (!document.body.contains(container)) return;
    if (
      state.selectedId &&
      state.selectedItemType === "work_application" &&
      application?.application_id &&
      state.selectedId !== application.application_id
    ) {
      return;
    }

    const targets = Array.isArray(application?.targets) ? application.targets : [];
    const matched = findTargetFeatures(mapData, targets);

    if (!matched.length) {
      if (status) status.textContent = "No matching target geometry found for this application.";
      return;
    }

    const map = L.map(container, {
      zoomControl: true,
      attributionControl: false,
      scrollWheelZoom: false,
      dragging: true,
      doubleClickZoom: false,
      boxZoom: false,
      keyboard: false,
      touchZoom: true
    });

    adminMiniMaps.set(container.id, map);

    L.tileLayer("https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png", {
      maxZoom: 19,
      attribution: "&copy; OpenStreetMap &copy; CARTO"
    }).addTo(map);

    const featureCollection = {
      type: "FeatureCollection",
      features: matched
    };

    const layer = L.geoJSON(featureCollection, {
      style: (feature) => {
        const targetType = normalizeTargetType(feature?.properties?.__target_type);
        return {
          color: targetType === "overhead_section" ? "#7c3aed" : "#e65100",
          weight: 6,
          opacity: 0.95
        };
      },
      onEachFeature: (feature, lyr) => {
        const label = feature?.properties?.__asset_label || feature?.properties?.__asset_id || getFeatureSegmentId(feature);
        lyr.bindTooltip(label, {
          sticky: true
        });
      }
    }).addTo(map);

    const boundsGroup = L.featureGroup([layer]);

    targets.forEach((target) => {
      const startLatLng = adminPointToLatLng(target?.work_start_point);
      const endLatLng = adminPointToLatLng(target?.work_end_point);

      if (startLatLng) {
        const marker = L.circleMarker(startLatLng, {
          radius: 5,
          color: "#047857",
          weight: 2,
          fillColor: "#10b981",
          fillOpacity: 1
        }).bindTooltip(`Start pin ${getTargetReviewLabel(target)}`, { sticky: true });
        marker.addTo(map);
        boundsGroup.addLayer(marker);
      }

      if (endLatLng) {
        const marker = L.circleMarker(endLatLng, {
          radius: 5,
          color: "#b91c1c",
          weight: 2,
          fillColor: "#ef4444",
          fillOpacity: 1
        }).bindTooltip(`End pin ${getTargetReviewLabel(target)}`, { sticky: true });
        marker.addTo(map);
        boundsGroup.addLayer(marker);
      }
    });

    const bounds = boundsGroup.getBounds();
    if (bounds.isValid()) {
      map.fitBounds(bounds, {
        padding: [24, 24],
        maxZoom: 17
      });
    } else {
      map.setView([52.3676, 4.9041], 12);
    }

    setTimeout(() => map.invalidateSize(), 100);

    if (status) {
      status.textContent = `${matched.length} target${matched.length === 1 ? "" : "s"} shown.`;
    }
  } catch (err) {
    console.error("Failed to render admin target mini map:", err);
    if (status) status.textContent = "Could not load target map preview.";
  }
}

function switchTab(tab) {
  state.activeTab = tab;
  document.body.classList.remove("admin-detail-active");
  if (tab === "dashboard" || tab === "tbgn") {
    cleanupAdminMiniMaps();
  }

  els.tabDashboard.classList.toggle("active", tab === "dashboard");
  els.tabApplications.classList.toggle("active", tab === "applications");
  els.tabTbgn?.classList.toggle("active", tab === "tbgn");

  els.sidebarDashboard.classList.toggle("hidden", tab !== "dashboard");
  els.sidebarApplications.classList.toggle("hidden", tab !== "applications");
  els.sidebarTbgn?.classList.toggle("hidden", tab !== "tbgn");

  els.viewDashboard.classList.toggle("hidden", tab !== "dashboard");
  els.viewDetail.classList.toggle("hidden", tab !== "applications");
  els.viewTbgn?.classList.toggle("hidden", tab !== "tbgn");

  if (tab === "applications" && !state.selectedId) {
    els.detailRoot.innerHTML = `<div class="bg-white border border-gray-200 rounded-lg p-6 max-w-5xl shadow-sm text-gray-600">Select an application to view details.</div>`;
  }

  if (tab === "tbgn" && !state.tbgnLoaded) {
    loadAdminTbgnProjects().catch((err) => showTbgnMessage(`Failed to load TBGN projects: ${err.message}`, "error"));
  }
}

els.tabDashboard.addEventListener('click', () => switchTab('dashboard'));
els.tabApplications.addEventListener('click', () => switchTab('applications'));
els.tabTbgn?.addEventListener('click', () => switchTab('tbgn'));
document.getElementById('viewAllBtn').addEventListener('click', () => switchTab('applications'));

function esc(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function normalizeStatus(status) {
  const s = String(status || "submitted").toLowerCase();
  return ["submitted", "approved", "rejected"].includes(s) ? s : "submitted";
}

function shortId(value) {
  const raw = String(value || "-");
  if (raw === "-") return "-";
  return raw.split("-")[0] || raw.slice(0, 8);
}

function formatDateTime(value) {
  const parsed = new Date(value || "");
  return Number.isFinite(parsed.getTime()) ? parsed.toLocaleString() : "-";
}

function getAdminItemKey(itemType, id) {
  return `${String(itemType || "")}:${String(id || "")}`;
}

function normalizeAdminListItem(raw) {
  if (!raw) return null;

  const isTransfer =
    raw.type === "transfer" ||
    raw.item_type === "transfer_trip" ||
    !!raw.transfer_trip_id;

  if (isTransfer) {
    const startStopName = String(raw.start_stop_name || raw.start_stop?.name || "").trim();
    const endStopName = String(raw.end_stop_name || raw.end_stop?.name || "").trim();
    const id = String(raw.transfer_trip_id || "").trim();
    return {
      itemType: "transfer_trip",
      id,
      displayId: id || "-",
      submittedAt: raw.submitted_at || "",
      status: raw.status || "submitted",
      submittedBy: raw.submitted_by_email || "-",
      title: startStopName && endStopName ? `${startStopName} -> ${endStopName}` : "Transfer trip",
      raw
    };
  }

  const id = String(raw.application_id || "").trim();
  return {
    itemType: "work_application",
    id,
    displayId: id || "-",
    submittedAt: raw.submitted_at || "",
    status: raw.status || "submitted",
    submittedBy: raw.submitted_by_email || "-",
    title: raw.submitted_by_email || "Application",
    raw
  };
}

function getStatusBadgeHTML(status) {
  const s = normalizeStatus(status);
  const pretty = s.toUpperCase();
  if (s === "approved") {
    return `<span class="inline-flex items-center justify-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-green-100 text-green-800 border border-green-200">${pretty}</span>`;
  } else if (s === "submitted") {
    return `<span class="inline-flex items-center justify-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-blue-100 text-blue-800 border border-blue-200">${pretty}</span>`;
  } else if (s === "rejected") {
    return `<span class="inline-flex items-center justify-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-red-100 text-red-800 border border-red-200">${pretty}</span>`;
  }
  return `<span class="inline-flex items-center justify-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-gray-100 text-gray-800 border border-gray-200">${pretty}</span>`;
}

function updateStats() {
  let pending = 0, approved = 0, rejected = 0, targetsCount = 0;
  
  state.applications.forEach(app => {
    const s = normalizeStatus(app.status);
    if (s === 'submitted') pending++;
    else if (s === 'approved') {
      approved++;
      if (app.itemType === "work_application" && Array.isArray(app.raw?.targets)) {
        targetsCount += app.raw.targets.length;
      }
    }
    else if (s === 'rejected') rejected++;
  });
  
  els.statPending.textContent = pending;
  els.statApproved.textContent = approved;
  els.statZones.textContent = targetsCount;
  els.statRejected.textContent = rejected;
  els.activeZonesSidebar.textContent = targetsCount;
}

function renderList() {
  updateStats();
  
  if (!state.applications.length) {
    els.appList.innerHTML = `<div class="text-sm text-gray-500">No applications found.</div>`;
    els.recentList.innerHTML = `<tr><td colspan="4" class="px-6 py-4 text-center text-sm text-gray-500">No recent applications</td></tr>`;
    return;
  }

  // Sidebar List
  els.appList.innerHTML = state.applications.map(item => {
    const isTransfer = item.itemType === "transfer_trip";
    const idPrefix = isTransfer ? "TR" : "WRK";
    const itemBadge = isTransfer
      ? `<span class="inline-flex items-center justify-center px-2 py-0.5 rounded-full text-[11px] font-medium bg-indigo-100 text-indigo-800 border border-indigo-200">Transfer trip</span>`
      : `<span class="inline-flex items-center justify-center px-2 py-0.5 rounded-full text-[11px] font-medium bg-slate-100 text-slate-700 border border-slate-200">Work application</span>`;
    const isActive =
      state.selectedId === item.id &&
      state.selectedItemType === item.itemType;
    
    return `
      <button class="app-row w-full text-left p-3 rounded-md transition-colors border ${isActive ? 'active border-black' : 'border-gray-200 bg-white hover:border-gray-300'}" data-id="${esc(item.id)}" data-item-type="${esc(item.itemType)}">
        <div class="font-bold text-sm text-gray-900 mb-0.5 overflow-hidden whitespace-nowrap" style="text-overflow:ellipsis">${esc(item.submittedBy)}</div>
        <div class="text-xs text-gray-500 mb-0.5 overflow-hidden whitespace-nowrap" style="text-overflow:ellipsis">${esc(idPrefix)}-${esc(shortId(item.displayId))}</div>
        <div class="text-xs text-gray-500 mb-0.5 overflow-hidden whitespace-nowrap" style="text-overflow:ellipsis">${esc(item.title || "-")}</div>
        <div class="text-xs text-gray-500 mb-2 overflow-hidden whitespace-nowrap" style="text-overflow:ellipsis">${esc(formatDateTime(item.submittedAt))}</div>
        <div class="flex items-center justify-between gap-2">
          ${getStatusBadgeHTML(item.status)}
          ${itemBadge}
        </div>
      </button>
    `;
  }).join("");

  [...els.appList.querySelectorAll(".app-row")].forEach(btn => {
    btn.addEventListener("click", () => {
      const id = btn.getAttribute("data-id");
      const itemType = btn.getAttribute("data-item-type");
      loadAdminItem(id, itemType);
    });
  });
  
  // Dashboard Table
  const recent = state.applications.slice(0, 10);
  els.recentList.innerHTML = recent.map(item => `
    <tr class="app-row" data-id="${esc(item.id)}" data-item-type="${esc(item.itemType)}">
      <td class="px-6 py-4 font-mono text-xs text-gray-500">${esc(shortId(item.displayId))}</td>
      <td class="px-6 py-4 font-medium text-gray-900">
        ${esc(item.submittedBy)}
        ${item.itemType === "transfer_trip"
          ? `<span class="ml-2 inline-flex items-center justify-center px-2 py-0.5 rounded-full text-[11px] font-medium bg-indigo-100 text-indigo-800 border border-indigo-200">Transfer trip</span>`
          : ""}
      </td>
      <td class="px-6 py-4 text-gray-500">${esc(formatDateTime(item.submittedAt))}</td>
      <td class="px-6 py-4">${getStatusBadgeHTML(item.status)}</td>
    </tr>
  `).join("");

  [...els.recentList.querySelectorAll(".app-row")].forEach(row => {
    row.addEventListener("click", () => {
      const id = row.getAttribute("data-id");
      const itemType = row.getAttribute("data-item-type");
      loadAdminItem(id, itemType);
    });
  });
}

function renderLoadingDetail() {
  cleanupAdminMiniMaps();
  els.detailRoot.innerHTML = `<div class="bg-white border border-gray-200 rounded-lg p-6 max-w-5xl shadow-sm"><p>Loading details...</p></div>`;
  switchTab('applications');
}

function renderErrorDetail(message) {
  cleanupAdminMiniMaps();
  els.detailRoot.innerHTML = `<div class="bg-white border border-gray-200 rounded-lg p-6 max-w-5xl shadow-sm text-red-500"><p><strong>Error:</strong> ${esc(message)}</p></div>`;
  switchTab('applications');
}

function renderWorkApplicationDetail(app) {
  switchTab('applications');
  document.body.classList.add("admin-detail-active");
  cleanupAdminMiniMaps();
  const currentStatus = normalizeStatus(app.status);
  const work = app.work_details || {};
  const contact = app.contact_details || {};

  const targets = (app.targets || []).map(t => `
    <li>
      <span class="font-bold">${esc(getTargetTypeLabel(t))}: ${esc(getTargetReviewLabel(t))}</span>
      <div class="ml-1 mt-1 text-gray-800 space-y-0.5">
        <div>asset: ${esc(t.asset_id || t.segment_id || "-")}</div>
        <div>source: ${esc(t.asset_source || "-")}</div>
        <div>location: ${esc(getTargetSubtitle(t))}</div>
        <div>segment: ${esc(t.segment_id || "-")}</div>
        <div>mode: ${esc(t.work_mode || "-")}</div>
        <div>start: ${esc(t.project_start || "-")}</div>
        <div>end: ${esc(t.project_end || "-")}</div>
        ${
          Array.isArray(t.schedules) && t.schedules.length
            ? `
              <div class="mt-1">
                <div class="font-semibold">schedule windows:</div>
                <ul class="list-disc pl-5">
                  ${t.schedules.map((s, idx) => `
                    <li>
                      ${idx + 1}. ${esc(s.label || "Custom work")} - ${esc(s.project_start || "-")} to ${esc(s.project_end || "-")}
                    </li>
                  `).join("")}
                </ul>
              </div>
            `
            : ""
        }
      </div>
    </li>
  `).join("");

  const people = (app.people || []).map(p => `
    <li>${esc(p.first_name)} ${esc(p.last_name)} - ${esc(p.email)} - ${esc(p.phone)} ${p.employee_id ? `- ${esc(p.employee_id)}` : ""}</li>
  `).join("");

  const uploads = (app.uploads || []).map(u => `
    <a href="/api/admin/uploads/${encodeURIComponent(u.stored_filename)}" target="_blank" rel="noopener" class="text-blue-600 hover-underline block">${esc(u.filename)}</a>
  `).join("");

  let actionButtons = "";
  if (currentStatus === "submitted") {
    actionButtons = `
      <div class="flex gap-4">
        <button class="flex-1 bg-green-600 hover:bg-green-700 text-white rounded-md py-2.5 font-medium transition-colors text-sm" data-status="approved">Approve</button>
        <button class="flex-1 bg-red-600 hover:bg-red-700 text-white rounded-md py-2.5 font-medium transition-colors text-sm" data-status="rejected">Reject</button>
      </div>
    `;
  } else if (currentStatus === "approved") {
    actionButtons = `<button class="w-full bg-green-600 text-white rounded-md py-2.5 font-medium transition-colors text-sm opacity-50 cursor-not-allowed" disabled>Approved</button>`;
  } else if (currentStatus === "rejected") {
    actionButtons = `<button class="w-full bg-red-600 text-white rounded-md py-2.5 font-medium transition-colors text-sm opacity-50 cursor-not-allowed" disabled>Rejected</button>`;
  }

  const menuHtml = `
    ${currentStatus !== "submitted"
      ? `<button type="button" class="menu-item" data-status="submitted">Reset to submitted</button>`
      : `<div class="menu-item disabled">Already submitted</div>`}
    <button type="button" class="menu-item danger" id="deleteAppBtn">Delete application</button>
  `;

  els.detailRoot.innerHTML = `
    <div class="bg-white border border-gray-200 rounded-lg p-8 max-w-5xl shadow-sm">
      <div class="flex justify-between items-start mb-6">
        <h2 class="text-3xl font-bold">Application</h2>
        <details class="app-menu">
          <summary class="p-1.5 border border-gray-300 rounded-md text-gray-500 hover:bg-gray-50 transition-colors cursor-pointer list-none flex items-center justify-center">
            <svg stroke="currentColor" fill="none" stroke-width="2" viewBox="0 0 24 24" width="20" height="20"><circle cx="12" cy="12" r="1"></circle><circle cx="19" cy="12" r="1"></circle><circle cx="5" cy="12" r="1"></circle></svg>
          </summary>
          <div class="menu-panel">${menuHtml}</div>
        </details>
      </div>

      <div class="space-y-4 mb-8 text-sm">
        <div><span class="font-bold mr-1">ID:</span> ${esc(app.application_id)}</div>
        <div class="flex items-center gap-2">
          <span class="font-bold">Status:</span> ${getStatusBadgeHTML(app.status)}
        </div>
        <div><span class="font-bold mr-1">Submitted by:</span> ${esc(app.submitted_by_email)}</div>
        <div><span class="font-bold mr-1">Submitted at:</span> ${new Date(app.submitted_at).toLocaleString()}</div>
        <div><span class="font-bold mr-1">Person mode:</span> ${esc(app.person_mode || "-")}</div>
      </div>

      <div class="mb-6">
        <label class="block font-bold text-sm mb-2">Admin note</label>
        <textarea id="adminNoteInput" class="w-full border border-gray-300 rounded-md p-3 text-sm focus-outline-none resize-y" rows="3" placeholder="Internal note for admins only">${esc(app.admin_note || "")}</textarea>
      </div>
      <div class="mb-8">
        <label class="block font-bold text-sm mb-2">Decision message</label>
        <textarea id="decisionMessageInput" class="w-full border border-gray-300 rounded-md p-3 text-sm focus-outline-none resize-y" rows="3" placeholder="Optional message shown to the user">${esc(app.decision_message || "")}</textarea>
      </div>

      <div class="mb-8">${actionButtons}</div>

      <div class="mb-6">
        <h3 class="font-bold text-base mb-3">Work details</h3>
        <div class="text-sm text-gray-800 space-y-1">
          <div><span class="font-bold mr-1">Description:</span> ${esc(work.description || "-")}</div>
          <div><span class="font-bold mr-1">Source:</span> ${esc(work.source || "-")}</div>
          <div><span class="font-bold mr-1">Urgency:</span> ${esc(work.urgency || "-")}</div>
          <div><span class="font-bold mr-1">Affected lines:</span> ${esc(work.affected_lines || "-")}</div>
          <div><span class="font-bold mr-1">Notes:</span> ${esc(work.notes || "-")}</div>
        </div>
      </div>

      <div class="mb-6">
        <h3 class="font-bold text-base mb-3">Contact &amp; VVW</h3>
        <div class="text-sm text-gray-800 space-y-1">
          <div><span class="font-bold mr-1">Coordinator:</span> ${esc(contact.coordinator || "-")}</div>
          <div><span class="font-bold mr-1">VVW measure:</span> ${esc(contact.vvw_measure || "-")}</div>
        </div>
      </div>

      <div class="mb-6">
        <h3 class="font-bold text-base mb-3">Target map preview</h3>
        <div id="adminTargetMiniMap" class="admin-target-mini-map"></div>
        <div id="adminTargetMiniMapStatus" class="admin-target-mini-map-status"></div>
      </div>

      <div class="mb-6">
        <h3 class="font-bold text-base mb-3">Targets</h3>
        ${targets ? `<ul class="list-disc pl-5 text-sm space-y-3">${targets}</ul>` : `<div class="text-sm text-gray-500">No targets specified.</div>`}
      </div>

      <div class="mb-6">
        <h3 class="font-bold text-base mb-3">People</h3>
        ${people ? `<ul class="list-disc pl-5 text-sm">${people}</ul>` : `<div class="text-sm text-gray-500">No people specified.</div>`}
      </div>

      <div>
        <h3 class="font-bold text-base mb-3">Uploads</h3>
        ${uploads ? `<div class="text-sm space-y-2">${uploads}</div>` : `<div class="text-sm text-gray-500">No uploads.</div>`}
      </div>
    </div>
  `;

  [...els.detailRoot.querySelectorAll("[data-status]")].forEach(btn => {
    btn.addEventListener("click", async () => {
      const newStatus = btn.getAttribute("data-status");
      const adminNote = document.getElementById("adminNoteInput")?.value || "";
      const decisionMessage = document.getElementById("decisionMessageInput")?.value || "";
      await updateWorkApplicationStatus(app.application_id, newStatus, adminNote, decisionMessage);
    });
  });

  const deleteBtn = document.getElementById("deleteAppBtn");
  if (deleteBtn) {
    deleteBtn.addEventListener("click", async () => {
      if (!confirm("Are you sure you want to permanently delete this application? This cannot be undone.")) return;
      try {
        await getJSON(`/api/admin/applications/${encodeURIComponent(app.application_id)}`, {
          method: "DELETE"
        });
        state.selectedId = null;
        state.selectedItemType = null;
        await loadList();
      } catch (err) {
        alert(`Failed to delete: ${err.message}`);
      }
    });
  }

  requestAnimationFrame(() => {
    renderAdminTargetMiniMap(app);
  });
}

function getTransferStopName(trip, side) {
  if (side === "start") {
    return String(trip?.start_stop_name || trip?.start_stop?.name || "").trim() || "-";
  }
  return String(trip?.end_stop_name || trip?.end_stop?.name || "").trim() || "-";
}

function formatDistanceMeters(distanceMeters) {
  const meters = Number(distanceMeters);
  if (!Number.isFinite(meters) || meters <= 0) return "-";
  if (meters >= 1000) return `${(meters / 1000).toFixed(2)} km`;
  return `${Math.round(meters)} m`;
}

function normalizeRoutePoint(coord) {
  if (!Array.isArray(coord) || coord.length < 2) return null;
  const lng = Number(coord[0]);
  const lat = Number(coord[1]);
  if (!Number.isFinite(lng) || !Number.isFinite(lat)) return null;
  if (Math.abs(lng) > 180 || Math.abs(lat) > 90) return null;
  return [lat, lng];
}

async function renderAdminTransferRouteMiniMap(trip) {
  const container = document.getElementById("adminTransferRouteMiniMap");
  const status = document.getElementById("adminTransferRouteMiniMapStatus");
  if (!container || typeof L === "undefined") {
    if (status) status.textContent = "Map preview is unavailable.";
    return;
  }

  cleanupAdminMiniMaps();

  try {
    if (
      state.selectedId &&
      state.selectedItemType === "transfer_trip" &&
      trip?.transfer_trip_id &&
      state.selectedId !== trip.transfer_trip_id
    ) {
      return;
    }

    const coordinates = Array.isArray(trip?.route_geometry?.coordinates)
      ? trip.route_geometry.coordinates
      : [];
    const latLngs = coordinates.map(normalizeRoutePoint).filter(Boolean);

    if (!latLngs.length) {
      if (status) status.textContent = "No route geometry found for this transfer trip.";
      return;
    }

    const map = L.map(container, {
      zoomControl: true,
      attributionControl: false,
      scrollWheelZoom: false,
      dragging: true,
      doubleClickZoom: false,
      boxZoom: false,
      keyboard: false,
      touchZoom: true
    });
    adminMiniMaps.set(container.id, map);

    L.tileLayer("https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png", {
      maxZoom: 19,
      attribution: "&copy; OpenStreetMap &copy; CARTO"
    }).addTo(map);

    const line = L.polyline(latLngs, {
      color: "#0f766e",
      weight: 5,
      opacity: 0.9
    }).addTo(map);

    const startMarker = L.circleMarker(latLngs[0], {
      radius: 6,
      color: "#166534",
      weight: 2,
      fillColor: "#22c55e",
      fillOpacity: 1
    }).bindTooltip(`Start: ${getTransferStopName(trip, "start")}`, { sticky: true }).addTo(map);

    const endMarker = L.circleMarker(latLngs[latLngs.length - 1], {
      radius: 6,
      color: "#9f1239",
      weight: 2,
      fillColor: "#f43f5e",
      fillOpacity: 1
    }).bindTooltip(`End: ${getTransferStopName(trip, "end")}`, { sticky: true }).addTo(map);

    const boundsGroup = L.featureGroup([line, startMarker, endMarker]);
    const bounds = boundsGroup.getBounds();
    if (bounds.isValid()) {
      map.fitBounds(bounds, { padding: [24, 24], maxZoom: 16 });
    } else {
      map.setView([52.3676, 4.9041], 12);
    }

    setTimeout(() => map.invalidateSize(), 100);
    if (status) status.textContent = `Route preview loaded (${latLngs.length} points).`;
  } catch (err) {
    console.error("Failed to render transfer trip mini map:", err);
    if (status) status.textContent = "Could not load route map preview.";
  }
}

function renderTransferTripDetail(trip) {
  switchTab("applications");
  document.body.classList.add("admin-detail-active");
  cleanupAdminMiniMaps();

  const currentStatus = normalizeStatus(trip.status);
  const transferTripId = String(trip.transfer_trip_id || "").trim();
  const startStopName = getTransferStopName(trip, "start");
  const endStopName = getTransferStopName(trip, "end");

  let actionButtons = "";
  if (currentStatus === "submitted") {
    actionButtons = `
      <div class="flex gap-4">
        <button class="flex-1 bg-green-600 hover:bg-green-700 text-white rounded-md py-2.5 font-medium transition-colors text-sm" data-status="approved">Approve</button>
        <button class="flex-1 bg-red-600 hover:bg-red-700 text-white rounded-md py-2.5 font-medium transition-colors text-sm" data-status="rejected">Reject</button>
      </div>
    `;
  } else if (currentStatus === "approved") {
    actionButtons = `<button class="w-full bg-green-600 text-white rounded-md py-2.5 font-medium transition-colors text-sm opacity-50 cursor-not-allowed" disabled>Approved</button>`;
  } else if (currentStatus === "rejected") {
    actionButtons = `<button class="w-full bg-red-600 text-white rounded-md py-2.5 font-medium transition-colors text-sm opacity-50 cursor-not-allowed" disabled>Rejected</button>`;
  }

  const menuHtml = `
    ${currentStatus !== "submitted"
      ? `<button type="button" class="menu-item" data-status="submitted">Reset to submitted</button>`
      : `<div class="menu-item disabled">Already submitted</div>`}
    <button type="button" class="menu-item danger" id="deleteTripBtn">Delete transfer trip</button>
  `;

  els.detailRoot.innerHTML = `
    <div class="bg-white border border-gray-200 rounded-lg p-8 max-w-5xl shadow-sm">
      <div class="flex justify-between items-start mb-6">
        <h2 class="text-3xl font-bold">Transfer trip</h2>
        <details class="app-menu">
          <summary class="p-1.5 border border-gray-300 rounded-md text-gray-500 hover:bg-gray-50 transition-colors cursor-pointer list-none flex items-center justify-center">
            <svg stroke="currentColor" fill="none" stroke-width="2" viewBox="0 0 24 24" width="20" height="20"><circle cx="12" cy="12" r="1"></circle><circle cx="19" cy="12" r="1"></circle><circle cx="5" cy="12" r="1"></circle></svg>
          </summary>
          <div class="menu-panel">${menuHtml}</div>
        </details>
      </div>

      <div class="space-y-4 mb-8 text-sm">
        <div><span class="font-bold mr-1">Transfer trip ID:</span> ${esc(transferTripId || "-")}</div>
        <div class="flex items-center gap-2">
          <span class="font-bold">Status:</span> ${getStatusBadgeHTML(trip.status)}
        </div>
        <div><span class="font-bold mr-1">Submitted by:</span> ${esc(trip.submitted_by_email || "-")}</div>
        <div><span class="font-bold mr-1">Submitted at:</span> ${esc(formatDateTime(trip.submitted_at))}</div>
      </div>

      <div class="mb-6">
        <label class="block font-bold text-sm mb-2">Admin note</label>
        <textarea id="adminNoteInput" class="w-full border border-gray-300 rounded-md p-3 text-sm focus-outline-none resize-y" rows="3" placeholder="Internal note for admins only">${esc(trip.admin_note || "")}</textarea>
      </div>
      <div class="mb-8">
        <label class="block font-bold text-sm mb-2">Decision message</label>
        <textarea id="decisionMessageInput" class="w-full border border-gray-300 rounded-md p-3 text-sm focus-outline-none resize-y" rows="3" placeholder="Optional message shown to the user">${esc(trip.decision_message || "")}</textarea>
      </div>

      <div class="mb-8">${actionButtons}</div>

      <div class="mb-6">
        <h3 class="font-bold text-base mb-3">Trip details</h3>
        <div class="text-sm text-gray-800 space-y-1">
          <div><span class="font-bold mr-1">Start stop:</span> ${esc(startStopName)}</div>
          <div><span class="font-bold mr-1">End stop:</span> ${esc(endStopName)}</div>
          <div><span class="font-bold mr-1">Planned date:</span> ${esc(trip.planned_date || "-")}</div>
          <div><span class="font-bold mr-1">Planned start time:</span> ${esc(trip.planned_start_time || "-")}</div>
          <div><span class="font-bold mr-1">Planned end time:</span> ${esc(trip.planned_end_time || "-")}</div>
          <div><span class="font-bold mr-1">Tram number:</span> ${esc(trip.tram_number || "-")}</div>
          <div><span class="font-bold mr-1">Reason:</span> ${esc(trip.reason || "-")}</div>
          <div><span class="font-bold mr-1">Notes:</span> ${esc(trip.notes || "-")}</div>
          <div><span class="font-bold mr-1">Route distance:</span> ${esc(formatDistanceMeters(trip.route_distance_m))}</div>
        </div>
      </div>

      <div class="mb-6">
        <h3 class="font-bold text-base mb-3">Route preview map</h3>
        <div id="adminTransferRouteMiniMap" class="admin-target-mini-map"></div>
        <div id="adminTransferRouteMiniMapStatus" class="admin-target-mini-map-status"></div>
      </div>
    </div>
  `;

  [...els.detailRoot.querySelectorAll("[data-status]")].forEach(btn => {
    btn.addEventListener("click", async () => {
      const newStatus = btn.getAttribute("data-status");
      const adminNote = document.getElementById("adminNoteInput")?.value || "";
      const decisionMessage = document.getElementById("decisionMessageInput")?.value || "";
      await updateTransferTripStatus(transferTripId, newStatus, adminNote, decisionMessage);
    });
  });

  const deleteBtn = document.getElementById("deleteTripBtn");
  if (deleteBtn) {
    deleteBtn.addEventListener("click", async () => {
      if (!confirm("Are you sure you want to permanently delete this transfer trip? This cannot be undone.")) return;
      try {
        await getJSON(`/api/admin/transfer_trips/${encodeURIComponent(transferTripId)}`, {
          method: "DELETE"
        });
        state.selectedId = null;
        state.selectedItemType = null;
        await loadList();
      } catch (err) {
        alert(`Failed to delete: ${err.message}`);
      }
    });
  }

  requestAnimationFrame(() => {
    renderAdminTransferRouteMiniMap(trip);
  });
}

async function loadList() {
  const status = els.statusFilter.value.trim();
  const email = els.emailFilter.value.trim();

  const params = new URLSearchParams();
  if (status) params.set("status", status);
  if (email) params.set("email", email);

  try {
    const [resApps, resTransfers] = await Promise.all([
      fetch(`/api/admin/applications?${params.toString()}`).then(r => r.json()).catch(() => ({})),
      fetch(`/api/admin/transfer_trips?${params.toString()}`).then(r => r.json()).catch(() => ({}))
    ]);

    const applications = Array.isArray(resApps?.applications) ? resApps.applications : [];
    const transferTrips = Array.isArray(resTransfers?.transfer_trips) ? resTransfers.transfer_trips : [];

    logAdminListDebug("Admin raw applications:", applications);
    logAdminListDebug("Admin raw transfer trips:", transferTrips);

    const normalizedItems = [];
    applications.forEach((raw) => {
      const normalized = normalizeAdminListItem(raw);
      if (!normalized || !normalized.id) {
        console.warn("Skipping admin work application item with missing id:", raw);
        return;
      }
      normalizedItems.push(normalized);
    });

    transferTrips.forEach((raw) => {
      const normalized = normalizeAdminListItem({
        ...raw,
        item_type: "transfer_trip"
      });
      if (!normalized || !normalized.id) {
        console.warn("Skipping admin transfer trip item with missing id:", raw);
        return;
      }
      normalizedItems.push(normalized);
    });

    logAdminListDebug("Admin normalized items:", normalizedItems);

    normalizedItems.sort((a, b) => {
      const aTime = Date.parse(a.submittedAt || "") || 0;
      const bTime = Date.parse(b.submittedAt || "") || 0;
      return bTime - aTime;
    });

    state.applications = normalizedItems;

    if (
      state.selectedId &&
      !state.applications.find(
        (item) => getAdminItemKey(item.itemType, item.id) === getAdminItemKey(state.selectedItemType, state.selectedId)
      )
    ) {
      state.selectedId = null;
      state.selectedItemType = null;
    }

    try {
      renderList();
    } catch (err) {
      console.error("Admin list render failed:", err);
      els.appList.innerHTML = `<div class="text-sm text-red-600">Failed to render list: ${esc(err.message)}</div>`;
      els.recentList.innerHTML = `<tr><td colspan="4" class="px-6 py-4 text-center text-sm text-red-600">Failed to render list: ${esc(err.message)}</td></tr>`;
      return;
    }

    if (state.selectedId && state.selectedItemType) {
      await loadAdminItem(state.selectedId, state.selectedItemType);
      return;
    }

    cleanupAdminMiniMaps();
    els.detailRoot.innerHTML = `<div class="bg-white border border-gray-200 rounded-lg p-6 max-w-5xl shadow-sm text-gray-600">Select an application to view details.</div>`;
  } catch (err) {
    console.error("Failed to load admin list:", err);
    els.appList.innerHTML = `<div class="text-sm text-red-600">Failed to load list: ${esc(err.message)}</div>`;
    els.recentList.innerHTML = `<tr><td colspan="4" class="px-6 py-4 text-center text-sm text-red-600">Failed to load list: ${esc(err.message)}</td></tr>`;
    cleanupAdminMiniMaps();
    if (!state.selectedId) {
      els.detailRoot.innerHTML = `<div class="bg-white border border-gray-200 rounded-lg p-6 max-w-5xl shadow-sm text-gray-600">Select an application to view details.</div>`;
    }
  }
}

async function loadAdminApplicationDetail(applicationId) {
  const data = await getJSON(`/api/admin/applications/${encodeURIComponent(applicationId)}`);
  try {
    renderWorkApplicationDetail(data);
  } catch (err) {
    console.error("Admin application detail render failed:", err);
    renderErrorDetail(`Failed to render application detail: ${err.message}`);
  }
}

async function loadAdminTransferTripDetail(transferTripId) {
  const data = await getJSON(`/api/admin/transfer_trips/${encodeURIComponent(transferTripId)}`);
  try {
    renderTransferTripDetail(data);
  } catch (err) {
    console.error("Admin transfer trip detail render failed:", err);
    renderErrorDetail(`Failed to render transfer trip detail: ${err.message}`);
  }
}

async function loadAdminItem(id, itemType = null) {
  const resolvedId = String(id || "").trim();
  if (!resolvedId) {
    renderErrorDetail("Invalid item id.");
    return;
  }

  const appMeta = state.applications.find((item) =>
    item.id === resolvedId && (!itemType || item.itemType === itemType)
  ) || state.applications.find((item) => item.id === resolvedId);
  const resolvedType = itemType || appMeta?.itemType || "work_application";

  state.selectedId = resolvedId;
  state.selectedItemType = resolvedType;

  try {
    renderList();
  } catch (err) {
    console.error("Admin list rerender failed while selecting item:", err);
  }
  renderLoadingDetail();

  try {
    if (resolvedType === "transfer_trip") {
      await loadAdminTransferTripDetail(resolvedId);
    } else {
      await loadAdminApplicationDetail(resolvedId);
    }
  } catch (err) {
    console.error("Failed to load admin detail:", err);
    renderErrorDetail(err.message || "Failed to load detail.");
  }
}

async function updateWorkApplicationStatus(applicationId, status, adminNote = "", decisionMessage = "") {
  await getJSON(`/api/admin/applications/${encodeURIComponent(applicationId)}/status`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status, admin_note: adminNote, decision_message: decisionMessage })
  });

  await loadList();
  await loadAdminItem(applicationId, "work_application");
}

async function updateTransferTripStatus(transferTripId, status, adminNote = "", decisionMessage = "") {
  await getJSON(`/api/admin/transfer_trips/${encodeURIComponent(transferTripId)}/status`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status, admin_note: adminNote, decision_message: decisionMessage })
  });

  await loadList();
  await loadAdminItem(transferTripId, "transfer_trip");
}

function showTbgnMessage(message, type = "success") {
  if (!els.tbgnMessage) return;
  const isError = type === "error";
  els.tbgnMessage.className = isError
    ? "bg-white border border-gray-200 rounded-lg p-4 text-sm text-red-600"
    : "bg-white border border-gray-200 rounded-lg p-4 text-sm text-green-700";
  els.tbgnMessage.textContent = message || "";
  els.tbgnMessage.classList.toggle("hidden", !message);
}

function tbgnStatusBadge(status) {
  const normalized = String(status || "draft").toLowerCase() === "published" ? "published" : "draft";
  const classes = normalized === "published"
    ? "inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-green-100 text-green-800 border border-green-200"
    : "inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-gray-100 text-gray-700 border border-gray-200";
  return `<span class="${classes}">${esc(normalized)}</span>`;
}

function formatTbgnGeometryForTextarea(geometry) {
  if (!geometry) return "";
  if (typeof geometry === "string") return geometry;
  try {
    return JSON.stringify(geometry, null, 2);
  } catch (_) {
    return "";
  }
}

const TBGN_ADMIN_GEOMETRY_TYPES = new Set([
  "Point",
  "LineString",
  "Polygon",
  "MultiLineString",
  "MultiPolygon"
]);

function setTbgnDrawStatus(message) {
  if (els.tbgnDrawStatus) {
    els.tbgnDrawStatus.textContent = message || "No geometries drawn.";
  }
}

function getTbgnDrawnGeometryCount() {
  if (!tbgnDrawnItems || typeof tbgnDrawnItems.getLayers !== "function") return 0;
  return tbgnDrawnItems.getLayers().filter((layer) => typeof layer.toGeoJSON === "function").length;
}

function updateTbgnDrawStatus() {
  const count = getTbgnDrawnGeometryCount();
  setTbgnDrawStatus(count ? `${count} geometr${count === 1 ? "y" : "ies"} drawn.` : "No geometries drawn.");
}

function clearTbgnDrawing(updateTextarea = true) {
  if (tbgnDrawnItems) {
    tbgnDrawnItems.clearLayers();
  }
  if (updateTextarea && els.tbgnGeometry) {
    els.tbgnGeometry.value = "";
  }
  updateTbgnDrawStatus();
}

function normalizeTbgnGeometryToFeatureCollection(geometry) {
  if (!geometry || typeof geometry !== "object") return null;

  const normalizeFeature = (feature) => ({
    type: "Feature",
    properties: feature.properties && typeof feature.properties === "object"
      ? feature.properties
      : {},
    geometry: feature.geometry
  });

  if (geometry.type === "FeatureCollection") {
    const features = Array.isArray(geometry.features)
      ? geometry.features.filter((feature) => feature?.type === "Feature" && feature.geometry)
      : [];
    return features.length ? { type: "FeatureCollection", features: features.map(normalizeFeature) } : null;
  }

  if (geometry.type === "Feature") {
    return geometry.geometry
      ? { type: "FeatureCollection", features: [normalizeFeature(geometry)] }
      : null;
  }

  if (TBGN_ADMIN_GEOMETRY_TYPES.has(geometry.type)) {
    return {
      type: "FeatureCollection",
      features: [
        {
          type: "Feature",
          properties: {},
          geometry
        }
      ]
    };
  }

  return null;
}

function collectTbgnDrawnGeometry() {
  if (!tbgnDrawnItems) return null;

  const features = [];
  tbgnDrawnItems.eachLayer((layer) => {
    if (typeof layer.toGeoJSON === "function") {
      const feature = layer.toGeoJSON();
      if (feature?.type === "Feature" && feature.geometry) {
        features.push({
          ...feature,
          properties: feature.properties && typeof feature.properties === "object"
            ? feature.properties
            : {}
        });
      }
    }
  });

  if (!features.length) return null;

  return {
    type: "FeatureCollection",
    features
  };
}

function syncTbgnGeometryFromDrawLayer(options = {}) {
  const clearWhenEmpty = options.clearWhenEmpty !== false;
  if (!tbgnDrawnItems || !els.tbgnGeometry) return 0;
  const geojson = collectTbgnDrawnGeometry();
  const count = geojson?.features?.length || 0;

  if (!count) {
    if (clearWhenEmpty) {
      els.tbgnGeometry.value = "";
    }
    updateTbgnDrawStatus();
    return 0;
  }

  els.tbgnGeometry.value = JSON.stringify(geojson, null, 2);
  updateTbgnDrawStatus();
  return count;
}

function loadTbgnGeometryIntoDrawLayer(geometry) {
  if (!tbgnDrawMap || !tbgnDrawnItems || typeof L === "undefined") return;
  clearTbgnDrawing(false);

  if (!geometry) {
    syncTbgnGeometryFromDrawLayer();
    return;
  }

  try {
    const geojsonLayer = L.geoJSON(geometry);
    geojsonLayer.eachLayer((layer) => {
      tbgnDrawnItems.addLayer(layer);
    });

    syncTbgnGeometryFromDrawLayer();

    if (tbgnDrawnItems.getLayers().length) {
      const bounds = tbgnDrawnItems.getBounds();
      if (bounds.isValid()) {
        tbgnDrawMap.fitBounds(bounds, { padding: [24, 24], maxZoom: 16 });
      }
    }
  } catch (err) {
    console.error("Failed to load TBGN geometry into draw map:", err);
    setTbgnDrawStatus("Could not load existing geometry. Check raw GeoJSON.");
  }
}

function initTbgnDrawingMap(geometry = null) {
  if (!els.tbgnDrawMap) return;
  if (typeof L === "undefined") {
    setTbgnDrawStatus("Leaflet is unavailable.");
    return;
  }

  if (!tbgnDrawMap) {
    tbgnDrawMap = L.map(els.tbgnDrawMap, {
      center: [52.3676, 4.9041],
      zoom: 12,
      minZoom: 7,
      maxZoom: 19
    });

    L.tileLayer("https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png", {
      attribution: "&copy; OpenStreetMap &copy; CARTO",
      maxZoom: 19,
      noWrap: true
    }).addTo(tbgnDrawMap);

    tbgnDrawnItems = new L.FeatureGroup();
    tbgnDrawMap.addLayer(tbgnDrawnItems);

    if (L.Control?.Draw) {
      tbgnDrawControl = new L.Control.Draw({
        draw: {
          marker: true,
          polyline: {
            shapeOptions: { color: "#7c3aed", weight: 5 }
          },
          polygon: {
            allowIntersection: false,
            showArea: true,
            shapeOptions: { color: "#7c3aed", weight: 3, fillOpacity: 0.18 }
          },
          rectangle: false,
          circle: false,
          circlemarker: false
        },
        edit: {
          featureGroup: tbgnDrawnItems,
          remove: true
        }
      });
      tbgnDrawMap.addControl(tbgnDrawControl);

      tbgnDrawMap.on(L.Draw.Event.CREATED, (event) => {
        tbgnDrawnItems.addLayer(event.layer);
        syncTbgnGeometryFromDrawLayer();
      });
      tbgnDrawMap.on(L.Draw.Event.EDITED, syncTbgnGeometryFromDrawLayer);
      tbgnDrawMap.on(L.Draw.Event.DELETED, syncTbgnGeometryFromDrawLayer);
    } else {
      setTbgnDrawStatus("Leaflet.draw is unavailable. Use raw GeoJSON below.");
    }
  }

  setTimeout(() => {
    tbgnDrawMap.invalidateSize();
    loadTbgnGeometryIntoDrawLayer(geometry);
  }, 80);
}

async function loadAdminTbgnProjects() {
  if (!els.tbgnTableBody) return;
  els.tbgnTableBody.innerHTML = `<tr><td colspan="6" class="px-6 py-4 text-sm text-gray-500">Loading TBGN projects...</td></tr>`;
  try {
    const data = await getJSON("/api/admin/tbgn");
    state.tbgnProjects = Array.isArray(data?.projects) ? data.projects : [];
    state.tbgnLoaded = true;
    renderAdminTbgnList();
  } catch (err) {
    state.tbgnProjects = [];
    state.tbgnLoaded = false;
    els.tbgnTableBody.innerHTML = `<tr><td colspan="6" class="px-6 py-4 text-sm text-red-600">Failed to load TBGN projects: ${esc(err.message)}</td></tr>`;
    throw err;
  }
}

function renderAdminTbgnList() {
  if (!els.tbgnTableBody) return;

  if (!state.tbgnProjects.length) {
    els.tbgnTableBody.innerHTML = `<tr><td colspan="6" class="px-6 py-4 text-center text-sm text-gray-500">No TBGN projects found.</td></tr>`;
    return;
  }

  els.tbgnTableBody.innerHTML = state.tbgnProjects.map((project) => `
    <tr>
      <td class="px-6 py-4 font-medium text-gray-900">
        <span class="inline-flex items-center gap-2">
          <span style="display:inline-block;width:10px;height:10px;border-radius:999px;background:${esc(project.color || "#7c3aed")};border:1px solid #d1d5db;"></span>
          ${esc(project.name)}
        </span>
      </td>
      <td class="px-6 py-4 text-gray-500">${esc(project.start_date || "-")}</td>
      <td class="px-6 py-4 text-gray-500">${esc(project.end_date || "-")}</td>
      <td class="px-6 py-4 text-gray-500">${esc(project.affected_lines || "-")}</td>
      <td class="px-6 py-4">${tbgnStatusBadge(project.status)}</td>
      <td class="px-6 py-4 whitespace-nowrap">
        <button type="button" class="text-sm text-blue-600 hover-underline font-medium tbgn-edit-btn" data-id="${esc(project.id)}" style="cursor:pointer;background:transparent;border:none;">Edit</button>
        <button type="button" class="text-sm text-red-600 hover-underline font-medium tbgn-delete-btn" data-id="${esc(project.id)}" style="cursor:pointer;background:transparent;border:none;margin-left:12px;">Delete</button>
      </td>
    </tr>
  `).join("");

  els.tbgnTableBody.querySelectorAll(".tbgn-edit-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const project = state.tbgnProjects.find((item) => item.id === btn.getAttribute("data-id"));
      openTbgnForm(project || null);
    });
  });

  els.tbgnTableBody.querySelectorAll(".tbgn-delete-btn").forEach((btn) => {
    btn.addEventListener("click", () => deleteTbgnProject(btn.getAttribute("data-id")));
  });
}

function openTbgnForm(project = null) {
  if (!els.tbgnFormCard || !els.tbgnForm) return;
  const editing = !!project?.id;
  state.tbgnEditingId = editing ? project.id : "";
  els.tbgnFormTitle.textContent = editing ? "Edit TBGN" : "Add TBGN";
  els.tbgnId.value = state.tbgnEditingId;
  els.tbgnName.value = project?.name || "";
  els.tbgnStartDate.value = project?.start_date || "";
  els.tbgnEndDate.value = project?.end_date || "";
  els.tbgnAffectedLines.value = project?.affected_lines || "";
  els.tbgnColor.value = /^#[0-9a-fA-F]{6}$/.test(project?.color || "") ? project.color : "#7c3aed";
  els.tbgnStatus.value = project?.status === "published" ? "published" : "draft";
  els.tbgnNotes.value = project?.notes || "";
  els.tbgnGeometry.value = formatTbgnGeometryForTextarea(project?.geometry);
  els.tbgnFormCard.classList.remove("hidden");
  showTbgnMessage("", "success");
  els.tbgnName.focus();
  initTbgnDrawingMap(project?.geometry || null);
}

function closeTbgnForm() {
  state.tbgnEditingId = "";
  els.tbgnForm?.reset();
  if (els.tbgnColor) els.tbgnColor.value = "#7c3aed";
  clearTbgnDrawing(true);
  els.tbgnFormCard?.classList.add("hidden");
}

function buildTbgnPayloadFromForm() {
  syncTbgnGeometryFromDrawLayer({ clearWhenEmpty: false });
  const name = els.tbgnName.value.trim();
  const startDate = els.tbgnStartDate.value.trim();
  const endDate = els.tbgnEndDate.value.trim();
  const rawGeometry = els.tbgnGeometry.value.trim();

  if (!name) throw new Error("Name is required.");
  if (!startDate || !endDate) throw new Error("Start date and end date are required.");
  if (endDate < startDate) throw new Error("End date must be on or after start date.");

  let geometry = null;
  if (rawGeometry) {
    try {
      geometry = JSON.parse(rawGeometry);
    } catch (_) {
      throw new Error("Geometry must be valid GeoJSON JSON.");
    }
    geometry = normalizeTbgnGeometryToFeatureCollection(geometry);
    if (!geometry) {
      throw new Error("Geometry must be a GeoJSON geometry, Feature, or FeatureCollection.");
    }
  }

  return {
    name,
    start_date: startDate,
    end_date: endDate,
    affected_lines: els.tbgnAffectedLines.value.trim(),
    color: els.tbgnColor.value || "#7c3aed",
    status: els.tbgnStatus.value === "published" ? "published" : "draft",
    notes: els.tbgnNotes.value.trim(),
    geometry
  };
}

async function saveTbgnProject(event) {
  event?.preventDefault();
  let payload;
  try {
    payload = buildTbgnPayloadFromForm();
  } catch (err) {
    showTbgnMessage(err.message, "error");
    return;
  }

  const projectId = els.tbgnId.value.trim();
  const method = projectId ? "PUT" : "POST";
  const url = projectId ? `/api/admin/tbgn/${encodeURIComponent(projectId)}` : "/api/admin/tbgn";

  try {
    await getJSON(url, {
      method,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    closeTbgnForm();
    await loadAdminTbgnProjects();
    showTbgnMessage(projectId ? "TBGN project updated." : "TBGN project created.");
  } catch (err) {
    showTbgnMessage(`Failed to save TBGN project: ${err.message}`, "error");
  }
}

async function deleteTbgnProject(id) {
  const projectId = String(id || "").trim();
  if (!projectId) return;
  const project = state.tbgnProjects.find((item) => item.id === projectId);
  const label = project?.name ? ` "${project.name}"` : "";
  if (!confirm(`Delete TBGN project${label}? This cannot be undone.`)) return;

  try {
    await getJSON(`/api/admin/tbgn/${encodeURIComponent(projectId)}`, {
      method: "DELETE"
    });
    if (state.tbgnEditingId === projectId) closeTbgnForm();
    await loadAdminTbgnProjects();
    showTbgnMessage("TBGN project deleted.");
  } catch (err) {
    showTbgnMessage(`Failed to delete TBGN project: ${err.message}`, "error");
  }
}

els.refreshBtn.addEventListener("click", loadList);
els.statusFilter.addEventListener("change", loadList);
els.emailFilter.addEventListener("keydown", (e) => {
  if (e.key === "Enter") loadList();
});
els.newTbgnBtn?.addEventListener("click", () => {
  switchTab("tbgn");
  openTbgnForm();
});
els.tbgnAddTopBtn?.addEventListener("click", () => openTbgnForm());
els.refreshTbgnBtn?.addEventListener("click", () => {
  loadAdminTbgnProjects().catch((err) => showTbgnMessage(`Failed to refresh TBGN projects: ${err.message}`, "error"));
});
els.tbgnRefreshTopBtn?.addEventListener("click", () => {
  loadAdminTbgnProjects().catch((err) => showTbgnMessage(`Failed to refresh TBGN projects: ${err.message}`, "error"));
});
els.tbgnForm?.addEventListener("submit", saveTbgnProject);
els.tbgnCancelBtn?.addEventListener("click", closeTbgnForm);
els.tbgnResetBtn?.addEventListener("click", () => openTbgnForm());
els.tbgnClearDrawingBtn?.addEventListener("click", () => clearTbgnDrawing(true));

const backBtn = document.getElementById("adminDetailBackBtn");
if (backBtn) {
  backBtn.addEventListener("click", () => {
    document.body.classList.remove("admin-detail-active");
    cleanupAdminMiniMaps();
  });
}


// Init
switchTab('dashboard');
loadList().catch(err => {
  els.appList.innerHTML = `<div class="text-sm text-gray-500">Failed to load list: ${esc(err.message)}</div>`;
});
