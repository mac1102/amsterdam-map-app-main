import { dom } from "./dom.js";

export function setStatus(msg) {
  if (dom.statusEl) dom.statusEl.textContent = msg;
}

export function setDetails(html) {
  if (dom.detailsEl) dom.detailsEl.innerHTML = html;
}

export function esc(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#039;"
  }[c]));
}

export async function getJSON(url, opts) {
  const res = await fetch(url, opts);
  if (!res.ok) {
    const tt = await res.text();
    throw new Error(`${url} -> ${res.status}: ${tt}`);
  }
  return await res.json();
}

export function toISODate(d) {
  const yyyy = d.getFullYear();
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd}`;
}

export function addDays(dateObj, days) {
  const d = new Date(dateObj);
  d.setDate(d.getDate() + days);
  return d;
}

export function showToast({ title, message, actionText, onAction, durationMs = 5000 }) {
  if (!dom.toastHost) return;

  const el = document.createElement("div");
  el.className = "toast";

  const ttEl = document.createElement("p");
  ttEl.className = "toast-title";
  ttEl.textContent = title || "";

  const mmEl = document.createElement("p");
  mmEl.className = "toast-msg";
  mmEl.textContent = message || "";

  el.appendChild(ttEl);
  el.appendChild(mmEl);

  const actions = document.createElement("div");
  actions.className = "toast-actions";

  const close = document.createElement("button");
  close.type = "button";
  close.className = "toast-btn";
  close.textContent = "Close";
  close.addEventListener("click", () => el.remove());
  actions.appendChild(close);

  if (actionText && typeof onAction === "function") {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "toast-btn primary";
    btn.textContent = actionText;
    btn.addEventListener("click", () => {
      try { onAction(); } catch {}
      el.remove();
    });
    actions.appendChild(btn);
  }

  el.appendChild(actions);
  dom.toastHost.appendChild(el);

  window.setTimeout(() => {
    if (el.isConnected) el.remove();
  }, durationMs);
}