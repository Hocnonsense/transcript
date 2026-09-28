/** Source version chain: index each record by the version it was live in and
 *  the line it covered, and map points between adjacent versions.  Pure: the
 *  store owns the source text and calls these. */

import type { DiffSlot } from '../text/diff';
import type { RecordEntry, SourceRecord } from './records';
import type { Point, Span } from './span';

/** Sources indexed by the version they were live in and the line they covered
 *  (``byVersion``), and successors keyed by the parent version boundary and old
 *  line their ``cover`` names (``successors``). */
export interface ReviewIndex {
  /** Version → line → the source live there, where the version is its
   *  ``before`` boundary (``null`` for the live version). Parents are found from a
   *  source's ``cover`` and looked up here. */
  byVersion: Map<string | null, Map<number, SourceRecord>>;
  /** Parent version → old line → the successors that replaced it. Keyed by
   *  the parent's ``before``, which is what a successor's ``cover`` names. */
  successors: Map<string, Map<number, SourceRecord[]>>;
}

export function buildIndex(records: RecordEntry[]) {
  const byVersion = new Map<string | null, Map<number, SourceRecord>>();
  const successors = new Map<string, Map<number, SourceRecord[]>>();
  for (const record of records) {
    if (record.type !== 'source') continue;
    const span = record.at;
    const stamp = record.before ?? null;
    const lines = byVersion.get(stamp) ?? byVersion.set(stamp, new Map()).get(stamp)!;
    for (let line = span.lastLine(); line >= span.start_line; line -= 1) {
      lines.set(line, record);
    }
    if (record.cover) {
      const { span: old, time } = record.cover;
      const bucket = successors.get(time) ?? successors.set(time, new Map()).get(time)!;
      for (let line = old.start_line; line <= old.lastLine(); line += 1) {
        const list = bucket.get(line) ?? bucket.set(line, []).get(line)!;
        list.push(record);
      }
    }
  }
  for (const bucket of successors.values()) {
    bucket.forEach(list => list.sort((a, b) => {
      const delta_line = a.cover!.span.start_line - b.cover!.span.start_line;
      if (delta_line !== 0) return delta_line;
      return a.cover!.span.start_column - b.cover!.span.start_column;
    }));
  }
  return { byVersion, successors };
}

/** Whether ``[start, end)`` is fully contained in the union of *ranges*. */
export function coveredBy(ranges: { start: number; end: number }[], start: number, end: number) {
  const spans = [...ranges].sort((a, b) => a.start - b.start);
  let reach = start;
  for (const span of spans) {
    if (span.start > reach) break;
    if (span.end > reach) reach = span.end;
    if (reach >= end) return true;
  }
  return false;
}

/** One step of a line's version chain: the source and the line it names. */
export interface ChainNode {
  source: SourceRecord;
  span: Span;
  line: number;
}

/** Map an offset on the old side of an alignment to the new side.  Equal runs
 *  translate exactly; a replaced run spreads linearly, the same approximation
 *  the record spans already carry. */
export function mapOffset(slots: DiffSlot[], offset: number) {
  let old = 0;
  let next = 0;
  for (const slot of slots) {
    const width = slot.orig.length;
    if (offset < old + width) {
      return next + (width ? Math.round((offset - old) * slot.mod.length / width) : 0);
    }
    old += width;
    next += slot.mod.length;
  }
  return next;
}

/** Map an offset on the new side back to the old side: the inverse of
 *  :func:`mapOffset`, used when walking a version chain backwards. */
export function unmapOffset(slots: DiffSlot[], offset: number) {
  let old = 0;
  let next = 0;
  for (const slot of slots) {
    const width = slot.mod.length;
    if (offset < next + width) {
      return old + (width ? Math.round((offset - next) * slot.orig.length / width) : 0);
    }
    old += slot.orig.length;
    next += slot.mod.length;
  }
  return old;
}

/** The successor whose ``cover`` span holds *point* (left-closed), or the
 *  nearest one to its left when none does.  Assume children at the same line of
 *  the point. */
export function childAt(childs: SourceRecord[], point: Point) {
  let best: SourceRecord | null = null;
  for (const child of childs) {
    if (!child.cover) continue;
    const contain = child.cover.span.contains(point);
    if (contain === 0) return child;
    if (best === null || contain < 0) best = child;
  }
  return best;
}
