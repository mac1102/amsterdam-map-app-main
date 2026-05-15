import { state } from "./state.js";
import { dom } from "./dom.js";
import { renderFavorites } from "./favorites.js";
import { renderFilterList } from "./filters.js";

export const I18N = {
  en: {
    app_title: "Tram communication map",
    hero_title: "Help Us Coordinate",
    hero_desc: "Statistics and price of unsafe working conditions",
    view_map: "View map",
    list_view: "List View",
    safety_info: "Safety info",
    selection_title: "Selection",
    select_tram_line: "Select tram line",
    select_tram_line_hint: "Type to search, then choose a tram line.",
    no_selection_yet: "No selection yet.",
    filter_lines: "Filter lines",
    show_all: "Show all",
    hide_all: "Hide all",
    filter_search_placeholder: "Search lines…",
    apply_for_project: "Apply for project",
    actions_hint_default: "Available after selecting a tram line or segment.",
    scroll_up_hint: "Scroll up to return to the welcome page.",
    favorites_title: "Favorite tram lines",
    favorites_hint: "Click a favorite to select & highlight it.",
    favorites_empty: "No favorite tram lines yet.",
    clear_favorites: "Clear favorites",
    remove: "Remove",
    safety_modal_title: "Safety: risks of overlapping schedules",
    safety_modal_body: "Overlapping or conflicting schedules can create safety and reliability risks, especially where multiple lines share the same track sections, platforms, or junctions.",
    apply_modal_title: "Apply for project",
    first_name: "First name *",
    last_name: "Last name *",
    phone: "Phone number *",
    email: "Email address *",
    employee_id: "Employee ID (optional)",
    upload_safety_plans: "Upload safety plan(s) *",
    upload_hint: "Upload PDF/DOC/DOCX or images. You can select multiple files.",
    event_days: "Event days *",
    start_date: "Start date",
    end_date: "End date",
    four_week_hint: "Start date must be at least 4 weeks from today.",
    submit_application: "Submit application",
    cancel: "Cancel",
    login: "Log in",
    logout: "Logout",
    login_title: "Log in",
    login_email: "Email",
    login_password: "Password",
    login_submit: "Log in",
    login_required_title: "Login required",
    login_required_msg: "You must log in before applying for a project.",
    login_action: "Log in",
    my_applications: "My applications",
    loading: "Loading…",
    no_applications: "No applications yet.",
    hover_login_needed: "Log in to see your application status.",
    search_placeholder: "Search…",
    no_results: "No matching tram lines."
  },
  nl: {
    app_title: "Tram communicatiekaart",
    hero_title: "Help ons coördineren",
    hero_desc: "Statistieken en kosten van onveilige werkomstandigheden",
    view_map: "Bekijk kaart",
    list_view: "Lijstweergave",
    safety_info: "Veiligheidsinfo",
    selection_title: "Selectie",
    select_tram_line: "Selecteer tramlijn",
    select_tram_line_hint: "Typ om te zoeken en kies daarna een tramlijn.",
    no_selection_yet: "Nog geen selectie.",
    filter_lines: "Lijnen filteren",
    show_all: "Alles tonen",
    hide_all: "Alles verbergen",
    filter_search_placeholder: "Lijnen zoeken…",
    apply_for_project: "Aanvragen voor project",
    actions_hint_default: "Beschikbaar na het kiezen van een tramlijn of segment.",
    scroll_up_hint: "Scroll omhoog om terug te gaan naar de startpagina.",
    favorites_title: "Favoriete tramlijnen",
    favorites_hint: "Klik op een favoriet om te selecteren en te markeren.",
    favorites_empty: "Nog geen favoriete tramlijnen.",
    clear_favorites: "Favorieten wissen",
    remove: "Verwijderen",
    safety_modal_title: "Veiligheid: risico’s bij overlappende planningen",
    safety_modal_body: "Overlappende of conflicterende planningen kunnen veiligheids- en betrouwbaarheidrisico’s veroorzaken, vooral waar meerdere lijnen dezelfde sporen, perrons of wissels delen.",
    apply_modal_title: "Aanvragen voor project",
    first_name: "Voornaam *",
    last_name: "Achternaam *",
    phone: "Telefoonnummer *",
    email: "E-mailadres *",
    employee_id: "Medewerker-ID (optioneel)",
    upload_safety_plans: "Veiligheidsplan(nen) uploaden *",
    upload_hint: "Upload PDF/DOC/DOCX of afbeeldingen. Je kunt meerdere bestanden kiezen.",
    event_days: "Evenementdagen *",
    start_date: "Startdatum",
    end_date: "Einddatum",
    four_week_hint: "Startdatum moet minimaal 4 weken vanaf vandaag zijn.",
    submit_application: "Aanvraag versturen",
    cancel: "Annuleren",
    login: "Inloggen",
    logout: "Uitloggen",
    login_title: "Inloggen",
    login_email: "E-mail",
    login_password: "Wachtwoord",
    login_submit: "Inloggen",
    login_required_title: "Inloggen vereist",
    login_required_msg: "Je moet eerst inloggen om een project aan te vragen.",
    login_action: "Inloggen",
    my_applications: "Mijn aanvragen",
    loading: "Laden…",
    no_applications: "Nog geen aanvragen.",
    hover_login_needed: "Log in om je aanvraagstatus te zien.",
    search_placeholder: "Zoeken…",
    no_results: "Geen passende tramlijnen."
  }
};

export function t(key) {
  const dict = I18N[state.currentLang] || I18N.en;
  return dict[key] ?? I18N.en[key] ?? key;
}

export function loadLang() {
  try {
    const v = localStorage.getItem("gvbLang");
    if (v === "nl" || v === "en") return v;
  } catch {}
  return "en";
}

export function setLang(lang) {
  state.currentLang = lang === "nl" ? "nl" : "en";
  try { localStorage.setItem("gvbLang", state.currentLang); } catch {}
  if (dom.langSelect) dom.langSelect.value = state.currentLang;
  applyTranslations();
}

export function applyTranslations() {
  document.documentElement.lang = state.currentLang;
  for (const el of document.querySelectorAll("[data-i18n]")) {
    el.textContent = t(el.getAttribute("data-i18n"));
  }
  if (dom.lineSelect) dom.lineSelect.placeholder = t("search_placeholder");
  if (dom.filterSearch) dom.filterSearch.placeholder = t("filter_search_placeholder");
  renderFavorites();
  renderFilterList();
}