// One renderer for Mermaid diagrams and charts. The editor node views, the read-only view, the diff view and the
// export page all call these functions, which is what makes diagrams and charts look the same everywhere.

let mermaidApi = null;
let mermaidCounter = 0;
let chartApi = null;

async function loadMermaid() {
  if (!mermaidApi) mermaidApi = (await import("mermaid")).default;
  return mermaidApi;
}

async function loadChart() {
  if (!chartApi) chartApi = (await import("chart.js/auto")).default;
  return chartApi;
}

const PALETTE = ["#4f6bed", "#e8743b", "#19a979", "#945ecf", "#13a4b4", "#cf4a6c", "#a3a31c", "#6c7a89"];
const PALETTE_DARK = ["#7d93ff", "#ff9a63", "#3ccf9c", "#b98aea", "#3cc7d6", "#ef7894", "#d2d24a", "#9fb0c0"];

function cleanupMermaidStrays(id) {
  document.getElementById(`d${id}`)?.remove();
  document.getElementById(id)?.remove();
}

// Renders `source` into `target`. Resolves {ok: true} or {ok: false, error}. On error the previous content of
// `target` is kept when `keepOnError` is set (the live preview does this so the last good diagram stays visible).
export async function renderMermaid(target, source, { theme = "light", keepOnError = false } = {}) {
  const mermaid = await loadMermaid();
  mermaid.initialize({
    startOnLoad: false,
    securityLevel: "strict",
    theme: theme === "dark" ? "dark" : "default",
    fontFamily: "Inter, system-ui, sans-serif",
  });
  const id = `cx-mermaid-${++mermaidCounter}`;
  try {
    await mermaid.parse(source);
    const { svg } = await mermaid.render(id, source);
    target.innerHTML = svg;
    target.classList.remove("cx-has-error");
    return { ok: true };
  } catch (error) {
    cleanupMermaidStrays(id);
    const message = String(error && error.message ? error.message : error).split("\n").slice(0, 4).join("\n");
    if (!keepOnError) {
      target.innerHTML = "";
      target.append(Object.assign(document.createElement("pre"), { className: "cx-error", textContent: message }));
      target.classList.add("cx-has-error");
    }
    return { ok: false, error: message };
  }
}

export function canonicalChart(spec) {
  return {
    type: spec.type,
    title: spec.title || "",
    labels: spec.labels,
    series: spec.series.map((s) => ({ name: s.name, values: s.values })),
  };
}

export function parseChart(raw) {
  try {
    const spec = JSON.parse(raw);
    if (!spec || !Array.isArray(spec.labels) || !Array.isArray(spec.series)) return null;
    return canonicalChart(spec);
  } catch {
    return null;
  }
}

function cssVar(node, name, fallback) {
  return getComputedStyle(node).getPropertyValue(name).trim() || fallback;
}

function chartConfig(spec, node, theme) {
  const dark = theme === "dark";
  const palette = dark ? PALETTE_DARK : PALETTE;
  const text = cssVar(node, "--cx-text", dark ? "#e6e8ee" : "#1f2430");
  const grid = cssVar(node, "--cx-border", dark ? "#343946" : "#e3e6ec");
  const pie = spec.type === "pie";
  const series = pie ? spec.series.slice(0, 1) : spec.series;
  const datasets = series.map((s, i) => ({
    label: s.name,
    data: s.values,
    backgroundColor: pie ? spec.labels.map((_, j) => palette[j % palette.length])
      : spec.type === "area" ? palette[i % palette.length] + "55" : palette[i % palette.length],
    borderColor: pie ? (dark ? "#1b1e27" : "#ffffff") : palette[i % palette.length],
    borderWidth: pie ? 2 : 2,
    fill: spec.type === "area",
    tension: spec.type === "line" || spec.type === "area" ? 0.3 : 0,
    pointRadius: spec.type === "line" || spec.type === "area" ? 3 : 0,
  }));
  return {
    type: spec.type === "area" ? "line" : spec.type,
    data: { labels: spec.labels, datasets },
    options: {
      animation: false, // deterministic for screenshots and print
      responsive: true,
      maintainAspectRatio: false,
      devicePixelRatio: Math.max(window.devicePixelRatio || 1, 2),
      plugins: {
        legend: { display: pie || series.length > 1, labels: { color: text, font: { family: "Inter, sans-serif" } } },
        title: { display: !!spec.title, text: spec.title, color: text, font: { family: "Inter, sans-serif", size: 14, weight: "600" } },
      },
      scales: pie ? {} : {
        x: { ticks: { color: text }, grid: { color: grid } },
        y: { ticks: { color: text }, grid: { color: grid }, beginAtZero: true },
      },
    },
  };
}

// Renders a chart into `target`. Returns {ok, destroy}.
export async function renderChart(target, spec, { theme = "light" } = {}) {
  const Chart = await loadChart();
  target.innerHTML = "";
  const holder = document.createElement("div");
  holder.className = "cx-chart-holder";
  const canvas = document.createElement("canvas");
  holder.append(canvas);
  target.append(holder);
  try {
    const chart = new Chart(canvas, chartConfig(spec, target, theme));
    return { ok: true, destroy: () => chart.destroy() };
  } catch (error) {
    holder.remove();
    target.append(Object.assign(document.createElement("pre"), { className: "cx-error", textContent: "This chart could not be drawn." }));
    return { ok: false, destroy() {} };
  }
}

// Static rendering of every diagram and chart under `root`: used by the diff view and by the export page.
// Resolves to {invalid: [elements whose diagram failed]}.
export async function renderBlocks(root, { theme = "light" } = {}) {
  const invalid = [];
  const jobs = [];
  root.querySelectorAll('div[data-type="mermaid"]').forEach((node) => {
    const source = node.textContent;
    node.classList.add("cx-block", "cx-mermaid");
    const holder = document.createElement("div");
    holder.className = "cx-block-render";
    node.textContent = "";
    node.append(holder);
    jobs.push(renderMermaid(holder, source, { theme }).then((result) => {
      if (!result.ok) invalid.push(node);
    }));
  });
  root.querySelectorAll('div[data-type="chart"]').forEach((node) => {
    const spec = parseChart(node.getAttribute("data-chart") || "");
    node.classList.add("cx-block", "cx-chart");
    const holder = document.createElement("div");
    holder.className = "cx-block-render";
    node.append(holder);
    if (spec) jobs.push(renderChart(holder, spec, { theme }));
    else {
      holder.textContent = "This chart has invalid data.";
      invalid.push(node);
    }
  });
  await Promise.all(jobs);
  return { invalid };
}
