/** Shared review persistence for every Markdown region on the page.
 *
 * Records use the archive's global 1-based ``L``/``C`` coordinates, while a
 * region works on its decoded literal. The store keeps, for each region, the
 * raw source span and the decoded-to-raw index map, so a record's ``at`` can be
 * translated both ways. It also owns the record list and serializes the
 * trailing ``snakedone.review`` block when the page is exported.
 */

import { Annotation } from './annotation';
import { History, HistoryEntry } from './history/history';
import { exportIsland, exportSource, renderBlock } from './model/block';
import { buildIndex, childAt, coveredBy, mapOffset, unmapOffset } from './model/chain';
import type { ChainNode, ReviewIndex } from './model/chain';
import {
  decodedLineSpan as regionLineSpan,
  decodedSpan as regionSpan,
  spanToDecoded as toDecoded,
} from './model/coords';
import type { RegionInfo } from './model/coords';
import { RawRecordEntry, RecordEntry, ReviewRecord, SourceRecord, parseRecords } from './model/records';
import { At, Span, fullLines, lineAt, lineStarts } from './model/span';
import type { Point } from './model/span';
import { diffText } from './text/diff';
import type { MarkdownReview } from './review';

export class ReviewStore {
  source: string;
  records: RecordEntry[];
  /** The body hash Python recorded for the body, reused when writing a block. */
  hash: string;
  lineStarts: number[];
  regions: Map<MarkdownReview, RegionInfo> = new Map();
  annotations: Map<MarkdownReview, Annotation[]> = new Map();
  /** Built on first use (first render); sources never change within the page. */
  private cache: ReviewIndex | null = null;

  constructor(source: string, records: RawRecordEntry[], hash: string) {
    this.source = source;
    this.records = Array.isArray(records) ? parseRecords(records) : [];
    this.hash = typeof hash === 'string' ? hash : '';
    this.lineStarts = lineStarts(source);
  }

  /** Register *region* and return the annotation array it should reference.
   *  The array is filled by :meth:`buildAnnotations` once every region is in. */
  addRegion(region: MarkdownReview, rawStart: number, rawEnd: number, text: string, map: number[]) {
    this.regions.set(region, { rawStart, rawEnd, text, map });
    const list: Annotation[] = [];
    this.annotations.set(region, list);
    return list;
  }

  /** The source index, built once on first use and rebuilt after a change. */
  private index() {
    if (!this.cache) this.cache = buildIndex(this.records);
    return this.cache;
  }

  /** The source that was live on *line* when *record* was written: the version
   *  its ``coveredAt`` names (the covering version's boundary), or the live source
   *  when the run is still current. */
  private anchor(line: number, record: ReviewRecord) {
    return this.index().byVersion.get(record.versionOf(line))?.get(line) ?? null;
  }

  /** Follow the version chain from a written review to the live text.  The
   *  first selected character and the position one past the last are located
   *  with the same left-closed ``[s, e)`` rule, so a split or a merge bounds
   *  every image.  A review already on the newest source keeps its span. */
  currentSpan(record: ReviewRecord) {
    const span = record.at;
    const start = this.forwardPoint(record, span.start());
    if (span.isEmpty()) return Span.fromPoints(start, start);
    let end: Point;
    if (span.end_column !== 0) {
      const last = this.forwardPoint(record, {
        line: span.end_line, column: span.end_column - 1,
      });
      end = { line: last.line, column: last.column + 1 };
    } else {
      const lastLine = span.lastLine();
      const source = this.anchor(lastLine, record);
      const length = source
        ? this.lineText(source, lastLine).length : this.bodyLine(lastLine).length;
      const last = this.forwardPoint(record, {
        line: lastLine, column: Math.max(length - 1, 0),
      });
      end = { line: last.line, column: last.column + 1 };
      if (end.column >= this.bodyLine(end.line).length) {
        end = { line: end.line + 1, column: 0 };
      }
    }
    if (start.line === span.start_line && start.column === span.start_column
      && end.line === span.end_line && end.column === span.end_column) return span;
    return Span.fromPoints(start, end);
  }

  /** The live point a written *point* maps to, stepping to the successor that
   *  covers it while the current source still has a ``cover``.  The newest
   *  source has none, so the point stays. */
  private forwardPoint(record: ReviewRecord, point: Point): Point {
    let source = this.anchor(point.line, record);
    if (!source) return point;
    let current = point;
    while (source.before) {
      const childs = this.index().successors.get(source.before)?.get(current.line) ?? [];
      const next = childAt(childs, current)!;
      current = this.mapPoint(next, current);
      source = next;
    }
    return current;
  }

