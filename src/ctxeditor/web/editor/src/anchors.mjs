// Text-quote anchors (the W3C TextQuoteSelector idea). The document is never touched: a comment stores the quoted
// text plus a little context, and the editor finds it again in whatever version is shown.
//
// The "projection" is the plain text of the document: text nodes in order, one "\n" between text blocks. Offsets in the
// projection map back to ProseMirror positions through `segments`.

const CONTEXT = 32;

export function buildProjection(doc) {
  let text = "";
  let first = true;
  const segments = [];
  doc.descendants((node, pos) => {
    if (node.isTextblock) {
      if (!first) text += "\n";
      first = false;
    } else if (node.isText) {
      segments.push({ docStart: pos, docEnd: pos + node.nodeSize, textStart: text.length });
      text += node.text;
    }
    return true;
  });
  return { text, segments };
}

function commonSuffixLength(a, b) {
  let n = 0;
  while (n < a.length && n < b.length && a[a.length - 1 - n] === b[b.length - 1 - n]) n++;
  return n;
}

function commonPrefixLength(a, b) {
  let n = 0;
  while (n < a.length && n < b.length && a[n] === b[n]) n++;
  return n;
}

// Returns {start, end} offsets in the projection text, or null when the quote is no longer present.
export function resolveAnchor(text, anchor) {
  const quote = anchor.quote || "";
  if (!quote) return null;
  const prefix = anchor.prefix || "";
  const suffix = anchor.suffix || "";
  const hint = anchor.hint || 0;
  let best = null;
  let at = text.indexOf(quote);
  while (at !== -1) {
    const before = text.slice(Math.max(0, at - prefix.length), at);
    const after = text.slice(at + quote.length, at + quote.length + suffix.length);
    const score = commonSuffixLength(before, prefix) + commonPrefixLength(after, suffix);
    const distance = Math.abs(at - hint);
    if (!best || score > best.score || (score === best.score && distance < best.distance)) {
      best = { start: at, score, distance };
    }
    at = text.indexOf(quote, at + 1);
  }
  return best ? { start: best.start, end: best.start + quote.length } : null;
}

// ProseMirror ranges [from, to] (one per text node touched) covering the projection offsets [start, end).
export function rangesForOffsets(proj, start, end) {
  const ranges = [];
  for (const seg of proj.segments) {
    const length = seg.docEnd - seg.docStart;
    const segEnd = seg.textStart + length;
    const from = Math.max(start, seg.textStart);
    const to = Math.min(end, segEnd);
    if (from < to) ranges.push([seg.docStart + (from - seg.textStart), seg.docStart + (to - seg.textStart)]);
  }
  return ranges;
}

function posToOffset(proj, pos, preferEnd) {
  let found = null;
  for (const seg of proj.segments) {
    if (pos >= seg.docStart && pos <= seg.docEnd) {
      found = seg.textStart + (pos - seg.docStart);
      if (!preferEnd || pos < seg.docEnd) return found;
    }
  }
  if (found !== null) return found;
  // Between blocks: use the nearest segment edge.
  let nearest = null;
  for (const seg of proj.segments) {
    const distance = pos < seg.docStart ? seg.docStart - pos : pos - seg.docEnd;
    if (!nearest || distance < nearest.distance) {
      nearest = { distance, offset: pos < seg.docStart ? seg.textStart : seg.textStart + (seg.docEnd - seg.docStart) };
    }
  }
  return nearest ? nearest.offset : 0;
}

// The selector for a selection [from, to], or null when it covers no text.
export function anchorFromRange(proj, from, to) {
  const start = posToOffset(proj, from, false);
  const end = posToOffset(proj, to, true);
  if (end <= start) return null;
  const quote = proj.text.slice(start, end);
  if (!quote.trim()) return null;
  return {
    quote,
    prefix: proj.text.slice(Math.max(0, start - CONTEXT), start),
    suffix: proj.text.slice(end, end + CONTEXT),
    hint: start,
  };
}
