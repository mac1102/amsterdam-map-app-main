import { state } from "../state.js";
import { esc } from "../utils.js";
import { getTargetReviewLabel, getTargetSubtitle } from "./apply-map.js";
import { VVW_MEASURES } from "./apply-validate.js";

export function defaultContactDetails() {
  return {
    coordinator: "",
    contactName: "",
    contactPhone: "",
    contactEmail: "",
    vvwMeasure: "BB",
  };
}

export function ensurePeopleBySegmentLength() {
  const needed = state.applyWizard.segments.length;
  state.applyWizard.peopleBySegment = Array.from({ length: needed }, (_, i) => {
    return state.applyWizard.peopleBySegment[i] || {
      firstName: "",
      lastName: "",
      phone: "",
      email: "",
      employeeId: "",
    };
  });
}

export function renderPersonModeStep4() {
  const host = document.getElementById("personModeForms");
  if (!host) return;

  host.innerHTML = "";

  const radios = document.querySelectorAll('input[name="personModeChoice"]');
  radios.forEach(r => {
    r.checked = r.value === state.applyWizard.personMode;
    r.onchange = () => {
      state.applyWizard.personMode = r.value;
      renderPersonModeStep4();
    };
  });

  if (state.applyWizard.personMode === "single") {
    host.innerHTML = `
      <div class="review-card">
        <h4>Personal information</h4>
        <div class="form-grid">
          <div class="field"><label>First name *</label><input id="sharedFirstName" type="text" value="${esc(state.applyWizard.sharedPerson.firstName)}"></div>
          <div class="field"><label>Last name *</label><input id="sharedLastName" type="text" value="${esc(state.applyWizard.sharedPerson.lastName)}"></div>
          <div class="field"><label>Phone *</label><input id="sharedPhone" type="text" value="${esc(state.applyWizard.sharedPerson.phone)}"></div>
          <div class="field"><label>Email *</label><input id="sharedEmail" type="email" value="${esc(state.applyWizard.sharedPerson.email)}"></div>
          <div class="field"><label>Employee ID</label><input id="sharedEmployeeId" type="text" value="${esc(state.applyWizard.sharedPerson.employeeId)}"></div>
        </div>
      </div>
    `;
  } else {
    state.applyWizard.segments.forEach((seg, index) => {
      const person = state.applyWizard.peopleBySegment[index];
      const card = document.createElement("div");
      card.className = "review-card";
      card.innerHTML = `
        <h4>Person for target ${index + 1}</h4>
        <p>${esc(getTargetReviewLabel(seg))}</p>
        <p class="hint">${esc(getTargetSubtitle(seg))}</p>
        <div class="form-grid">
          <div class="field"><label>First name *</label><input id="person_${index}_first" type="text" value="${esc(person.firstName)}"></div>
          <div class="field"><label>Last name *</label><input id="person_${index}_last" type="text" value="${esc(person.lastName)}"></div>
          <div class="field"><label>Phone *</label><input id="person_${index}_phone" type="text" value="${esc(person.phone)}"></div>
          <div class="field"><label>Email *</label><input id="person_${index}_email" type="email" value="${esc(person.email)}"></div>
          <div class="field"><label>Employee ID</label><input id="person_${index}_employee" type="text" value="${esc(person.employeeId)}"></div>
        </div>
      `;
      host.appendChild(card);
    });
  }

  renderContactVvwStep4();
}

