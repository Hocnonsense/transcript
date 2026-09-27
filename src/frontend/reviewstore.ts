/** Shared review persistence for every Markdown region on the page.
 *
 * Records use the archive's global 1-based ``L``/``C`` coordinates, while a
 * region works on its decoded literal. The store keeps, for each region, the
 * raw source span and the decoded-to-raw index map, so a record's ``at`` can be
 * translated both ways. It also owns the record list and serializes the
 * trailing ``snakedone.review`` block when the page is exported.
 */

import { Annotation } from './annotation';
import { History, HistoryEntry } from './history';
import { ReviewRecord, ReviewRecordEntry, SourceRecord } from './records';
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

function emptySpan(span: Span) {
  return span.sl === span.el && span.sc === span.ec;
}

/** The inclusive last line a half-open span touches. */
function lastLine(span: Span) {
  return span.ec > 0 ? span.el : span.el - 1;
}

/** Whether two whole-line spans share a line. */
function overlaps(a: Span, b: Span) {
  return a.sl <= lastLine(b) && b.sl <= lastLine(a);
}

/** Map a span inside *source* into *target*, on whole-line coordinates. */
function projectSpan(span: Span, source: Span, target: Span) {
  if (emptySpan(target)) return new Span(target.sl, target.sc, target.sl, target.sc);
  const width = Math.max(lastLine(source) - source.sl, 1);
  const depth = lastLine(target) - target.sl;
  const first = Math.min(Math.max(
    target.sl + Math.round((span.sl - source.sl) * depth / width),
    target.sl), lastLine(target));
  const last = Math.min(Math.max(
    target.sl + Math.round((lastLine(span) - source.sl) * depth / width),
    first), lastLine(target));
  return new Span(first, 0, last + 1, 0);
}

/** Map one line inside *source* into *target*. */
function projectLine(line: number, source: Span, target: Span) {
  const width = Math.max(lastLine(source) - source.sl, 1);
  const depth = lastLine(target) - target.sl;
  const moved = target.sl + Math.round((line - source.sl) * depth / width);
  return Math.min(Math.max(moved, target.sl), lastLine(target));
}

/** One step of a line's version chain: the source and the line it names. */
interface ChainNode {
  source: SourceRecord;
  span: Span;
  line: number;
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
  /** The body hash Python recorded for the body, reused when writing a block. */
  hash: string;
  lineStarts: number[];
  regions: Map<any, RegionInfo> = new Map();
  annotations: Map<any, Annotation[]> = new Map();

