import { state } from "../state.js";
import { dom } from "../dom.js";
import { showToast, esc, getJSON } from "../utils.js";
import { t } from "../i18n.js";
import { openModal, closeModal } from "../modals.js";
import { openLogin } from "../auth.js";
import {
  normalizeTargetType,
  getTargetTypeLabel,
  getTargetReviewLabel,
  getTargetSubtitle,
  uniqueTruthy,
  renderSegmentCardsStep1,
} from "./apply-map.js";
import {
  ensureSegmentSchedules,
  syncSegmentProjectRange,
  normalizeScheduleWindow,
  DEFAULT_SCHEDULE_LABEL,
  MAX_SCHEDULE_WINDOWS,
  renderTimeCardsStep3,
} from "./apply-scheduler.js";
import {
  ensurePeopleBySegmentLength,
  renderPersonModeStep4,
  collectStep4Data,
} from "./apply-people.js";
import {
  WORK_SOURCES,
  URGENCY_OPTIONS,
  validateCurrentStep,
} from "./apply-validate.js";

export const APPLY_TOTAL_STEPS = 5;

export const TRAM_LINE_COLORS = Object.freeze({
  "1": "#E53935",
  "2": "#FDD835",
  "4": "#1565C0",
  "5": "#00838F",
  "7": "#43A047",
  "12": "#9C27B0",
  "13": "#6A1B9A",
  "14": "#FB8C00",
  "17": "#00695C",
  "19": "#AD1457",
  "24": "#F4511E",
  "25": "#558B2F",
  "26": "#0277BD",
});
export const TRAM_LINE_IDS = Object.freeze(["1", "2", "4", "5", "7", "12", "13", "14", "17", "19", "24", "25", "26"]);

let reviewRenderRequestToken = 0;

export function parseAffectedLines(value) {
  return String(value || "")
    .split(",")
    .map((x) => x.trim())
    .filter(Boolean);
}

export function getAffectedLineList() {
  const raw = state.applyWizard?.workDetails?.affectedLines || "";
  const set = new Set(parseAffectedLines(raw).filter((id) => TRAM_LINE_IDS.includes(id)));
  return TRAM_LINE_IDS.filter((id) => set.has(id));
}

export function setAffectedLineList(nextList) {
  const normalized = TRAM_LINE_IDS.filter((id) => new Set(nextList).has(id));
  state.applyWizard.workDetails.affectedLines = normalized.join(",");
}

export function toggleAffectedLine(lineId) {
  if (!TRAM_LINE_IDS.includes(lineId)) return;

  const current = getAffectedLineList();
  const next = current.includes(lineId)
    ? current.filter((x) => x !== lineId)
    : [...current, lineId];

  setAffectedLineList(next);
  renderWorkDetailsStep2();
}

export function renderTramLineChipsHtml(lineIds, selectedSet, options = {}) {
  const readonly = !!options.readonly;
  return lineIds.map((lineId) => {
    const color = TRAM_LINE_COLORS[lineId] || "#0863b5";
    const selected = selectedSet.has(lineId);
    const yellowClass = lineId === "2" ? " is-yellow" : "";
    const selectedClass = selected ? " is-selected" : "";
    const readonlyClass = readonly ? " is-readonly" : "";
    const tag = readonly ? "span" : "button";
    const typeAttr = readonly ? "" : " type=\"button\"";
    const dataAttr = readonly ? "" : ` data-line-id="${esc(lineId)}"`;
    return `
      <${tag}${typeAttr}${dataAttr} class="tram-line-chip${selectedClass}${yellowClass}${readonlyClass}" style="--line-color:${esc(color)};">
        ${esc(lineId)}
      </${tag}>
    `;
  }).join("");
}

export function defaultWorkDetails() {
  return {
    description: "",
    source: "Civielwerk",
    urgency: "normal",
    affectedLines: "",
    notes: "",
  };
}

function stepSections() {
  return [dom.applyStep1, dom.applyStep2, dom.applyStep3, dom.applyStep4, dom.applyStep5].filter(Boolean);
}

function resetApplySubmissionState() {
  state.applySubmission.isSubmitting = false;
  state.applySubmission.successModal.open = false;
  state.applySubmission.successModal.applicationId = null;
}

function hideApplyAlert() {
  if (!dom.applyResult) return;
  dom.applyResult.textContent = "";
  dom.applyResult.className = "form-result apply-wizard-alert is-hidden";
}

function showApplyAlert(message, type = "info", options = {}) {
  if (!dom.applyResult) return;

  const nextType = ["error", "success", "warning", "info"].includes(type) ? type : "info";
  dom.applyResult.textContent = String(message || "");
  dom.applyResult.className = `form-result apply-wizard-alert ${nextType}`;

  if (options.scroll === false) return;

  requestAnimationFrame(() => {
    dom.applyResult.scrollIntoView({ behavior: "smooth", block: "nearest" });
    if (typeof dom.applyResult.focus === "function") {
      dom.applyResult.focus({ preventScroll: true });
    }
  });
}

