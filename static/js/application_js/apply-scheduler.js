import { state } from "../state.js";
import { esc } from "../utils.js";
import {
  getTargetTypeLabel,
  getTargetReviewLabel,
  getTargetSubtitle,
} from "./apply-map.js";

export const MAX_SCHEDULE_WINDOWS = 8;
export const DEFAULT_SCHEDULE_LABEL = "Custom work";
const DAY_WORK_LABEL = "Day work";
const NIGHT_WORK_LABEL = "Night work";
const WEEKEND_SATURDAY_LABEL = "Weekend Saturday";
const WEEKEND_SUNDAY_LABEL = "Weekend Sunday";

export function formatLocalIsoMinute(d) {
  const yyyy = d.getFullYear();
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  const hh = String(d.getHours()).padStart(2, "0");
  const mi = String(d.getMinutes()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd}T${hh}:${mi}`;
}

export function toDateInputFromIso(value) {
  return String(value || "").slice(0, 10);
}

export function toDateTimeLocalValue(value) {
  const raw = String(value || "").trim();
  if (!raw) return "";
  if (raw.length >= 16) return raw.slice(0, 16);
  return raw;
}

export function datePartFromIso(value) {
  const raw = String(value || "").trim();
  const match = raw.match(/^(\d{4}-\d{2}-\d{2})/);
  return match ? match[1] : "";
}

export function combineDateAndTime(dateStr, timeStr) {
  if (!dateStr || !timeStr) return "";
  return `${dateStr}T${timeStr}`;
}

export function parseDateOnly(dateStr) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(String(dateStr || ""))) return null;
  const parsed = new Date(`${dateStr}T00:00:00`);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

export function formatDateOnly(dateObj) {
  if (!(dateObj instanceof Date) || Number.isNaN(dateObj.getTime())) return "";
  const yyyy = dateObj.getFullYear();
  const mm = String(dateObj.getMonth() + 1).padStart(2, "0");
  const dd = String(dateObj.getDate()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd}`;
}

export function addDaysToDateString(dateStr, days) {
  const parsed = parseDateOnly(dateStr);
  if (!parsed) return "";
  parsed.setDate(parsed.getDate() + days);
  return formatDateOnly(parsed);
}

export function normalizeScheduleWindow(raw) {
  return {
    project_start: String(raw?.project_start || "").trim(),
    project_end: String(raw?.project_end || "").trim(),
    label: String(raw?.label || DEFAULT_SCHEDULE_LABEL).trim() || DEFAULT_SCHEDULE_LABEL,
  };
}

export function ensureSegmentSchedules(seg) {
  let schedules = Array.isArray(seg.schedules)
    ? seg.schedules.map(normalizeScheduleWindow)
    : [];

  if (!schedules.length && seg.projectStart && seg.projectEnd) {
    schedules = [normalizeScheduleWindow({
      project_start: seg.projectStart,
      project_end: seg.projectEnd,
      label: DEFAULT_SCHEDULE_LABEL,
    })];
  }

  if (!schedules.length) {
    schedules = [normalizeScheduleWindow({})];
  }

  seg.schedules = schedules.slice(0, MAX_SCHEDULE_WINDOWS);
  return seg.schedules;
}

export function syncSegmentProjectRange(seg) {
  const schedules = ensureSegmentSchedules(seg);
  const first = schedules[0] || normalizeScheduleWindow({});
  seg.projectStart = first.project_start || "";
  seg.projectEnd = first.project_end || "";
}

export function cloneSchedulesForCopy(schedules) {
  return (schedules || []).map((entry) => ({ ...normalizeScheduleWindow(entry) }));
}

export function getSchedulerUiState(index) {
  const current = state.schedulerBySegment[index] || {};
  state.schedulerBySegment[index] = {
    weekDates: [],
    mouseDownCell: null,
    dragging: false,
    didDrag: false,
    anchorCell: null,
    hoverCell: null,
    selectedRange: null,
    bookings: [],
    activeWindowIndex: Number.isInteger(current.activeWindowIndex) ? current.activeWindowIndex : 0,
  };
  return state.schedulerBySegment[index];
}

export function setSchedulerSummary(index, message, isError = false) {
  const summary = document.getElementById(`schedulerSummary_${index}`);
  if (!summary) return;
  summary.textContent = String(message || "");
  summary.classList.toggle("is-error", !!message && isError);
}

