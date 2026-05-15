import { state } from "../state.js";
import { addDays } from "../utils.js";
import { getTargetReviewLabel } from "./apply-map.js";
import {
  ensureSegmentSchedules,
  MAX_SCHEDULE_WINDOWS,
  parseLocalIsoToDate,
  startOfDay,
  syncSegmentProjectRange,
} from "./apply-scheduler.js";
import { collectWorkDetailsStep2 } from "./apply-wizard.js";
import { collectStep4Data } from "./apply-people.js";

export const WORK_SOURCES = ["Civielwerk", "Onderhoud", "DO werkzaamheden", "Spoed", "Derden"];
export const URGENCY_OPTIONS = [
  { value: "normal", label: "Normal" },
  { value: "high", label: "High" },
  { value: "urgent", label: "Urgent" },
];
export const VVW_MEASURES = ["BB", "BD", "BT-A", "BT-L", "FA", "PW", "AG"];

export function validateStep1() {
  for (const seg of state.applyWizard.segments) {
    if (seg.workMode === "custom-area" && (!seg.workStartPoint || !seg.workEndPoint)) {
      return { ok: false, msg: `Please complete pin placement for ${getTargetReviewLabel(seg)}.` };
    }
  }
  return { ok: true };
}

export function validateStep2() {
  collectWorkDetailsStep2();

  const details = state.applyWizard.workDetails;
  if (!details.description) {
    return { ok: false, msg: "Please enter a work description." };
  }
  if (!details.source) {
    return { ok: false, msg: "Please choose a work source/type." };
  }
  if (!WORK_SOURCES.includes(details.source)) {
    return { ok: false, msg: "Please choose a valid work source/type." };
  }
  if (!details.urgency) {
    return { ok: false, msg: "Please choose an urgency." };
  }
  if (!URGENCY_OPTIONS.some(option => option.value === details.urgency)) {
    return { ok: false, msg: "Please choose a valid urgency." };
  }

  return { ok: true };
}

export function validateStep4() {
  collectStep4Data();

  if (state.applyWizard.personMode === "single") {
    const p = state.applyWizard.sharedPerson;
    if (!p.firstName || !p.lastName || !p.phone || !p.email) {
      return { ok: false, msg: "Please complete the shared personal information." };
    }
  } else {
    for (let i = 0; i < state.applyWizard.peopleBySegment.length; i += 1) {
      const p = state.applyWizard.peopleBySegment[i];
      if (!p.firstName || !p.lastName || !p.phone || !p.email) {
        return { ok: false, msg: `Please complete personal information for target ${i + 1}.` };
      }
    }
  }

  const files = document.getElementById("safetyPlans")?.files || [];
  if (!files.length) {
    return { ok: false, msg: "Please upload at least one safety plan." };
  }

  if (!state.applyWizard.contactDetails.vvwMeasure) {
    return { ok: false, msg: "Please choose the expected VVW measure." };
  }
  if (!VVW_MEASURES.includes(state.applyWizard.contactDetails.vvwMeasure)) {
    return { ok: false, msg: "Please choose a valid expected VVW measure." };
  }

  return { ok: true };
}

export function validateStep3() {
  const minStartDate = addDays(new Date(), 28);
  minStartDate.setHours(0, 0, 0, 0);

  for (let i = 0; i < state.applyWizard.segments.length; i += 1) {
    const seg = state.applyWizard.segments[i];
    const schedules = ensureSegmentSchedules(seg);

    if (!schedules.length) {
      return { ok: false, msg: `Target ${i + 1}: at least one schedule window is required.` };
    }

    if (schedules.length > MAX_SCHEDULE_WINDOWS) {
      return { ok: false, msg: `Target ${i + 1}: maximum ${MAX_SCHEDULE_WINDOWS} schedule windows allowed.` };
    }

    for (let scheduleIndex = 0; scheduleIndex < schedules.length; scheduleIndex += 1) {
      const schedule = schedules[scheduleIndex];
      const projectStart = String(schedule.project_start || "").trim();
      const projectEnd = String(schedule.project_end || "").trim();

      if (!projectStart || !projectEnd) {
        return { ok: false, msg: `Target ${i + 1}, window ${scheduleIndex + 1}: start and end are required.` };
      }

      const startDt = parseLocalIsoToDate(projectStart);
      const endDt = parseLocalIsoToDate(projectEnd);

      if (!startDt || !endDt) {
        return { ok: false, msg: `Target ${i + 1}, window ${scheduleIndex + 1}: invalid date/time.` };
      }

      if (endDt <= startDt) {
        return { ok: false, msg: `Target ${i + 1}, window ${scheduleIndex + 1}: end must be after start.` };
      }

      const startDay = startOfDay(startDt);
      if (startDay < minStartDate) {
        return { ok: false, msg: `Target ${i + 1}, window ${scheduleIndex + 1}: start must be at least 4 weeks from today.` };
      }
    }

    syncSegmentProjectRange(seg);
  }

  return { ok: true };
}

export function validateCurrentStep() {
  if (state.applyWizard.step === 1) return validateStep1();
  if (state.applyWizard.step === 2) return validateStep2();
  if (state.applyWizard.step === 3) return validateStep3();
  if (state.applyWizard.step === 4) return validateStep4();
  return { ok: true };
}
