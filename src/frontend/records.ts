/** The flat records of the trailing ``snakedone.review`` block.
 *
 * Mirrors ``snakedone/review/_records.py``: a ``source`` is one whole line
 * (``at``) and the region it replaced (``diffRange``); a ``review`` carries an
 * absolute range plus the time its comment was written (``time``).
 */

export interface SourceRecord {
  type: 'source';
  at: string;
  source?: string;
  /** The old region this whole line came from (absent when inserted). */
  diffRange?: string;
  expire?: string;
}

export interface ReviewRecord {
  type: 'review';
  at: string;
  edit?: string;
  time: string;
  expireAt?: Record<string, string>;
  comment?: string;
}

export type ReviewRecordEntry = SourceRecord | ReviewRecord;
