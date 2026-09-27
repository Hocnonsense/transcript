/** Draws the multi-version history stack built by ``ReviewStore.history``.
 *  Rendering only; the data and per-character marks live in ``history.ts``. */

import { Annotation } from './annotation';
import {
  aboveMarks, belowMarks, HISTORY_PALETTE, History, HistoryEntry,
} from './history';

function rgba(hex: string, alpha: number) {
  const value = hex.replace('#', '');
  const r = parseInt(value.slice(0, 2), 16);
  const g = parseInt(value.slice(2, 4), 16);
  const b = parseInt(value.slice(4, 6), 16);
  return `rgba(${r},${g},${b},${alpha})`;
}

function colorize(span: HTMLElement, color: string) {
  span.style.color = color;
  span.style.textDecorationColor = color;
}

/** A zero-width diff mark:
 *  - `v`: `last-del`, above the line (a run the last version had and this row lost),
 *  - `^`: `next-ins`, below it (a run the next version adds and this row lacks)
 *  - `|`: `edit-del`, the edit-box deletion bar
*
*  The reviewed range reuses the two chevrons for its ends.
*  An optional `color` sets the anchor's `currentColor`*/
export const markDel = (() => {
  /** The zero-width anchor every diff mark is built on. It holds no inline space,
   *  so the overlay fill stays aligned with the textarea. */
  function markAnchor(inner: string) {
    const span = document.createElement('span');
    span.className = 'snd-diff-anchor';
    span.innerHTML = inner;
    return span;
  }

  const markDelMap = { 'v': 'last-del', '^': 'next-ins', '|': 'edit-del' } as const;
  return (kind: 'v' | '^' | '|', color?: string) => {
    const mark = markAnchor(`<i class="snd-diff-${markDelMap[kind]}"></i>`);
    if (color) mark.style.color = color;
    return mark;
  }
})()

/** A row of the stack: one version's text with the marks of both adjacent
 *  boundaries. */
function historyRow(text: string, above: ReturnType<typeof aboveMarks>,
  below: ReturnType<typeof belowMarks>, aboveColor: string, belowColor: string) {
  const row = document.createElement('pre');
  row.className = 'snd-history-row';
  for (let index = 0; index <= text.length; index += 1) {
    // Each side appends its own chevron, in its boundary colour; a replacement
    // has a gap on both sides, so both appear — two zero-width anchors at the
    // same boundary, one above and one below the line.
    if (above.gaps.includes(index)) row.appendChild(markDel('v', aboveColor));
    if (below.gaps.includes(index)) row.appendChild(markDel('^', belowColor));
    if (index === text.length) break;
    const isIns = above.ins[index];
    const isDel = below.del[index];
    if (!isIns && !isDel) {
      row.appendChild(document.createTextNode(text[index]));
      continue;
    }
    const span = document.createElement('span');
    span.className = isIns ? 'snd-diff-ins' : 'snd-diff-del';
    const color = isIns ? aboveColor : belowColor;
    colorize(span, color);
    span.style.background = rgba(color, isIns ? 0.14 : 0.12);
    if (isIns && isDel) {
      // One element cannot carry two decoration colours: the overline keeps the
      // boundary-above colour on the outer span, the underline the
      // boundary-below colour on an inner span, matching the two chevrons.
      const inner = document.createElement('span');
      inner.className = 'snd-diff-del';
      inner.style.background = 'transparent';
      inner.style.textDecorationColor = belowColor;
      inner.textContent = text[index];
      span.appendChild(inner);
    } else {
      span.textContent = text[index];
    }
    row.appendChild(span);
  }
  return row;
}

function entryBlock(entry: HistoryEntry, color: string,
  onOpen: (annotation: Annotation) => void) {
  const block = document.createElement('div');
  block.className = 'snd-history-entry';
  if (entry.highlight) {
    const target = document.createElement('div');
    target.className = 'snd-history-target';
    target.textContent = entry.highlight;
    target.style.borderColor = rgba(color, 0.6);
    target.style.background = rgba(color, 0.1);
    target.addEventListener('click', () => onOpen(entry.annotation));
    block.appendChild(target);
  }
  const body = document.createElement('div');
  body.className = 'snd-history-comment';
  body.textContent = entry.text || '……';
  block.appendChild(body);
  return block;
}

/** Draw *history* into *container* (which is emptied first). */
export function renderHistory(container: HTMLElement, history: History | null,
  onOpen: (annotation: Annotation) => void) {
  container.replaceChildren();
  if (!history || !history.layers.length) {
    container.hidden = true;
    return;
  }
  container.hidden = false;
  // Colour boundaries from the newest one, cycling toward older versions: the
  // newest (fresh) boundary gets HISTORY_PALETTE[0], older ones follow.
  const boundaries = history.layers.length - 1;
  const colors = Array.from({ length: boundaries }, (_, index) =>
    HISTORY_PALETTE[(boundaries - 1 - index) % HISTORY_PALETTE.length]);
  for (let index = 0; index < history.layers.length; index += 1) {
    const above = index > 0
      ? aboveMarks(history.layers[index - 1], history.layers[index])
      : { ins: new Array(history.layers[index].length).fill(false), gaps: [] };
    const below = index < history.layers.length - 1
      ? belowMarks(history.layers[index], history.layers[index + 1])
      : { del: new Array(history.layers[index].length).fill(false), gaps: [] };
    const aboveColor = colors[index - 1] || HISTORY_PALETTE[0];
    const belowColor = colors[index] || HISTORY_PALETTE[0];
    container.appendChild(historyRow(
      history.layers[index], above, below, aboveColor, belowColor));
    for (const entry of history.entries[index] || []) {
      if (entry.hidden) continue;
      const color = index < colors.length ? colors[index] : HISTORY_PALETTE[0];
      container.appendChild(entryBlock(entry, color, onOpen));
    }
  }
}
