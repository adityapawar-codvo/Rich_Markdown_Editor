import { createController, documentCss, uiCss } from "context-editor-bundle";

const STYLE_ID = "context-editor-styles";
const FONTS_ID = "context-editor-fonts";

function injectStyles() {
  if (!document.getElementById(STYLE_ID)) {
    const style = document.createElement("style");
    style.id = STYLE_ID;
    style.textContent = documentCss + "\n" + uiCss;
    document.head.appendChild(style);
  }
  if (!document.getElementById(FONTS_ID)) {
    const link = document.createElement("link");
    link.id = FONTS_ID;
    link.rel = "stylesheet";
    link.href = "/_ctxeditor/fonts.css";
    document.head.appendChild(link);
  }
}

export default {
  template: `
    <div ref="root" class="cx-root"
         :class="{ 'cx-dark': isDark, 'cx-readonly': readonly, 'cx-commenting': commenting }">
      <div ref="toolbar" class="cx-toolbar-host" v-show="!readonly && !inDiff"></div>
      <div class="cx-scroll" ref="scroll">
        <div v-if="!ready" class="cx-skeleton" aria-hidden="true"><span></span><span></span><span></span><span></span><span></span></div>
        <div ref="canvas" class="cx-canvas"></div>
        <div ref="diff" class="cx-diff-host" style="display:none"></div>
      </div>
    </div>`,
  props: {
    value: String,
    readonly: Boolean,
    commenting: Boolean,
    guard: Boolean, // the server holds unsaved edits aside: warn before the page is closed
    theme: { type: String, default: "auto" }, // "auto" follows Quasar dark mode, or "light" / "dark"
    placeholder: { type: String, default: "Write, or type / for commands" },
  },
  data() {
    return { ready: false, inDiff: false };
  },
  computed: {
    isDark() {
      return this.theme === "dark" || (this.theme !== "light" && this.$q.dark.isActive);
    },
  },
  watch: {
    value(next) {
      if (this.controller) this.controller.setHtml(next ?? "");
    },
    readonly(next) {
      if (this.controller) this.controller.setReadonly(next);
    },
    isDark() {
      this.$nextTick(() => document.dispatchEvent(new CustomEvent("cx-theme-change")));
    },
  },
  mounted() {
    injectStyles();
    this.controller = createController({
      root: this.$refs.root,
      toolbarHost: this.$refs.toolbar,
      canvasHost: this.$refs.canvas,
      diffHost: this.$refs.diff,
      html: this.value ?? "",
      readonly: this.readonly,
      commenting: this.commenting,
      placeholder: this.placeholder,
      theme: () => (this.isDark ? "dark" : "light"),
      callbacks: {
        onValue: (html) => this.$emit("update:value", html),
        onDirty: (dirty) => {
          this.isDirty = dirty;
          this.$emit("dirty", dirty);
        },
        onSave: () => this.$emit("save"),
        onSelectionComment: (anchor) => this.$emit("selection_comment", anchor),
        onCommentClick: (id) => this.$emit("comment_click", id),
        onAnchorsResolved: (map) => this.$emit("anchors_resolved", map),
        onHunkDecision: (decision) => this.$emit("hunk_decision", decision),
        onDiffReady: (info) => this.$emit("diff_ready", info),
      },
    });
    this.beforeUnload = (event) => {
      if ((this.isDirty && !this.readonly) || this.guard) {
        event.preventDefault();
        event.returnValue = ""; // the browser shows its own "leave site?" prompt
      }
    };
    window.addEventListener("beforeunload", this.beforeUnload);
    this.$refs.root.__cxController = this.controller; // lets browser tests read the editor's own serialization
    this.ready = true;
    this.$emit("ready", this.controller.getHtml());
  },
  beforeUnmount() {
    window.removeEventListener("beforeunload", this.beforeUnload);
    if (this.controller) this.controller.destroy();
  },
  methods: {
    getHTML() {
      return this.controller.getHtml();
    },
    setContent(html) {
      this.controller.setHtml(html ?? "");
    },
    restoreEdits(html) {
      this.controller.restoreEdits(html ?? "");
    },
    markClean() {
      this.controller.markClean();
    },
    focus() {
      this.controller.focus();
    },
    setAnchors(anchors) {
      this.controller.setAnchors(anchors);
    },
    setActiveAnchor(id) {
      this.controller.setActiveAnchor(id);
    },
    scrollToAnchor(id) {
      return this.controller.scrollToAnchor(id);
    },
    async showDiff(segments, decisions) {
      this.inDiff = true;
      await this.controller.showDiff(segments, { decisions });
    },
    hideDiff() {
      this.controller.hideDiff();
      this.inDiff = false;
    },
    setAllDecisions(value) {
      this.controller.setAllDecisions(value);
    },
    getDecisions() {
      return this.controller.decisions();
    },
  },
};