function syncApplySubmitUi() {
  const isSubmitting = !!state.applySubmission.isSubmitting;

  if (dom.applySubmitBtn) {
    dom.applySubmitBtn.disabled = isSubmitting;
    dom.applySubmitBtn.textContent = isSubmitting ? "Submitting..." : "Submit application";
  }
  if (dom.applyNextBtn) {
    dom.applyNextBtn.disabled = isSubmitting;
  }
  if (dom.applyBackBtn) {
    dom.applyBackBtn.disabled = isSubmitting || state.applyWizard.step === 1;
  }
  if (dom.applyCancelBtn) {
    dom.applyCancelBtn.disabled = isSubmitting;
  }
  if (dom.applyCloseBtn) {
    dom.applyCloseBtn.disabled = isSubmitting;
  }
}

function openApplySuccessModal(applicationId) {
  state.applySubmission.successModal.open = true;
  state.applySubmission.successModal.applicationId = applicationId || null;

  if (dom.applySuccessReference) {
    dom.applySuccessReference.textContent = applicationId || "-";
  }

  openModal(dom.applySuccessModal);
}

function closeApplySuccessModal(options = {}) {
  const resetWizard = options.resetWizard !== false;
  const closeApplyWizard = options.closeApplyWizard !== false;

  state.applySubmission.successModal.open = false;
  closeModal(dom.applySuccessModal);

  if (resetWizard) {
    resetApplyFormUiAfterSuccess();
    hideApplyAlert();
    syncWizardUI();
  }

  if (closeApplyWizard) {
    closeModal(dom.applyModal);
  }
}

function resetApplyWizard() {
  state.applyWizard = {
    step: 1,
    personMode: "single",
    segments: [],
    sharedPerson: {
      firstName: "",
      lastName: "",
      phone: "",
      email: state.currentUser?.email || "",
      employeeId: "",
    },
    peopleBySegment: [],
    workDetails: defaultWorkDetails(),
    contactDetails: {
      coordinator: "",
      contactName: "",
      contactPhone: "",
      contactEmail: "",
      vvwMeasure: "BB",
    },
  };

  state.segmentPreviews = [];
  state.schedulerBySegment = [];
  resetApplySubmissionState();
  hideApplyAlert();
  if (dom.applyContextText) dom.applyContextText.textContent = "";
}

export function syncWizardUI() {
  const step = state.applyWizard.step;
  const sections = stepSections();

  sections.forEach((el, idx) => {
    el.classList.toggle("is-hidden", idx !== step - 1);
  });

  if (dom.applyStepLabel) {
    dom.applyStepLabel.textContent = `Step ${step} of ${APPLY_TOTAL_STEPS}`;
  }

  if (dom.wizardProgressBar) {
    dom.wizardProgressBar.style.width = `${(step / APPLY_TOTAL_STEPS) * 100}%`;
  }

  if (dom.applyBackBtn) {
    dom.applyBackBtn.disabled = step === 1 || state.applySubmission.isSubmitting;
  }

  if (dom.applyNextBtn) {
    dom.applyNextBtn.classList.toggle("is-hidden", step === APPLY_TOTAL_STEPS);
  }

  if (dom.applySubmitBtn) {
    dom.applySubmitBtn.classList.toggle("is-hidden", step !== APPLY_TOTAL_STEPS);
  }

  if (step === 1) renderSegmentCardsStep1();
  if (step === 2) renderWorkDetailsStep2();
  if (step === 3) renderTimeCardsStep3();
  if (step === 4) renderPersonModeStep4();
  if (step === 5) renderReviewStep5();
  syncApplySubmitUi();
}

function normalizeStatus(status) {
  const s = String(status || "submitted").toLowerCase();
  return ["submitted", "approved", "rejected"].includes(s) ? s : "submitted";
}

function prettyStatus(status) {
  const s = normalizeStatus(status);
  return s.charAt(0).toUpperCase() + s.slice(1);
}

