/** One review drawn in a Markdown region, backed by a record once saved.
 *
 * The range and text are in the region's decoded literal; the store translates
 * them to archive coordinates when persisting.  A brand-new annotation has no
 * `record` yet; `ReviewStore.save` attaches one.
 */

import type { ReviewRecord } from './records';

export interface Range { start: number; end: number; }

/** Screen band of the drawn box, filled by the renderer. */
export interface Band { l: number; r: number; t: number; b: number; }

export class Annotation {
  /** The stored record this annotation edits, once it has been saved. */
  record: ReviewRecord | null;
  /** The reviewed range, in the region's decoded literal. */
  chosen: Range;
  /** The whole source line(s) the range spans, before editing. */
  original: string;
  /** The replacement text, equal to `original` when only commenting. */
  edit: string;
  comment: string;
  modified: boolean;
  /** The range the annotation opened on, kept for the popup. */
  selection: Range | null;
  /** Screen bands of the drawn box, filled by the renderer. */
  bands: Band[] | null;
  /** Read-only because part of the range is expired (or untracked): it can be
   *  deleted but not edited, since the recorded text no longer matches. */
  locked: boolean;

  constructor(options: {
    chosen: Range;
    original: string;
    edit: string;
    comment: string;
    modified: boolean;
    record?: ReviewRecord | null;
    selection?: Range | null;
    locked?: boolean;
  }) {
    this.record = options.record ?? null;
    this.chosen = options.chosen;
    this.original = options.original;
    this.edit = options.edit;
    this.comment = options.comment;
    this.modified = options.modified;
    this.selection = options.selection ?? null;
    this.bands = null;
    this.locked = options.locked ?? false;
  }
}
