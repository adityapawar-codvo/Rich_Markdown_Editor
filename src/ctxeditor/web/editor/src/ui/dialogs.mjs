// Dialogs: Mermaid split view, chart data table, link popover.
import { canonicalChart, renderChart, renderMermaid } from "../render/blocks.mjs";
import { debounce, el, openModal } from "./dom.mjs";

export const DEFAULT_MERMAID = "flowchart TD\n  A[Start] --> B{Decision}\n  B -->|Yes| C[Do it]\n  B -->|No| D[Skip]";

export const DEFAULT_CHART = {
  type: "bar",
  title: "",
  labels: ["A", "B", "C"],
  series: [{ name: "Series 1", values: [10, 20, 15] }],
};

// Split view: Mermaid code on the left, live preview on the right, syntax errors shown inline.
export function openMermaidDialog(root, { code, theme, onSave }) {
  const textarea = el("textarea", {
    class: "cx-code-input", spellcheck: "false", "aria-label": "Mermaid code", rows: "16",
  });
  textarea.value = code;
  const preview = el("div", { class: "cx-preview", "aria-live": "polite" });
  const status = el("div", { class: "cx-status", role: "status" });
  let ok = true;
  let seq = 0;

  const update = debounce(async () => {
    const mine = ++seq;
    const result = await renderMermaid(preview, textarea.value, { theme, keepOnError: true });
    if (mine !== seq) return;
    ok = result.ok;
    status.className = `cx-status ${result.ok ? "cx-status-ok" : "cx-status-error"}`;
    status.textContent = result.ok ? "Diagram is valid" : result.error;
  }, 250);
  textarea.addEventListener("input", update);

  const save = el("button", { type: "button", class: "cx-primary", text: "Save diagram" });
  const cancel = el("button", { type: "button", class: "cx-secondary", text: "Cancel" });
  const modal = openModal(root, { title: "Edit diagram", wide: true });
  modal.body.append(
    el("div", { class: "cx-split" },
      el("div", { class: "cx-split-pane" }, el("label", { class: "cx-label", text: "Mermaid code" }), textarea, status),
      el("div", { class: "cx-split-pane" }, el("label", { class: "cx-label", text: "Preview" }), preview)),
    el("div", { class: "cx-modal-actions" }, cancel, save),
  );
  cancel.addEventListener("click", () => modal.close());
  save.addEventListener("click", () => {
    onSave(textarea.value, ok);
    modal.close();
  });
  update.flush();
  textarea.focus();
  return modal;
}