export function getAnchorDateForSchedule(seg, index) {
  const schedules = ensureSegmentSchedules(seg);
  const schedulerState = getSchedulerUiState(index);
  const active = schedules[schedulerState.activeWindowIndex] || schedules[0];
  const activeDate = datePartFromIso(active?.project_start);
  if (activeDate) return activeDate;

  const startInputValue = String(
    document.getElementById(`seg_${index}_startDate`)?.value || seg?.planningAnchorDate || ""
  ).trim();
  if (startInputValue) return startInputValue;

  const firstDate = datePartFromIso(schedules[0]?.project_start);
  if (firstDate) return firstDate;

  return "";
}

export function createDayWindowForDate(dateStr) {
  if (!parseDateOnly(dateStr)) return null;
  return {
    project_start: combineDateAndTime(dateStr, "07:00"),
    project_end: combineDateAndTime(dateStr, "17:00"),
    label: DAY_WORK_LABEL,
  };
}

export function createNightWindowForDate(dateStr) {
  if (!parseDateOnly(dateStr)) return null;
  const nextDate = addDaysToDateString(dateStr, 1);
  if (!nextDate) return null;
  return {
    project_start: combineDateAndTime(dateStr, "23:00"),
    project_end: combineDateAndTime(nextDate, "05:00"),
    label: NIGHT_WORK_LABEL,
  };
}

export function createWeekendWindowsForDate(dateStr) {
  const baseDate = parseDateOnly(dateStr);
  if (!baseDate) return [];

  const day = baseDate.getDay();
  const saturdayOffset = day === 0 ? -1 : 6 - day;
  const sundayOffset = day === 0 ? 0 : 7 - day;
  const saturdayDate = addDaysToDateString(dateStr, saturdayOffset);
  const sundayDate = addDaysToDateString(dateStr, sundayOffset);
  if (!saturdayDate || !sundayDate) return [];

  return [
    {
      project_start: combineDateAndTime(saturdayDate, "07:00"),
      project_end: combineDateAndTime(saturdayDate, "17:00"),
      label: WEEKEND_SATURDAY_LABEL,
    },
    {
      project_start: combineDateAndTime(sundayDate, "07:00"),
      project_end: combineDateAndTime(sundayDate, "17:00"),
      label: WEEKEND_SUNDAY_LABEL,
    },
  ];
}

export function parseLocalIsoToDate(value) {
  if (!value) return null;
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? null : d;
}

export function startOfDay(d) {
  const out = new Date(d);
  out.setHours(0, 0, 0, 0);
  return out;
}

export function sameDay(a, b) {
  return a.getFullYear() === b.getFullYear()
    && a.getMonth() === b.getMonth()
    && a.getDate() === b.getDate();
}

export function overlapsRange(slotStart, slotEnd, bookingStart, bookingEnd) {
  return bookingStart < slotEnd && bookingEnd > slotStart;
}

export async function fetchTargetBookings(target, weekStart) {
  const params = new URLSearchParams({
    week_start: weekStart,
    target_type: String(target?.targetType || "rail_segment"),
    asset_id: String(target?.assetId || target?.segmentId || "").trim(),
  });
  if (target?.segmentId) params.set("segment_id", target.segmentId);

  const res = await fetch(
    `/api/segment_bookings?${params.toString()}`
  );

  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data?.detail || `Failed to load bookings (${res.status})`);
  }
  return data.bookings || [];
}

export function duplicateScheduleWindow(index, windowIndex) {
  const seg = state.applyWizard.segments[index];
  if (!seg) return { ok: false, msg: "Target not found." };

  const schedules = ensureSegmentSchedules(seg);
  if (schedules.length >= MAX_SCHEDULE_WINDOWS) {
    return { ok: false, msg: `Maximum ${MAX_SCHEDULE_WINDOWS} schedule windows per target.` };
  }

  const source = schedules[windowIndex];
  if (!source) return { ok: false, msg: "Schedule window not found." };

  schedules.splice(windowIndex + 1, 0, normalizeScheduleWindow(source));
  seg.schedules = schedules.slice(0, MAX_SCHEDULE_WINDOWS);

  const schedulerState = getSchedulerUiState(index);
  schedulerState.activeWindowIndex = Math.max(0, Math.min(windowIndex + 1, seg.schedules.length - 1));
  syncSegmentProjectRange(seg);
  renderScheduleWindowsEditor(index);
  return { ok: true, msg: "Schedule window duplicated." };
}

