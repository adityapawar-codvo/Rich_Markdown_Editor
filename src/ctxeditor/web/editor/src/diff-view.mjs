// Diff view for the AI agent's proposal and for comparing versions. The server computes the segments
// (ctxeditor/diffing.py); this draws them and reports accept/reject decisions. It never builds HTML to save.
import { renderBlocks } from "./render/blocks.mjs";
import { el, iconButton } from "./ui/dom.mjs";

const LABELS = { added: "Added", removed: "Removed", modified: "Changed" };

export async function mountDiff(host, segments, { decisions = true, theme = "light", onDecision, onReady }) {
  host.replaceChildren();
  const state = new Map();
  const invalid = new Set();
  const hunkNodes = new Map();

  const setState = (id, value, emit) => {
    state.set(id, value);
    const node = hunkNodes.get(id);
    if (node) {
      node.classList.remove("is-accepted", "is-rejected");
      if (value === "accepted") node.classList.add("is-accepted");
      if (value === "rejected") node.classList.add("is-rejected");
      node.querySelector(".cx-hunk-accept")?.setAttribute("aria-pressed", String(value === "accepted"));
      node.querySelector(".cx-hunk-reject")?.setAttribute("aria-pressed", String(value === "rejected"));
    }
    if (emit && onDecision) onDecision({ id, decision: value });
  };

  const body = (html, className = "") => {
    const node = el("div", { class: `cx-diff-body cx-doc ${className}` });
    node.innerHTML = html; // sanitized on the server
    return node;
  };

  for (const seg of segments) {
    if (seg.kind === "equal") {
      host.append(body(seg.new_html));
      continue;
    }
    const id = seg.hunk_id;
    const node = el("section", { class: `cx-hunk cx-hunk-${seg.kind}`, "data-hunk": id });
    const head = el("div", { class: "cx-hunk-head" }, el("span", { class: "cx-hunk-label", text: LABELS[seg.kind] }));
    if (decisions) {
      const accept = iconButton("check", `Accept this change`, () => setState(id, state.get(id) === "accepted" ? "pending" : "accepted", true), { class: "cx-btn cx-hunk-accept" });
      const reject = iconButton("close", `Reject this change`, () => setState(id, state.get(id) === "rejected" ? "pending" : "rejected", true), { class: "cx-btn cx-hunk-reject" });
      head.append(el("span", { class: "cx-group" }, accept, reject));
    }
    node.append(head);
    if (seg.kind === "added") node.append(body(seg.new_html, "cx-new"));
    else if (seg.kind === "removed") node.append(body(seg.old_html, "cx-old"));
    else if (seg.inline_html) node.append(body(seg.inline_html, "cx-inline"));
    else node.append(body(seg.old_html, "cx-old"), body(seg.new_html, "cx-new"));
    hunkNodes.set(id, node);
    state.set(id, "pending");
    host.append(node);
  }

  const { invalid: badBlocks } = await renderBlocks(host, { theme });
  for (const block of badBlocks) {
    const hunk = block.closest("[data-hunk]");
    if (hunk && block.closest(".cx-new, .cx-inline, .cx-diff-body")) {
      const id = hunk.getAttribute("data-hunk");
      if (block.closest(".cx-old")) continue;
      invalid.add(id);
      hunk.classList.add("is-invalid");
      hunk.querySelector(".cx-hunk-head")?.append(el("span", { class: "cx-hunk-warning", text: "Invalid diagram or chart" }));
      const accept = hunk.querySelector(".cx-hunk-accept");
      if (accept) accept.disabled = true;
    }
  }
  if (onReady) onReady({ invalid: [...invalid], hunks: [...hunkNodes.keys()] });

  return {
    decisions: () => Object.fromEntries(state),
    setAll(value) {
      for (const id of hunkNodes.keys()) {
        if (value === "accepted" && invalid.has(id)) continue;
        setState(id, value, true);
      }
    },
    scrollToFirst() {
      host.querySelector(".cx-hunk")?.scrollIntoView({ block: "center", behavior: "smooth" });
    },
  };
}
