import { state } from "./state.js";
import { t } from "./i18n.js";

function findTourElement(selector) {
  try {
    return document.querySelector(selector);
  } catch (e) {
    return null;
  }
}

let helpHandlerWired = false;
let autoStartScheduled = false;

function markTourSeen() {
  try {
    localStorage.setItem("gvbTourSeen", "1");
  } catch {}
}

function hasSeenTour() {
  try {
    return !!localStorage.getItem("gvbTourSeen");
  } catch {
    return false;
  }
}

function attachIfPresent(selector, on = "bottom") {
  const element = findTourElement(selector);
  if (!element) return undefined;
  const rect = element.getBoundingClientRect();
  if (rect.width === 0 && rect.height === 0) return undefined;
  return { element, on };
}

function buildStep(tour, step) {
  const nextButton = {
    text: t("tour_next"),
    classes: "shepherd-button-primary",
    action: () => tour.next(),
  };
  const backButton = {
    text: t("tour_back"),
    classes: "shepherd-button-secondary",
    action: () => tour.back(),
  };

  const stepConfig = {
    id: step.id,
    text: step.text,
    buttons: step.buttons === "finish"
      ? [{
          text: t("tour_done"),
          classes: "shepherd-button-primary",
          action: () => {
            markTourSeen();
            tour.complete();
          },
        }]
      : step.buttons === "welcome"
        ? [{
            text: t("tour_skip"),
            classes: "shepherd-button-secondary",
            action: () => {
              markTourSeen();
              tour.cancel();
            },
          }, nextButton]
        : [backButton, nextButton],
  };

  if (step.selector) {
    const attachTo = attachIfPresent(step.selector, step.on);
    if (attachTo) stepConfig.attachTo = attachTo;
  }

  tour.addStep(stepConfig);
}

export function startTour(_options = {}) {
  if (!window.Shepherd) {
    window.addEventListener("shepherd:ready", () => startTour(_options), { once: true });
    setTimeout(() => {
      if (!window.Shepherd) {
        console.warn("[tour] Shepherd.js failed to load; help tour unavailable.");
      }
    }, 5000);
    return;
  }

  if (window._gvbTour) {
    window._gvbTour.complete();
    window._gvbTour = null;
  }

  const tour = new window.Shepherd.Tour({
    useModalOverlay: true,
    defaultStepOptions: {
      cancelIcon: {
        enabled: true,
        label: t("tour_skip_label"),
      },
      classes: "gvb-shepherd-step",
      scrollTo: {
        behavior: "smooth",
        block: "center",
      },
    },
  });

  window._gvbTour = tour;

  tour.on("complete", markTourSeen);
  tour.on("cancel", markTourSeen);

  [
    {
      id: "welcome",
      text: t("tour_welcome"),
      buttons: "welcome",
    },
    {
      id: "map",
      selector: "#map",
      on: "right",
      text: t("tour_map"),
    },
    {
      id: "layers",
      selector: "#mapLayerPanel",
      on: "right",
      text: t("tour_layers"),
    },
    {
      id: "kge-layer",
      selector: '[data-layer-key="kgeModelGauge"]',
      on: "right",
      text: t("tour_kge_layer"),
    },
    {
      id: "select-segment",
      selector: "#map",
      on: "right",
      text: t("tour_select_segment"),
    },
    {
      id: "apply-button",
      selector: "#projectActions",
      on: "left",
      text: t("tour_apply_button"),
    },
    {
      id: "wizard-overview",
      text: t("tour_wizard_overview"),
    },
    {
      id: "wizard-nav",
      text: t("tour_wizard_nav"),
    },
    {
      id: "timeline",
      selector: "#timelineBar",
      on: "top",
      text: t("tour_timeline"),
    },
    {
      id: "transfer",
      selector: "#timelineTransferBtn",
      on: "top",
      text: t("tour_transfer"),
    },
    {
      id: "feedback",
      selector: ".btn-feedback",
      on: "top",
      text: t("tour_feedback"),
    },
    {
      id: "finish",
      text: t("tour_finish"),
      buttons: "finish",
    },
  ].forEach((step) => buildStep(tour, step));

  tour.start();
}

export function wireHelpButton() {
  if (helpHandlerWired) return;
  helpHandlerWired = true;

  document.addEventListener("click", (e) => {
    const target = e.target.closest && e.target.closest("#helpTourBtn");
    if (target) {
      e.preventDefault();
      startTour({ force: true });
    }
  });
}

export function maybeInitTour() {
  wireHelpButton();

  if (autoStartScheduled) return;
  autoStartScheduled = true;

  setTimeout(() => {
    if (state.currentUser && !hasSeenTour()) {
      startTour();
    }
  }, 1500);
}

if (typeof document !== "undefined") {
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", wireHelpButton, { once: true });
  } else {
    wireHelpButton();
  }
}
