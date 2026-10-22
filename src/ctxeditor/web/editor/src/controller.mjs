// The editor controller: wires TipTap, the toolbars, comment highlights and the diff view together.
// The Vue component (context_editor.js) is a thin shell around this.
import { Editor } from "@tiptap/core";
import { BubbleMenu } from "@tiptap/extension-bubble-menu";
import { mountDiff } from "./diff-view.mjs";
import { CommentHighlights, anchorPosition, selectionAnchor } from "./extensions/comments.mjs";
import { blockContext } from "./extensions/blocks.mjs";
import { SlashCommands } from "./extensions/slash.mjs";
import { buildExtensions } from "./schema.mjs";
import { openLinkDialog } from "./ui/dialogs.mjs";
import { debounce, el } from "./ui/dom.mjs";
import { buildBubble, buildToolbar } from "./ui/toolbar.mjs";

export function createController({ root, toolbarHost, canvasHost, diffHost, html, readonly, commenting, placeholder, theme, callbacks }) {
  let currentTheme = theme;
  blockContext.root = root;
  blockContext.theme = () => currentTheme();
  blockContext.readonly = () => !editor.isEditable;

  let baseline = "";
  let dirty = false;
  let lastEmitted = null;
  let diff = null;

  const openLink = () => {
    if (!editor.isEditable) return;
    const href = editor.getAttributes("link").href || "";
    openLinkDialog(root, {
      href,
      onApply: (value) => editor.chain().focus().extendMarkRange("link").setLink({ href: value }).run(),
      onRemove: () => editor.chain().focus().extendMarkRange("link").unsetLink().run(),
    });
  };

  const emitValue = debounce(() => {
    const value = editor.getHTML();
    if (value !== lastEmitted) {
      lastEmitted = value;
      callbacks.onValue(value);
    }
  }, 500);

  const checkDirty = debounce(() => {
    const next = editor.getHTML() !== baseline;
    if (next !== dirty) {
      dirty = next;
      callbacks.onDirty(dirty);
    }
  }, 120);

  const bubbleEl = el("div", { class: "cx-bubble" });
  const editor = new Editor({
    element: canvasHost,
    content: html || "",
    editable: !readonly,
    extensions: [
      ...buildExtensions({ placeholder, shortcuts: { save: () => callbacks.onSave(), link: openLink } }),
      SlashCommands,
      CommentHighlights.configure({
        onClick: (id) => callbacks.onCommentClick(id),
        onResolved: (map) => callbacks.onAnchorsResolved(map),
      }),
      BubbleMenu.configure({
        element: bubbleEl,
        options: { placement: "top", offset: 8 },
        shouldShow: ({ editor: ed, state }) => {
          if (state.selection.empty) return false;
          if (ed.isActive("mermaid") || ed.isActive("chart")) return false;
          return ed.isEditable || root.classList.contains("cx-commenting");
        },
      }),
    ],
    editorProps: {
      attributes: { class: "cx-doc", spellcheck: "true", role: "textbox", "aria-multiline": "true", "aria-label": "Document" },
      handleClickOn: (_view, _pos, _node, _nodePos, event) => {
        const link = event.target instanceof Element ? event.target.closest("a[href]") : null;
        if (link && (!editor.isEditable || event.metaKey || event.ctrlKey)) {
          window.open(link.getAttribute("href"), "_blank", "noopener,noreferrer");
          return true;
        }
        return false;
      },
    },
    onUpdate: () => {
      emitValue();
      checkDirty();
    },
  });

  buildBubble(editor, bubbleEl, {
    openLink,
    onComment: () => {
      const anchor = selectionAnchor(editor);
      if (anchor) callbacks.onSelectionComment(anchor);
    },
  });
  const toolbar = buildToolbar(editor, { root, openLink });
  toolbarHost.append(toolbar.element);

  baseline = editor.getHTML();
  lastEmitted = baseline;

  return {
    editor,
    getHtml: () => editor.getHTML(),
    setHtml(next) {
      if (next === editor.getHTML()) return;
      editor.chain().setMeta("addToHistory", false).setContent(next || "", { emitUpdate: false }).run();
      baseline = editor.getHTML();
      lastEmitted = baseline;
      dirty = false;
      callbacks.onDirty(false);
    },
    // Put unsaved edits back after the owner looked at another version. The baseline stays the saved text, so the
    // document is dirty again, and the new value is pushed to the server straight away.
    restoreEdits(next) {
      editor.chain().setMeta("addToHistory", false).setContent(next || "", { emitUpdate: false }).run();
      lastEmitted = null;
      emitValue.flush();
      checkDirty.flush();
    },
    markClean() {
      baseline = editor.getHTML();
      lastEmitted = baseline;
      dirty = false;
      callbacks.onDirty(false);
    },
    isDirty: () => dirty,
    setReadonly(value) {
      editor.setEditable(!value);
      toolbar.refresh();
    },
    setAnchors: (anchors) => editor.commands.setCommentAnchors(anchors),
    setActiveAnchor: (id) => editor.commands.setActiveComment(id),
    scrollToAnchor(id) {
      const pos = anchorPosition(editor, id);
      if (pos === null) return false;
      const { node } = editor.view.domAtPos(pos);
      (node.nodeType === 1 ? node : node.parentElement)?.scrollIntoView({ block: "center", behavior: "smooth" });
      return true;
    },
    focus: () => editor.commands.focus(),
    async showDiff(segments, { decisions = true } = {}) {
      canvasHost.style.display = "none";
      diffHost.style.display = "";
      root.classList.add("cx-diffing");
      diff = await mountDiff(diffHost, segments, {
        decisions,
        theme: currentTheme(),
        onDecision: (d) => callbacks.onHunkDecision(d),
        onReady: (info) => callbacks.onDiffReady(info),
      });
      diff.scrollToFirst();
    },
    hideDiff() {
      diff = null;
      diffHost.replaceChildren();
      diffHost.style.display = "none";
      canvasHost.style.display = "";
      root.classList.remove("cx-diffing");
    },
    setAllDecisions: (value) => diff && diff.setAll(value),
    decisions: () => (diff ? diff.decisions() : {}),
    destroy() {
      emitValue.cancel();
      checkDirty.cancel();
      editor.destroy();
    },
  };
}
