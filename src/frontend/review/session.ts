/** The mutable state of one open review editor, plus the small typed views of
 *  the DOM the region works with.  Pure data: the behavior lives in
 *  ``MarkdownReview``. */

import type { Annotation, Range } from './annotation';

/** The two end anchors of a reviewed range in the source-fill overlay. */
export interface MarkerSet {
  left: HTMLElement;
  right: HTMLElement;
}

/** An in-progress drag of a range delimiter inside the source box. */
export interface MarkerDrag {
  side: 'left' | 'right';
  /** Per-character hit rectangles, measured once on the first move. */
  rects: { x: number; y: number }[] | null;
}

/** The live state of the two-box editor: the original text being edited, the
 *  comment, and where both are anchored in the literal.
 *
 *  ``original`` is the whole source line(s) the box holds.  ``text`` is the
 *  current box value (equal to ``original`` until edited).  ``committed`` is
 *  the comment state saved so far (the "已编辑" state); ``body`` is the draft
 *  shown in the box, which may be newer. */
export class ReviewSession {
  annotation: Annotation | null;
  chosen: Range;
  chosenLocal: Range;
  lineStart: number;
  baseline: Range;
  original: string;
  text: string;
  body: string;
  committed: string;
  mode: string;

  constructor(options: {
    annotation: Annotation | null;
    chosen: Range;
    chosenLocal: Range;
    lineStart: number;
    baseline: Range;
    original: string;
    text: string;
    committed: string;
    mode: string;
  }) {
    this.annotation = options.annotation;
    this.chosen = options.chosen;
    this.chosenLocal = options.chosenLocal;
    this.lineStart = options.lineStart;
    this.baseline = options.baseline;
    this.original = options.original;
    this.text = options.text;
    this.body = options.committed;
    this.committed = options.committed;
    this.mode = options.mode;
  }
}
