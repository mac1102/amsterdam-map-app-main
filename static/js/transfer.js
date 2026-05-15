import { state } from "./state.js";
import { dom } from "./dom.js";

const STEP_LABELS = ["Route", "Details", "Planning", "Review"];
const TOTAL_STEPS = STEP_LABELS.length;
const TRANSFER_VISIBLE_LAYER_KEYS = new Set(["tramStops"]);
let routeRequestSeq = 0;
const ROUTE_STYLE = {
  color: "#1565C0",
  weight: 6,
  opacity: 0.95,
  dashArray: "12 8",
  lineCap: "round",
  lineJoin: "round"
};

function getJSON(url) {
  return fetch(url, { credentials: "same-origin" }).then((r) => {
    if (!r.ok) throw new Error(`${r.status}`);
    return r.json();
  });
}

function postJSON(url, body) {
  return fetch(url, {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body)
  }).then((r) => {
    if (!r.ok) return r.json().then((d) => Promise.reject(d));
    return r.json();
  });
}

function toast(msg, type = "info") {
  const host = dom.toastHost;
  if (!host) return;
  const el = document.createElement("div");
  el.className = `toast toast-${type}`;
  el.textContent = msg;
  host.appendChild(el);
  setTimeout(() => el.classList.add("show"), 10);
  setTimeout(() => {
    el.classList.remove("show");
    setTimeout(() => el.remove(), 300);
  }, 3500);
}

