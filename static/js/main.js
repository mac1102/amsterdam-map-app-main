import { state } from "./state.js";
import { dom } from "./dom.js";
import { setStatus } from "./utils.js";
import { loadLang, setLang, applyTranslations, t } from "./i18n.js";
import {
  refreshMe,
  toggleAccountMenu,
  openLogin,
  closeLogin,
  doLogout,
  setAccountMenuOpen
} from "./auth.js";
import { openModal, closeModal } from "./modals.js";
import {
  loadFavorites,
  renderFavorites,
  saveFavorites,
  updateFavoriteButton,
  favKeyForSelection
} from "./favorites.js";
import {
  renderFilterList,
  setAllLinesVisible,
  setAllLinesHidden,
  clearHighlights,
  setFilterSelectionHandler,
  applyOverlayStyles
} from "./filters.js";
import {
  syncClearButton,
  openCombo,
  closeCombo,
  renderCombo,
  filterLines,
  setActiveIndex,
  chooseLine,
  resolveLineIdFromText,
  setChooseLineHandler
} from "./combo.js";
import { openMyApplications, wireApplicationHandlers, openApplyForSegments } from "./applications.js";
import { initMap, selectLineById, setSelection } from "./map.js";
import { initTransfer } from "./transfer.js";
import { startTour, maybeInitTour } from "./tour.js";
import { openSettings, closeSettings } from "./settings.js";


