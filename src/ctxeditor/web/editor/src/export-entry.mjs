// Entry for the export page (headless Chromium). Renders every diagram and chart with the same functions the
// editor uses, then flags completion so the exporter knows when to print or screenshot.
import { renderBlocks } from "./render/blocks.mjs";

async function run() {
  const root = document.querySelector(".cx-doc");
  try {
    if (root) await renderBlocks(root, { theme: "light" });
    if (document.fonts && document.fonts.ready) await document.fonts.ready;
  } finally {
    window.__renderDone = true;
  }
}

run();