export async function openMyApplications() {
  if (!state.currentUser) {
    showToast({
      title: t("login_required_title"),
      message: t("login_required_msg"),
      actionText: t("login_action"),
      onAction: () => openLogin(),
      durationMs: 5000
    });
    return;
  }

  openModal(dom.appsModal);

  if (dom.appsLoading) dom.appsLoading.classList.remove("is-hidden");
  if (dom.appsEmpty) dom.appsEmpty.classList.add("is-hidden");
  if (dom.appsList) dom.appsList.innerHTML = "";

  try {
    const [resApps, resTransfers] = await Promise.all([
      fetch("/api/my_applications").catch(() => null),
      fetch("/api/my_transfer_trips").catch(() => null)
    ]);

    let apps = [];
    if (resApps && resApps.ok) {
      const data = await resApps.json().catch(() => ({}));
      apps = apps.concat((data.applications || []).map(a => ({ ...a, _type: 'work' })));
    }

    if (resTransfers && resTransfers.ok) {
      const data = await resTransfers.json().catch(() => ({}));
      apps = apps.concat((data.transfer_trips || []).map(t => ({ ...t, _type: 'transfer' })));
    }

    // Sort combined apps by submission date descending
    apps.sort((a, b) => {
      const timeA = new Date(a.submitted_at || 0).getTime();
      const timeB = new Date(b.submitted_at || 0).getTime();
      return timeB - timeA;
    });

    if (dom.appsLoading) dom.appsLoading.classList.add("is-hidden");

    if (!apps.length) {
      if (dom.appsEmpty) dom.appsEmpty.classList.remove("is-hidden");
      return;
    }

    if (dom.appsEmpty) dom.appsEmpty.classList.add("is-hidden");

    for (const a of apps) {
      const targets = Array.isArray(a.targets) ? a.targets : [];
      const uploads = Array.isArray(a.uploads) ? a.uploads : [];
      const work = a.work_details || {};
      const contact = a.contact_details || {};
      const submitted = a.submitted_at ? new Date(a.submitted_at).toLocaleString() : "-";
      const status = normalizeStatus(a.status);

      const decisionMessageHtml = a.decision_message
        ? `
          <div class="app-decision-message">
            <strong>Message:</strong> ${esc(a.decision_message)}
          </div>
        `
        : "";

      const li = document.createElement("li");
      li.className = "app-item app-item-rich my-application-card";
      li.tabIndex = 0;
      li.setAttribute("role", "button");

      if (a._type === 'transfer') {
        const distance = a.route_geometry?.distance_m
          ? (a.route_geometry.distance_m / 1000).toFixed(2) + " km"
          : "Unknown";

        li.setAttribute("aria-label", `Show transfer trip ${a.transfer_trip_id || ""} on map`);
        li.innerHTML = `
          <div class="app-item-head">
            <div>
              <p class="app-title">🚊 Transfer Trip ${esc((a.transfer_trip_id || "").slice(0,8))}</p>
              <p class="app-meta">Submitted: ${esc(submitted)}</p>
            </div>
            <span class="app-status-badge status-${status}">${esc(prettyStatus(status))}</span>
          </div>
          <div class="app-item-body">
            <p><strong>Date:</strong> ${esc(a.planned_date || "—")} (${esc(a.planned_start_time || "")} - ${esc(a.planned_end_time || "")})</p>
            <p><strong>Tram:</strong> ${esc(a.tram_number || "—")}</p>
            <p><strong>Distance:</strong> ${distance}</p>
          </div>
          ${decisionMessageHtml}
        `;

        li.addEventListener("click", async () => {
          const modal = dom.appsModal;
          if (modal) {
            modal.classList.remove("is-open");
            modal.setAttribute("aria-hidden", "true");
          }
          // Import showTransferTripOnMap dynamically
          const { showTransferTripOnMap } = await import("../transfer.js");
          showTransferTripOnMap(a);
        });
      } else {
        li.setAttribute("aria-label", `Show application ${a.application_id || ""} on map`);
        li.innerHTML = `
          <div class="app-item-head">
            <div>
              <p class="app-title">Application ${esc(a.application_id || "")}</p>
              <p class="app-meta">Submitted: ${esc(submitted)}</p>
            </div>
            <span class="app-status-badge status-${status}">${esc(prettyStatus(status))}</span>
          </div>
          <div class="app-item-body">
            <p><strong>Work:</strong> ${esc(work.description || "—")}</p>
            <p><strong>Status:</strong> ${esc(prettyStatus(status))}</p>
          </div>
          ${decisionMessageHtml}
        `;

        li.addEventListener("click", () => {
          const modal = dom.appsModal;
          if (modal) {
            modal.classList.remove("is-open");
            modal.setAttribute("aria-hidden", "true");
          }
          showApplicationOnMap(a);
        });
      }

      li.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          li.click();
        }
      });

      li.addEventListener("keydown", async (event) => {
        if (event.key !== "Enter" && event.key !== " ") return;
        event.preventDefault();
        await showOnMap();
      });

      li.querySelectorAll("a, button").forEach((el) => {
        if (el.classList.contains("app-show-map-btn")) {
          el.addEventListener("click", async (event) => {
            event.preventDefault();
            event.stopPropagation();
            await showOnMap();
          });
          return;
        }

        el.addEventListener("click", (event) => {
          event.stopPropagation();
        });
      });

      dom.appsList.appendChild(li);
    }
  } catch (err) {
    if (dom.appsLoading) dom.appsLoading.classList.add("is-hidden");
    if (dom.appsEmpty) {
      dom.appsEmpty.classList.remove("is-hidden");
      dom.appsEmpty.textContent = `Error: ${err.message}`;
    }
  }
}