// Chart editor: a small table (rows = labels, columns = series) plus type and title, with a live preview.
export function openChartDialog(root, { spec, theme, onSave }) {
  const state = JSON.parse(JSON.stringify(spec || DEFAULT_CHART));
  const typeSelect = el("select", { "aria-label": "Chart type", class: "cx-select" },
    ...["bar", "line", "pie", "area"].map((t) => el("option", { value: t, text: t[0].toUpperCase() + t.slice(1) })));
  typeSelect.value = state.type;
  const title = el("input", { class: "cx-input", type: "text", maxlength: "200", placeholder: "Chart title", "aria-label": "Chart title" });
  title.value = state.title || "";
  const tableHost = el("div", { class: "cx-table-scroll" });
  const preview = el("div", { class: "cx-preview cx-chart-preview" });
  const message = el("div", { class: "cx-status", role: "status" });
  let handle = null;
  let seq = 0;

  const refresh = debounce(async () => {
    const mine = ++seq;
    const valid = validate();
    message.className = `cx-status ${valid.ok ? "" : "cx-status-error"}`;
    message.textContent = valid.ok ? "" : valid.error;
    if (!valid.ok) return;
    if (handle) handle.destroy();
    const result = await renderChart(preview, canonicalChart(state), { theme });
    if (mine === seq) handle = result;
    else result.destroy();
  }, 200);

  function validate() {
    if (!state.labels.length) return { ok: false, error: "Add at least one row." };
    if (state.labels.length > 200) return { ok: false, error: "At most 200 rows." };
    if (!state.series.length) return { ok: false, error: "Add at least one series." };
    if (state.series.length > 12) return { ok: false, error: "At most 12 series." };
    for (const s of state.series) {
      if (s.values.some((v) => typeof v !== "number" || !Number.isFinite(v))) {
        return { ok: false, error: "Every value must be a number." };
      }
    }
    return { ok: true };
  }

  function numberInput(value, onChange) {
    const input = el("input", { class: "cx-input cx-num", type: "text", inputmode: "decimal", "aria-label": "Value" });
    input.value = Number.isFinite(value) ? String(value) : "";
    input.addEventListener("input", () => {
      const parsed = input.value.trim() === "" ? NaN : Number(input.value);
      input.classList.toggle("cx-invalid", !Number.isFinite(parsed));
      onChange(parsed);
      refresh();
    });
    return input;
  }

  function buildTable() {
    tableHost.textContent = "";
    const table = el("table", { class: "cx-data-table" });
    const head = el("tr", {}, el("th", { text: "Label" }));
    state.series.forEach((s, i) => {
      const name = el("input", { class: "cx-input", type: "text", maxlength: "100", "aria-label": `Series ${i + 1} name` });
      name.value = s.name;
      name.addEventListener("input", () => { s.name = name.value; refresh(); });
      const remove = el("button", {
        type: "button", class: "cx-mini", title: "Remove series", "aria-label": `Remove series ${i + 1}`,
      }, el("span", { class: "material-icons", text: "close" }));
      remove.addEventListener("click", () => {
        if (state.series.length > 1) { state.series.splice(i, 1); buildTable(); refresh(); }
      });
      head.append(el("th", {}, el("div", { class: "cx-th" }, name, remove)));
    });
    head.append(el("th", {}));
    table.append(head);
    state.labels.forEach((label, r) => {
      const labelInput = el("input", { class: "cx-input", type: "text", maxlength: "100", "aria-label": `Row ${r + 1} label` });
      labelInput.value = label;
      labelInput.addEventListener("input", () => { state.labels[r] = labelInput.value; refresh(); });
      const row = el("tr", {}, el("td", {}, labelInput));
      state.series.forEach((s) => row.append(el("td", {}, numberInput(s.values[r], (v) => { s.values[r] = v; }))));
      const remove = el("button", { type: "button", class: "cx-mini", title: "Remove row", "aria-label": `Remove row ${r + 1}` },
        el("span", { class: "material-icons", text: "close" }));
      remove.addEventListener("click", () => {
        if (state.labels.length > 1) {
          state.labels.splice(r, 1);
          state.series.forEach((s) => s.values.splice(r, 1));
          buildTable();
          refresh();
        }
      });
      row.append(el("td", {}, remove));
      table.append(row);
    });
    tableHost.append(table);
  }

  const addRow = el("button", { type: "button", class: "cx-secondary", text: "Add row" });
  const addSeries = el("button", { type: "button", class: "cx-secondary", text: "Add series" });
  addRow.addEventListener("click", () => {
    state.labels.push(`Item ${state.labels.length + 1}`);
    state.series.forEach((s) => s.values.push(0));
    buildTable();
    refresh();
  });
  addSeries.addEventListener("click", () => {
    if (state.series.length >= 12) return;
    state.series.push({ name: `Series ${state.series.length + 1}`, values: state.labels.map(() => 0) });
    buildTable();
    refresh();
  });
  typeSelect.addEventListener("change", () => { state.type = typeSelect.value; refresh(); });
  title.addEventListener("input", () => { state.title = title.value; refresh(); });

  const save = el("button", { type: "button", class: "cx-primary", text: "Save chart" });
  const cancel = el("button", { type: "button", class: "cx-secondary", text: "Cancel" });
  const modal = openModal(root, {
    title: "Edit chart", wide: true, onClose: () => { if (handle) handle.destroy(); },
  });
  modal.body.append(
    el("div", { class: "cx-split" },
      el("div", { class: "cx-split-pane" },
        el("div", { class: "cx-row" }, typeSelect, title),
        tableHost,
        el("div", { class: "cx-row" }, addRow, addSeries),
        el("p", { class: "cx-hint", text: "Pie charts use the first series." }),
        message),
      el("div", { class: "cx-split-pane" }, el("label", { class: "cx-label", text: "Preview" }), preview)),
    el("div", { class: "cx-modal-actions" }, cancel, save),
  );
  cancel.addEventListener("click", () => modal.close());
  save.addEventListener("click", () => {
    const valid = validate();
    if (!valid.ok) {
      message.className = "cx-status cx-status-error";
      message.textContent = valid.error;
      return;
    }
    onSave(canonicalChart(state));
    modal.close();
  });
  buildTable();
  refresh.flush();
  return modal;
}

// Link popover: add, edit, remove, open in a new tab.
export function openLinkDialog(root, { href, onApply, onRemove }) {
  const input = el("input", {
    class: "cx-input", type: "url", placeholder: "https://example.com", "aria-label": "Link address",
  });
  input.value = href || "";
  const error = el("div", { class: "cx-status cx-status-error", role: "alert" });
  const apply = el("button", { type: "button", class: "cx-primary", text: "Apply" });
  const remove = el("button", { type: "button", class: "cx-secondary", text: "Remove link" });
  const open = el("button", { type: "button", class: "cx-secondary", text: "Open in new tab" });
  const modal = openModal(root, { title: href ? "Edit link" : "Add link" });
  modal.body.append(
    el("label", { class: "cx-label", text: "Address" }), input, error,
    el("div", { class: "cx-modal-actions" }, href ? remove : null, href ? open : null, apply));
  const submit = () => {
    let value = input.value.trim();
    if (!value) { error.textContent = "Enter an address."; return; }
    if (!/^[a-z][a-z0-9+.-]*:/i.test(value) && !value.startsWith("/") && !value.startsWith("#")) value = `https://${value}`;
    if (/^[a-z][a-z0-9+.-]*:/i.test(value) && !/^(https?|mailto):/i.test(value)) {
      error.textContent = "Only http, https and mailto links are allowed.";
      return;
    }
    onApply(value);
    modal.close();
  };
  apply.addEventListener("click", submit);
  input.addEventListener("keydown", (event) => { if (event.key === "Enter") { event.preventDefault(); submit(); } });
  remove.addEventListener("click", () => { onRemove(); modal.close(); });
  open.addEventListener("click", () => window.open(input.value, "_blank", "noopener,noreferrer"));
  input.focus();
  input.select();
  return modal;
}
