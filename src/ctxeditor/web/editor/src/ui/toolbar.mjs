// The fixed top toolbar and the floating selection toolbar. Icon buttons only, each with an accessible name and a
// tooltip (AGENTS.md). Active and disabled states follow the editor state.
import { el, iconButton } from "./dom.mjs";

const TEXT_COLORS = ["#1f2430", "#c62828", "#e8743b", "#b58900", "#19a979", "#2563eb", "#7c3aed", "#6c7a89"];
const HIGHLIGHTS = ["#fff59d", "#ffd6a5", "#c8f7c5", "#bde0fe", "#e9d5ff", "#ffc9de"];

function swatches(root, anchor, colors, onPick, onClear, label) {
  root.querySelectorAll(".cx-swatches").forEach((node) => node.remove());
  const box = el("div", { class: "cx-swatches", role: "dialog", "aria-label": label });
  for (const color of colors) {
    const chip = el("button", { type: "button", class: "cx-swatch", title: color, "aria-label": `${label} ${color}`, style: `background:${color}` });
    chip.addEventListener("mousedown", (event) => event.preventDefault());
    chip.addEventListener("click", () => { onPick(color); box.remove(); });
    box.append(chip);
  }
  const clear = el("button", { type: "button", class: "cx-swatch cx-swatch-clear", title: "No color", "aria-label": `Remove ${label}` },
    el("span", { class: "material-icons", text: "format_color_reset" }));
  clear.addEventListener("mousedown", (event) => event.preventDefault());
  clear.addEventListener("click", () => { onClear(); box.remove(); });
  box.append(clear);
  const rect = anchor.getBoundingClientRect();
  const host = root.getBoundingClientRect();
  box.style.left = `${rect.left - host.left}px`;
  box.style.top = `${rect.bottom - host.top + 4}px`;
  root.append(box);
  const close = (event) => {
    if (!box.contains(event.target)) { box.remove(); document.removeEventListener("mousedown", close, true); }
  };
  setTimeout(() => document.addEventListener("mousedown", close, true), 0);
}

