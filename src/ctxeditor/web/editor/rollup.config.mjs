import commonjs from "@rollup/plugin-commonjs";
import json from "@rollup/plugin-json";
import nodeResolve from "@rollup/plugin-node-resolve";
import replace from "@rollup/plugin-replace";
import terser from "@rollup/plugin-terser";
import { copyFileSync, mkdirSync, readFileSync } from "node:fs";

// Imports of .css files become strings, so the component can inject them once and scope the dark theme.
const cssString = () => ({
  name: "css-string",
  transform(code, id) {
    if (!id.endsWith(".css")) return null;
    return { code: `export default ${JSON.stringify(readFileSync(id, "utf8"))};`, map: null };
  },
});

// The export page and the print template need the document stylesheet as a plain file.
const copyDocumentCss = () => ({
  name: "copy-document-css",
  writeBundle() {
    mkdirSync("./dist", { recursive: true });
    copyFileSync("./src/document.css", "./dist/document.css");
  },
});

export default {
  input: { index: "./src/index.mjs", export: "./src/export-entry.mjs" },
  output: {
    dir: "./dist/",
    format: "es",
    entryFileNames: "[name].js",
    chunkFileNames: "chunks/[name]-[hash].js",
    sourcemap: false,
  },
  plugins: [
    replace({ preventAssignment: true, values: { "process.env.NODE_ENV": JSON.stringify("production") } }),
    nodeResolve({ browser: true }),
    commonjs(),
    json(),
    cssString(),
    terser({ mangle: true }),
    copyDocumentCss(),
  ],
};
