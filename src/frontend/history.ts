/** The multi-version history stack: its data shape and per-character marks.
 *
 * ``ReviewStore.history`` builds the data (one text per version, oldest first,
 * with the reviews placed after the version they were written against);
 * ``aboveMarks``/``belowMarks`` align adjacent versions character by character
 * with the same diff as the edit view.  Pure: the drawing lives in
 * ``historyrender.ts``. */

import { Annotation } from './annotation';
import { diffText } from './diff';

/** Okabe–Ito colour-blind safe palette; boundaries cycle through it. */
export const HISTORY_PALETTE = ['#0072B2', '#D55E00', '#009E73', '#E69F00'];

export interface HistoryEntry {
  annotation: Annotation;
  /** The review's first-save time, used to order and to hide older covered ones. */
  time: string;
  kind: 'comment' | 'edit';
  /** The comment body, or the replacement text for an edit. */
  text: string;
  /** Substring of the layer to highlight, when it can be found. */
  highlight: string | null;
  /** A newer review covers this one's whole range, so it is not shown. */
  hidden: boolean;
}

export interface History {
  /** Version texts, oldest first; the last one is the current text. */
  layers: string[];
  /** Reviews to show after `layers[i]`, in time order. */
  entries: HistoryEntry[][];
}

/** Per-character marks of one row against the boundary above it (the row is
 *  the newer side: inserted characters get an overline, and a gap is left
 *  where the older side had text that the row lost). */
export function aboveMarks(previous: string, text: string) {
  const ins = new Array<boolean>(text.length).fill(false);
  const gaps: number[] = [];
  let offset = 0;
  for (const slot of diffText(previous, text)) {
    if (slot.kind === 'equal') offset += slot.mod.length;
    else if (slot.kind === 'ins') {
      for (let i = offset; i < offset + slot.mod.length; i += 1) ins[i] = true;
      offset += slot.mod.length;
    } else gaps.push(offset);
  }
  return { ins, gaps };
}

/** Per-character marks of one row against the boundary below it (the row is
 *  the older side: deleted characters get an underline, and a gap is left
 *  where the newer side added text). */
export function belowMarks(text: string, next: string) {
  const del = new Array<boolean>(text.length).fill(false);
  const gaps: number[] = [];
  let offset = 0;
  for (const slot of diffText(text, next)) {
    if (slot.kind === 'equal') offset += slot.orig.length;
    else if (slot.kind === 'del') {
      for (let i = offset; i < offset + slot.orig.length; i += 1) del[i] = true;
      offset += slot.orig.length;
    } else gaps.push(offset);
  }
  return { del, gaps };
}