  /** The predecessor text ``cover.span`` names and the successor's own text
   *  ``at`` names, with the cached diff between them. */
  private getDiff(next: SourceRecord) {
    const cover = next.cover;
    if (!cover) return null;
    const prevText = this.coverText(cover);
    const nextText = next.source ?? next.at.extract(this.source, this.lineStarts) ?? '';
    const diff = next.parts(() => diffText(prevText, nextText)) ?? [];
    return { prevText, nextText, diff };
  }

  /** Map a point from a source's predecessor version into its own. */
  private mapPoint(next: SourceRecord, point: Point): Point {
    const diff = this.getDiff(next);
    if (!diff || !next.cover) return point;
    const offset = next.cover.span.offsetOf(diff.prevText, point);
    return next.at.pointAt(diff.nextText, mapOffset(diff.diff, offset));
  }

  /** Map a point from a source's own version back into its predecessor's. */
  private backPoint(next: SourceRecord, point: Point): Point {
    const diff = this.getDiff(next);
    if (!diff || !next.cover) return point;
    const offset = next.at.offsetOf(diff.nextText, point);
    return next.cover.span.pointAt(diff.prevText, unmapOffset(diff.diff, offset));
  }

  /** The text ``cover.span`` names, assembled line by line from whichever
   *  source was live then (a merge spans several). */
  private coverText(cover: At) {
    const lines: string[] = [];
    for (let line = cover.span.start_line; line <= cover.span.lastLine(); line += 1) {
      const parent = this.index().byVersion.get(cover.time)?.get(line);
      lines.push((parent ? this.lineText(parent, line) : '') + '\n');
    }
    const joined = lines.join('');
    const local = cover.span.relativeTo({ line: cover.span.start_line, column: 0 });
    return local.extract(joined) ?? '';
  }

  /** One line of the current body. */
  private bodyLine(line: number): string {
    return lineAt(this.source, this.lineStarts, line);
  }

  /** The recorded text of *source*'s line *line*: its own frozen ``source``
   *  when superseded, the current body otherwise. */
  private lineText(source: SourceRecord, line: number): string {
    const span = source.at;
    const offset = line - span.start_line;
    if (typeof source.source === 'string') {
      return source.source.replace(/\n$/, '').split('\n')[offset] ?? '';
    }
    return this.bodyLine(line);
  }

  /** The versions of *line*, oldest first, as source plus line in that version.
   *  Walks the ``cover`` chain backwards, mapping the point through the same
   *  cached diff the forward pass uses. */
  private chainFor(line: number): ChainNode[] {
    const { byVersion } = this.index();
    let node: SourceRecord | null = byVersion.get(null)?.get(line) ?? null;
    let at: Point = { line, column: 0 };
    const nodes: ChainNode[] = [];
    while (node) {
      nodes.push({ source: node, span: node.at, line: at.line });
      const point = this.backPoint(node, at);
      const parent = node.cover
        ? byVersion.get(node.cover.time)?.get(point.line) : null;
      if (!parent || parent === node) break;
      node = parent;
      at = point;
    }
    nodes.reverse();
    return nodes;
  }

  /** Distribute every review record to the regions it intersects.  Called once
   *  after all regions are registered, so a record is mapped to the live text
   *  only once and then clipped into each region. */
  buildAnnotations() {
    for (const record of this.records) {
      if (record.type !== 'review') continue;
      let live: Span;
      try { live = this.currentSpan(record); } catch (error) { continue; }
      // A review keeps its written coordinates; follow the chain to place it on the current document.
      const modified = typeof record.edit === 'string';
      const locked = this.isLocked(record, live);
      for (const [region, info] of this.regions) {
        const chosen = this.spanToDecoded(info, live);
        if (!chosen) continue;
        const line = fullLines(info.text, chosen.start, chosen.end);
        const original = info.text.slice(line.start, line.end);
        this.annotations.get(region)!.push(new Annotation({
          record,
          chosen,
          original,
          edit: modified ? record.edit : original,
          comment: record.comment || '',
          modified,
          locked,
        }));
      }
    }
  }

  /** Whether a review touches a superseded or untracked line. Such a review can
   *  be deleted but not edited: its recorded text no longer matches the
   *  current document, so the box would edit text the reviewer never saw. */
  private isLocked(record: ReviewRecord, span: Span) {
    if (record.coveredAt.length) return true;
    for (let line = span.start_line; line <= span.lastLine(); line += 1) {
      if (!this.hasLiveSource(line)) return true;
    }
    return false;
  }