export function autoFillFirstEmptyWindow(index, anchorDate) {
  const seg = state.applyWizard.segments[index];
  if (!seg) return { ok: false, msg: "Target not found." };

  const dayWindow = createDayWindowForDate(anchorDate);
  if (!dayWindow) return { ok: false, msg: "Choose a work date first." };

  const schedules = ensureSegmentSchedules(seg);
  const emptyIndex = schedules.findIndex((entry) => !entry.project_start && !entry.project_end);
  if (emptyIndex < 0) {
    return { ok: true, changed: false, msg: "" };
  }

  schedules[emptyIndex] = normalizeScheduleWindow(dayWindow);
  const schedulerState = getSchedulerUiState(index);
  schedulerState.activeWindowIndex = emptyIndex;
  syncSegmentProjectRange(seg);
  renderScheduleWindowsEditor(index);
  return { ok: true, changed: true, msg: "Day work applied to the first empty window." };
}

export function renderScheduleWindowsEditor(index) {
  const seg = state.applyWizard.segments[index];
  if (!seg) return;

  const host = document.getElementById(`scheduleWindows_${index}`);
  if (!host) return;

  const schedulerState = getSchedulerUiState(index);
  const schedules = ensureSegmentSchedules(seg);

  schedulerState.activeWindowIndex = Math.max(
    0,
    Math.min(schedulerState.activeWindowIndex, schedules.length - 1)
  );

  host.innerHTML = schedules.map((windowItem, scheduleIndex) => {
    const isActive = scheduleIndex === schedulerState.activeWindowIndex;
    return `
      <div class="schedule-window-card ${isActive ? "is-active" : ""}">
        <div class="schedule-window-head">
          <div class="schedule-window-head-left">
            <button type="button" class="btn btn-mini schedule-window-select ${isActive ? "is-active" : ""}" data-schedule-select="${index}" data-window-index="${scheduleIndex}">
              Window ${scheduleIndex + 1}
            </button>
            ${isActive ? `<span class="schedule-window-active-badge">Active</span>` : ""}
          </div>
          <div class="schedule-window-actions">
            <button type="button" class="btn btn-mini" data-schedule-duplicate="${index}" data-window-index="${scheduleIndex}">
              Duplicate
            </button>
            <button
              type="button"
              class="btn btn-mini"
              data-schedule-remove="${index}"
              data-window-index="${scheduleIndex}"
              ${schedules.length <= 1 ? "disabled" : ""}
            >
              Remove
            </button>
          </div>
        </div>
        <div class="schedule-window-grid">
          <div class="field schedule-label-field">
            <label>Label</label>
            <input
              type="text"
              data-schedule-label="${index}"
              data-window-index="${scheduleIndex}"
              value="${esc(windowItem.label || DEFAULT_SCHEDULE_LABEL)}"
            >
          </div>
          <div class="field">
            <label>Start</label>
            <input
              type="datetime-local"
              data-schedule-start="${index}"
              data-window-index="${scheduleIndex}"
              value="${esc(toDateTimeLocalValue(windowItem.project_start))}"
            >
          </div>
          <div class="field">
            <label>End</label>
            <input
              type="datetime-local"
              data-schedule-end="${index}"
              data-window-index="${scheduleIndex}"
              value="${esc(toDateTimeLocalValue(windowItem.project_end))}"
            >
          </div>
        </div>
      </div>
    `;
  }).join("");

  host.querySelectorAll(`[data-schedule-select="${index}"]`).forEach((btn) => {
    btn.addEventListener("click", () => {
      const nextIndex = Number(btn.dataset.windowIndex || 0);
      schedulerState.activeWindowIndex = Math.max(0, Math.min(nextIndex, schedules.length - 1));
      renderScheduleWindowsEditor(index);
    });
  });

  host.querySelectorAll(`[data-schedule-duplicate="${index}"]`).forEach((btn) => {
    btn.addEventListener("click", () => {
      const windowIndex = Number(btn.dataset.windowIndex || -1);
      const result = duplicateScheduleWindow(index, windowIndex);
      setSchedulerSummary(index, result.msg, !result.ok);
    });
  });

  host.querySelectorAll(`[data-schedule-remove="${index}"]`).forEach((btn) => {
    btn.addEventListener("click", () => {
      const removeIndex = Number(btn.dataset.windowIndex || -1);
      if (schedules.length <= 1) return;

      const next = schedules.filter((_, i) => i !== removeIndex);
      seg.schedules = next.map(normalizeScheduleWindow);
      schedulerState.activeWindowIndex = Math.max(0, Math.min(schedulerState.activeWindowIndex, seg.schedules.length - 1));
      syncSegmentProjectRange(seg);
      renderScheduleWindowsEditor(index);
      setSchedulerSummary(index, "Schedule window removed.");
    });
  });

  host.querySelectorAll(`[data-schedule-start="${index}"]`).forEach((input) => {
    input.addEventListener("change", () => {
      const windowIndex = Number(input.dataset.windowIndex || -1);
      const nextValue = String(input.value || "").trim();
      if (!seg.schedules[windowIndex]) return;
      seg.schedules[windowIndex].project_start = nextValue;
      seg.planningAnchorDate = datePartFromIso(nextValue) || seg.planningAnchorDate || "";
      syncSegmentProjectRange(seg);
    });
  });

  host.querySelectorAll(`[data-schedule-end="${index}"]`).forEach((input) => {
    input.addEventListener("change", () => {
      const windowIndex = Number(input.dataset.windowIndex || -1);
      const nextValue = String(input.value || "").trim();
      if (!seg.schedules[windowIndex]) return;
      seg.schedules[windowIndex].project_end = nextValue;
      syncSegmentProjectRange(seg);
    });
  });

  host.querySelectorAll(`[data-schedule-label="${index}"]`).forEach((input) => {
    input.addEventListener("input", () => {
      const windowIndex = Number(input.dataset.windowIndex || -1);
      const nextValue = String(input.value || "").trim();
      if (!seg.schedules[windowIndex]) return;
      seg.schedules[windowIndex].label = nextValue || DEFAULT_SCHEDULE_LABEL;
    });
  });
}