export function openApplyForSegments(segments) {
  resetApplyWizard();

  state.applyWizard.segments = segments.map(seg => ({
    targetType: normalizeTargetType(seg.target_type),
    assetId: String(seg.asset_id || seg.segment_id || "").trim(),
    assetLabel: seg.asset_label || getTargetReviewLabel(seg),
    assetSource: seg.asset_source || (normalizeTargetType(seg.target_type) === "overhead_section" ? "BOVENLEIDING_DATA" : "SPOOR_DATA"),
    segmentId: String(seg.segment_id || "").trim(),
    lineId: String(seg.line_id || "").trim(),
    lineName: seg.line_name || "",
    geometry: Array.isArray(seg.geometry) ? seg.geometry : [],
    workMode: "whole-segment",
    workStartPoint: null,
    workEndPoint: null,
    planningAnchorDate: "",
    projectStart: "",
    projectEnd: "",
    schedules: [],
  }));

  state.applyWizard.workDetails.affectedLines = uniqueTruthy(
    state.applyWizard.segments.map(seg => seg.lineId)
  ).join(", ");

  ensurePeopleBySegmentLength();

  if (dom.contextSegmentId) {
    dom.contextSegmentId.value = state.applyWizard.segments.map(s => s.segmentId).join(",");
  }
  if (dom.contextLineIds) {
    dom.contextLineIds.value = state.applyWizard.segments.map(s => s.lineId).join(",");
  }
  if (dom.contextLineNames) {
    dom.contextLineNames.value = state.applyWizard.segments.map(s => s.lineName).join(",");
  }

  if (dom.applyContextText) {
    dom.applyContextText.textContent =
      `Applying for ${segments.length} target${segments.length > 1 ? "s" : ""}.`;
  }

  syncWizardUI();
  openModal(dom.applyModal);
}

function renderWorkDetailsStep2() {
  const host = dom.workDetailsStep2;
  if (!host) return;

  const details = {
    ...defaultWorkDetails(),
    ...(state.applyWizard.workDetails || {}),
  };
  state.applyWizard.workDetails = details;
  const selectedLines = new Set(getAffectedLineList());

  host.innerHTML = `
    <div class="review-card wizard-card-compact">
      <div class="field">
        <label for="workDescription">Work description / project description *</label>
        <textarea id="workDescription" rows="4" placeholder="Describe the planned work and project scope.">${esc(details.description)}</textarea>
      </div>

      <div class="form-grid">
        <div class="field">
          <label for="workSource">Work source / type *</label>
          <select id="workSource">
            ${WORK_SOURCES.map(source => `
              <option value="${esc(source)}" ${details.source === source ? "selected" : ""}>${esc(source)}</option>
            `).join("")}
          </select>
        </div>

        <div class="field">
          <label>Urgency *</label>
          <div class="urgency-picker" id="workUrgencyOptions">
            ${URGENCY_OPTIONS.map(option => `
              <button
                type="button"
                class="urgency-option ${details.urgency === option.value ? "is-selected" : ""}"
                data-urgency="${esc(option.value)}"
              >${esc(option.label)}</button>
            `).join("")}
          </div>
        </div>
      </div>

      <div class="field">
        <label>Expected affected tram lines</label>
        <div class="tram-line-picker" id="affectedLinePicker">
          ${renderTramLineChipsHtml(TRAM_LINE_IDS, selectedLines)}
        </div>
      </div>

      <div class="field">
        <label for="workNotes">Notes / special conditions</label>
        <textarea id="workNotes" rows="3" placeholder="Risks, dependencies, access notes, or other conditions.">${esc(details.notes)}</textarea>
      </div>
    </div>
  `;

  document.getElementById("workDescription")?.addEventListener("input", (e) => {
    state.applyWizard.workDetails.description = e.target.value;
  });
  document.getElementById("workSource")?.addEventListener("change", (e) => {
    state.applyWizard.workDetails.source = e.target.value;
  });
  document.getElementById("workNotes")?.addEventListener("input", (e) => {
    state.applyWizard.workDetails.notes = e.target.value;
  });

  document.querySelectorAll("#affectedLinePicker [data-line-id]").forEach((btn) => {
    btn.addEventListener("click", () => {
      toggleAffectedLine(btn.dataset.lineId || "");
    });
  });

  document.querySelectorAll("[data-urgency]").forEach((btn) => {
    btn.addEventListener("click", () => {
      state.applyWizard.workDetails.urgency = btn.dataset.urgency || "normal";
      renderWorkDetailsStep2();
    });
  });
}

export function collectWorkDetailsStep2() {
  const selectedLines = getAffectedLineList();
  state.applyWizard.workDetails = {
    ...defaultWorkDetails(),
    description: document.getElementById("workDescription")?.value.trim() || state.applyWizard.workDetails?.description?.trim() || "",
    source: document.getElementById("workSource")?.value.trim() || state.applyWizard.workDetails?.source || "Civielwerk",
    urgency: state.applyWizard.workDetails?.urgency || "normal",
    affectedLines: selectedLines.join(","),
    notes: document.getElementById("workNotes")?.value.trim() || state.applyWizard.workDetails?.notes?.trim() || "",
  };
}

function formatDisplayDateTime(value) {
  if (!value) return "-";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;

  return d.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatWorkModeLabel(mode) {
  if (mode === "whole-segment") return "Whole target";
  if (mode === "custom-area") return "Custom area";
  return mode || "-";
}

function formatPin(point) {
  if (!point) return "-";
  return `${point.x}, ${point.y}`;
}

async function fetchWiorConflictsForTargets(targets) {
  const response = await fetch("/api/wior/conflicts/check", {
    method: "POST",
    credentials: "same-origin",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ targets }),
  });

  const data = await response.json().catch(() => ({}));

  if (!response.ok) {
    throw new Error(data?.detail || `Failed to check WIOR conflicts (${response.status})`);
  }

  return data;
}

