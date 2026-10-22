import { describe, expect, it } from "vitest";
import { anchorFromRange, rangesForOffsets, resolveAnchor } from "./anchors.mjs";

const proj = {
  text: "Risk Impact\nVendor lock-in High\nVendor lock-in Low",
  segments: [
    { docStart: 1, docEnd: 12, textStart: 0 },
    { docStart: 14, docEnd: 31, textStart: 12 },
    { docStart: 33, docEnd: 49, textStart: 30 },
  ],
};

describe("resolveAnchor", () => {
  it("finds an exact quote", () => {
    const hit = resolveAnchor(proj.text, { quote: "Risk Impact", prefix: "", suffix: "", hint: 0 });
    expect(hit).toEqual({ start: 0, end: 11 });
  });

  it("disambiguates duplicates by prefix and suffix", () => {
    const second = proj.text.lastIndexOf("Vendor lock-in");
    const hit = resolveAnchor(proj.text, { quote: "Vendor lock-in", prefix: "High\n", suffix: " Low", hint: 0 });
    expect(hit.start).toBe(second);
    const first = resolveAnchor(proj.text, { quote: "Vendor lock-in", prefix: "Impact\n", suffix: " High", hint: 999 });
    expect(first.start).toBe(proj.text.indexOf("Vendor lock-in"));
  });

  it("falls back to the hint when context does not decide", () => {
    const hit = resolveAnchor(proj.text, { quote: "Vendor lock-in", prefix: "", suffix: "", hint: 40 });
    expect(hit.start).toBe(proj.text.lastIndexOf("Vendor lock-in"));
  });

  it("returns null when the text is gone", () => {
    expect(resolveAnchor(proj.text, { quote: "no longer here", prefix: "", suffix: "", hint: 0 })).toBeNull();
    expect(resolveAnchor(proj.text, { quote: "", prefix: "", suffix: "", hint: 0 })).toBeNull();
  });

  it("still finds moved text", () => {
    const moved = "Intro paragraph. " + proj.text;
    const hit = resolveAnchor(moved, { quote: "Risk Impact", prefix: "", suffix: "\nVendor", hint: 0 });
    expect(moved.slice(hit.start, hit.end)).toBe("Risk Impact");
  });
});

describe("rangesForOffsets", () => {
  it("maps offsets inside one text node", () => {
    expect(rangesForOffsets(proj, 0, 4)).toEqual([[1, 5]]);
  });
  it("splits a range across blocks", () => {
    const ranges = rangesForOffsets(proj, 5, 20);
    expect(ranges.length).toBe(2);
    expect(ranges[0]).toEqual([6, 12]);
  });
});

describe("anchorFromRange", () => {
  it("builds a selector with context and round-trips through resolveAnchor", () => {
    const anchor = anchorFromRange(proj, 14, 28);
    expect(anchor.quote).toBe("Vendor lock-in");
    expect(anchor.prefix.endsWith("\n")).toBe(true);
    const hit = resolveAnchor(proj.text, anchor);
    expect(proj.text.slice(hit.start, hit.end)).toBe("Vendor lock-in");
    expect(hit.start).toBe(12);
  });
  it("returns null for an empty selection", () => {
    expect(anchorFromRange(proj, 5, 5)).toBeNull();
  });
});
