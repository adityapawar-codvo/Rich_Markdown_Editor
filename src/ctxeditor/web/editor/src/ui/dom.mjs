// Tiny DOM helpers shared by the toolbar, dialogs and the diff view.

export function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === undefined || value === null || value === false) continue;
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2).toLowerCase(), value);
    else node.setAttribute(key, value === true ? "" : value);
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child.nodeType ? child : document.createTextNode(String(child)));
  }
  return node;
}

// Icon button: icon-only, with an accessible name and a tooltip (AGENTS.md button rule).
export function iconButton(icon, label, onClick, extra = {}) {
  const button = el(
    "button",
    { type: "button", class: "cx-btn", title: label, "aria-label": label, ...extra },
    el("span", { class: "material-icons", "aria-hidden": "true", text: icon }),
  );
  button.addEventListener("mousedown", (event) => event.preventDefault()); // keep the editor selection
  button.addEventListener("click", (event) => {
    event.preventDefault();
    if (!button.disabled) onClick(event);
  });
  return button;
}

// A modal inside `root` so it inherits the theme variables. Returns {close, body}.
export function openModal(root, { title, wide = false, onClose }) {
  const body = el("div", { class: "cx-modal-body" });
  const closeButton = iconButton("close", "Close", () => close());
  const dialog = el(
    "div",
    { class: `cx-modal ${wide ? "cx-modal-wide" : ""}`, role: "dialog", "aria-modal": "true", "aria-label": title },
    el("div", { class: "cx-modal-head" }, el("h3", { text: title }), closeButton),
    body,
  );
  const overlay = el("div", { class: "cx-overlay" }, dialog);
  const onKey = (event) => {
    if (event.key === "Escape") {
      event.stopPropagation();
      close();
    }
  };
  function close() {
    document.removeEventListener("keydown", onKey, true);
    overlay.remove();
    if (onClose) onClose();
  }
  overlay.addEventListener("mousedown", (event) => {
    if (event.target === overlay) close();
  });
  document.addEventListener("keydown", onKey, true);
  root.append(overlay);
  return { close, body, dialog };
}

export function debounce(fn, wait) {
  let timer = null;
  const debounced = (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), wait);
  };
  debounced.cancel = () => clearTimeout(timer);
  debounced.flush = (...args) => {
    clearTimeout(timer);
    fn(...args);
  };
  return debounced;
}