export function buildToolbar(editor, { root, openLink }) {
  const refreshers = [];
  const bar = el("div", { class: "cx-toolbar", role: "toolbar", "aria-label": "Formatting" });

  const add = (group, icon, label, run, { active, can, shortcut } = {}) => {
    const button = iconButton(icon, shortcut ? `${label} (${shortcut})` : label, () => run(editor, button));
    group.append(button);
    refreshers.push(() => {
      const on = active ? active(editor) : false;
      button.classList.toggle("is-active", !!on);
      button.setAttribute("aria-pressed", active ? String(!!on) : "false");
      button.disabled = can ? !can(editor) : false;
    });
    return button;
  };
  const group = (...nodes) => {
    const g = el("div", { class: "cx-group", role: "group" });
    bar.append(g);
    return g;
  };
  const chain = (e) => e.chain().focus();
  const mod = navigator.platform.includes("Mac") ? "⌘" : "Ctrl+";

  // History
  let g = group();
  add(g, "undo", "Undo", (e) => chain(e).undo().run(), { can: (e) => e.can().undo(), shortcut: `${mod}Z` });
  add(g, "redo", "Redo", (e) => chain(e).redo().run(), { can: (e) => e.can().redo(), shortcut: `${mod}Shift+Z` });

  // Block type
  g = group();
  const blockSelect = el("select", { class: "cx-select", "aria-label": "Text style", title: "Text style" },
    el("option", { value: "p", text: "Paragraph" }),
    ...[1, 2, 3, 4].map((n) => el("option", { value: `h${n}`, text: `Heading ${n}` })));
  blockSelect.addEventListener("change", () => {
    const v = blockSelect.value;
    if (v === "p") chain(editor).setParagraph().run();
    else chain(editor).setHeading({ level: Number(v[1]) }).run();
  });
  g.append(blockSelect);
  refreshers.push(() => {
    const level = [1, 2, 3, 4].find((n) => editor.isActive("heading", { level: n }));
    blockSelect.value = level ? `h${level}` : "p";
  });

  // Text marks
  g = group();
  add(g, "format_bold", "Bold", (e) => chain(e).toggleBold().run(), { active: (e) => e.isActive("bold"), shortcut: `${mod}B` });
  add(g, "format_italic", "Italic", (e) => chain(e).toggleItalic().run(), { active: (e) => e.isActive("italic"), shortcut: `${mod}I` });
  add(g, "format_underlined", "Underline", (e) => chain(e).toggleUnderline().run(), { active: (e) => e.isActive("underline"), shortcut: `${mod}U` });
  add(g, "strikethrough_s", "Strikethrough", (e) => chain(e).toggleStrike().run(), { active: (e) => e.isActive("strike"), shortcut: `${mod}Shift+S` });
  add(g, "subscript", "Subscript", (e) => chain(e).toggleSubscript().run(), { active: (e) => e.isActive("subscript"), shortcut: `${mod},` });
  add(g, "superscript", "Superscript", (e) => chain(e).toggleSuperscript().run(), { active: (e) => e.isActive("superscript"), shortcut: `${mod}.` });
  add(g, "code", "Inline code", (e) => chain(e).toggleCode().run(), { active: (e) => e.isActive("code"), shortcut: `${mod}E` });
  add(g, "format_color_text", "Text color", (e, button) => swatches(root, button, TEXT_COLORS,
    (c) => chain(e).setColor(c).run(), () => chain(e).unsetColor().run(), "Text color"));
  add(g, "highlight", "Highlight", (e, button) => swatches(root, button, HIGHLIGHTS,
    (c) => chain(e).setHighlight({ color: c }).run(), () => chain(e).unsetHighlight().run(), "Highlight color"),
  { active: (e) => e.isActive("highlight") });
  add(g, "link", "Link", () => openLink(), { active: (e) => e.isActive("link"), shortcut: `${mod}K` });
  add(g, "format_clear", "Clear formatting", (e) => chain(e).unsetAllMarks().clearNodes().run());

  // Alignment
  g = group();
  for (const [value, icon] of [["left", "format_align_left"], ["center", "format_align_center"], ["right", "format_align_right"], ["justify", "format_align_justify"]]) {
    add(g, icon, `Align ${value}`, (e) => chain(e).setTextAlign(value).run(), { active: (e) => e.isActive({ textAlign: value }) });
  }

  // Lists and blocks
  g = group();
  add(g, "format_list_bulleted", "Bulleted list", (e) => chain(e).toggleBulletList().run(), { active: (e) => e.isActive("bulletList"), shortcut: `${mod}Shift+8` });
  add(g, "format_list_numbered", "Numbered list", (e) => chain(e).toggleOrderedList().run(), { active: (e) => e.isActive("orderedList"), shortcut: `${mod}Shift+7` });
  add(g, "checklist", "Checklist", (e) => chain(e).toggleTaskList().run(), { active: (e) => e.isActive("taskList"), shortcut: `${mod}Shift+9` });
  add(g, "format_indent_increase", "Indent", (e) => {
    if (e.isActive("taskItem")) chain(e).sinkListItem("taskItem").run(); else chain(e).sinkListItem("listItem").run();
  }, { can: (e) => e.can().sinkListItem("listItem") || e.can().sinkListItem("taskItem"), shortcut: "Tab" });
  add(g, "format_indent_decrease", "Outdent", (e) => {
    if (e.isActive("taskItem")) chain(e).liftListItem("taskItem").run(); else chain(e).liftListItem("listItem").run();
  }, { can: (e) => e.can().liftListItem("listItem") || e.can().liftListItem("taskItem"), shortcut: "Shift+Tab" });
  add(g, "format_quote", "Quote", (e) => chain(e).toggleBlockquote().run(), { active: (e) => e.isActive("blockquote") });
  add(g, "data_object", "Code block", (e) => chain(e).toggleCodeBlock().run(), { active: (e) => e.isActive("codeBlock") });
  add(g, "horizontal_rule", "Divider", (e) => chain(e).setHorizontalRule().run());

  // Insert
  g = group();
  add(g, "table_chart", "Insert table", (e) => chain(e).insertTable({ rows: 3, cols: 3, withHeaderRow: true }).run(), { can: (e) => !e.isActive("table") });
  add(g, "account_tree", "Insert diagram", (e) => chain(e).insertMermaid().run());
  add(g, "bar_chart", "Insert chart", (e) => chain(e).insertChart().run());

  // Table controls, shown while the cursor is in a table
  const tableGroup = el("div", { class: "cx-group cx-table-tools", role: "group", "aria-label": "Table" });
  bar.append(tableGroup);
  add(tableGroup, "keyboard_double_arrow_up", "Add row above", (e) => chain(e).addRowBefore().run(), { can: (e) => e.can().addRowBefore() });
  add(tableGroup, "keyboard_double_arrow_down", "Add row below", (e) => chain(e).addRowAfter().run(), { can: (e) => e.can().addRowAfter() });
  add(tableGroup, "keyboard_double_arrow_left", "Add column before", (e) => chain(e).addColumnBefore().run(), { can: (e) => e.can().addColumnBefore() });
  add(tableGroup, "keyboard_double_arrow_right", "Add column after", (e) => chain(e).addColumnAfter().run(), { can: (e) => e.can().addColumnAfter() });
  add(tableGroup, "table_rows", "Delete row", (e) => chain(e).deleteRow().run(), { can: (e) => e.can().deleteRow() });
  add(tableGroup, "view_column", "Delete column", (e) => chain(e).deleteColumn().run(), { can: (e) => e.can().deleteColumn() });
  add(tableGroup, "title", "Toggle header row", (e) => chain(e).toggleHeaderRow().run(), { can: (e) => e.can().toggleHeaderRow() });
  add(tableGroup, "call_merge", "Merge cells", (e) => chain(e).mergeCells().run(), { can: (e) => e.can().mergeCells() });
  add(tableGroup, "call_split", "Split cell", (e) => chain(e).splitCell().run(), { can: (e) => e.can().splitCell() });
  add(tableGroup, "delete", "Delete table", (e) => chain(e).deleteTable().run(), { can: (e) => e.can().deleteTable() });
  refreshers.push(() => tableGroup.classList.toggle("is-visible", editor.isActive("table")));

  const refresh = () => refreshers.forEach((fn) => fn());
  editor.on("transaction", refresh);
  editor.on("selectionUpdate", refresh);
  refresh();
  return { element: bar, refresh };
}

