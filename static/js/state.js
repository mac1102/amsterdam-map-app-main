export const state = {
  map: null,
  tileLayer: null,
  mapLayers: new Map(),
  mapLayerOrder: [],
  mapLayerVisibility: {},
  mapLayerCollapsed: false,
  mapLayerPrefsLoaded: false,

  segmentLayers: new Map(),
  switchLayers: new Map(),
  switchSegmentLayers: new Map(),
  overheadLayers: new Map(),
  lineIndex: new Map(),
  segmentsByLine: new Map(),
  allSegments: [],
  wiorLayer: null,
  wiorFilterMode: "active",

  maxZoom: 4,
  imageW: 2000,
  imageH: 1400,

  currentSelection: null,
  favorites: new Set(),
  currentUser: null,
  applicationTargetHighlightLayer: null,
  applicationTargetHighlightTimeout: null,

  visibleLineIds: new Set(),
  savedVisibleLineIds: null,

  spotlightLineId: "",
  highlightedLineId: "",
  highlightedLineIds: new Set(),
  selectedSegmentId: null,
  selectedTargetKeys: new Set(),
  suppressNextMapClear: false,

  lineStatusCache: new Map(),

  lineItems: [],
  comboOpen: false,
  comboActiveIndex: -1,
  comboFiltered: [],

  currentLang: "en",

  applyWizard: {
    step: 1,
    personMode: "single",
    segments: [],
    sharedPerson: {
      firstName: "",
      lastName: "",
      phone: "",
      email: "",
      employeeId: "",
    },
    peopleBySegment: [],
    workDetails: {
      description: "",
      source: "Civielwerk",
      urgency: "normal",
      affectedLines: "",
      notes: "",
    },
    contactDetails: {
      coordinator: "",
      contactName: "",
      contactPhone: "",
      contactEmail: "",
      vvwMeasure: "BB",
    },
  },

  applySubmission: {
    isSubmitting: false,
    successModal: {
      open: false,
      applicationId: null,
    },
  },

  timeline: {
    enabled: true,
    selectedDate: null,
    overview: [],
    dayItems: [],
    loading: false,
    error: "",
    highlightLayer: null,
    rangeStart: null,
    days: 84,
    wiorBaseLayer: null,
    wiorFilteredLayer: null,
    previousWiorVisible: null,
  },

  segmentPreviews: [],
  schedulerBySegment: [],

  schedulerDefaults: {
    slotMinutes: 30,
    startHour: 6,
    endHour: 23,
  },

  transferTrip: {
    active: false,
    step: 1,
    startStop: null,
    endStop: null,
    routeResult: null,
    routeError: "",
    routeLayer: null,
    startMarker: null,
    endMarker: null,
    savedLayerVisibility: null,
    savedSpecialLayerState: null,
    plannedDate: "",
    plannedStartTime: "09:00",
    plannedEndTime: "11:00",
    tramNumber: "",
    reason: "",
    notes: "",
    isSubmitting: false,
  },
};

export const STYLE_BASE = { weight: 9, opacity: 0.35 };
export const STYLE_DIM = { weight: 7, opacity: 0.12 };
export const STYLE_SEL = { weight: 16, opacity: 1 };