export function applyQuickScheduleTypeForSegment(index, quickType) {
  const seg = state.applyWizard.segments[index];
  if (!seg) return { ok: false, msg: "Target not found." };

  const schedulerState = getSchedulerUiState(index);
  const schedules = ensureSegmentSchedules(seg);
  const activeIndex = Math.max(0, Math.min(schedulerState.activeWindowIndex, schedules.length - 1));
  const anchorDate = getAnchorDateForSchedule(seg, index);

  if (!anchorDate) {
    return { ok: false, msg: "Choose a work date first." };
  }

  if (quickType === "weekend") {
    const weekendWindows = createWeekendWindowsForDate(anchorDate);
    if (!weekendWindows.length) {
      return { ok: false, msg: "Choose a work date first." };
    }

    const nextSchedules = [
      ...schedules.slice(0, activeIndex),
      ...weekendWindows,
      ...schedules.slice(activeIndex + 1),
    ];

    if (nextSchedules.length > MAX_SCHEDULE_WINDOWS) {
      return { ok: false, msg: `Maximum ${MAX_SCHEDULE_WINDOWS} schedule windows per target.` };
    }

    seg.schedules = nextSchedules.map(normalizeScheduleWindow);
    schedulerState.activeWindowIndex = Math.max(0, Math.min(activeIndex, seg.schedules.length - 1));
    seg.planningAnchorDate = anchorDate;
    syncSegmentProjectRange(seg);
    renderScheduleWindowsEditor(index);
    return { ok: true, msg: "Weekend windows applied." };
  }

  let window = null;
  if (quickType === "day") {
    window = createDayWindowForDate(anchorDate);
  } else if (quickType === "night") {
    window = createNightWindowForDate(anchorDate);
  }

  if (!window) {
    return { ok: false, msg: quickType ? "Choose a work date first." : "Unknown quick schedule option." };
  }

  seg.schedules[activeIndex] = normalizeScheduleWindow(window);
  seg.planningAnchorDate = anchorDate;
  syncSegmentProjectRange(seg);
  renderScheduleWindowsEditor(index);
  return { ok: true, msg: `${window.label} applied.` };
}

export function copySchedulesToAllSegments(sourceIndex) {
  const sourceSeg = state.applyWizard.segments[sourceIndex];
  if (!sourceSeg) return { ok: false, msg: "Source target not found." };

  const sourceSchedules = cloneSchedulesForCopy(ensureSegmentSchedules(sourceSeg));
  if (!sourceSchedules.length) return { ok: false, msg: "No schedule windows to copy." };

  state.applyWizard.segments.forEach((seg, idx) => {
    seg.schedules = cloneSchedulesForCopy(sourceSchedules);
    seg.planningAnchorDate = sourceSeg.planningAnchorDate || datePartFromIso(sourceSchedules[0]?.project_start) || "";
    syncSegmentProjectRange(seg);
    const schedulerState = getSchedulerUiState(idx);
    schedulerState.activeWindowIndex = Math.max(0, Math.min(schedulerState.activeWindowIndex, seg.schedules.length - 1));
  });

  renderTimeCardsStep3();
  return { ok: true, msg: "Schedule windows copied to all selected targets." };
}

