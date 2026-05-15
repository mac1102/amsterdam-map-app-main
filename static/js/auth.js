import { state } from "./state.js";
import { dom } from "./dom.js";
import { getJSON } from "./utils.js";
import { openModal, closeModal } from "./modals.js";

export async function refreshMe() {
  try {
    const me = await getJSON("/api/me");
    state.currentUser = me.authenticated ? me.user : null;
  } catch {
    state.currentUser = null;
  }
  updateAuthUI();
}

export function updateAuthUI() {
  const authed = !!state.currentUser;
  const isAdmin = !!state.currentUser?.is_admin;

  // Gate map + protected sections via CSS class on body
  document.body.classList.toggle("is-authenticated", authed);

  if (dom.loginBtn) dom.loginBtn.classList.toggle("is-hidden", authed);
  if (dom.accountBtn) dom.accountBtn.classList.toggle("is-hidden", !authed);

  setAccountMenuOpen(false);

  if (authed) {
    const email = state.currentUser.email || "Account";
    if (dom.accountLabel) dom.accountLabel.textContent = email;
    if (dom.accountEmail) dom.accountEmail.textContent = email;
    if (dom.applyEmailEl && state.currentUser.email) {
      dom.applyEmailEl.value = state.currentUser.email;
    }

    if (dom.myAppsBtn) {
      dom.myAppsBtn.textContent = "My applications";
      dom.myAppsBtn.classList.remove("is-hidden");
    }

    if (dom.manageAppsBtn) {
      dom.manageAppsBtn.textContent = "Manage applications";
      dom.manageAppsBtn.classList.toggle("is-hidden", !isAdmin);
    }
  } else {
    if (dom.accountLabel) dom.accountLabel.textContent = "Account";
    if (dom.accountEmail) dom.accountEmail.textContent = "";

    if (dom.myAppsBtn) {
      dom.myAppsBtn.textContent = "My applications";
      dom.myAppsBtn.classList.remove("is-hidden");
    }

    if (dom.manageAppsBtn) {
      dom.manageAppsBtn.textContent = "Manage applications";
      dom.manageAppsBtn.classList.add("is-hidden");
    }
  }
}

export function openLogin() {
  if (dom.loginResultEl) dom.loginResultEl.textContent = "";
  openModal(dom.loginModal);
}

export function closeLogin() {
  closeModal(dom.loginModal);
}

export async function doLogout() {
  try {
    await fetch("/api/logout", { method: "POST" });
  } catch {}
  state.currentUser = null;
  state.lineStatusCache.clear();
  updateAuthUI();
}

export function setAccountMenuOpen(open) {
  if (!dom.accountDropdown || !dom.accountBtn) return;
  dom.accountDropdown.classList.toggle("is-hidden", !open);
  dom.accountBtn.setAttribute("aria-expanded", open ? "true" : "false");
}

export function toggleAccountMenu() {
  if (!dom.accountDropdown) return;
  const isOpen = !dom.accountDropdown.classList.contains("is-hidden");
  setAccountMenuOpen(!isOpen);
}