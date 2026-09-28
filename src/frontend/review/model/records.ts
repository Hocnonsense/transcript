/** The review records as runtime objects.
 *
 * The archive and the island carry them as JSON with coordinate strings; the
 * store parses every ``at``, ``cover`` and ``coveredAt`` span once on load and
 * formats them back only when writing a block or the island.  A ``cover`` is a
 * ``span@stamp`` string that pins a source's predecessor; ``coveredAt`` holds
 * the corresponding strings for superseded parts of a review. */

import { At, Span } from './span';
import type { DiffSlot } from '../text/diff';

/** The JSON shape of a source record. */
export interface RawSourceRecord {
  type: 'source';
  at: string;
  before?: string;
  source?: string;
  cover?: string;
}

/** The JSON shape of a review record. */
export interface RawReviewRecord {
  type: 'review';
  at: string;
  time: string;
  edit?: string;
  comment?: string;
  coveredAt?: string[];
}

export type RawRecordEntry = RawSourceRecord | RawReviewRecord;

/** One whole source line (``at``) and the region it replaced. */
export class SourceRecord {
  readonly type = 'source';
  at: Span;
  cover: At | null;
  source?: string;
  before?: string;
  /** Cached alignment with this line's predecessor, built on first use. */
  private diff?: DiffSlot[] | null;

  constructor(data: RawSourceRecord) {
    this.at = Span.parse(data.at);
    this.cover = data.cover === undefined ? null : At.parse(data.cover);
    this.source = data.source;
    this.before = data.before;
  }

  /** The alignment between ``cover.span`` (old) and ``at`` (new), computed once
   *  by *build* — which needs the store to reach the predecessor's text.  The
   *  slots map an offset inside the old span to one inside the new span. */
  parts(build: (self: SourceRecord) => DiffSlot[] | null) {
    if (this.diff === undefined) this.diff = build(this)!;
    return this.diff;
  }

  data(): RawSourceRecord {
    const result: RawSourceRecord = { type: 'source', at: this.at.format() };
    if (this.source !== undefined) result.source = this.source;
    if (this.cover) result.cover = this.cover.format();
    if (this.before !== undefined) result.before = this.before;
    return result;
  }
}

/** A range plus the time its comment was last edited. */
export class ReviewRecord {
  readonly type = 'review';
  at: Span;
  time: string;
  edit?: string;
  comment?: string;
  coveredAt: At[];

  constructor(data: RawReviewRecord) {
    this.at = Span.parse(data.at);
    this.time = data.time;
    this.edit = data.edit;
    this.comment = data.comment;
    if (data.coveredAt !== undefined && !Array.isArray(data.coveredAt)) {
      throw new Error('coveredAt must be an array');
    }
    this.coveredAt = (data.coveredAt ?? []).map(text => At.parse(text));
  }

  /** The version stamp covering *line* — the version live when the review was
   *  written — or ``null`` when that run is still current. */
  versionOf(line: number): string | null {
    for (const { span, time } of this.coveredAt) {
      if (span.start_line <= line && line <= span.lastLine()) return time;
    }
    return null;
  }

  data() {
    const result: RawReviewRecord = { type: 'review', at: this.at.format(), time: this.time };
    if (this.edit !== undefined) result.edit = this.edit;
    if (this.comment !== undefined) result.comment = this.comment;
    if (this.coveredAt.length) result.coveredAt = this.coveredAt.map(cover => cover.format());
    return result;
  }
}

export type RecordEntry = SourceRecord | ReviewRecord;

export function parseRecords(data: RawRecordEntry[]): RecordEntry[] {
  const result: RecordEntry[] = [];
  for (const item of data) {
    try {
      result.push(item.type === 'source' ? new SourceRecord(item) : new ReviewRecord(item));
    } catch (error) { /* drop a malformed record */ }
  }
  return result;
}
