// Comment highlights as ProseMirror decorations. Nothing is written into the document: a comment's anchor is a
// text-quote selector stored by the server, resolved against whatever version the editor is showing.
import { Extension } from "@tiptap/core";
import { Plugin, PluginKey } from "@tiptap/pm/state";
import { Decoration, DecorationSet } from "@tiptap/pm/view";
import { anchorFromRange, buildProjection, rangesForOffsets, resolveAnchor } from "../anchors.mjs";

export const commentKey = new PluginKey("contextComments");

function compute(doc, anchors, activeId) {
  const proj = buildProjection(doc);
  const decorations = [];
  const resolved = {};
  for (const anchor of anchors) {
    const hit = resolveAnchor(proj.text, anchor);
    resolved[anchor.id] = !!hit;
    if (!hit) continue;
    const classes = ["cx-comment"];
    if (anchor.status === "resolved") classes.push("cx-comment-resolved");
    if (anchor.id === activeId) classes.push("cx-comment-active");
    for (const [from, to] of rangesForOffsets(proj, hit.start, hit.end)) {
      decorations.push(Decoration.inline(from, to, { class: classes.join(" "), "data-anchor-id": anchor.id }));
    }
  }
  return { set: DecorationSet.create(doc, decorations), resolved };
}

export const CommentHighlights = Extension.create({
  name: "commentHighlights",

  addOptions() {
    return { onClick: () => {}, onResolved: () => {} };
  },

  addCommands() {
    return {
      setCommentAnchors: (anchors) => ({ tr, dispatch }) => {
        if (dispatch) dispatch(tr.setMeta(commentKey, { anchors }));
        return true;
      },
      setActiveComment: (id) => ({ tr, dispatch }) => {
        if (dispatch) dispatch(tr.setMeta(commentKey, { active: id }));
        return true;
      },
    };
  },

  addProseMirrorPlugins() {
    const options = this.options;
    let lastReported = "";
    return [
      new Plugin({
        key: commentKey,
        state: {
          init: (_, state) => ({ anchors: [], active: null, ...compute(state.doc, [], null) }),
          apply(tr, value, _old, state) {
            const meta = tr.getMeta(commentKey);
            if (!meta && !tr.docChanged) return value;
            const anchors = meta?.anchors ?? value.anchors;
            const active = meta && "active" in meta ? meta.active : value.active;
            return { anchors, active, ...compute(state.doc, anchors, active) };
          },
        },
        props: {
          decorations: (state) => commentKey.getState(state).set,
          handleDOMEvents: {
            click: (_view, event) => {
              const target = event.target instanceof Element ? event.target.closest("[data-anchor-id]") : null;
              if (target) options.onClick(target.getAttribute("data-anchor-id"));
              return false;
            },
          },
        },
        view: () => ({
          update: (view) => {
            const { resolved } = commentKey.getState(view.state);
            const key = JSON.stringify(resolved);
            if (key !== lastReported) {
              lastReported = key;
              queueMicrotask(() => options.onResolved(resolved));
            }
          },
        }),
      }),
    ];
  },
});

// The selector for the current selection, or null.
export function selectionAnchor(editor) {
  const { from, to, empty } = editor.state.selection;
  if (empty) return null;
  return anchorFromRange(buildProjection(editor.state.doc), from, to);
}

// First document position of an anchor (for scrolling), or null.
export function anchorPosition(editor, id) {
  const { anchors } = commentKey.getState(editor.state);
  const anchor = anchors.find((a) => a.id === id);
  if (!anchor) return null;
  const proj = buildProjection(editor.state.doc);
  const hit = resolveAnchor(proj.text, anchor);
  if (!hit) return null;
  const ranges = rangesForOffsets(proj, hit.start, hit.end);
  return ranges.length ? ranges[0][0] : null;
}
