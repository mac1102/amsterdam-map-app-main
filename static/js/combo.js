import { state } from "./state.js";
import { dom } from "./dom.js";
import { esc } from "./utils.js";
import { t } from "./i18n.js";
import { renderFilterList } from "./filters.js";

export function lineDisplay(lineId) {
  const line = state.lineIndex.get(lineId);
  return line ? `${line.name} (${lineId})` : lineId;
}

export function setLineInputDisplay(lineId) {
  if (!dom.lineSelect) return;
  dom.lineSelect.value = lineId ? lineDisplay(lineId) : "";
  syncClearButton();
}

export function resolveLineIdFromText(text) {
  const v = (text || "").trim();
  if (!v) return "";

  if (state.lineIndex.has(v)) return v;

  const m = v.match(/\(([^)]+)\)\s*$/);
  if (m && m[1] && state.lineIndex.has(m[1].trim())) return m[1].trim();

  const exact = state.lineItems.find(it => it.display === v);
  if (exact) return exact.id;

  const low = v.toLowerCase();
  const matches = state.lineItems.filter(it => it.nameLower === low);
  if (matches.length === 1) return matches[0].id;

  return "";
}

export function syncClearButton() {
  if (!dom.lineClearBtn || !dom.lineSelect) return;
  dom.lineClearBtn.style.display = dom.lineSelect.value.trim() ? "inline-flex" : "none";
}

export function openCombo() {
  if (!dom.lineDropdown || !dom.lineSelect) return;
  state.comboOpen = true;
  dom.lineDropdown.classList.remove("is-hidden");
  dom.lineSelect.setAttribute("aria-expanded", "true");
}

export function closeCombo() {
  if (!dom.lineDropdown || !dom.lineSelect) return;
  state.comboOpen = false;
  state.comboActiveIndex = -1;
  dom.lineDropdown.classList.add("is-hidden");
  dom.lineSelect.setAttribute("aria-expanded", "false");
}

export function highlightMatch(text, query) {
  const safe = esc(text);
  const q = (query || "").trim();
  if (!q) return safe;

  const idx = text.toLowerCase().indexOf(q.toLowerCase());
  if (idx < 0) return safe;

  const before = esc(text.slice(0, idx));
  const mid = esc(text.slice(idx, idx + q.length));
  const after = esc(text.slice(idx + q.length));
  return `${before}<span class="combo-mark">${mid}</span>${after}`;
}

export function filterLines(query) {
  const q = (query || "").trim().toLowerCase();
  if (!q) return state.lineItems.slice(0, 12);

  const res = [];
  for (const it of state.lineItems) {
    if (it.nameLower.includes(q) || it.idLower.includes(q) || it.display.toLowerCase().includes(q)) {
      res.push(it);
    }
    if (res.length >= 30) break;
  }
  return res;
}

export function renderCombo(results, query) {
  if (!dom.lineDropdown) return;

  dom.lineDropdown.innerHTML = "";
  state.comboFiltered = results;
  state.comboActiveIndex = -1;

  if (results.length === 0) {
    const empty = document.createElement("div");
    empty.className = "combo-empty";
    empty.textContent = t("no_results");
    dom.lineDropdown.appendChild(empty);
    return;
  }

  results.forEach((it, idx) => {
    const row = document.createElement("div");
    row.className = "combo-item";
    row.setAttribute("role", "option");
    row.dataset.index = String(idx);

    const left = document.createElement("div");
    left.innerHTML = `
      <div class="combo-title">${highlightMatch(it.name, query)}</div>
      <div class="combo-meta">${highlightMatch(it.display, query)}</div>
    `;

    const right = document.createElement("div");
    right.className = "combo-id";
    right.innerHTML = highlightMatch(it.id, query);

    row.appendChild(left);
    row.appendChild(right);

    row.addEventListener("mousedown", (e) => {
      e.preventDefault();
      chooseLine(it.id);
    });

    dom.lineDropdown.appendChild(row);
  });
}

export function setActiveIndex(newIndex) {
  if (!dom.lineDropdown) return;
  const items = Array.from(dom.lineDropdown.querySelectorAll(".combo-item"));
  items.forEach(el => el.classList.remove("is-active"));

  state.comboActiveIndex = newIndex;

  if (newIndex >= 0 && newIndex < items.length) {
    const el = items[newIndex];
    el.classList.add("is-active");
    el.scrollIntoView({ block: "nearest" });
  }
}

let chooseLineHandler = null;

export function setChooseLineHandler(fn) {
  chooseLineHandler = fn;
}

export function chooseLine(lineId) {
  if (!lineId) return;

  const item = state.lineItems.find(it => it.id === lineId);
  if (!item) return;

  if (dom.lineSelect) {
    dom.lineSelect.value = item.display;
  }

  syncClearButton();
  closeCombo();

  if (typeof chooseLineHandler === "function") {
    chooseLineHandler(lineId);
  }
}