  /** The annotations that deserve a badge: those whose range is not fully
   *  covered by the union of newer such annotations. A newer annotation counts
   *  even when it is superseded, so long as it is itself not covered. */
  visible(region: any): Annotation[] {
    const list = (this.annotations.get(region) ?? []).filter(item => item.record);
    // Newest first; a tie on time treats the later record as newer, so the
    // result does not depend on the sort's stability.
    const order = new Map(list.map((item, index) => [item, index]));
    const newestFirst = [...list].sort((a, b) => {
      const left = a.record?.time ?? '';
      const right = b.record?.time ?? '';
      if (left !== right) return left < right ? 1 : -1;
      return (order.get(b) ?? 0) - (order.get(a) ?? 0);
    });
    const accepted: { start: number; end: number }[] = [];
    const shown: Annotation[] = [];
    for (const annotation of newestFirst) {
      if (!coveredBy(accepted, annotation.chosen.start, annotation.chosen.end)) {
        shown.push(annotation);
        accepted.push(annotation.chosen);
      }
    }
    return shown;
  }

  private hasLiveSource(line: number) {
    return this.index().byVersion.get(null)?.has(line) ?? false;
  }

  private rawLine(line: number) {
    return lineAt(this.source, this.lineStarts, line);
  }

  /** The version stack for *annotation*'s window: one text per version, oldest
   *  first, with the reviews placed after the version they were written
   *  against. A review fully covered by a newer one is marked hidden. Returns
   *  null for a not-yet-saved annotation. */
  history(region: MarkdownReview, annotation: Annotation): History | null {
    const info = this.regions.get(region);
    if (!info || !annotation.record) return null;
    const window = this.decodedSpan(
      info, annotation.chosen.start, annotation.chosen.end);
    const sl = window.start_line;
    const el = window.lastLine();
    let indent = '';
    for (let line = sl; line <= el; line += 1) {
      const text = this.rawLine(line);
      if (text.trim()) { indent = (text.match(/^[ \t]*/) || [''])[0]; break; }
    }
    const strip = (text: string) =>
      indent && text.startsWith(indent) ? text.slice(indent.length) : text;

    const chains = new Map<number, ChainNode[]>();
    for (let line = sl; line <= el; line += 1) {
      chains.set(line, this.chainFor(line));
    }

    const oldLine = (node: ChainNode, line: number) => {
      const text = node.source.source;
      if (text === null || text === undefined) return null;
      const lines = text.replace(/\n$/, '').split('\n');
      const count = node.span.lastLine() - node.span.start_line + 1;
      if (count === 1 || lines.length === count) {
        return lines[line - node.span.start_line] ?? lines[lines.length - 1] ?? '';
      }
      return lines.join(' ');
    };
    const boundaries = new Set<string>();
    for (const list of chains.values()) {
      for (const node of list) {
        if (node.source.before) boundaries.add(node.source.before);
      }
    }
    const sorted = [...boundaries].sort();
    const moments: (string | null)[] = [...sorted, null];
    const build = (moment: string | null) => {
      const lines: string[] = [];
      for (let line = sl; line <= el; line += 1) {
        let text: string | null = null;
        for (const node of chains.get(line) ?? []) {
          const before = node.source.before ?? null;
          if (before === null || (moment !== null && before >= moment)) {
            text = before === null ? this.rawLine(line) : oldLine(node, node.line);
            break;
          }
        }
        lines.push(strip(text ?? this.rawLine(line)));
      }
      return lines.join('\n');
    };
    const layers = sorted.map(before => build(before));
    layers.push(build(null));

    const entries: HistoryEntry[][] = layers.map(() => []);
    const placed: HistoryEntry[] = [];
    for (const other of this.annotations.get(region) ?? []) {
      if (!other.record) continue;
      // Keep only reviews that share a line with the opened window; a review
      // on another line of the same region is unrelated to this history.
      const otherWindow = this.decodedSpan(
        info, other.chosen.start, other.chosen.end);
      if (otherWindow.lastLine() < sl || otherWindow.start_line > el) continue;
      const time = other.record.time;
      let layer = 0;
      for (const before of sorted) if (before <= time) layer += 1;
      if (layer >= layers.length) layer = layers.length - 1;
      // The annotated text is the review's own range, not the whole line, so a
      // partial or cross-line review aligns with the newest record.
      const text = layers[layer];
      const snippet = info.text.slice(other.chosen.start, other.chosen.end).trim();
      // Prefer the exact annotated text; otherwise show the review's lines as
      // that version had them (a superseded review's current text is stale).
      let highlightRange: { start: number; end: number } | null = null;
      if (snippet) {
        const at = text.indexOf(snippet);
        if (at !== -1) highlightRange = { start: at, end: at + snippet.length };
      }
      if (!highlightRange && other.record) {
        try {
          const span = this.currentSpan(other.record);
          const first = Math.max(span.start_line, sl) - sl;
          const last = Math.min(span.lastLine(), el) - sl;
          const lines = text.split('\n');
          if (first <= last && last < lines.length) {
            const before = lines.slice(0, first)
              .reduce((size, line) => size + line.length + 1, 0);
            const width = lines.slice(first, last + 1)
              .reduce((size, line) => size + line.length + 1, 0) - 1;
            const slice = text.slice(before, before + Math.max(width, 0));
            const lead = (slice.match(/^\s*/) || [''])[0].length;
            const trail = (slice.match(/\s*$/) || [''])[0].length;
            if (slice.trim()) {
              highlightRange = { start: before + lead, end: before + slice.length - trail };
            }
          }
        } catch (error) { /* leave unhighlighted */ }
      }
      const entry: HistoryEntry = {
        annotation: other,
        time,
        kind: other.modified ? 'edit' : 'highlight',
        text: other.modified ? (other.edit || '') : (other.comment || ''),
        comment: other.comment || '',
        highlight: highlightRange ? text.slice(highlightRange.start, highlightRange.end) : null,
        highlightRange,
        hidden: false,
      };
      entries[layer].push(entry);
      placed.push(entry);
    }
    for (const list of entries) list.sort((a, b) => (a.time < b.time ? -1 : 1));
    for (const entry of placed) {
      for (const newer of placed) {
        if (newer === entry || newer.time <= entry.time) continue;
        if (newer.annotation.chosen.start <= entry.annotation.chosen.start
          && newer.annotation.chosen.end >= entry.annotation.chosen.end) {
          entry.hidden = true;
          break;
        }
      }
    }
    return { layers, before: moments, entries };
  }