// The floating toolbar over a text selection. In a read-only document only the comment button is shown.
export function buildBubble(editor, bubble, { openLink, onComment }) {
  bubble.setAttribute("role", "toolbar");
  bubble.setAttribute("aria-label", "Selection");
  const editing = el("div", { class: "cx-group" });
  const make = (group, icon, label, run, active) => {
    const button = iconButton(icon, label, run);
    group.append(button);
    if (active) editor.on("transaction", () => button.classList.toggle("is-active", active()));
  };
  make(editing, "format_bold", "Bold", () => editor.chain().focus().toggleBold().run(), () => editor.isActive("bold"));
  make(editing, "format_italic", "Italic", () => editor.chain().focus().toggleItalic().run(), () => editor.isActive("italic"));
  make(editing, "format_underlined", "Underline", () => editor.chain().focus().toggleUnderline().run(), () => editor.isActive("underline"));
  make(editing, "strikethrough_s", "Strikethrough", () => editor.chain().focus().toggleStrike().run(), () => editor.isActive("strike"));
  make(editing, "code", "Inline code", () => editor.chain().focus().toggleCode().run(), () => editor.isActive("code"));
  make(editing, "link", "Link", () => openLink(), () => editor.isActive("link"));
  const commenting = el("div", { class: "cx-group cx-bubble-comment" });
  make(commenting, "add_comment", "Comment on selection", onComment);
  bubble.append(editing, commenting);
  const sync = () => {
    editing.style.display = editor.isEditable ? "" : "none";
  };
  editor.on("transaction", sync);
  sync();
}