function renderWiorConflictWarning(conflicts) {
  const list = Array.isArray(conflicts) ? conflicts : [];
  if (!list.length) return "";

  const itemsHtml = list.map((conflict) => {
    const projectId = conflict?.project_code || conflict?.wior_id || "-";
    const projectName = conflict?.project_name || "-";
    const segmentId = conflict?.matched_segment_id || "-";
    const startDate = conflict?.start_date || "-";
    const endDate = conflict?.end_date || "-";
    const scheduleStart = conflict?.project_start || "-";
    const scheduleEnd = conflict?.project_end || "-";
    const targetIndex = Number.isInteger(conflict?.target_index) ? conflict.target_index + 1 : "-";
    const scheduleIndex = Number.isInteger(conflict?.schedule_index) ? conflict.schedule_index + 1 : "-";
    const scheduleLabel = conflict?.schedule_label || DEFAULT_SCHEDULE_LABEL;

    return `
      <li class="wior-conflict-item">
        <div><strong>${esc(projectId)}</strong> ${projectName ? ` - ${esc(projectName)}` : ""}</div>
        <div>Segment: ${esc(segmentId)}</div>
        <div>Target/window: ${esc(String(targetIndex))} / ${esc(String(scheduleIndex))} (${esc(scheduleLabel)})</div>
        <div>Planned window: ${esc(scheduleStart)} to ${esc(scheduleEnd)}</div>
        <div>Dates: ${esc(startDate)} to ${esc(endDate)}</div>
      </li>
    `;
  }).join("");

  return `
    <div class="wior-conflict-warning">
      <div class="wior-conflict-warning-title">WIOR conflict warning</div>
      <div class="wior-conflict-warning-text">
        One or more selected work areas overlap with external public-space works.
        You can still submit this application.
      </div>
      <ul class="wior-conflict-list">
        ${itemsHtml}
      </ul>
    </div>
  `;
}