  constructor(source: string, records: ReviewRecordEntry[], hash: string) {
    this.source = source;
    this.records = Array.isArray(records) ? records.slice() : [];
    this.hash = typeof hash === 'string' ? hash : '';
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

  /** Every source record, in record order (the chain reads this order). */
  private sources(): SourceRecord[] {
    return this.records.filter(
      (record): record is SourceRecord => record.type === 'source');
  }

  /** Follow the successor chain from a written span to the live version.  A
   *  span no successor covers is already current and kept as-is, so character
   *  ranges (not just whole lines) survive. */
  currentSpan(span: Span): Span {
    const sources = this.sources();
    let current = span;
    for (let step = 0; step < sources.length; step += 1) {
      let chosen: { window: Span; at: Span } | null = null;
      for (const source of sources) {
        if (!source.diffRange) continue;
        let window: Span;
        let at: Span;
        try {
          window = Span.parse(source.diffRange);
          at = Span.parse(source.at);
        } catch (error) { continue; }
        if (overlaps(window, current)) { chosen = { window, at }; break; }
      }
      if (!chosen) break;
      current = projectSpan(current, chosen.window, chosen.at);
    }
    return current;
  }

  /** The versions of *line*, oldest first, as source plus line in that version. */
  private chainFor(line: number): ChainNode[] {
    const sources = this.sources();
    const order = new Map<SourceRecord, number>();
    sources.forEach((source, index) => order.set(source, index));
    let node: SourceRecord | null = null;
    for (const candidate of sources) {
      if (candidate.expire) continue;
      let span: Span;
      try { span = Span.parse(candidate.at); } catch (error) { continue; }
      if (span.sl <= line && line <= lastLine(span)) { node = candidate; break; }
    }
    const nodes: ChainNode[] = [];
    while (node) {
      let span: Span;
      try { span = Span.parse(node.at); } catch (error) { break; }
      nodes.push({ source: node, span, line });
      if (!node.diffRange) break;
      let window: Span;
      try { window = Span.parse(node.diffRange); } catch (error) { break; }
      const before = sources.slice(0, order.get(node) ?? 0);
      let predecessor: SourceRecord | null = null;
      for (let index = before.length - 1; index >= 0; index -= 1) {
        let candidate: Span;
        try { candidate = Span.parse(before[index].at); } catch (error) { continue; }
        if (overlaps(candidate, window)) { predecessor = before[index]; break; }
      }
      if (!predecessor) break;
      line = Math.round(projectLine(line, span, window));
      node = predecessor;
    }
    nodes.reverse();
    return nodes;
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
      // A review keeps its written coordinates; follow the chain to place it
      // on the current document.
      const live = this.currentSpan(span);
      const decoded = this.spanToDecoded(info, live);
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
        locked: this.isLocked(record, live),
      }));
    }
    return result;
  }

  /** Whether a review touches a superseded or untracked line. Such a review can
   *  be deleted but not edited: its recorded text no longer matches the
   *  current document, so the box would edit text the reviewer never saw. */
  private isLocked(record: ReviewRecord, span: Span) {
    if (record.expireAt && Object.keys(record.expireAt).length) return true;
    for (let line = span.sl; line <= lastLine(span); line += 1) {
      if (!this.hasLiveSource(line)) return true;
    }
    return false;
  }

  private hasLiveSource(line: number) {
    for (const record of this.records) {
      if (record.type !== 'source' || record.expire) continue;
      let source;
      try { source = Span.parse(record.at); } catch (error) { continue; }
      if (source.sl <= line && line <= lastLine(source)) return true;
    }
    return false;
  }

  /** The version stack for *annotation*'s window: one text per version, oldest
   *  first, with the reviews placed after the version they were written
   *  against. A review fully covered by a newer one is marked hidden. Returns
   *  null for a not-yet-saved annotation. */
  history(region: any, annotation: Annotation): History | null {
    const info = this.regions.get(region);
    if (!info || !annotation.record) return null;
    const window = this.decodedSpan(
      info, annotation.chosen.start, annotation.chosen.end);
    const sl = window.sl;
    const el = lastLine(window);
    const rawLine = (line: number) => {
      const start = line < this.lineStarts.length
        ? this.lineStarts[line] : this.source.length;
      const end = line + 1 < this.lineStarts.length
        ? this.lineStarts[line + 1] - 1 : this.source.length;
      return this.source.slice(start, end);
    };
    let indent = '';
    for (let line = sl; line <= el; line += 1) {
      const text = rawLine(line);
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
      const count = lastLine(node.span) - node.span.sl + 1;
      if (count === 1 || lines.length === count) {
        return lines[line - node.span.sl] ?? lines[lines.length - 1] ?? '';
      }
      return lines.join(' ');
    };
    const expiries = new Set<string>();
    for (const list of chains.values()) {
      for (const node of list) {
        if (node.source.expire) expiries.add(node.source.expire);
      }
    }
    const sorted = [...expiries].sort();
    const build = (moment: string | null) => {
      const lines: string[] = [];
      for (let line = sl; line <= el; line += 1) {
        let text: string | null = null;
        for (const node of chains.get(line) ?? []) {
          const expire = node.source.expire ?? null;
          if (expire === null || (moment !== null && expire >= moment)) {
            text = expire === null ? rawLine(line) : oldLine(node, node.line);
            break;
          }
        }
        lines.push(strip(text ?? rawLine(line)));
      }
      return lines.join('\n');
    };
    const layers = sorted.map(expire => build(expire));
    layers.push(build(null));

    const entries: HistoryEntry[][] = layers.map(() => []);
    const placed: HistoryEntry[] = [];
    for (const other of this.annotations.get(region) ?? []) {
      if (!other.record) continue;
      // Keep only reviews that share a line with the opened window; a review
      // on another line of the same region is unrelated to this history.
      const otherWindow = this.decodedSpan(
        info, other.chosen.start, other.chosen.end);
      if (lastLine(otherWindow) < sl || otherWindow.sl > el) continue;
      const time = other.record.time;
      let layer = 0;
      for (const expire of sorted) if (expire <= time) layer += 1;
      if (layer >= layers.length) layer = layers.length - 1;
      // The annotated text is the review's own range, not the whole line, so a
      // partial or cross-line review aligns with the newest record.
      const snippet = info.text.slice(other.chosen.start, other.chosen.end).trim();
      // Prefer the exact annotated text; otherwise show the review's lines as
      // that version had them (a superseded review's current text is stale).
      let highlight = snippet && layers[layer].includes(snippet) ? snippet : null;
      if (!highlight && other.record) {
        try {
          const span = this.currentSpan(Span.parse(other.record.at));
          const first = Math.max(span.sl, sl) - sl;
          const last = Math.min(lastLine(span), el) - sl;
          const lines = layers[layer].split('\n');
          if (first <= last && last < lines.length) {
            const before = lines.slice(0, first)
              .reduce((size, line) => size + line.length + 1, 0);
            const width = lines.slice(first, last + 1)
              .reduce((size, line) => size + line.length + 1, 0) - 1;
            highlight = layers[layer].slice(before, before + Math.max(width, 0)).trim()
              || null;
          }
        } catch (error) { /* leave unhighlighted */ }
      }
      const entry: HistoryEntry = {
        annotation: other,
        time,
        kind: other.modified ? 'edit' : 'comment',
        text: other.modified ? (other.edit || '') : (other.comment || ''),
        highlight,
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
    return { layers, entries };
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
    const body = this.source.replace(/\n+$/, '') + '\n';
    if (!this.records.length) return body;
    return body + '\n' + this.renderBlock() + '\n';
  }

  renderBlock() {
    const lines = this.records.map(record => JSON.stringify(record));
    const inner = lines.length
      ? '[\n' + lines.map(line => '    ' + line).join(',\n') + '\n    ]'
      : '[]';
    const marker = this.hash ? `snakedone.review=${this.hash}` : 'snakedone.review';
    return `if "${marker}":\n    """${escapeSlot(inner)}"""`;
  }

  /** Serialize the current records for the ``snakedone-reviews`` island, so a
   *  saved page reloads with the annotations the user added. The source island
   *  holds only the archive body and is never rewritten. */
  exportIsland() {
    const payload = { records: this.records, hash: this.hash };
    return JSON.stringify(payload)
      .replace(/</g, '\\u003c')
      .replace(/>/g, '\\u003e');
  }

  private ensureSource(span: Span) {
    const whole = new Span(span.sl, 0, lastLine(span) + 1, 0);
    for (const record of this.records) {
      if (record.type !== 'source' || record.expire) continue;
      let existing;
      try { existing = Span.parse(record.at); } catch (error) { continue; }
      if (existing.sl <= whole.sl && lastLine(existing) >= lastLine(whole)) return;
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
    return new Span(first.line, first.col, last.line, last.col + 1);
  }

  private decodedLineSpan(info: RegionInfo, start: number, end: number) {
    const startRaw = info.rawStart + this.decodedRaw(info, start);
    const lastRaw = info.rawStart + this.decodedRaw(info, Math.max(end - 1, start));
    return new Span(
      this.lineCol(startRaw).line, 0, this.lineCol(lastRaw).line + 1, 0);
  }

  private spanToDecoded(info: RegionInfo, span: Span) {
    if (emptySpan(span)) return null;
    const startRaw = this.rawOf(span.sl, span.sc);
    const endRaw = this.rawOf(span.el, span.ec);
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