export function addCustomScheduleWindow(index) {
  const seg = state.applyWizard.segments[index];
  if (!seg) return { ok: false, msg: "Target not found." };

  const schedules = ensureSegmentSchedules(seg);
  if (schedules.length >= MAX_SCHEDULE_WINDOWS) {
    return { ok: false, msg: `Maximum ${MAX_SCHEDULE_WINDOWS} schedule windows per target.` };
  }

  const anchorDate = getAnchorDateForSchedule(seg, index);
  if (!anchorDate) {
    return { ok: false, msg: "Choose a work date first." };
  }

  const customWindow = createDayWindowForDate(anchorDate);
  if (!customWindow) {
    return { ok: false, msg: "Choose a work date first." };
  }

  customWindow.label = DEFAULT_SCHEDULE_LABEL;
  schedules.push(normalizeScheduleWindow(customWindow));

  const schedulerState = getSchedulerUiState(index);
  schedulerState.activeWindowIndex = schedules.length - 1;
  seg.planningAnchorDate = anchorDate;
  syncSegmentProjectRange(seg);
  renderScheduleWindowsEditor(index);
  return { ok: true, msg: "Custom schedule window added." };
}

export function createSchedulerCard(index, seg) {
  const slotMinutes = state.schedulerDefaults.slotMinutes;
  const startHour = state.schedulerDefaults.startHour;
  const endHour = state.schedulerDefaults.endHour;
  const slotCount = ((endHour - startHour) * 60) / slotMinutes;
  const schedulerState = getSchedulerUiState(index);

  function setSummary(message) {
    setSchedulerSummary(index, message, false);
  }

  function getWeekDates(startDateStr) {
    const d = new Date(`${startDateStr}T00:00:00`);
    const out = [];
    for (let i = 0; i < 7; i += 1) {
      const n = new Date(d);
      n.setDate(d.getDate() + i);
      out.push(n);
    }
    return out;
  }

  function formatHourMinute(totalMinutes) {
    const hh = Math.floor(totalMinutes / 60);
    const mm = totalMinutes % 60;
    return `${String(hh).padStart(2, "0")}:${String(mm).padStart(2, "0")}`;
  }

  function formatDateShort(d) {
    return d.toLocaleDateString(undefined, {
      weekday: "short",
      day: "numeric",
      month: "short"
    });
  }

  function cellHasBooking(dayIndex, slotIndex) {
    const bookings = schedulerState.bookings || [];
    const dayDate = schedulerState.weekDates[dayIndex];
    if (!dayDate) return false;

    const slotStartMinutes = (startHour * 60) + (slotIndex * slotMinutes);
    const slotEndMinutes = slotStartMinutes + slotMinutes;

    const slotStart = new Date(dayDate);
    slotStart.setHours(Math.floor(slotStartMinutes / 60), slotStartMinutes % 60, 0, 0);

    const slotEnd = new Date(dayDate);
    slotEnd.setHours(Math.floor(slotEndMinutes / 60), slotEndMinutes % 60, 0, 0);

    return bookings.some((booking) => {
      const bookingStart = parseLocalIsoToDate(booking.project_start);
      const bookingEnd = parseLocalIsoToDate(booking.project_end);
      if (!bookingStart || !bookingEnd) return false;
      return overlapsRange(slotStart, slotEnd, bookingStart, bookingEnd);
    });
  }

  function clearSelectionVisual() {
    const host = document.getElementById(`scheduler_${index}`);
    if (!host) return;
    host.querySelectorAll(".scheduler-cell").forEach(cell => {
      cell.classList.remove("is-selected");
    });
  }

  function normalizeRange(a, b) {
    const startDayIndex = Math.min(a.dayIndex, b.dayIndex);
    const endDayIndex = Math.max(a.dayIndex, b.dayIndex);

    let startSlot = a.slotIndex;
    let endSlot = b.slotIndex;

    if (a.dayIndex === b.dayIndex) {
      startSlot = Math.min(a.slotIndex, b.slotIndex);
      endSlot = Math.max(a.slotIndex, b.slotIndex);
    } else if (a.dayIndex < b.dayIndex) {
      startSlot = a.slotIndex;
      endSlot = b.slotIndex;
    } else {
      startSlot = b.slotIndex;
      endSlot = a.slotIndex;
    }

    return { startDayIndex, endDayIndex, startSlot, endSlot };
  }

  function makeSingleCellRange(dayIndex, slotIndex) {
    return {
      startDayIndex: dayIndex,
      endDayIndex: dayIndex,
      startSlot: slotIndex,
      endSlot: slotIndex,
    };
  }

  function cellIsWithinRange(dayIndex, slotIndex, range) {
    if (!range) return false;
    if (dayIndex < range.startDayIndex || dayIndex > range.endDayIndex) return false;

    if (range.startDayIndex === range.endDayIndex) {
      return dayIndex === range.startDayIndex &&
        slotIndex >= range.startSlot &&
        slotIndex <= range.endSlot;
    }

    if (dayIndex === range.startDayIndex) {
      return slotIndex >= range.startSlot && slotIndex <= slotCount - 1;
    }

    if (dayIndex === range.endDayIndex) {
      return slotIndex >= 0 && slotIndex <= range.endSlot;
    }

    return true;
  }

  function paintSelection(range) {
    clearSelectionVisual();
    const host = document.getElementById(`scheduler_${index}`);
    if (!host || !range) return;

    host.querySelectorAll(".scheduler-cell").forEach(cell => {
      const dayIndex = Number(cell.dataset.dayIndex);
      const slotIndex = Number(cell.dataset.slotIndex);
      if (cellIsWithinRange(dayIndex, slotIndex, range)) {
        cell.classList.add("is-selected");
      }
    });
  }

  function paintExistingBookings(bookings) {
    const host = document.getElementById(`scheduler_${index}`);
    if (!host) return;

    host.querySelectorAll(".scheduler-booking").forEach(el => el.remove());
    host.querySelectorAll(".scheduler-cell").forEach(cell => {
      cell.classList.remove("is-booked");
    });

    schedulerState.bookings = bookings || [];

    if (!schedulerState.bookings.length) return;

    host.querySelectorAll(".scheduler-cell").forEach(cell => {
      const dayIndex = Number(cell.dataset.dayIndex);
      const slotIndex = Number(cell.dataset.slotIndex);

      if (cellHasBooking(dayIndex, slotIndex)) {
        cell.classList.add("is-booked");

        const block = document.createElement("div");
        block.className = "scheduler-booking";
        block.title = "Already booked";
        cell.appendChild(block);
      }
    });
  }

  function buildGrid(startDateValue) {
    schedulerState.weekDates = getWeekDates(startDateValue);
    schedulerState.mouseDownCell = null;
    schedulerState.dragging = false;
    schedulerState.didDrag = false;
    schedulerState.anchorCell = null;
    schedulerState.hoverCell = null;
    schedulerState.selectedRange = null;

    const host = document.getElementById(`scheduler_${index}`);
    if (!host) return;

    const wrap = document.createElement("div");
    wrap.className = "scheduler-grid";

    const corner = document.createElement("div");
    corner.className = "scheduler-corner";
    wrap.appendChild(corner);

    schedulerState.weekDates.forEach((d) => {
      const head = document.createElement("div");
      head.className = "scheduler-day-header";
      head.textContent = formatDateShort(d);
      wrap.appendChild(head);
    });

    for (let slot = 0; slot < slotCount; slot += 1) {
      const totalMinutes = (startHour * 60) + (slot * slotMinutes);

      const timeLabel = document.createElement("div");
      timeLabel.className = "scheduler-time-label";
      timeLabel.textContent = formatHourMinute(totalMinutes);
      wrap.appendChild(timeLabel);

      for (let dayIndex = 0; dayIndex < 7; dayIndex += 1) {
        const cell = document.createElement("div");
        cell.className = "scheduler-cell";
        cell.dataset.dayIndex = String(dayIndex);
        cell.dataset.slotIndex = String(slot);

        cell.addEventListener("mousedown", (e) => {
          e.preventDefault();

          if (cellHasBooking(dayIndex, slot)) {
            setSummary("This time slot is already booked.");
            schedulerState.mouseDownCell = null;
            schedulerState.dragging = false;
            schedulerState.didDrag = false;
            return;
          }

          schedulerState.mouseDownCell = { dayIndex, slotIndex: slot };
          schedulerState.dragging = false;
          schedulerState.didDrag = false;
        });

        cell.addEventListener("mouseenter", (e) => {
          if (!(e.buttons === 1)) return;
          if (!schedulerState.mouseDownCell) return;

          if (cellHasBooking(dayIndex, slot)) {
            setSummary("Selection cannot include already booked time.");
            return;
          }

          const hovered = { dayIndex, slotIndex: slot };

          if (!schedulerState.dragging) {
            if (
              hovered.dayIndex === schedulerState.mouseDownCell.dayIndex &&
              hovered.slotIndex === schedulerState.mouseDownCell.slotIndex
            ) {
              return;
            }

            schedulerState.dragging = true;
            schedulerState.didDrag = true;
            schedulerState.anchorCell = schedulerState.mouseDownCell;
          }

          schedulerState.hoverCell = hovered;
          schedulerState.selectedRange = normalizeRange(
            schedulerState.anchorCell,
            schedulerState.hoverCell
          );

          paintSelection(schedulerState.selectedRange);
        });

        cell.addEventListener("click", () => {
          if (cellHasBooking(dayIndex, slot)) {
            setSummary("This time slot is already booked.");
            return;
          }

          if (schedulerState.didDrag) {
            schedulerState.didDrag = false;
            schedulerState.mouseDownCell = null;
            return;
          }

          const clicked = { dayIndex, slotIndex: slot };

          if (!schedulerState.anchorCell) {
            schedulerState.anchorCell = clicked;
            schedulerState.hoverCell = clicked;
            schedulerState.selectedRange = makeSingleCellRange(dayIndex, slot);
            paintSelection(schedulerState.selectedRange);
            setSummary("Start selected. Click another cell to set the end time, or drag to select.");
            schedulerState.mouseDownCell = null;
            return;
          }

          schedulerState.hoverCell = clicked;
          schedulerState.selectedRange = normalizeRange(
            schedulerState.anchorCell,
            schedulerState.hoverCell
          );
          paintSelection(schedulerState.selectedRange);

          schedulerState.anchorCell = null;
          schedulerState.hoverCell = null;
          schedulerState.mouseDownCell = null;
          setSummary("Range selected. Click Set time to confirm.");
        });

        wrap.appendChild(cell);
      }
    }

    host.innerHTML = "";
    host.appendChild(wrap);

    document.addEventListener("mouseup", () => {
      schedulerState.mouseDownCell = null;

      if (!schedulerState.dragging) return;

      schedulerState.dragging = false;
      schedulerState.anchorCell = null;
      schedulerState.hoverCell = null;

      if (schedulerState.selectedRange) {
        setSummary("Range selected. Click Set time to confirm, or start a new selection.");
      }
    }, { once: true });
  }

  function rangeToDateTimes() {
    const range = schedulerState.selectedRange;
    if (!range || !schedulerState.weekDates?.length) return null;

    const startDate = schedulerState.weekDates[range.startDayIndex];
    const endDate = schedulerState.weekDates[range.endDayIndex];
    if (!startDate || !endDate) return null;

    const startMinutes = (startHour * 60) + (range.startSlot * slotMinutes);
    const endMinutes = (startHour * 60) + ((range.endSlot + 1) * slotMinutes);

    const start = new Date(startDate);
    start.setHours(Math.floor(startMinutes / 60), startMinutes % 60, 0, 0);

    const end = new Date(endDate);
    end.setHours(Math.floor(endMinutes / 60), endMinutes % 60, 0, 0);

    return { start, end };
  }

  const buildBtn = document.querySelector(`[data-build-scheduler="${index}"]`);
  const setBtn = document.querySelector(`[data-set-time="${index}"]`);
  const startInput = document.getElementById(`seg_${index}_startDate`);
  const addWindowBtn = document.querySelector(`[data-add-window="${index}"]`);
  const copyBtn = document.querySelector(`[data-copy-schedules="${index}"]`);

  if (startInput) {
    startInput.addEventListener("change", () => {
      const nextDate = String(startInput.value || "").trim();
      seg.planningAnchorDate = nextDate;

      if (!nextDate) {
        setSchedulerSummary(index, "");
        return;
      }

      const result = autoFillFirstEmptyWindow(index, nextDate);
      if (!result.ok) {
        setSchedulerSummary(index, result.msg, true);
        return;
      }
      if (result.changed) {
        setSchedulerSummary(index, result.msg);
      } else {
        setSchedulerSummary(index, "");
      }
    });
  }

  if (buildBtn) {
    buildBtn.addEventListener("click", async () => {
      if (!startInput?.value) {
        setSchedulerSummary(index, "Choose a work date first.", true);
        return;
      }

      buildGrid(startInput.value);
      setSummary("Loading existing bookings...");

      try {
        if (seg.assetId || seg.segmentId) {
          const bookings = await fetchTargetBookings(seg, startInput.value);
          paintExistingBookings(bookings);

          if (bookings.length) {
            setSummary(`Loaded ${bookings.length} existing booking(s). You can drag to select, or click one cell for start and another for end.`);
          } else {
            setSummary("No existing bookings for this week. You can drag to select, or click one cell for start and another for end.");
          }
        } else {
          setSummary("No target ID available for booking lookup.");
        }
      } catch (err) {
        setSummary(`Could not load existing bookings: ${err.message}`);
      }
    });
  }

  if (setBtn) {
    setBtn.addEventListener("click", () => {
      const result = rangeToDateTimes();
      if (!result) {
        setSummary("Please select a block first.");
        return;
      }

      const schedules = ensureSegmentSchedules(seg);
      const activeIndex = Math.max(0, Math.min(schedulerState.activeWindowIndex, schedules.length - 1));
      const currentLabel = schedules[activeIndex]?.label || DEFAULT_SCHEDULE_LABEL;
      schedules[activeIndex] = normalizeScheduleWindow({
        project_start: formatLocalIsoMinute(result.start),
        project_end: formatLocalIsoMinute(result.end),
        label: currentLabel,
      });

      seg.schedules = schedules;
      seg.planningAnchorDate = datePartFromIso(schedules[activeIndex].project_start) || seg.planningAnchorDate || "";
      syncSegmentProjectRange(seg);
      renderScheduleWindowsEditor(index);
      setSummary(`Window ${activeIndex + 1} set: ${schedules[activeIndex].project_start} to ${schedules[activeIndex].project_end}`);

      if (startInput && !startInput.value) {
        startInput.value = datePartFromIso(schedules[activeIndex].project_start);
      }
    });
  }

  document.querySelectorAll(`[data-quick-schedule="${index}"]`).forEach((btn) => {
    btn.addEventListener("click", () => {
      const quickType = btn.dataset.quickType || "";
      const result = applyQuickScheduleTypeForSegment(index, quickType);
      setSchedulerSummary(index, result.msg, !result.ok);
    });
  });

  if (addWindowBtn) {
    addWindowBtn.addEventListener("click", () => {
      const result = addCustomScheduleWindow(index);
      setSchedulerSummary(index, result.msg, !result.ok);
    });
  }

  if (copyBtn) {
    copyBtn.addEventListener("click", () => {
      const result = copySchedulesToAllSegments(index);
      setSchedulerSummary(index, result.msg, !result.ok);
    });
  }

  renderScheduleWindowsEditor(index);
}