async function renderReviewStep5() {
  if (!dom.applyReviewBox) return;

  collectWorkDetailsStep2();
  collectStep4Data();

  const work = {
    ...defaultWorkDetails(),
    ...(state.applyWizard.workDetails || {}),
  };
  const affectedLinesSet = new Set(parseAffectedLines(work.affectedLines).filter((lineId) => TRAM_LINE_IDS.includes(lineId)));
  const affectedLinesInOrder = TRAM_LINE_IDS.filter((lineId) => affectedLinesSet.has(lineId));
  const affectedLinesReviewHtml = affectedLinesSet.size
    ? `
      <div class="tram-line-picker tram-line-picker-review">
        ${renderTramLineChipsHtml(affectedLinesInOrder, affectedLinesSet, { readonly: true })}
      </div>
    `
    : `<span class="review-value">-</span>`;
  const contact = {
    coordinator: "",
    contactName: "",
    contactPhone: "",
    contactEmail: "",
    vvwMeasure: "BB",
    ...(state.applyWizard.contactDetails || {}),
  };

  const segmentHtml = state.applyWizard.segments.map((seg, index) => `
    <div class="review-card review-card-segment">
      <div class="review-card-headline">
        <h4>Target ${index + 1}</h4>
        <span class="review-badge">${esc(getTargetTypeLabel(seg))}</span>
      </div>

      <p class="review-strong">
        ${esc(getTargetReviewLabel(seg))}
      </p>
      <p class="hint">${esc(getTargetSubtitle(seg))}</p>

      <div class="review-schedule-block">
        <div class="review-label">Schedule windows</div>
        <ol class="review-schedule-list">
          ${
            ensureSegmentSchedules(seg).map((windowItem, scheduleIndex) => `
              <li>
                <strong>${esc(windowItem.label || DEFAULT_SCHEDULE_LABEL)}</strong>:
                ${esc(formatDisplayDateTime(windowItem.project_start))} to ${esc(formatDisplayDateTime(windowItem.project_end))}
                <span class="review-schedule-index">(${scheduleIndex + 1})</span>
              </li>
            `).join("")
          }
        </ol>
      </div>

      <div class="review-fields">
        <div class="review-field">
          <span class="review-label">Work mode</span>
          <span class="review-value">${esc(formatWorkModeLabel(seg.workMode))}</span>
        </div>

        <div class="review-field">
          <span class="review-label">Start pin</span>
          <span class="review-value">${esc(formatPin(seg.workStartPoint))}</span>
        </div>

        <div class="review-field">
          <span class="review-label">End pin</span>
          <span class="review-value">${esc(formatPin(seg.workEndPoint))}</span>
        </div>

      </div>
    </div>
  `).join("");

  const workHtml = `
    <div class="review-card review-card-work">
      <div class="review-card-headline">
        <h4>Work details</h4>
        <span class="review-badge">${esc(work.source || "-")}</span>
      </div>

      <div class="review-fields">
        <div class="review-field">
          <span class="review-label">Description</span>
          <span class="review-value">${esc(work.description || "-")}</span>
        </div>
        <div class="review-field">
          <span class="review-label">Urgency</span>
          <span class="review-value">${esc(work.urgency || "-")}</span>
        </div>
        <div class="review-field">
          <span class="review-label">Expected affected lines</span>
          ${affectedLinesReviewHtml}
        </div>
        <div class="review-field">
          <span class="review-label">Notes / special conditions</span>
          <span class="review-value">${esc(work.notes || "-")}</span>
        </div>
      </div>
    </div>
  `;

  let peopleHtml = "";

  if (state.applyWizard.personMode === "single") {
    const p = state.applyWizard.sharedPerson;
    peopleHtml = `
      <div class="review-card review-card-person">
        <div class="review-card-headline">
          <h4>Shared person</h4>
          <span class="review-badge">1 person</span>
        </div>

        <div class="review-fields">
          <div class="review-field">
            <span class="review-label">Full name</span>
            <span class="review-value">${esc(`${p.firstName || ""} ${p.lastName || ""}`.trim() || "-")}</span>
          </div>

          <div class="review-field">
            <span class="review-label">Phone</span>
            <span class="review-value">${esc(p.phone || "-")}</span>
          </div>

          <div class="review-field">
            <span class="review-label">Email</span>
            <span class="review-value">${esc(p.email || "-")}</span>
          </div>

          <div class="review-field">
            <span class="review-label">Employee ID</span>
            <span class="review-value">${esc(p.employeeId || "-")}</span>
          </div>
        </div>
      </div>
    `;
  } else {
    peopleHtml = state.applyWizard.peopleBySegment.map((p, index) => `
      <div class="review-card review-card-person">
        <div class="review-card-headline">
          <h4>Person for target ${index + 1}</h4>
          <span class="review-badge">${index + 1}</span>
        </div>

        <div class="review-fields">
          <div class="review-field">
            <span class="review-label">Full name</span>
            <span class="review-value">${esc(`${p.firstName || ""} ${p.lastName || ""}`.trim() || "-")}</span>
          </div>

          <div class="review-field">
            <span class="review-label">Phone</span>
            <span class="review-value">${esc(p.phone || "-")}</span>
          </div>

          <div class="review-field">
            <span class="review-label">Email</span>
            <span class="review-value">${esc(p.email || "-")}</span>
          </div>

          <div class="review-field">
            <span class="review-label">Employee ID</span>
            <span class="review-value">${esc(p.employeeId || "-")}</span>
          </div>
        </div>
      </div>
    `).join("");
  }

  const files = Array.from(document.getElementById("safetyPlans")?.files || []);

  const filesHtml = `
    <div class="review-card review-card-files">
      <div class="review-card-headline">
        <h4>Safety plans</h4>
        <span class="review-badge">${files.length} file${files.length === 1 ? "" : "s"}</span>
      </div>

      ${
        files.length
          ? `
            <div class="review-file-list">
              ${files.map(file => `
                <div class="review-file-item">
                  <span class="review-file-name">${esc(file.name)}</span>
                  <span class="review-file-size">${Math.round(file.size / 1024)} KB</span>
                </div>
              `).join("")}
            </div>
          `
          : `<p class="hint">No files selected.</p>`
      }
    </div>
  `;

  const contactHtml = `
    <div class="review-card review-card-contact">
      <div class="review-card-headline">
        <h4>Contact &amp; VVW</h4>
        <span class="review-badge">${esc(contact.vvwMeasure || "-")}</span>
      </div>

      <div class="review-fields">
        <div class="review-field">
          <span class="review-label">Department / team / coordinator</span>
          <span class="review-value">${esc(contact.coordinator || "-")}</span>
        </div>
        <div class="review-field">
          <span class="review-label">Contact name</span>
          <span class="review-value">${esc(contact.contactName || "-")}</span>
        </div>
        <div class="review-field">
          <span class="review-label">Contact phone</span>
          <span class="review-value">${esc(contact.contactPhone || "-")}</span>
        </div>
        <div class="review-field">
          <span class="review-label">Contact email</span>
          <span class="review-value">${esc(contact.contactEmail || "-")}</span>
        </div>
      </div>
    </div>
  `;

  dom.applyReviewBox.innerHTML = `
    <div class="review-grid">
      ${segmentHtml}
      ${workHtml}
      ${peopleHtml}
      ${contactHtml}
      ${filesHtml}
    </div>
  `;

  const requestToken = ++reviewRenderRequestToken;
  const conflictTargets = state.applyWizard.segments.flatMap((seg, targetIndex) =>
    ensureSegmentSchedules(seg).map((schedule, scheduleIndex) => ({
      segment_id: seg.segmentId || "",
      target_type: seg.targetType || "rail_segment",
      project_start: schedule.project_start || "",
      project_end: schedule.project_end || "",
      schedule_index: scheduleIndex,
      schedule_label: schedule.label || DEFAULT_SCHEDULE_LABEL,
      target_index: targetIndex,
    }))
  ).filter((target) => target.segment_id && target.project_start && target.project_end);

  if (!conflictTargets.length) return;

  try {
    const conflictResult = await fetchWiorConflictsForTargets(conflictTargets);

    if (requestToken !== reviewRenderRequestToken) return;
    if (state.applyWizard.step !== 5) return;
    if (!dom.applyReviewBox) return;

    if (conflictResult?.has_conflicts) {
      const warningHtml = renderWiorConflictWarning(conflictResult.conflicts || []);
      if (warningHtml) {
        dom.applyReviewBox.insertAdjacentHTML("afterbegin", warningHtml);
      }
    }
  } catch (err) {
    if (requestToken !== reviewRenderRequestToken) return;
    if (state.applyWizard.step !== 5) return;
    console.warn("Failed to load WIOR conflict warning:", err);
  }
}