function esc(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function stopLeafletEvent(event) {
  if (!event?.originalEvent) return;
  event.originalEvent.preventDefault?.();
  event.originalEvent.stopPropagation?.();
  if (typeof L !== "undefined" && L.DomEvent) {
    L.DomEvent.stop(event.originalEvent);
  }
}

function setTransferCursor(active) {
  const enabled = !!active;
  if (dom.mapEl) {
    dom.mapEl.classList.toggle("transfer-mode-active", enabled);
  }
  if (state.map && typeof state.map.getContainer === "function") {
    state.map.getContainer().classList.toggle("transfer-mode-active", enabled);
  }
}

function setLayerVisibilityLocal(layerKey, visible) {
  if (!state.mapLayers || !(state.mapLayers instanceof Map)) return;
  const entry = state.mapLayers.get(layerKey);
  if (!entry) return;

  const nextVisible = !!visible && !!entry.available;
  state.mapLayerVisibility[layerKey] = nextVisible;

  if (!state.map || !entry.layer) return;
  const isOnMap = state.map.hasLayer(entry.layer);
  if (nextVisible && !isOnMap) {
    entry.layer.addTo(state.map);
  } else if (!nextVisible && isOnMap) {
    state.map.removeLayer(entry.layer);
  }
}

function refreshLayerPanelUi() {
  if (dom.mapLayerList) {
    const rows = dom.mapLayerList.querySelectorAll("[data-layer-key]");
    rows.forEach((row) => {
      const layerKey = row.dataset.layerKey;
      const entry = state.mapLayers?.get(layerKey);
      const isAvailable = !!entry?.available;
      const isVisible = !!state.mapLayerVisibility[layerKey] && isAvailable;

      row.classList.toggle("is-disabled", !isAvailable);
      row.classList.toggle("is-active", isVisible);

      const checkbox = row.querySelector(".map-layer-checkbox");
      if (checkbox) {
        checkbox.disabled = !isAvailable;
        checkbox.checked = isVisible;
      }
    });
  }

  if (dom.mapLayerActiveCount && state.mapLayers && state.mapLayers instanceof Map) {
    let total = 0;
    let active = 0;
    state.mapLayers.forEach((entry, key) => {
      total += 1;
      if (entry.available && state.mapLayerVisibility[key]) active += 1;
    });
    dom.mapLayerActiveCount.textContent = `${active} / ${total} active`;
  }
}

function captureAndHideSpecialLayers() {
  const snapshot = {
    timelineHighlightVisible: false,
    applicationHighlightVisible: false
  };

  if (!state.map) return snapshot;

  const timelineHighlight = state.timeline?.highlightLayer || null;
  if (timelineHighlight && state.map.hasLayer(timelineHighlight)) {
    state.map.removeLayer(timelineHighlight);
    snapshot.timelineHighlightVisible = true;
  }

  const appHighlight = state.applicationTargetHighlightLayer;
  if (appHighlight && state.map.hasLayer(appHighlight)) {
    state.map.removeLayer(appHighlight);
    snapshot.applicationHighlightVisible = true;
  }

  return snapshot;
}

function restoreSpecialLayers(snapshot) {
  if (!snapshot || !state.map) return;

  const timelineHighlight = state.timeline?.highlightLayer || null;
  if (snapshot.timelineHighlightVisible && timelineHighlight && !state.map.hasLayer(timelineHighlight)) {
    timelineHighlight.addTo(state.map);
  }

  const appHighlight = state.applicationTargetHighlightLayer;
  if (snapshot.applicationHighlightVisible && appHighlight && !state.map.hasLayer(appHighlight)) {
    appHighlight.addTo(state.map);
  }
}

function applyTransferLayerMode() {
  if (!state.mapLayers || !(state.mapLayers instanceof Map)) return;
  state.mapLayers.forEach((_, layerKey) => {
    setLayerVisibilityLocal(layerKey, TRANSFER_VISIBLE_LAYER_KEYS.has(layerKey));
  });
  refreshLayerPanelUi();
}

function restoreSavedLayerMode(savedVisibility) {
  if (!savedVisibility || !state.mapLayers || !(state.mapLayers instanceof Map)) return;
  state.mapLayers.forEach((_, layerKey) => {
    const desired = !!savedVisibility[layerKey];
    setLayerVisibilityLocal(layerKey, desired);
  });
  refreshLayerPanelUi();
}

function removeRouteLayer() {
  const trip = state.transferTrip;
  if (trip.routeLayer && state.map) {
    state.map.removeLayer(trip.routeLayer);
  }
  trip.routeLayer = null;
}

function drawStopMarkers() {
  const trip = state.transferTrip;
  if (!state.map) return;

  if (trip.startMarker) state.map.removeLayer(trip.startMarker);
  if (trip.endMarker) state.map.removeLayer(trip.endMarker);
  trip.startMarker = null;
  trip.endMarker = null;

  if (trip.startStop?.coordinates?.length >= 2) {
    trip.startMarker = L.circleMarker([trip.startStop.coordinates[1], trip.startStop.coordinates[0]], {
      radius: 9,
      fillColor: "#22c55e",
      color: "#ffffff",
      weight: 3,
      fillOpacity: 1
    })
      .bindTooltip(`Start: ${trip.startStop.name}`, { permanent: false })
      .addTo(state.map);
  }

  if (trip.endStop?.coordinates?.length >= 2) {
    trip.endMarker = L.circleMarker([trip.endStop.coordinates[1], trip.endStop.coordinates[0]], {
      radius: 9,
      fillColor: "#ef4444",
      color: "#ffffff",
      weight: 3,
      fillOpacity: 1
    })
      .bindTooltip(`End: ${trip.endStop.name}`, { permanent: false })
      .addTo(state.map);
  }
}

function clearTransferLayers() {
  removeRouteLayer();
  const trip = state.transferTrip;
  if (trip.startMarker && state.map) state.map.removeLayer(trip.startMarker);
  if (trip.endMarker && state.map) state.map.removeLayer(trip.endMarker);
  trip.startMarker = null;
  trip.endMarker = null;
}

function drawRouteOnMap(routeData) {
  if (!state.map || !routeData) return;
  const coords = routeData.geometry?.coordinates || [];
  if (!Array.isArray(coords) || coords.length < 2) {
    throw new Error("No valid KGE route geometry returned.");
  }

  removeRouteLayer();
  const latLngs = coords.map(([lng, lat]) => [lat, lng]);
  state.transferTrip.routeLayer = L.polyline(latLngs, ROUTE_STYLE).addTo(state.map);
  drawStopMarkers();

  const bounds = state.transferTrip.routeLayer.getBounds();
  if (bounds?.isValid()) {
    state.map.fitBounds(bounds, { padding: [40, 40] });
  }
}

function resetTransferStateData() {
  const trip = state.transferTrip;
  trip.step = 1;
  trip.startStop = null;
  trip.endStop = null;
  trip.routeResult = null;
  trip.routeError = "";
  trip.plannedDate = "";
  trip.plannedStartTime = "09:00";
  trip.plannedEndTime = "11:00";
  trip.tramNumber = "";
  trip.reason = "";
  trip.notes = "";
  trip.isSubmitting = false;
}

function showTransferUi() {
  dom.transferMapBanner?.classList.remove("is-hidden");
  dom.transferRoutePanel?.classList.remove("is-hidden");
}

function hideTransferUi() {
  dom.transferMapBanner?.classList.add("is-hidden");
  dom.transferRoutePanel?.classList.add("is-hidden");
}

function getStepRouteStatusText() {
  const trip = state.transferTrip;
  if (trip.routeError) return trip.routeError;
  if (!trip.startStop) return "Click a start tram stop.";
  if (!trip.endStop) return "Click an end tram stop.";
  if (!trip.routeResult) return "Calculating route...";
  return "Route ready - continue to details.";
}

function getBannerInstructionText() {
  const trip = state.transferTrip;
  if (trip.routeError) return trip.routeError;
  if (trip.step !== 1) return "Route ready - continue to details.";
  if (!trip.startStop) return "Click a start tram stop";
  if (!trip.endStop) return "Click an end tram stop";
  if (!trip.routeResult) return "Calculating route...";
  return "Route ready - continue to details";
}

function renderRouteStepBody() {
  const trip = state.transferTrip;
  const segmentCount = trip.routeResult?.segments?.length || 0;

  dom.transferPanelBody.innerHTML = `
    <div class="transfer-step-card">
      <h4 class="transfer-step-title">Route selection</h4>
      <p class="transfer-step-note">Select two tram stops directly on the map.</p>
      <p class="transfer-step-note">First click sets start, second click sets end and calculates the KGE route.</p>
      ${trip.routeResult ? `<p class="transfer-step-note"><strong>${segmentCount}</strong> rail segment${segmentCount === 1 ? "" : "s"} in route.</p>` : ""}
    </div>
  `;
}

function renderDetailsStepBody() {
  const trip = state.transferTrip;
  dom.transferPanelBody.innerHTML = `
    <div class="transfer-step-card">
      <h4 class="transfer-step-title">Trip details</h4>
      <div class="field">
        <label for="transferTramNumber">Tram number</label>
        <input id="transferTramNumber" type="text" placeholder="e.g. 2045" />
      </div>
      <div class="field">
        <label for="transferReason">Reason for transfer</label>
        <textarea id="transferReason" rows="3" placeholder="Reason for transfer"></textarea>
      </div>
      <div class="field">
        <label for="transferNotes">Additional notes</label>
        <textarea id="transferNotes" rows="2" placeholder="Optional"></textarea>
      </div>
    </div>
  `;

  const tramInput = document.getElementById("transferTramNumber");
  const reasonInput = document.getElementById("transferReason");
  const notesInput = document.getElementById("transferNotes");

  if (tramInput) {
    tramInput.value = trip.tramNumber || "";
    tramInput.addEventListener("input", (e) => {
      trip.tramNumber = e.target.value;
    });
  }

  if (reasonInput) {
    reasonInput.value = trip.reason || "";
    reasonInput.addEventListener("input", (e) => {
      trip.reason = e.target.value;
    });
  }

  if (notesInput) {
    notesInput.value = trip.notes || "";
    notesInput.addEventListener("input", (e) => {
      trip.notes = e.target.value;
    });
  }
}

function renderPlanningStepBody() {
  const trip = state.transferTrip;
  const minDate = new Date(Date.now() + 7 * 24 * 60 * 60 * 1000).toISOString().split("T")[0];

  dom.transferPanelBody.innerHTML = `
    <div class="transfer-step-card">
      <h4 class="transfer-step-title">Planning</h4>
      <p class="transfer-step-note">Planned date must be at least one week from today.</p>
      <div class="field">
        <label for="transferDate">Planned date</label>
        <input id="transferDate" type="date" min="${minDate}" required />
      </div>
      <div class="field-row">
        <div class="field">
          <label for="transferStartTime">Start time</label>
          <input id="transferStartTime" type="time" required />
        </div>
        <div class="field">
          <label for="transferEndTime">End time</label>
          <input id="transferEndTime" type="time" required />
        </div>
      </div>
    </div>
  `;

  const dateInput = document.getElementById("transferDate");
  const startTimeInput = document.getElementById("transferStartTime");
  const endTimeInput = document.getElementById("transferEndTime");

  if (dateInput) {
    dateInput.value = trip.plannedDate || "";
    dateInput.addEventListener("input", (e) => {
      trip.plannedDate = e.target.value;
    });
  }

  if (startTimeInput) {
    startTimeInput.value = trip.plannedStartTime || "09:00";
    startTimeInput.addEventListener("input", (e) => {
      trip.plannedStartTime = e.target.value;
    });
  }

  if (endTimeInput) {
    endTimeInput.value = trip.plannedEndTime || "11:00";
    endTimeInput.addEventListener("input", (e) => {
      trip.plannedEndTime = e.target.value;
    });
  }
}

function renderReviewStepBody() {
  const trip = state.transferTrip;
  const route = trip.routeResult;
  const routeDistance = route ? `${(route.distance_m / 1000).toFixed(2)} km` : "-";
  const routeSegments = route?.segments?.length || 0;

  dom.transferPanelBody.innerHTML = `
    <div class="transfer-step-card">
      <h4 class="transfer-step-title">Review</h4>
      <ul class="transfer-review-list">
        <li><strong>Route:</strong> ${esc(trip.startStop?.name || "-")} -> ${esc(trip.endStop?.name || "-")}</li>
        <li><strong>Distance:</strong> ${esc(routeDistance)} (${routeSegments} segment${routeSegments === 1 ? "" : "s"})</li>
        <li><strong>Date:</strong> ${esc(trip.plannedDate || "-")}</li>
        <li><strong>Time:</strong> ${esc(trip.plannedStartTime || "-")} - ${esc(trip.plannedEndTime || "-")}</li>
        <li><strong>Tram number:</strong> ${esc(trip.tramNumber || "-")}</li>
        <li><strong>Reason:</strong> ${esc(trip.reason || "-")}</li>
        <li><strong>Notes:</strong> ${esc(trip.notes || "-")}</li>
      </ul>
      <div id="transferResult" class="form-result" role="status" aria-live="polite"></div>
    </div>
  `;
}

function renderPanelBodyByStep() {
  if (!dom.transferPanelBody) return;

  const trip = state.transferTrip;
  if (trip.step === 1) {
    renderRouteStepBody();
    return;
  }
  if (trip.step === 2) {
    renderDetailsStepBody();
    return;
  }
  if (trip.step === 3) {
    renderPlanningStepBody();
    return;
  }
  renderReviewStepBody();
}

function updatePanelActions() {
  const trip = state.transferTrip;

  if (dom.transferBackBtn) {
    dom.transferBackBtn.classList.toggle("is-hidden", trip.step === 1);
  }

  if (dom.transferContinueBtn) {
    dom.transferContinueBtn.classList.toggle("is-hidden", trip.step === TOTAL_STEPS);
    dom.transferContinueBtn.textContent = trip.step === 1 ? "Continue" : "Next";
    dom.transferContinueBtn.disabled = trip.step === 1 ? !trip.routeResult : false;
  }

  if (dom.transferSubmitBtn) {
    dom.transferSubmitBtn.classList.toggle("is-hidden", trip.step !== TOTAL_STEPS);
    dom.transferSubmitBtn.disabled = !!trip.isSubmitting;
  }
}

function renderTransferUi() {
  if (!state.transferTrip.active) return;

  const trip = state.transferTrip;
  const routeDistance = trip.routeResult ? `${(trip.routeResult.distance_m / 1000).toFixed(2)} km` : "-";
  const statusText = getStepRouteStatusText();

  if (dom.transferMapInstruction) {
    dom.transferMapInstruction.textContent = getBannerInstructionText();
  }
  if (dom.transferStartLabel) dom.transferStartLabel.textContent = trip.startStop?.name || "-";
  if (dom.transferEndLabel) dom.transferEndLabel.textContent = trip.endStop?.name || "-";
  if (dom.transferDistanceLabel) dom.transferDistanceLabel.textContent = routeDistance;

  if (dom.transferRouteStatus) {
    dom.transferRouteStatus.textContent = statusText;
    dom.transferRouteStatus.classList.toggle("error", !!trip.routeError);
  }

  if (dom.transferPanelStepLabel) {
    dom.transferPanelStepLabel.textContent = STEP_LABELS[Math.max(0, trip.step - 1)] || "Route";
  }

  renderPanelBodyByStep();
  updatePanelActions();
}

function undoLastStopSelection() {
  const trip = state.transferTrip;
  routeRequestSeq += 1;

  if (trip.endStop) {
    trip.endStop = null;
    trip.routeResult = null;
    trip.routeError = "";
    removeRouteLayer();
    drawStopMarkers();
  } else if (trip.startStop) {
    trip.startStop = null;
    trip.routeResult = null;
    trip.routeError = "";
    clearTransferLayers();
  }

  if (trip.step > 1) trip.step = 1;
  renderTransferUi();
}

function resetTransferRouteSelection() {
  const trip = state.transferTrip;
  routeRequestSeq += 1;
  trip.startStop = null;
  trip.endStop = null;
  trip.routeResult = null;
  trip.routeError = "";
  if (trip.step > 1) trip.step = 1;
  clearTransferLayers();
  renderTransferUi();
}

function normalizeStopFromFeature(feature) {
  const props = feature?.properties || {};
  const geom = feature?.geometry || {};
  const coords = geom.coordinates || [];
  const id = feature?.id;

  if (id == null || !Array.isArray(coords) || coords.length < 2) return null;

  return {
    id,
    name: props.Naam || props.Label || `Stop ${id}`,
    coordinates: [coords[0], coords[1]]
  };
}

async function calculateTransferRoute() {
  const trip = state.transferTrip;
  if (!trip.startStop || !trip.endStop) return;
  const requestSeq = ++routeRequestSeq;

  trip.routeError = "";
  trip.routeResult = null;
  removeRouteLayer();
  drawStopMarkers();
  renderTransferUi();

  try {
    const response = await postJSON("/api/transfer/route", {
      start_stop_id: trip.startStop.id,
      end_stop_id: trip.endStop.id
    });
    if (!trip.active || requestSeq !== routeRequestSeq) return;

    const route = response?.route || null;
    if (!route?.geometry?.coordinates || route.geometry.coordinates.length < 2) {
      throw new Error("No valid route geometry returned.");
    }

    trip.routeResult = route;
    trip.routeError = "";
    drawRouteOnMap(route);
    renderTransferUi();
  } catch (err) {
    if (!trip.active || requestSeq !== routeRequestSeq) return;
    trip.routeResult = null;
    trip.routeError = err?.detail || err?.message || "Route calculation failed.";
    removeRouteLayer();
    drawStopMarkers();
    renderTransferUi();
    toast(trip.routeError, "error");
  }
}

function validateCurrentStep() {
  const trip = state.transferTrip;
  if (trip.step === 1) {
    if (!trip.startStop || !trip.endStop || !trip.routeResult) {
      toast("Please select a valid start/end stop pair first.", "error");
      return false;
    }
    return true;
  }

  if (trip.step === 3) {
    if (!trip.plannedDate) {
      toast("Please select a planned date.", "error");
      return false;
    }
    if (!trip.plannedStartTime || !trip.plannedEndTime) {
      toast("Please set planned start and end times.", "error");
      return false;
    }
  }

  return true;
}

function goToNextStep() {
  const trip = state.transferTrip;
  if (!validateCurrentStep()) return;
  if (trip.step < TOTAL_STEPS) {
    trip.step += 1;
    renderTransferUi();
  }
}

function goToPreviousStep() {
  const trip = state.transferTrip;
  if (trip.step > 1) {
    trip.step -= 1;
    renderTransferUi();
  }
}

async function submitTransferTrip() {
  const trip = state.transferTrip;
  if (trip.isSubmitting) return;

  if (!trip.startStop || !trip.endStop || !trip.routeResult) {
    toast("Route is not ready.", "error");
    return;
  }

  if (!trip.plannedDate || !trip.plannedStartTime || !trip.plannedEndTime) {
    toast("Please complete planning details before submitting.", "error");
    return;
  }

  trip.isSubmitting = true;
  renderTransferUi();

  const resultEl = document.getElementById("transferResult");
  if (resultEl) resultEl.innerHTML = "<p class=\"hint\">Submitting...</p>";

  try {
    const result = await postJSON("/api/transfer/apply", {
      start_stop_id: trip.startStop.id,
      end_stop_id: trip.endStop.id,
      planned_date: trip.plannedDate,
      planned_start_time: trip.plannedStartTime,
      planned_end_time: trip.plannedEndTime,
      tram_number: trip.tramNumber,
      reason: trip.reason,
      notes: trip.notes
    });

    const reference = result.transfer_trip_id ? String(result.transfer_trip_id).slice(0, 8) : "";
    if (resultEl) {
      resultEl.innerHTML = `<p><strong>Transfer trip submitted.</strong> ${reference ? `Reference: <code>${esc(reference)}...</code>` : ""}</p>`;
    }
    toast("Transfer trip submitted successfully.", "success");

    setTimeout(() => {
      exitTransferMode();
    }, 1800);
  } catch (err) {
    const msg = err?.detail || "Submission failed.";
    if (resultEl) resultEl.innerHTML = `<p class="error">${esc(msg)}</p>`;
    toast(msg, "error");
  } finally {
    trip.isSubmitting = false;
    renderTransferUi();
  }
}

export function enterTransferMode() {
  if (!state.currentUser) {
    toast("Please log in first.", "error");
    return;
  }

  const trip = state.transferTrip;

  if (!trip.active) {
    trip.savedLayerVisibility = { ...(state.mapLayerVisibility || {}) };
    trip.savedSpecialLayerState = captureAndHideSpecialLayers();
  }

  trip.active = true;
  resetTransferStateData();
  clearTransferLayers();
  applyTransferLayerMode();
  setTransferCursor(true);
  showTransferUi();
  renderTransferUi();
}

export function exitTransferMode() {
  const trip = state.transferTrip;
  routeRequestSeq += 1;
  trip.active = false;
  clearTransferLayers();
  hideTransferUi();
  setTransferCursor(false);

  restoreSavedLayerMode(trip.savedLayerVisibility);
  restoreSpecialLayers(trip.savedSpecialLayerState);
  trip.savedLayerVisibility = null;
  trip.savedSpecialLayerState = null;

  resetTransferStateData();
}

export function handleTransferStopClick(feature, event = null) {
  const trip = state.transferTrip;
  if (!trip.active) return false;
  stopLeafletEvent(event);

  if (trip.step !== 1) {
    toast("Use Back to return to route selection before changing stops.", "info");
    return true;
  }

  const stop = normalizeStopFromFeature(feature);
  if (!stop) return true;

  if (!trip.startStop) {
    routeRequestSeq += 1;
    trip.startStop = stop;
    trip.endStop = null;
    trip.routeResult = null;
    trip.routeError = "";
    removeRouteLayer();
    drawStopMarkers();
    renderTransferUi();
    return true;
  }

  if (!trip.endStop) {
    if (stop.id === trip.startStop.id) {
      trip.routeError = "End stop must be different from start stop.";
      renderTransferUi();
      toast(trip.routeError, "error");
      return true;
    }
    trip.endStop = stop;
    calculateTransferRoute();
    return true;
  }

  if (stop.id === trip.startStop.id) {
    trip.routeError = "End stop must be different from start stop.";
    renderTransferUi();
    toast(trip.routeError, "error");
    return true;
  }

  // Third click replaces the end stop and recalculates.
  trip.endStop = stop;
  calculateTransferRoute();
  return true;
}

export function handleHalteClickForTransfer(feature, event = null) {
  return handleTransferStopClick(feature, event);
}

export function showTransferTripOnMap(trip) {
  clearTransferLayers();
  if (!state.map || !trip?.route_geometry) return;

  const coords = trip.route_geometry.coordinates || [];
  if (!Array.isArray(coords) || coords.length < 2) return;

  const latLngs = coords.map(([lng, lat]) => [lat, lng]);
  state.transferTrip.routeLayer = L.polyline(latLngs, ROUTE_STYLE).addTo(state.map);

  const bounds = state.transferTrip.routeLayer.getBounds();
  if (bounds?.isValid()) {
    state.map.fitBounds(bounds, { padding: [40, 40] });
  }

  setTimeout(() => {
    removeRouteLayer();
  }, 10000);
}

export function initTransfer() {
  if (dom.timelineTransferBtn) {
    dom.timelineTransferBtn.addEventListener("click", () => {
      enterTransferMode();
    });
  }

  if (dom.transferTripBtn) {
    dom.transferTripBtn.addEventListener("click", () => {
      enterTransferMode();
    });
  }

  dom.transferUndoBtn?.addEventListener("click", undoLastStopSelection);
  dom.transferResetBtn?.addEventListener("click", resetTransferRouteSelection);
  dom.transferCloseModeBtn?.addEventListener("click", exitTransferMode);

  dom.transferBackBtn?.addEventListener("click", goToPreviousStep);
  dom.transferContinueBtn?.addEventListener("click", goToNextStep);
  dom.transferSubmitBtn?.addEventListener("click", submitTransferTrip);

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && state.transferTrip.active) {
      exitTransferMode();
    }
  });
}

// Reuse existing endpoint contract to keep transfer list compatible.
export async function getMyTransferTrips() {
  return getJSON("/api/my_transfer_trips");
}
