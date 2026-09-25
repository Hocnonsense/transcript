/** Shared review persistence for every Markdown region on the page.
 *
 * Records use the archive's global 1-based ``L``/``C`` coordinates, while a
 * region works on its decoded literal. The store keeps, for each region, the
 * raw source span and the decoded-to-raw index map, so a record's ``at`` can be
 * translated both ways. It also owns the record list and serializes the
 * trailing ``snakedone.review`` block when the page is exported.
 */

import { Annotation } from './annotation';
import { ReviewRecord, ReviewRecordEntry } from './records';
import { Span } from './span';

interface RegionInfo {
  rawStart: number;
  rawEnd: number;
  text: string;
  map: number[];
}

function fullLines(text: string, start: number, end: number) {
  const before = text.lastIndexOf('\n', start - 1);
  const lineStart = before === -1 ? 0 : before + 1;
  const lineEnd = text.indexOf('\n', end);
  return { start: lineStart, end: lineEnd === -1 ? text.length : lineEnd };
}

function escapeSlot(content: string) {
  let text = content.replace(/\\/g, '\\\\').replace(/\r/g, '\\r').replace(/\t/g, '\\t');
  text = text.replace(
    /[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]/g,
    char => '\\x' + char.charCodeAt(0).toString(16).padStart(2, '0'));
  return text.replace(/"{3,}|"+$/g, match => match.replace(/"/g, '\\"'));
}

export class ReviewStore {
  source: string;
  records: ReviewRecordEntry[];
  blockStart: number | null;
  blockEnd: number | null;
  lineStarts: number[];
  regions: Map<any, RegionInfo> = new Map();
  annotations: Map<any, Annotation[]> = new Map();

  constructor(source: string, records: ReviewRecordEntry[], start: number | null, end: number | null) {
    this.source = source;
    this.records = Array.isArray(records) ? records.slice() : [];
    this.blockStart = start;
    this.blockEnd = end;
    this.lineStarts = [0];
    for (let index = 0; index < source.length; index += 1) {
      if (source[index] === '\n') this.lineStarts.push(index + 1);
    }
  }

  /** Set and return the region's annotations; the same array the region itself references. */
  addRegion(region: any, rawStart: number, rawEnd: number, text: string, map: number[]) {
    this.regions.set(region, { rawStart, rawEnd, text, map });
    this.annotations.set(region, this.buildAnnotations(region));
    return this.annotations.get(region) ?? [];
  }

  /** Build every review record whose range falls in this region. */
  private buildAnnotations(region: any): Annotation[] {
    const info = this.regions.get(region);
    if (!info) return [];
    const result: Annotation[] = [];
    for (const record of this.records) {
      if (record.type !== 'review') continue;
      let span;
      try { span = Span.parse(record.at); } catch (error) { continue; }
      const decoded = this.spanToDecoded(info, span);
      if (!decoded) continue;
      const chosen = { start: decoded.start, end: decoded.end };
      const line = fullLines(info.text, chosen.start, chosen.end);
      const original = info.text.slice(line.start, line.end);
      const modified = typeof record.edit === 'string';
      result.push(new Annotation({
        record,
        chosen,
        original,
        edit: modified ? record.edit : original,
        comment: record.comment || '',
        modified,
      }));
    }
    return result;
  }

  save(region: any, annotation: Annotation) {
    const info = this.regions.get(region);
    if (!info) return;
    const span = annotation.modified
      ? this.decodedLineSpan(info, annotation.chosen.start, annotation.chosen.end)
      : this.decodedSpan(info, annotation.chosen.start, annotation.chosen.end);
    const at = span.format();
    let record: ReviewRecord = annotation.record ?? null;
    if (!record) {
      record = { type: 'review', time: new Date().toISOString(), at };
      this.records.push(record);
      annotation.record = record;
      this.annotations.get(region)?.push(annotation);
    }
    record.at = at;
    if (annotation.modified) record.edit = annotation.edit;
    else delete record.edit;
    if (annotation.comment) record.comment = annotation.comment;
    else delete record.comment;
    delete record.expireAt;
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
    let body = this.blockStart === null ? this.source : this.source.slice(0, this.blockStart);
    body = body.replace(/\n+$/, '') + '\n';
    if (!this.records.length) return body;
    return body + '\n' + this.renderBlock() + '\n';
  }

  renderBlock() {
    const lines = this.records.map(record => JSON.stringify(record));
    const inner = lines.length
      ? '[\n' + lines.map(line => '    ' + line).join(',\n') + '\n    ]'
      : '[]';
    return `if "snakedone.review":\n    """${escapeSlot(inner)}"""`;
  }

  private ensureSource(span: Span) {
    const whole = new Span(span.sl, 0, span.el, -1);
    for (const record of this.records) {
      if (record.type !== 'source' || record.expire) continue;
      let existing;
      try { existing = Span.parse(record.at); } catch (error) { continue; }
      if (existing.sl <= whole.sl && existing.el >= whole.el) return;
    }
    this.records.push({ type: 'source', at: whole.format() });
  }

  private lineCol(raw: number) {
    let low = 0;
    let high = this.lineStarts.length - 1;
    while (low < high) {
      const mid = (low + high + 1) >> 1;
      if (this.lineStarts[mid] <= raw) low = mid;
      else high = mid - 1;
    }
    return { line: low, col: raw - this.lineStarts[low] };
  }

  private rawOf(line: number, col: number) {
    const base = line < this.lineStarts.length ? this.lineStarts[line] : this.source.length;
    return Math.min(base + col, this.source.length);
  }

  private decodedSpan(info: RegionInfo, start: number, end: number) {
    const startRaw = info.rawStart + this.decodedRaw(info, start);
    const lastRaw = info.rawStart + this.decodedRaw(info, Math.max(end - 1, start));
    const first = this.lineCol(startRaw);
    const last = this.lineCol(lastRaw);
    return new Span(first.line, first.col, last.line, last.col);
  }

  private decodedLineSpan(info: RegionInfo, start: number, end: number) {
    const startRaw = info.rawStart + this.decodedRaw(info, start);
    const lastRaw = info.rawStart + this.decodedRaw(info, Math.max(end - 1, start));
    return new Span(this.lineCol(startRaw).line, 0, this.lineCol(lastRaw).line, -1);
  }

  private spanToDecoded(info: RegionInfo, span: Span) {
    const startRaw = this.rawOf(span.sl, span.sc);
    const endRaw = span.ec === -1
      ? (span.el + 1 < this.lineStarts.length
        ? this.lineStarts[span.el + 1] : this.source.length)
      : this.rawOf(span.el, span.ec) + 1;
    if (endRaw <= info.rawStart || startRaw >= info.rawEnd) return null;
    const start = rawToIndex(info.map, Math.max(startRaw - info.rawStart, 0));
    let end = rawToIndex(info.map, Math.min(endRaw - info.rawStart, info.map.length));
    // A whole-line span reaches the next line's first character; drop the
    // trailing newline so the decoded range covers the line's content.
    while (end > start && info.text[end - 1] === '\n') end -= 1;
    if (end <= start) return null;
    return { start, end };
  }

  private decodedRaw(info: RegionInfo, decoded: number) {
    if (decoded >= info.map.length) return info.rawEnd - info.rawStart;
    return info.map[decoded];
  }
}

/** The largest index whose ``map`` entry is <= *raw*, or the map length. */
function rawToIndex(map: number[], raw: number) {
  let low = 0;
  let high = map.length;
  while (low < high) {
    const mid = (low + high) >> 1;
    if (map[mid] < raw) low = mid + 1;
    else high = mid;
  }
  return low;
}