function buildApplicationPayload() {
  collectWorkDetailsStep2();
  collectStep4Data();

  const work = {
    ...defaultWorkDetails(),
    ...(state.applyWizard.workDetails || {}),
  };
  const contact = {
    coordinator: "",
    contactName: "",
    contactPhone: "",
    contactEmail: "",
    vvwMeasure: "BB",
    ...(state.applyWizard.contactDetails || {}),
  };

  const payload = {
    person_mode: state.applyWizard.personMode,
    shared_person: null,
    people_by_target: [],
    work_details: {
      description: work.description || "",
      source: work.source || "",
      urgency: work.urgency || "",
      affected_lines: work.affectedLines || "",
      notes: work.notes || "",
    },
    contact_details: {
      coordinator: contact.coordinator || "",
      vvw_measure: contact.vvwMeasure || "",
    },
    targets: state.applyWizard.segments.map(seg => {
      const schedules = ensureSegmentSchedules(seg)
        .map(normalizeScheduleWindow)
        .slice(0, MAX_SCHEDULE_WINDOWS);
      seg.schedules = schedules;
      syncSegmentProjectRange(seg);

      return {
        target_type: normalizeTargetType(seg.targetType),
        asset_id: seg.assetId || seg.segmentId || "",
        asset_label: seg.assetLabel || getTargetReviewLabel(seg),
        asset_source: seg.assetSource || (normalizeTargetType(seg.targetType) === "overhead_section" ? "BOVENLEIDING_DATA" : "SPOOR_DATA"),
        segment_id: seg.segmentId || "",
        line_id: seg.lineId || "",
        line_name: seg.lineName || "",
        work_mode: seg.workMode || "whole-segment",
        work_start_point: seg.workStartPoint || null,
        work_end_point: seg.workEndPoint || null,
        project_start: seg.projectStart || "",
        project_end: seg.projectEnd || "",
        schedules: schedules.map((windowItem) => ({
          project_start: windowItem.project_start || "",
          project_end: windowItem.project_end || "",
          label: windowItem.label || DEFAULT_SCHEDULE_LABEL,
        })),
      };
    })
  };

  if (state.applyWizard.personMode === "single") {
    payload.shared_person = {
      first_name: state.applyWizard.sharedPerson.firstName || "",
      last_name: state.applyWizard.sharedPerson.lastName || "",
      phone: state.applyWizard.sharedPerson.phone || "",
      email: state.applyWizard.sharedPerson.email || "",
      employee_id: state.applyWizard.sharedPerson.employeeId || ""
    };
    payload.people_by_target = [];
  } else {
    payload.shared_person = null;
    payload.people_by_target = state.applyWizard.peopleBySegment.map(person => ({
      first_name: person.firstName || "",
      last_name: person.lastName || "",
      phone: person.phone || "",
      email: person.email || "",
      employee_id: person.employeeId || ""
    }));
  }

  return payload;
}

function resetApplyFormUiAfterSuccess() {
  if (dom.applyForm) dom.applyForm.reset();

  state.applyWizard.step = 1;
  state.applyWizard.personMode = "single";
  state.applyWizard.sharedPerson = {
    firstName: "",
    lastName: "",
    phone: "",
    email: state.currentUser?.email || "",
    employeeId: "",
  };
  state.applyWizard.peopleBySegment = [];
  state.applyWizard.workDetails = defaultWorkDetails();
  state.applyWizard.contactDetails = {
    coordinator: "",
    contactName: "",
    contactPhone: "",
    contactEmail: "",
    vvwMeasure: "BB",
  };

  state.applyWizard.segments.forEach(seg => {
    seg.workMode = "whole-segment";
    seg.workStartPoint = null;
    seg.workEndPoint = null;
    seg.planningAnchorDate = "";
    seg.projectStart = "";
    seg.projectEnd = "";
    seg.schedules = [];
  });

  state.segmentPreviews.forEach(p => {
    if (p?.startMarker) {
      p.map.removeLayer(p.startMarker);
      p.startMarker = null;
    }
    if (p?.endMarker) {
      p.map.removeLayer(p.endMarker);
      p.endMarker = null;
    }
    if (p) p.clickMode = null;
  });

  state.schedulerBySegment = [];
  resetApplySubmissionState();
  hideApplyAlert();
  syncApplySubmitUi();
}

function renderSubmitSuccess(applicationId) {
  openApplySuccessModal(applicationId);
}

