// The "/" command menu for inserting blocks.
import { Extension } from "@tiptap/core";
import { Suggestion } from "@tiptap/suggestion";
import { el } from "../ui/dom.mjs";

export const SLASH_ITEMS = [
  { title: "Text", hint: "Plain paragraph", icon: "notes", run: (e) => e.chain().focus().setParagraph().run() },
  { title: "Heading 1", hint: "Large section title", icon: "looks_one", run: (e) => e.chain().focus().setHeading({ level: 1 }).run() },
  { title: "Heading 2", hint: "Section title", icon: "looks_two", run: (e) => e.chain().focus().setHeading({ level: 2 }).run() },
  { title: "Heading 3", hint: "Subsection title", icon: "looks_3", run: (e) => e.chain().focus().setHeading({ level: 3 }).run() },
  { title: "Heading 4", hint: "Minor heading", icon: "looks_4", run: (e) => e.chain().focus().setHeading({ level: 4 }).run() },
  { title: "Bulleted list", hint: "Simple list", icon: "format_list_bulleted", run: (e) => e.chain().focus().toggleBulletList().run() },
  { title: "Numbered list", hint: "Ordered steps", icon: "format_list_numbered", run: (e) => e.chain().focus().toggleOrderedList().run() },
  { title: "Checklist", hint: "Track tasks", icon: "checklist", run: (e) => e.chain().focus().toggleTaskList().run() },
  { title: "Quote", hint: "Call out a quote", icon: "format_quote", run: (e) => e.chain().focus().toggleBlockquote().run() },
  { title: "Code block", hint: "Code with highlighting", icon: "data_object", run: (e) => e.chain().focus().toggleCodeBlock().run() },
  { title: "Table", hint: "Rows and columns", icon: "table_chart", run: (e) => e.chain().focus().insertTable({ rows: 3, cols: 3, withHeaderRow: true }).run() },
  { title: "Divider", hint: "Horizontal rule", icon: "horizontal_rule", run: (e) => e.chain().focus().setHorizontalRule().run() },
  { title: "Diagram", hint: "Mermaid diagram", icon: "account_tree", run: (e) => e.chain().focus().insertMermaid().run() },
  { title: "Chart", hint: "Bar, line, pie, area", icon: "bar_chart", run: (e) => e.chain().focus().insertChart().run() },
];

export const SlashCommands = Extension.create({
  name: "slashCommands",

  addProseMirrorPlugins() {
    const editor = this.editor;
    return [
      Suggestion({
        editor,
        char: "/",
        allowSpaces: true, // so "/heading 2" works; the menu hides itself when nothing matches
        startOfLine: false,
        items: ({ query }) => {
          const q = query.toLowerCase();
          return SLASH_ITEMS.filter((i) => i.title.toLowerCase().includes(q) || i.hint.toLowerCase().includes(q)).slice(0, 10);
        },
        command: ({ editor: ed, range, props }) => {
          ed.chain().focus().deleteRange(range).run();
          props.run(ed);
        },
        render: () => {
          let menu = null;
          let selected = 0;
          let items = [];
          let pick = () => {};

          const draw = () => {
            menu.style.display = items.length ? "" : "none";
            menu.replaceChildren(...(items.length
              ? items.map((item, i) => {
                const row = el("button", {
                  type: "button", role: "option", "aria-selected": String(i === selected),
                  class: `cx-slash-item ${i === selected ? "is-selected" : ""}`,
                }, el("span", { class: "material-icons", "aria-hidden": "true", text: item.icon }),
                el("span", { class: "cx-slash-text" }, el("strong", { text: item.title }), el("small", { text: item.hint })));
                row.addEventListener("mousedown", (event) => { event.preventDefault(); pick(item); });
                return row;
              })
              : [el("div", { class: "cx-slash-empty", text: "No matches" })]));
          };
          const place = (rect) => {
            if (!rect || !menu) return;
            const box = rect();
            if (!box) return;
            menu.style.left = `${Math.min(box.left, window.innerWidth - 280)}px`;
            menu.style.top = `${box.bottom + 6}px`;
          };
          return {
            onStart: (props) => {
              menu = el("div", { class: `cx-slash ${editor.options.element.closest(".cx-root")?.classList.contains("cx-dark") ? "cx-dark" : ""}`, role: "listbox", "aria-label": "Insert block" });
              document.body.append(menu);
              items = props.items;
              selected = 0;
              pick = (item) => props.command(item);
              draw();
              place(props.clientRect);
            },
            onUpdate: (props) => {
              items = props.items;
              selected = Math.min(selected, Math.max(items.length - 1, 0));
              pick = (item) => props.command(item);
              draw();
              place(props.clientRect);
            },
            onKeyDown: ({ event }) => {
              if (!items.length) return false; // nothing to pick: let the key through (Enter, arrows, ...)
              if (event.key === "ArrowDown") { selected = (selected + 1) % Math.max(items.length, 1); draw(); return true; }
              if (event.key === "ArrowUp") { selected = (selected - 1 + items.length) % Math.max(items.length, 1); draw(); return true; }
              if (event.key === "Enter") { if (items[selected]) pick(items[selected]); return true; }
              if (event.key === "Escape") { menu?.remove(); menu = null; return true; }
              return false;
            },
            onExit: () => { menu?.remove(); menu = null; },
          };
        },
      }),
    ];
  },
});
