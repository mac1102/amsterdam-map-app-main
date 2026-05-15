export function openModal(modalEl) {
  if (!modalEl) return;
  modalEl.classList.add("is-open");
  modalEl.setAttribute("aria-hidden", "false");
  const card = modalEl.querySelector(".modal-card");
  if (card) card.focus();
}

export function closeModal(modalEl) {
  if (!modalEl) return;
  modalEl.classList.remove("is-open");
  modalEl.setAttribute("aria-hidden", "true");
}