export function wireApplicationHandlers() {
  if (dom.appsCloseBtn) {
    dom.appsCloseBtn.addEventListener("click", () => closeModal(dom.appsModal));
  }
  if (dom.appsBackdrop) {
    dom.appsBackdrop.addEventListener("click", () => closeModal(dom.appsModal));
  }

  if (dom.applyCloseBtn) {
    dom.applyCloseBtn.addEventListener("click", () => {
      if (state.applySubmission.isSubmitting) return;
      closeModal(dom.applyModal);
    });
  }
  if (dom.applyBackdrop) {
    dom.applyBackdrop.addEventListener("click", () => {
      if (state.applySubmission.isSubmitting) return;
      closeModal(dom.applyModal);
    });
  }
  if (dom.applyCancelBtn) {
    dom.applyCancelBtn.addEventListener("click", () => {
      if (state.applySubmission.isSubmitting) return;
      closeModal(dom.applyModal);
    });
  }
  if (dom.applySuccessBackdrop) {
    dom.applySuccessBackdrop.addEventListener("click", () => {
      closeApplySuccessModal();
    });
  }
  if (dom.applySuccessCloseBtn) {
    dom.applySuccessCloseBtn.addEventListener("click", () => {
      closeApplySuccessModal();
    });
  }
  if (dom.applySuccessViewAppsBtn) {
    dom.applySuccessViewAppsBtn.addEventListener("click", async () => {
      closeApplySuccessModal();
      await openMyApplications();
    });
  }


  if (dom.timelineApplyBtn) {
    dom.timelineApplyBtn.addEventListener("click", () => {
      if (!state.currentUser) {
        showToast({
          title: t("login_required_title"),
          message: t("login_required_msg"),
          actionText: t("login_action"),
          onAction: () => openLogin(),
        });
        return;
      }
      openApplyForSegments();
    });
  }
if (dom.applyProjectBtn) {
    dom.applyProjectBtn.addEventListener("click", () => {
      if (!state.currentUser) {
        showToast({
          title: t("login_required_title"),
          message: t("login_required_msg"),
          actionText: t("login_action"),
          onAction: () => openLogin(),
          durationMs: 5000
        });
        return;
      }

      if (!state.currentSelection) {
        showToast({
          title: "Apply for project",
          message: "Please select up to 3 bookable targets first.",
          durationMs: 4000
        });
        return;
      }

      if (state.currentSelection.type === "segment-list") {
        const segments = state.currentSelection.segments || [];
        if (segments.length === 0) {
          showToast({
            title: "Apply for project",
            message: "No targets available for the current selection.",
            durationMs: 4000
          });
          return;
        }

        openApplyForSegments(segments);
        return;
      }

      showToast({
        title: "Apply for project",
        message: "Please select a valid target first.",
        durationMs: 4000
      });
    });
  }

  if (dom.applyBackBtn) {
    dom.applyBackBtn.addEventListener("click", () => {
      if (state.applySubmission.isSubmitting) return;
      if (state.applyWizard.step > 1) {
        hideApplyAlert();
        state.applyWizard.step -= 1;
        syncWizardUI();
      }
    });
  }

  if (dom.applyNextBtn) {
    dom.applyNextBtn.addEventListener("click", () => {
      if (state.applySubmission.isSubmitting) return;
      const v = validateCurrentStep();
      if (!v.ok) {
        showApplyAlert(v.msg, "error");
        return;
      }

      hideApplyAlert();

      if (state.applyWizard.step < APPLY_TOTAL_STEPS) {
        state.applyWizard.step += 1;
        syncWizardUI();
      }
    });
  }

  if (dom.applyForm) {
    dom.applyForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      if (state.applySubmission.isSubmitting) return;

      const v = validateCurrentStep();
      if (!v.ok) {
        showApplyAlert(v.msg, "error");
        return;
      }

      try {
        state.applySubmission.isSubmitting = true;
        syncApplySubmitUi();
        showApplyAlert("Submitting application...", "info", { scroll: false });

        const payload = buildApplicationPayload();

        const fd = new FormData();
        fd.append("payload_json", JSON.stringify(payload));

        const files = dom.safetyPlans?.files || [];
        for (const file of files) {
          fd.append("safety_plans", file);
        }

        const res = await fetch("/api/apply", {
          method: "POST",
          body: fd
        });

        const data = await res.json().catch(() => ({}));

        if (!res.ok) {
          state.applySubmission.isSubmitting = false;
          syncApplySubmitUi();

          if (res.status === 401) {
            showApplyAlert(data?.detail || "Session expired. Please log in again.", "warning");
            showToast({
              title: t("login_required_title"),
              message: data?.detail || "Please log in again.",
              actionText: t("login_action"),
              onAction: () => openLogin(),
              durationMs: 5000
            });
            return;
          }

          if (res.status === 409) {
            state.applyWizard.step = 3;
            syncWizardUI();
            showApplyAlert(data?.detail || "Selected time conflicts with an existing booking.", "error");
            return;
          }

          showApplyAlert(data?.detail || `Submit failed (${res.status})`, "error");
          return;
        }

        state.lineStatusCache.clear();
        state.applySubmission.isSubmitting = false;
        syncApplySubmitUi();
        hideApplyAlert();
        renderSubmitSuccess(data.application_id);
      } catch (err) {
        state.applySubmission.isSubmitting = false;
        syncApplySubmitUi();
        showApplyAlert(`Error: ${err.message}`, "error");
      }
    });
  }
}
