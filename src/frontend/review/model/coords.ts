/** Translate between archive coordinates (global 1-based ``L``/``C``) and a
 *  Markdown region's decoded literal, using the region's raw span and the
 *  decoded-to-raw index map recorded when it was sliced from the island. */

import { Span } from './span';

/** One region's slice of the archive body: its raw character span plus the raw
 *  offset each decoded character came from (monotonic). */
export interface RegionInfo {
  rawStart: number;
  rawEnd: number;
  text: string;
  map: number[];
}

/** The line and column (0-based) of raw offset *raw*. */
export function lineCol(lineStarts: number[], raw: number) {
  let low = 0;
  let high = lineStarts.length - 1;
  while (low < high) {
    const mid = (low + high + 1) >> 1;
    if (lineStarts[mid] <= raw) low = mid;
    else high = mid - 1;
  }
  return { line: low, col: raw - lineStarts[low] };
}

/** The raw offset of a 0-based line and column, clamped to the source. */
export function rawOf(source: string, lineStarts: number[], line: number, col: number) {
  const base = line < lineStarts.length ? lineStarts[line] : source.length;
  return Math.min(base + col, source.length);
}

/** The raw offset for decoded index *decoded*, or the region end when past it. */
export function decodedRaw(info: RegionInfo, decoded: number) {
  if (decoded >= info.map.length) return info.rawEnd - info.rawStart;
  return info.map[decoded];
}

/** The largest index whose *map* entry is <= *raw*, or the map length. */
export function rawToIndex(map: number[], raw: number) {
  let low = 0;
  let high = map.length;
  while (low < high) {
    const mid = (low + high) >> 1;
    if (map[mid] < raw) low = mid + 1;
    else high = mid;
  }
  return low;
}

/** The archive span covering decoded range ``[start, end)`` of *info*. */
export function decodedSpan(
  source: string, lineStarts: number[], info: RegionInfo, start: number, end: number,
) {
  const startRaw = info.rawStart + decodedRaw(info, start);
  const lastRaw = info.rawStart + decodedRaw(info, Math.max(end - 1, start));
  const first = lineCol(lineStarts, startRaw);
  const last = lineCol(lineStarts, lastRaw);
  return new Span(first.line, first.col, last.line, last.col + 1);
}

/** The archive span of the whole lines covering decoded range ``[start, end)``. */
export function decodedLineSpan(
  source: string, lineStarts: number[], info: RegionInfo, start: number, end: number,
) {
  const startRaw = info.rawStart + decodedRaw(info, start);
  const lastRaw = info.rawStart + decodedRaw(info, Math.max(end - 1, start));
  return new Span(
    lineCol(lineStarts, startRaw).line, 0, lineCol(lineStarts, lastRaw).line + 1, 0);
}

/** Decode an archive *span* into a decoded range of *info*, or ``null`` when it
 *  does not overlap the region or collapses to nothing. */
export function spanToDecoded(
  source: string, lineStarts: number[], info: RegionInfo, span: Span,
) {
  if (span.isEmpty()) return null;
  const startRaw = rawOf(source, lineStarts, span.start_line, span.start_column);
  const endRaw = rawOf(source, lineStarts, span.end_line, span.end_column);
  if (endRaw <= info.rawStart || startRaw >= info.rawEnd) return null;
  const start = rawToIndex(info.map, Math.max(startRaw - info.rawStart, 0));
  let end = rawToIndex(info.map, Math.min(endRaw - info.rawStart, info.rawEnd - info.rawStart));
  // A whole-line span reaches the next line's first character; drop the
  // trailing newline so the decoded range covers the line's content.
  while (end > start && info.text[end - 1] === '\n') end -= 1;
  if (end <= start) return null;
  return { start, end };
}
