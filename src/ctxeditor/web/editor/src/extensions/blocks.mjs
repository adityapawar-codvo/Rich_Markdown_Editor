// Mermaid and chart blocks: atom nodes whose node views use the shared renderers.
import { Node } from "@tiptap/core";
import { canonicalChart, parseChart, renderChart, renderMermaid } from "../render/blocks.mjs";
import { DEFAULT_CHART, DEFAULT_MERMAID, openChartDialog, openMermaidDialog } from "../ui/dialogs.mjs";

// The editor passes its environment (theme, root element) through this context object.
export const blockContext = { root: null, theme: () => "light", readonly: () => false };

function blockDom(kind, label) {
  const dom = document.createElement("div");
  dom.className = `cx-block cx-${kind}`;
  dom.setAttribute("data-block-kind", kind);
  const render = document.createElement("div");
  render.className = "cx-block-render";
  const edit = document.createElement("button");
  edit.type = "button";
  edit.className = "cx-block-edit";
  edit.setAttribute("aria-label", label);
  edit.title = label;
  edit.innerHTML = '<span class="material-icons" aria-hidden="true">edit</span>';
  dom.append(render, edit);
  return { dom, render, edit };
}

export const MermaidBlock = Node.create({
  name: "mermaid",
  group: "block",
  atom: true,
  selectable: true,
  draggable: true,

  addAttributes() {
    return { code: { default: DEFAULT_MERMAID, rendered: false, parseHTML: (element) => element.textContent } };
  },

  parseHTML() {
    return [{ tag: 'div[data-type="mermaid"]', preserveWhitespace: "full" }];
  },

  renderHTML({ node }) {
    return ["div", { "data-type": "mermaid" }, node.attrs.code];
  },

  addCommands() {
    return {
      insertMermaid: () => ({ commands }) =>
        commands.insertContent({ type: this.name, attrs: { code: DEFAULT_MERMAID } }),
    };
  },

  addNodeView() {
    return ({ node, getPos, editor }) => {
      const { dom, render, edit } = blockDom("mermaid", "Edit diagram");
      let current = node;
      let token = 0;
      const draw = async () => {
        const mine = ++token;
        const holder = document.createElement("div");
        const result = await renderMermaid(holder, current.attrs.code, { theme: blockContext.theme() });
        if (mine !== token) return;
        render.replaceChildren(...holder.childNodes);
        dom.classList.toggle("cx-has-error", !result.ok);
      };
      const openEditor = () => {
        if (blockContext.readonly()) return;
        openMermaidDialog(blockContext.root, {
          code: current.attrs.code,
          theme: blockContext.theme(),
          onSave: (code) => {
            const pos = getPos();
            editor.chain().focus().command(({ tr }) => {
              tr.setNodeMarkup(pos, undefined, { code });
              return true;
            }).run();
          },
        });
      };
      dom.addEventListener("click", openEditor);
      edit.addEventListener("click", (event) => { event.stopPropagation(); openEditor(); });
      document.addEventListener("cx-theme-change", draw);
      draw();
      return {
        dom,
        update(next) {
          if (next.type !== node.type) return false;
          const changed = next.attrs.code !== current.attrs.code;
          current = next;
          if (changed) draw();
          return true;
        },
        stopEvent: () => true,
        ignoreMutation: () => true,
        destroy() { document.removeEventListener("cx-theme-change", draw); },
      };
    };
  },
});

export const ChartBlock = Node.create({
  name: "chart",
  group: "block",
  atom: true,
  selectable: true,
  draggable: true,

  addAttributes() {
    return {
      spec: {
        default: DEFAULT_CHART,
        rendered: false,
        parseHTML: (element) => parseChart(element.getAttribute("data-chart") || "") || DEFAULT_CHART,
      },
    };
  },

  parseHTML() {
    return [{ tag: 'div[data-type="chart"]' }];
  },

  renderHTML({ node }) {
    return ["div", { "data-type": "chart", "data-chart": JSON.stringify(canonicalChart(node.attrs.spec)) }];
  },

  addCommands() {
    return {
      insertChart: () => ({ commands }) =>
        commands.insertContent({ type: this.name, attrs: { spec: DEFAULT_CHART } }),
    };
  },

  addNodeView() {
    return ({ node, getPos, editor }) => {
      const { dom, render, edit } = blockDom("chart", "Edit chart");
      let current = node;
      let handle = null;
      let token = 0;
      const draw = async () => {
        const mine = ++token;
        const holder = document.createElement("div");
        const result = await renderChart(holder, canonicalChart(current.attrs.spec), { theme: blockContext.theme() });
        if (mine !== token) { result.destroy(); return; }
        if (handle) handle.destroy();
        handle = result;
        render.replaceChildren(...holder.childNodes);
      };
      const openEditor = () => {
        if (blockContext.readonly()) return;
        openChartDialog(blockContext.root, {
          spec: current.attrs.spec,
          theme: blockContext.theme(),
          onSave: (spec) => {
            const pos = getPos();
            editor.chain().focus().command(({ tr }) => {
              tr.setNodeMarkup(pos, undefined, { spec });
              return true;
            }).run();
          },
        });
      };
      dom.addEventListener("click", openEditor);
      edit.addEventListener("click", (event) => { event.stopPropagation(); openEditor(); });
      document.addEventListener("cx-theme-change", draw);
      draw();
      return {
        dom,
        update(next) {
          if (next.type !== node.type) return false;
          const changed = JSON.stringify(next.attrs.spec) !== JSON.stringify(current.attrs.spec);
          current = next;
          if (changed) draw();
          return true;
        },
        stopEvent: () => true,
        ignoreMutation: () => true,
        destroy() {
          document.removeEventListener("cx-theme-change", draw);
          if (handle) handle.destroy();
        },
      };
    };
  },
});