export function renderContactVvwStep4() {
  const host = document.getElementById("contactVvwForms");
  if (!host) return;

  const contact = {
    ...defaultContactDetails(),
    ...(state.applyWizard.contactDetails || {}),
  };
  state.applyWizard.contactDetails = contact;

  host.innerHTML = `
    <div class="review-card wizard-card-compact contact-vvw-card">
      <h4>Department / team / coordinator</h4>
      <div class="form-grid">
        <div class="field">
          <label for="contactCoordinator">Department / team / coordinator</label>
          <input id="contactCoordinator" type="text" value="${esc(contact.coordinator)}" placeholder="Example: Coordinatie Tram">
        </div>
        <div class="field">
          <label for="contactName">Contact name</label>
          <input id="contactName" type="text" value="${esc(contact.contactName)}" placeholder="Optional contact person">
        </div>
        <div class="field">
          <label for="contactPhone">Contact phone</label>
          <input id="contactPhone" type="text" value="${esc(contact.contactPhone)}" placeholder="Optional phone number">
        </div>
        <div class="field">
          <label for="contactEmail">Contact email</label>
          <input id="contactEmail" type="email" value="${esc(contact.contactEmail)}" placeholder="Optional email address">
        </div>
      </div>

      <div class="field">
        <label>Expected VVW measure *</label>
        <div class="vvw-measure-grid">
          ${VVW_MEASURES.map(code => `
            <button
              type="button"
              class="vvw-measure-btn ${contact.vvwMeasure === code ? "is-active" : ""}"
              data-vvw-measure="${esc(code)}"
            >${esc(code)}</button>
          `).join("")}
        </div>
      </div>
    </div>
  `;

  document.getElementById("contactCoordinator")?.addEventListener("input", (e) => {
    state.applyWizard.contactDetails.coordinator = e.target.value;
  });
  document.getElementById("contactName")?.addEventListener("input", (e) => {
    state.applyWizard.contactDetails.contactName = e.target.value;
  });
  document.getElementById("contactPhone")?.addEventListener("input", (e) => {
    state.applyWizard.contactDetails.contactPhone = e.target.value;
  });
  document.getElementById("contactEmail")?.addEventListener("input", (e) => {
    state.applyWizard.contactDetails.contactEmail = e.target.value;
  });

  document.querySelectorAll("[data-vvw-measure]").forEach((btn) => {
    btn.addEventListener("click", () => {
      state.applyWizard.contactDetails.vvwMeasure = btn.dataset.vvwMeasure || "BB";
      renderContactVvwStep4();
    });
  });
}

export function collectContactDetailsStep4() {
  state.applyWizard.contactDetails = {
    ...defaultContactDetails(),
    coordinator: document.getElementById("contactCoordinator")?.value.trim() || state.applyWizard.contactDetails?.coordinator?.trim() || "",
    contactName: document.getElementById("contactName")?.value.trim() || state.applyWizard.contactDetails?.contactName?.trim() || "",
    contactPhone: document.getElementById("contactPhone")?.value.trim() || state.applyWizard.contactDetails?.contactPhone?.trim() || "",
    contactEmail: document.getElementById("contactEmail")?.value.trim() || state.applyWizard.contactDetails?.contactEmail?.trim() || "",
    vvwMeasure: state.applyWizard.contactDetails?.vvwMeasure || "BB",
  };
}

export function collectStep4Data() {
  if (state.applyWizard.personMode === "single") {
    state.applyWizard.sharedPerson = {
      firstName: document.getElementById("sharedFirstName")?.value.trim() || "",
      lastName: document.getElementById("sharedLastName")?.value.trim() || "",
      phone: document.getElementById("sharedPhone")?.value.trim() || "",
      email: document.getElementById("sharedEmail")?.value.trim() || "",
      employeeId: document.getElementById("sharedEmployeeId")?.value.trim() || "",
    };
  } else {
    state.applyWizard.peopleBySegment = state.applyWizard.segments.map((_, index) => ({
      firstName: document.getElementById(`person_${index}_first`)?.value.trim() || "",
      lastName: document.getElementById(`person_${index}_last`)?.value.trim() || "",
      phone: document.getElementById(`person_${index}_phone`)?.value.trim() || "",
      email: document.getElementById(`person_${index}_email`)?.value.trim() || "",
      employeeId: document.getElementById(`person_${index}_employee`)?.value.trim() || "",
    }));
  }

  collectContactDetailsStep4();
}
