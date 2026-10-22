// The editor schema. Every node and mark configured here must serialize to HTML that the server-side allowlist
// (ctxeditor/sanitizer.py) accepts unchanged. tests/test_roundtrip.py proves that against the real editor.
import { Extension } from "@tiptap/core";
import Link from "@tiptap/extension-link";
import { CodeBlockLowlight } from "@tiptap/extension-code-block-lowlight";
import { Highlight } from "@tiptap/extension-highlight";
import { TaskItem, TaskList } from "@tiptap/extension-list";
import Subscript from "@tiptap/extension-subscript";
import Superscript from "@tiptap/extension-superscript";
import { Table, TableCell, TableHeader, TableRow } from "@tiptap/extension-table";
import TextAlign from "@tiptap/extension-text-align";
import { Color, TextStyle } from "@tiptap/extension-text-style";
import { Placeholder } from "@tiptap/extensions";
import StarterKit from "@tiptap/starter-kit";
import { common, createLowlight } from "lowlight";
import { ChartBlock, MermaidBlock } from "./extensions/blocks.mjs";

const lowlight = createLowlight(common);

// Only http, https and mailto links (and relative ones) are ever stored.
function isAllowedUri(url, context) {
  if (!context.defaultValidate(url)) return false;
  return !/^[a-z][a-z0-9+.-]*:/i.test(url) || /^(https?|mailto):/i.test(url);
}

// The checkbox exists only in the node view. Storage is <li data-type="taskItem" data-checked><div>..</div></li>.
const ChecklistItem = TaskItem.extend({
  renderHTML({ node }) {
    return ["li", { "data-type": "taskItem", "data-checked": node.attrs.checked ? "true" : "false" }, ["div", 0]];
  },
  addNodeView() {
    return ({ node, getPos, editor }) => {
      const dom = document.createElement("li");
      dom.setAttribute("data-type", "taskItem");
      const box = document.createElement("input");
      box.type = "checkbox";
      box.setAttribute("aria-label", "Done");
      const label = document.createElement("label");
      label.contentEditable = "false";
      label.append(box);
      const content = document.createElement("div");
      dom.append(label, content);
      const sync = (n) => {
        box.checked = !!n.attrs.checked;
        dom.setAttribute("data-checked", n.attrs.checked ? "true" : "false");
        box.disabled = !editor.isEditable;
      };
      sync(node);
      box.addEventListener("change", () => {
        if (!editor.isEditable) { box.checked = !box.checked; return; }
        editor.chain().focus().command(({ tr }) => {
          tr.setNodeMarkup(getPos(), undefined, { ...node.attrs, checked: box.checked });
          return true;
        }).run();
      });
      return {
        dom,
        contentDOM: content,
        update(next) {
          if (next.type !== node.type) return false;
          node = next;
          sync(next);
          return true;
        },
      };
    };
  },
}).configure({ nested: true });

// No colgroup or widths are stored: column resizing is off.
const PlainTable = Table.extend({
  renderHTML() {
    return ["table", {}, ["tbody", 0]];
  },
}).configure({ resizable: false });

const noWidth = { colwidth: { default: null, rendered: false } };
const Cell = TableCell.extend({ addAttributes() { return { ...this.parent?.(), ...noWidth }; } });
const HeaderCell = TableHeader.extend({ addAttributes() { return { ...this.parent?.(), ...noWidth }; } });

// Highlight stores only a background-color style (the sanitizer keeps nothing else).
const Marker = Highlight.extend({
  addAttributes() {
    return {
      color: {
        default: null,
        parseHTML: (element) => element.style.backgroundColor || element.getAttribute("data-color") || null,
        renderHTML: (attributes) => (attributes.color ? { style: `background-color: ${attributes.color}` } : {}),
      },
    };
  },
}).configure({ multicolor: true });

const Hyperlink = Link.extend({
  renderHTML({ HTMLAttributes }) {
    return ["a", { href: HTMLAttributes.href, target: "_blank", rel: "noopener noreferrer" }, 0];
  },
}).configure({ openOnClick: false, autolink: true, linkOnPaste: true, isAllowedUri });

export function buildExtensions({ placeholder = "Write, or type / for commands", shortcuts = {} } = {}) {
  const hooks = Extension.create({
    name: "contextShortcuts",
    addKeyboardShortcuts() {
      return {
        "Mod-s": () => { shortcuts.save?.(); return true; },
        "Mod-k": () => { shortcuts.link?.(); return true; },
      };
    },
  });
  return [
    StarterKit.configure({
      heading: { levels: [1, 2, 3, 4] },
      codeBlock: false,
      trailingNode: false, // would append an empty paragraph to every document
      link: false, // replaced below so href comes first, like the stored form
    }),
    CodeBlockLowlight.configure({ lowlight, defaultLanguage: null }),
    Hyperlink,
    Subscript,
    Superscript,
    TextStyle,
    Color,
    Marker,
    TextAlign.configure({ types: ["heading", "paragraph"] }),
    PlainTable,
    TableRow,
    HeaderCell,
    Cell,
    TaskList,
    ChecklistItem,
    MermaidBlock,
    ChartBlock,
    Placeholder.configure({ placeholder }),
    hooks,
  ];
}
