import { state } from "./state.js";
import { dom } from "./dom.js";
import { esc } from "./utils.js";
import { t } from "./i18n.js";

export function favKeyForSelection(sel) {
  if (!sel) return null;
  const lineId = sel.line_id;
  if (!lineId) return null;
  return `line:${lineId}`;
}

export function loadFavorites() {
  try {
    const raw = localStorage.getItem("gvbFavorites");
    if (!raw) return;
    const arr = JSON.parse(raw);
    if (!Array.isArray(arr)) return;

    const out = [];
    for (const v of arr) {
      const s = String(v);
      if (s.startsWith("line:")) out.push(s);
      else if (!s.includes(":")) out.push(`line:${s}`);
    }
    state.favorites = new Set(out);
  } catch {}
}

export function saveFavorites() {
  try {
    localStorage.setItem("gvbFavorites", JSON.stringify(Array.from(state.favorites)));
  } catch {}
}

export function updateFavoriteButton() {
  if (!dom.favoriteBtn) return;
  const key = favKeyForSelection(state.currentSelection);
  if (!key) return;

  const on = state.favorites.has(key);
  dom.favoriteBtn.classList.toggle("is-on", on);
  dom.favoriteBtn.setAttribute("aria-pressed", on ? "true" : "false");
  dom.favoriteBtn.textContent = on ? "★ Favorited line" : "☆ Add line to favorite";
}

export function getFavoriteLineIds() {
  return Array.from(state.favorites)
    .filter(k => String(k).startsWith("line:"))
    .map(k => String(k).slice("line:".length));
}

export function renderFavorites() {
  if (!dom.favoritesList || !dom.favoritesEmpty) return;

  const ids = getFavoriteLineIds();
  ids.sort((a, b) => {
    const an = (state.lineIndex.get(a)?.name || a).toLowerCase();
    const bn = (state.lineIndex.get(b)?.name || b).toLowerCase();
    return an.localeCompare(bn);
  });

  dom.favoritesList.innerHTML = "";

  if (ids.length === 0) {
    dom.favoritesEmpty.style.display = "block";
    return;
  }

  dom.favoritesEmpty.style.display = "none";

  for (const lineId of ids) {
    const line = state.lineIndex.get(lineId);
    const lineName = line?.name || lineId;

    const li = document.createElement("li");
    li.className = "fav-item";

    const left = document.createElement("button");
    left.type = "button";
    left.className = "fav-select";
    left.innerHTML = `${esc(lineName)} <span class="fav-meta">(${esc(lineId)})</span>`;

    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "fav-remove";
    remove.textContent = t("remove");

    li.appendChild(left);
    li.appendChild(remove);
    dom.favoritesList.appendChild(li);
  }
}