export function renderTimeCardsStep3() {
  const host = document.getElementById("multiSegmentTimeList");
  if (!host) return;

  host.innerHTML = "";

  state.applyWizard.segments.forEach((seg, index) => {
    ensureSegmentSchedules(seg);
    syncSegmentProjectRange(seg);

    const startDateValue = seg.planningAnchorDate || datePartFromIso(seg.projectStart);
    seg.planningAnchorDate = startDateValue;
    const card = document.createElement("div");
    card.className = "review-card planning-card";
    card.innerHTML = `
      <h4>Planning for target ${index + 1}</h4>
      <p class="planning-segment-title">
        <span class="target-type-badge">${esc(getTargetTypeLabel(seg))}</span>
        ${esc(getTargetReviewLabel(seg))}
      </p>
      <p class="hint">${esc(getTargetSubtitle(seg))}</p>

      <div class="field">
        <label>Work date / week anchor</label>
        <input type="date" id="seg_${index}_startDate" value="${esc(startDateValue)}">
      </div>

      <div class="quick-schedule-row" aria-label="Quick planning presets">
        <button type="button" class="btn quick-schedule-btn" data-quick-schedule="${index}" data-quick-type="day">Day 07:00-17:00</button>
        <button type="button" class="btn quick-schedule-btn" data-quick-schedule="${index}" data-quick-type="night">Night 23:00-05:00</button>
        <button type="button" class="btn quick-schedule-btn" data-quick-schedule="${index}" data-quick-type="weekend">Weekend Sat/Sun</button>
      </div>

      <div class="schedule-actions-row">
        <button type="button" class="btn quick-schedule-btn" data-add-window="${index}">+ Add custom window</button>
        <button type="button" class="btn quick-schedule-btn" data-copy-schedules="${index}">Copy schedule to all selected targets</button>
      </div>

      <div id="schedulerSummary_${index}" class="form-result scheduler-summary-inline"></div>

      <div id="scheduleWindows_${index}" class="schedule-window-list"></div>

      <details class="scheduler-advanced">
        <summary>Advanced week calendar</summary>
        <div class="scheduler-wrap">
          <div id="scheduler_${index}" class="scheduler-placeholder">Load week calendar only when you need manual slot selection.</div>
        </div>
        <div class="form-actions scheduler-advanced-actions">
          <button type="button" class="btn" data-build-scheduler="${index}">Load week calendar</button>
          <button type="button" class="btn btn-apply" data-set-time="${index}">Set time to active window</button>
        </div>
      </details>
    `;
    host.appendChild(card);
  });

  state.applyWizard.segments.forEach((seg, index) => {
    createSchedulerCard(index, seg);
  });
}