  save(region: any, annotation: Annotation) {
    const info = this.regions.get(region);
    if (!info || annotation.locked) return;
    const span = annotation.modified
      ? this.decodedLineSpan(info, annotation.chosen.start, annotation.chosen.end)
      : this.decodedSpan(info, annotation.chosen.start, annotation.chosen.end);
    const at = span.format();
    let record: ReviewRecord = annotation.record ?? null;
    if (!record) {
      record = new ReviewRecord({ type: 'review', time: new Date().toISOString(), at });
      this.records.push(record);
      annotation.record = record;
      this.annotations.get(region)?.push(annotation);
    }
    record.at = span;
    if (annotation.modified) record.edit = annotation.edit;
    else delete record.edit;
    if (annotation.comment) record.comment = annotation.comment;
    else delete record.comment;
    this.ensureSource(span);
  }

  remove(region: any, annotation: Annotation) {
    if (!annotation.record) return;
    this.records = this.records.filter(item => item !== annotation.record);
    const list = this.annotations.get(region);
    if (list) {
      const index = list.indexOf(annotation);
      if (index !== -1) list.splice(index, 1);
    }
  }

  exportSource() {
    return exportSource(this.source, this.records, this.hash);
  }

  renderBlock() {
    return renderBlock(this.records, this.hash);
  }

  /** Serialize the current records for the ``snakedone-reviews`` island, so a
   *  saved page reloads with the annotations the user added. The source island
   *  holds only the archive body and is never rewritten. */
  exportIsland() {
    return exportIsland(this.records, this.hash);
  }

  private ensureSource(span: Span) {
    const whole = new Span(span.start_line, 0, span.lastLine() + 1, 0);
    for (const record of this.records) {
      if (record.type !== 'source' || record.before) continue;
      const existing = record.at;
      if (existing.start_line <= whole.start_line && existing.lastLine() >= whole.lastLine()) return;
    }
    this.records.push(new SourceRecord({ type: 'source', at: whole.format() }));
  }

  private decodedSpan(info: RegionInfo, start: number, end: number) {
    return regionSpan(this.source, this.lineStarts, info, start, end);
  }

  private decodedLineSpan(info: RegionInfo, start: number, end: number) {
    return regionLineSpan(this.source, this.lineStarts, info, start, end);
  }

  private spanToDecoded(info: RegionInfo, span: Span) {
    return toDecoded(this.source, this.lineStarts, info, span);
  }
}