async function init() {
  try {
    setLang(loadLang());

    if (dom.langSelect) {
      dom.langSelect.addEventListener("change", () => setLang(dom.langSelect.value));
    }

    await refreshMe();
    loadFavorites();
    renderFavorites();

    try {
      const saved = localStorage.getItem("gvbPanelHidden") === "1";
      document.body.classList.toggle("panel-hidden", saved);
      if (dom.togglePanelBtn) {
        dom.togglePanelBtn.setAttribute("aria-expanded", saved ? "false" : "true");
      }
    } catch {}

    if (dom.togglePanelBtn) {
      dom.togglePanelBtn.addEventListener("click", () => {
        const hidden = !document.body.classList.contains("panel-hidden");
        document.body.classList.toggle("panel-hidden", hidden);
        dom.togglePanelBtn.setAttribute("aria-expanded", hidden ? "false" : "true");
        try {
          localStorage.setItem("gvbPanelHidden", hidden ? "1" : "0");
        } catch {}
        if (state.map) setTimeout(() => state.map.invalidateSize(), 0);
      });
    }

    try {
      const filterHidden = localStorage.getItem("gvbFilterBlockHidden") === "1";
      document.body.classList.toggle("filter-block-hidden", filterHidden);

      if (dom.toggleFilterBlockBtn) {
        dom.toggleFilterBlockBtn.setAttribute("aria-expanded", filterHidden ? "false" : "true");
        dom.toggleFilterBlockBtn.textContent = filterHidden ? t("filter_show") : t("filter_hide");
        dom.toggleFilterBlockBtn.title = filterHidden ? t("filter_show") : t("filter_hide");
      }
    } catch {}

    if (dom.toggleFilterBlockBtn) {
      dom.toggleFilterBlockBtn.addEventListener("click", () => {
        const hidden = !document.body.classList.contains("filter-block-hidden");
        document.body.classList.toggle("filter-block-hidden", hidden);

        dom.toggleFilterBlockBtn.setAttribute("aria-expanded", hidden ? "false" : "true");
        dom.toggleFilterBlockBtn.textContent = hidden ? t("filter_show") : t("filter_hide");
        dom.toggleFilterBlockBtn.title = hidden ? t("filter_show") : t("filter_hide");

        try {
          localStorage.setItem("gvbFilterBlockHidden", hidden ? "1" : "0");
        } catch {}

        if (state.map) setTimeout(() => state.map.invalidateSize(), 0);
      });
    }

    if (dom.accountBtn) dom.accountBtn.addEventListener("click", toggleAccountMenu);

    if (dom.myAppsBtn) {
      dom.myAppsBtn.addEventListener("click", () => {
        setAccountMenuOpen(false);
        openMyApplications();
      });
    }

    if (dom.manageAppsBtn) {
      dom.manageAppsBtn.addEventListener("click", () => {
        setAccountMenuOpen(false);
        window.location.href = "/admin";
      });
    }

    if (dom.settingsBtn) {
      dom.settingsBtn.addEventListener("click", () => {
        setAccountMenuOpen(false);
        openSettings();
      });
    }

    if (dom.logoutBtn) {
      dom.logoutBtn.addEventListener("click", () => {
        setAccountMenuOpen(false);
        doLogout();
      });
    }

    document.addEventListener("mousedown", (e) => {
      if (!dom.accountDropdown || !dom.accountBtn) return;
      const inside = dom.accountDropdown.contains(e.target) || dom.accountBtn.contains(e.target);
      if (!inside) setAccountMenuOpen(false);
    });

    if (dom.loginBtn) dom.loginBtn.addEventListener("click", openLogin);
    if (dom.loginCloseBtn) dom.loginCloseBtn.addEventListener("click", closeLogin);
    if (dom.loginBackdrop) dom.loginBackdrop.addEventListener("click", closeLogin);
    if (dom.loginCancelBtn) dom.loginCancelBtn.addEventListener("click", closeLogin);

    if (dom.loginForm) {
      dom.loginForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        if (dom.loginResultEl) dom.loginResultEl.textContent = "";

        const email = (dom.loginEmailEl?.value || "").trim();
        const password = (dom.loginPasswordEl?.value || "").trim();

        try {
          const res = await fetch("/api/login", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ email, password })
          });

          const data = await res.json().catch(() => ({}));

          if (!res.ok) {
            if (dom.loginResultEl) {
              dom.loginResultEl.textContent = data?.detail || "Login failed";
            }
            return;
          }

          state.currentUser = data.user;
          state.lineStatusCache.clear();
          setAccountMenuOpen(false);
          closeLogin();
          await refreshMe();

          if (!state.map && state.currentUser) {
            await initMap();
            maybeInitTour();
          }

          if (state.map) setTimeout(() => state.map.invalidateSize(), 50);
        } catch (err) {
          if (dom.loginResultEl) {
            dom.loginResultEl.textContent = `Error: ${err.message}`;
          }
        }
      });
    }

    if (dom.safetyBtn) dom.safetyBtn.addEventListener("click", () => openModal(dom.safetyModal));
    if (dom.heroSafetyBtn) dom.heroSafetyBtn.addEventListener("click", () => openModal(dom.safetyModal));
    if (dom.safetyCloseBtn) dom.safetyCloseBtn.addEventListener("click", () => closeModal(dom.safetyModal));
    if (dom.safetyBackdrop) dom.safetyBackdrop.addEventListener("click", () => closeModal(dom.safetyModal));

    if (dom.favoritesBtn) {
      dom.favoritesBtn.addEventListener("click", () => {
        renderFavorites();
        openModal(dom.favoritesModal);
      });
    }
    if (dom.favoritesCloseBtn) dom.favoritesCloseBtn.addEventListener("click", () => closeModal(dom.favoritesModal));
    if (dom.favoritesBackdrop) dom.favoritesBackdrop.addEventListener("click", () => closeModal(dom.favoritesModal));

    if (dom.settingsCloseBtn) dom.settingsCloseBtn.addEventListener("click", closeSettings);
    if (dom.settingsBackdrop) dom.settingsBackdrop.addEventListener("click", closeSettings);

    if (dom.favoritesClearBtn) {
      dom.favoritesClearBtn.addEventListener("click", () => {
        state.favorites = new Set();
        saveFavorites();
        updateFavoriteButton();
        renderFavorites();
      });
    }

    if (dom.filterSearch) dom.filterSearch.addEventListener("input", () => renderFilterList());
    if (dom.showAllLinesBtn) dom.showAllLinesBtn.addEventListener("click", () => setAllLinesVisible());
    if (dom.hideAllLinesBtn) dom.hideAllLinesBtn.addEventListener("click", () => setAllLinesHidden());

    if (dom.favoriteBtn) {
      dom.favoriteBtn.addEventListener("click", () => {
        const key = favKeyForSelection(state.currentSelection);
        if (!key) return;

        if (state.favorites.has(key)) state.favorites.delete(key);
        else state.favorites.add(key);

        saveFavorites();
        updateFavoriteButton();
        renderFavorites();
      });
    }

    wireApplicationHandlers();
    initTransfer();

      setChooseLineHandler((lineId) => {
        if (!lineId) return;

        // If user is already selecting segments, keep that selection alive.
        // Just make the chosen line visible and focused.
        if (state.currentSelection?.type === "segment-list") {
          state.visibleLineIds = new Set([...state.visibleLineIds, lineId]);

          renderFilterList();

          state.highlightedLineId = lineId;
          applyOverlayStyles();

          if (dom.lineSelect) {
            dom.lineSelect.value = lineId;
          }

          return;
        }

        // Normal behavior when no segment selection is active
        selectLineById(lineId);
      });

    if (dom.lineSelect) {
      syncClearButton();

      dom.lineSelect.addEventListener("focus", () => {
        renderCombo(filterLines(dom.lineSelect.value), dom.lineSelect.value);
        openCombo();
      });

      dom.lineSelect.addEventListener("input", () => {
        syncClearButton();
        renderCombo(filterLines(dom.lineSelect.value), dom.lineSelect.value);
        openCombo();

        const resolved = resolveLineIdFromText(dom.lineSelect.value);
        if (resolved) chooseLine(resolved);
      });

      dom.lineSelect.addEventListener("keydown", (e) => {
        if (!state.comboOpen && (e.key === "ArrowDown" || e.key === "ArrowUp")) {
          renderCombo(filterLines(dom.lineSelect.value), dom.lineSelect.value);
          openCombo();
        }

        if (e.key === "ArrowDown") {
          e.preventDefault();
          const max = state.comboFiltered.length - 1;
          setActiveIndex(Math.min(max, state.comboActiveIndex + 1));
        }

        if (e.key === "ArrowUp") {
          e.preventDefault();
          setActiveIndex(Math.max(0, state.comboActiveIndex - 1));
        }

        if (e.key === "Enter") {
          if (
            state.comboOpen &&
            state.comboActiveIndex >= 0 &&
            state.comboActiveIndex < state.comboFiltered.length
          ) {
            e.preventDefault();
            chooseLine(state.comboFiltered[state.comboActiveIndex].id);
          }
        }

        if (e.key === "Escape") {
          closeCombo();
        }
      });
    }

    if (dom.lineClearBtn) {
      dom.lineClearBtn.addEventListener("click", () => {
        if (dom.lineSelect) dom.lineSelect.value = "";
        syncClearButton();
        closeCombo();
        clearHighlights();
        setSelection(null);
      });
    }

    document.addEventListener("mousedown", (e) => {
      if (!dom.lineCombo) return;
      if (!dom.lineCombo.contains(e.target)) closeCombo();
    });

    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") {
        closeLogin();
        closeModal(dom.safetyModal);
        closeModal(dom.favoritesModal);
        closeModal(dom.appsModal);
        closeModal(dom.applyModal);
        closeCombo();
        setAccountMenuOpen(false);
      }
    });

    if (state.currentUser) {
      await initMap();
      maybeInitTour();
    } else {
      setStatus(t("status_login_required"));
    }

    const urlParams = new URLSearchParams(window.location.search);
    const applySegmentsStr = urlParams.get("apply_segments");
    if (applySegmentsStr) {
      const segIds = applySegmentsStr.split(",");
      const matchingSegments = [];
      for (const segId of segIds) {
        const seg = state.allSegments.find(s => s.segment_id === segId);
        if (seg) matchingSegments.push(seg);
      }
      if (matchingSegments.length > 0) {
        openApplyForSegments(matchingSegments);
      }
      urlParams.delete("apply_segments");
      const newUrl = window.location.pathname + (urlParams.toString() ? "?" + urlParams.toString() : "") + window.location.hash;
      window.history.replaceState({}, document.title, newUrl);
    }

    applyTranslations();
    setStatus(state.currentUser ? t("status_ready") : t("status_login_required"));
  } catch (err) {
    console.error(err);
    setStatus(`Error: ${err.message}`);
  }
}

init();
