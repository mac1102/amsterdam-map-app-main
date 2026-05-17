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
    settings: "Settings",
    activity: "Activity",
    activity_loading: "Loading activity...",
    activity_empty: "No activity recorded yet.",
    activity_error: "Could not load activity.",
    my_applications: "My applications",
    loading: "Loading…",
    no_applications: "No applications yet.",
    hover_login_needed: "Log in to see your application status.",
    search_placeholder: "Search…",
    no_results: "No matching tram lines.",

    // Top utility / nav
    status_loading: "Loading...",
    status_ready: "Ready",
    status_login_required: "Login to load map data",
    account_label: "Account",
    account_menu_aria: "Account menu",
    manage_applications: "Manage applications",
    plan_work: "Plan Work",
    help: "Help",

    // Hero / quick widget
    active_alert: "Active Alert",
    alert_body: "Overlapping or conflicting schedules can create safety and reliability risks.",
    quick_access: "Quick Access",
    quick_access_desc: "Choose how you want to view the network and coordinate work.",
    manuals: "Manuals",

    // Quick links
    network_map: "Network Map",
    all_lines: "All Lines",
    safety_rules: "Safety Rules",

    // Info blocks
    info_why_title: "Why use the coordination map?",
    info_why_body: "Overlapping schedules create safety risks. Our tool automatically detects conflicts where multiple lines share track sections, platforms, or junctions.",
    info_why_li1: "Real-time conflict detection",
    info_why_li2: "Direct approval workflow",
    info_why_li3: "Mobile-friendly for on-site use",
    info_read_more: "Read the safety guidelines",
    info_process_title: "Application Process",
    info_process_body: "Applying for a project work area is mandatory. Follow the 4 steps to get your project approved safely by the network control center.",
    info_process_step1: "Select segment or custom area",
    info_process_step2: "Upload required documents (PDF/DOCX)",
    info_process_step3: "Set specific time blocks",
    info_process_step4: "Review and submit",

    // Transfer banner / panel
    transfer_intekenen: "Overbrengsrit intekenen",
    transfer_click_start: "Click a start tram stop",
    transfer_undo_last: "Undo last",
    transfer_reset: "Reset",
    transfer_close: "Close",
    transfer_aanvragen: "Overbrengsrit aanvragen",
    transfer_route: "Route",
    transfer_start: "Start",
    transfer_end: "End",
    transfer_distance: "Distance",
    transfer_select_two_stops: "Select two tram stops.",
    transfer_back: "Back",
    transfer_continue: "Continue",
    transfer_submit: "Submit Transfer Trip",
    transfer_button: "Overbrengsrit",

    // Map layers panel
    map_layers: "MAP LAYERS",
    layer_order: "Order",
    layer_priority_low: "LOW",
    layer_active_count: "active",

    // Timeline
    timeline_title: "Timeline werkzaamheden",
    timeline_loading: "Loading timeline...",
    timeline_legend_internal: "Internal",
    timeline_legend_warning: "BB/Warning",
    timeline_prev_week: "< Week",
    timeline_next_week: "Week >",
    timeline_reset: "Reset",
    feedback_btn: "Feedback",

    // Filter block
    filter_hide: "Hide",
    filter_show: "Show",
    filter_search_lines: "Search lines...",

    // Favorites
    add_to_favorites: "Add line to favorite",

    // Apply wizard
    apply_step_of: "Step {n} of 5",
    wizard_step1: "Step 1 - Location",
    wizard_step2: "Step 2 - Work details",
    wizard_step3: "Step 3 - Planning",
    wizard_step4: "Step 4 - Contact & VVW",
    wizard_step5: "Step 5 - Review",
    wizard_step1_hint: "You can apply for up to 3 selected segments. For each segment, choose whole segment or custom area.",
    wizard_step3_hint: "Set one time block for each selected segment.",
    wizard_person_single: "One person for all selected segments",
    wizard_person_multi: "Different person for each segment",
    apply_back: "Back",
    apply_next: "Next",
    apply_submit: "Submit application",

    // Apply success
    apply_success_title: "Application submitted",
    apply_success_text: "Your application has been submitted successfully.",
    apply_success_reference: "Reference:",
    apply_success_view: "View my applications",
    apply_success_close: "Close",

    // My applications
    apps_loading: "Loading applications...",

    // Footer
    footer_about: "Internal tool for coordinating track work, maintenance, and projects across the Amsterdam tram network.",
    footer_quick_links: "Quick Links",
    footer_support: "Support",
    footer_contact: "Contact Control Center",
    footer_safety_manuals: "Safety Manuals",
    footer_report: "Report an Issue",
    footer_copyright: "© 2026 GVB Amsterdam. All rights reserved.",
    footer_privacy: "Privacy",
    footer_terms: "Terms",
    footer_cookies: "Cookies",

    // Tour
    tour_next: "Next",
    tour_back: "Back",
    tour_done: "Done",
    tour_skip: "Skip",
    tour_skip_label: "Skip tour",
    tour_welcome: "Welcome to the GVB tram coordination map. This short tour shows you how to submit a work application.",
    tour_map: "This is the map. It shows tram infrastructure - rails, switches, and overhead lines. You'll select segments here to apply for work.",
    tour_layers: "Toggle map layers on or off here: KGE rail, switches, overhead sections, WIOR, and TBGN. <br><br><strong>Note:</strong> the layer at the top of this list is the most recently selected layer and is drawn on top of the others on the map.",
    tour_kge_layer: "Make sure <strong>KGE rail segments</strong> is enabled - these are the green rail lines you can apply work for.",
    tour_select_segment: "Now click a <strong>green KGE rail segment</strong> on the map. You can select up to 3 segments per application. Selected segments appear in the side panel.",
    tour_apply_button: "After selecting at least one segment, an <strong>Apply for project</strong> button appears in the side panel. Click it to open the 5-step wizard.",
    tour_wizard_overview: "The wizard has 5 steps:<br><br><strong>1. Location</strong> - confirm the selected segment(s) and pick whole-segment or a custom area.<br><strong>2. Work details</strong> - describe the work and affected lines.<br><strong>3. Planning</strong> - set a date and time block for each segment.<br><strong>4. Contact & VVW</strong> - enter contact details and upload the safety plan (PDF/DOC/image).<br><strong>5. Review</strong> - check everything and submit.",
    tour_wizard_nav: "Use <strong>Next</strong> and <strong>Back</strong> at the bottom of the wizard to move between steps. Required fields must be filled before you can advance. On Step 5, press <strong>Submit</strong> to send the application.",
    tour_timeline: "The timeline shows planned activity by day and week. Click a day to filter the map by date.",
    tour_transfer: "Use Overbrengsrit to plan a tram transfer trip between two stops.",
    tour_feedback: "Use Feedback to report issues or suggest improvements.",
    tour_finish: "Tour complete. You can replay it anytime by clicking <strong>Help</strong> in the top nav."
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
    settings: "Instellingen",
    activity: "Activiteit",
    activity_loading: "Activiteit laden...",
    activity_empty: "Nog geen activiteit vastgelegd.",
    activity_error: "Activiteit kon niet worden geladen.",
    my_applications: "Mijn aanvragen",
    loading: "Laden…",
    no_applications: "Nog geen aanvragen.",
    hover_login_needed: "Log in om je aanvraagstatus te zien.",
    search_placeholder: "Zoeken…",
    no_results: "Geen passende tramlijnen.",

    // Top utility / nav
    status_loading: "Laden...",
    status_ready: "Gereed",
    status_login_required: "Log in om kaartgegevens te laden",
    account_label: "Account",
    account_menu_aria: "Accountmenu",
    manage_applications: "Aanvragen beheren",
    plan_work: "Werk plannen",
    help: "Help",

    // Hero / quick widget
    active_alert: "Actieve melding",
    alert_body: "Overlappende of conflicterende planningen kunnen veiligheids- en betrouwbaarheidsrisico's veroorzaken.",
    quick_access: "Snelle toegang",
    quick_access_desc: "Kies hoe je het netwerk wilt bekijken en werkzaamheden wilt coördineren.",
    manuals: "Handleidingen",

    // Quick links
    network_map: "Netwerkkaart",
    all_lines: "Alle lijnen",
    safety_rules: "Veiligheidsregels",

    // Info blocks
    info_why_title: "Waarom de coördinatiekaart gebruiken?",
    info_why_body: "Overlappende planningen veroorzaken veiligheidsrisico's. Onze tool detecteert automatisch conflicten waar meerdere lijnen dezelfde sporen, perrons of wissels delen.",
    info_why_li1: "Realtime conflictdetectie",
    info_why_li2: "Directe goedkeuringsworkflow",
    info_why_li3: "Mobielvriendelijk voor gebruik op locatie",
    info_read_more: "Lees de veiligheidsrichtlijnen",
    info_process_title: "Aanvraagproces",
    info_process_body: "Een werkgebied aanvragen is verplicht. Volg de 4 stappen om je project veilig te laten goedkeuren door het netwerkcontrolecentrum.",
    info_process_step1: "Selecteer segment of aangepast gebied",
    info_process_step2: "Upload vereiste documenten (PDF/DOCX)",
    info_process_step3: "Stel specifieke tijdsblokken in",
    info_process_step4: "Controleer en verstuur",

    // Transfer banner / panel
    transfer_intekenen: "Overbrengsrit intekenen",
    transfer_click_start: "Klik op een begin-tramhalte",
    transfer_undo_last: "Laatste ongedaan maken",
    transfer_reset: "Resetten",
    transfer_close: "Sluiten",
    transfer_aanvragen: "Overbrengsrit aanvragen",
    transfer_route: "Route",
    transfer_start: "Start",
    transfer_end: "Eind",
    transfer_distance: "Afstand",
    transfer_select_two_stops: "Selecteer twee tramhaltes.",
    transfer_back: "Terug",
    transfer_continue: "Doorgaan",
    transfer_submit: "Overbrengsrit versturen",
    transfer_button: "Overbrengsrit",

    // Map layers panel
    map_layers: "KAARTLAGEN",
    layer_order: "Volgorde",
    layer_priority_low: "LAAG",
    layer_active_count: "actief",

    // Timeline
    timeline_title: "Tijdlijn werkzaamheden",
    timeline_loading: "Tijdlijn laden...",
    timeline_legend_internal: "Intern",
    timeline_legend_warning: "BB/Waarschuwing",
    timeline_prev_week: "< Week",
    timeline_next_week: "Week >",
    timeline_reset: "Resetten",
    feedback_btn: "Feedback",

    // Filter block
    filter_hide: "Verbergen",
    filter_show: "Tonen",
    filter_search_lines: "Lijnen zoeken...",

    // Favorites
    add_to_favorites: "Lijn toevoegen aan favorieten",

    // Apply wizard
    apply_step_of: "Stap {n} van 5",
    wizard_step1: "Stap 1 - Locatie",
    wizard_step2: "Stap 2 - Werkdetails",
    wizard_step3: "Stap 3 - Planning",
    wizard_step4: "Stap 4 - Contact & VVW",
    wizard_step5: "Stap 5 - Controleren",
    wizard_step1_hint: "Je kunt voor maximaal 3 geselecteerde segmenten aanvragen. Kies voor elk segment heel segment of aangepast gebied.",
    wizard_step3_hint: "Stel één tijdsblok in voor elk geselecteerd segment.",
    wizard_person_single: "Eén persoon voor alle geselecteerde segmenten",
    wizard_person_multi: "Andere persoon voor elk segment",
    apply_back: "Terug",
    apply_next: "Volgende",
    apply_submit: "Aanvraag versturen",

    // Apply success
    apply_success_title: "Aanvraag verstuurd",
    apply_success_text: "Je aanvraag is succesvol verstuurd.",
    apply_success_reference: "Referentie:",
    apply_success_view: "Mijn aanvragen bekijken",
    apply_success_close: "Sluiten",

    // My applications
    apps_loading: "Aanvragen laden...",

    // Footer
    footer_about: "Interne tool voor het coördineren van spoorwerk, onderhoud en projecten in het Amsterdamse tramnetwerk.",
    footer_quick_links: "Snelle links",
    footer_support: "Ondersteuning",
    footer_contact: "Neem contact op met het controlecentrum",
    footer_safety_manuals: "Veiligheidshandleidingen",
    footer_report: "Meld een probleem",
    footer_copyright: "© 2026 GVB Amsterdam. Alle rechten voorbehouden.",
    footer_privacy: "Privacy",
    footer_terms: "Voorwaarden",
    footer_cookies: "Cookies",

    // Tour
    tour_next: "Volgende",
    tour_back: "Terug",
    tour_done: "Klaar",
    tour_skip: "Overslaan",
    tour_skip_label: "Rondleiding overslaan",
    tour_welcome: "Welkom bij de GVB tram-coördinatiekaart. Deze korte rondleiding laat zien hoe je een werkaanvraag indient.",
    tour_map: "Dit is de kaart. Deze toont de traminfrastructuur - sporen, wissels en bovenleidingen. Hier selecteer je segmenten om werk aan te vragen.",
    tour_layers: "Zet hier kaartlagen aan of uit: KGE-spoor, wissels, bovenleidingsecties, WIOR en TBGN. <br><br><strong>Let op:</strong> de laag bovenaan deze lijst is de meest recent geselecteerde laag en wordt bovenop de andere op de kaart getekend.",
    tour_kge_layer: "Zorg dat <strong>KGE-spoorsegmenten</strong> is ingeschakeld - dit zijn de groene spoorlijnen waarvoor je werk kunt aanvragen.",
    tour_select_segment: "Klik nu op een <strong>groen KGE-spoorsegment</strong> op de kaart. Je kunt maximaal 3 segmenten per aanvraag selecteren. Geselecteerde segmenten verschijnen in het zijpaneel.",
    tour_apply_button: "Na het selecteren van minstens één segment verschijnt er een <strong>Aanvragen voor project</strong>-knop in het zijpaneel. Klik erop om de wizard met 5 stappen te openen.",
    tour_wizard_overview: "De wizard heeft 5 stappen:<br><br><strong>1. Locatie</strong> - bevestig het geselecteerde segment(en) en kies heel segment of een aangepast gebied.<br><strong>2. Werkdetails</strong> - beschrijf het werk en de getroffen lijnen.<br><strong>3. Planning</strong> - stel een datum en tijdsblok in voor elk segment.<br><strong>4. Contact & VVW</strong> - voer contactgegevens in en upload het veiligheidsplan (PDF/DOC/afbeelding).<br><strong>5. Controleren</strong> - controleer alles en verstuur.",
    tour_wizard_nav: "Gebruik <strong>Volgende</strong> en <strong>Terug</strong> onderaan de wizard om tussen stappen te navigeren. Verplichte velden moeten worden ingevuld voordat je verder kunt. Druk in stap 5 op <strong>Versturen</strong> om de aanvraag te verzenden.",
    tour_timeline: "De tijdlijn toont geplande activiteiten per dag en week. Klik op een dag om de kaart op datum te filteren.",
    tour_transfer: "Gebruik Overbrengsrit om een tramoverbrengsrit tussen twee haltes te plannen.",
    tour_feedback: "Gebruik Feedback om problemen te melden of verbeteringen voor te stellen.",
    tour_finish: "Rondleiding voltooid. Je kunt deze altijd opnieuw afspelen door op <strong>Help</strong> in de bovenste navigatie te klikken."
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
  for (const el of document.querySelectorAll("[data-i18n-html]")) {
    el.innerHTML = t(el.getAttribute("data-i18n-html"));
  }
  for (const el of document.querySelectorAll("[data-i18n-placeholder]")) {
    el.setAttribute("placeholder", t(el.getAttribute("data-i18n-placeholder")));
  }
  for (const el of document.querySelectorAll("[data-i18n-title]")) {
    el.setAttribute("title", t(el.getAttribute("data-i18n-title")));
  }
  for (const el of document.querySelectorAll("[data-i18n-aria-label]")) {
    el.setAttribute("aria-label", t(el.getAttribute("data-i18n-aria-label")));
  }
  if (dom.lineSelect) dom.lineSelect.placeholder = t("search_placeholder");
  if (dom.filterSearch) dom.filterSearch.placeholder = t("filter_search_lines");
  renderFavorites();
  renderFilterList();
}
