import { dom } from "./dom.js";
import { esc, getJSON } from "./utils.js";
import { openModal, closeModal } from "./modals.js";

const ACTION_LABELS = {
  login_success: "Logged in",
  login_failed: "Login failed",
  application_submitted: "Submitted an application",
  file_upload_metadata_saved: "Saved file upload metadata",
  transfer_trip_submitted: "Submitted a transfer trip",
  application_status_changed: "Changed application status",
  application_deleted: "Deleted an application",
  transfer_trip_status_changed: "Changed transfer trip status",
  transfer_trip_deleted: "Deleted a transfer trip",
  tbgn_project_created: "Created a TBGN project",
  tbgn_project_updated: "Updated a TBGN project",
  tbgn_project_deleted: "Deleted a TBGN project",
  wior_conflict_checked: "Checked WIOR conflicts",
  wior_postgis_fallback_to_legacy: "WIOR check used legacy fallback",
  wior_refresh_and_sync_completed: "Completed WIOR refresh and PostGIS sync",
  wior_refresh_and_sync_failed: "WIOR refresh and PostGIS sync failed"
};

function formatActivityDate(value) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString([], {
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit"
  });
}

function activityLabel(item) {
  return item?.summary || ACTION_LABELS[item?.action] || item?.action || "Activity";
}

function renderActivity(items) {
  if (!dom.settingsActivityList) return;
  const list = Array.isArray(items) ? items : [];
  dom.settingsActivityList.innerHTML = list.map((item) => {
    const label = activityLabel(item);
    const entityBits = [item?.entity_type, item?.entity_id].filter(Boolean).join(" ");
    return `
      <li class="activity-item">
        <div class="activity-item-main">
          <strong>${esc(label)}</strong>
          <span>${esc(formatActivityDate(item?.created_at))}</span>
        </div>
        ${entityBits ? `<div class="activity-item-meta">${esc(entityBits)}</div>` : ""}
      </li>
    `;
  }).join("");
}

async function loadActivity() {
  if (dom.settingsActivityLoading) dom.settingsActivityLoading.classList.remove("is-hidden");
  if (dom.settingsActivityEmpty) dom.settingsActivityEmpty.classList.add("is-hidden");
  if (dom.settingsActivityError) dom.settingsActivityError.classList.add("is-hidden");
  if (dom.settingsActivityList) dom.settingsActivityList.innerHTML = "";

  try {
    const data = await getJSON("/api/settings/activity?limit=50");
    const items = Array.isArray(data?.items) ? data.items : [];
    renderActivity(items);
    if (dom.settingsActivityEmpty) dom.settingsActivityEmpty.classList.toggle("is-hidden", items.length > 0);
  } catch {
    if (dom.settingsActivityError) dom.settingsActivityError.classList.remove("is-hidden");
  } finally {
    if (dom.settingsActivityLoading) dom.settingsActivityLoading.classList.add("is-hidden");
  }
}

export function openSettings() {
  openModal(dom.settingsModal);
  loadActivity();
}

export function closeSettings() {
  closeModal(dom.settingsModal);
}
