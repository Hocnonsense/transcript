/** Draws the revision record list built by ``ReviewStore.history``: one row per
 *  source version and one per review, oldest at the top.  Each row is an
 *  unrendered code box (``raw``) beside its metadata (``comment``).  Rendering
 *  only; the data and per-character marks live in ``history.ts``. */

import type { Annotation } from './annotation';
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

/** One version's text with the marks of both adjacent boundaries, as a raw code
 *  box.  The row is the newer side above (inserted characters get an overline;
 *  a run the older side dropped outright leaves a gap) and the older side below
 *  (deleted characters get an underline; a run the newer side inserted outright
 *  leaves a gap).  A replacement has a character to decorate on each side, so
 *  it needs no chevron. */
function sourceRow(text: string, above: ReturnType<typeof aboveMarks>,
  below: ReturnType<typeof belowMarks>, aboveColor: string, belowColor: string) {
  const row = document.createElement('pre');
  row.className = 'snd-rec-code';
  for (let index = 0; index <= text.length; index += 1) {
    // Each side appends its own chevron, in its boundary colour, only where the
    // adjacent version changed text this row has nothing to show for.
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
    span.style.color = color;
    span.style.textDecorationColor = color;
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

/** The reviewed range of a highlight: the same text as its source, with only
 *  the annotated run carrying the source's colour. */
function highlightRow(text: string, range: { start: number; end: number } | null, color: string) {
  const row = document.createElement('pre');
  row.className = 'snd-rec-code';
  const start = range ? Math.max(0, Math.min(range.start, text.length)) : -1;
  const end = range ? Math.max(start, Math.min(range.end, text.length)) : -1;
  if (start < 0 || end <= start) {
    row.textContent = text;
    return row;
  }
  row.append(
    document.createTextNode(text.slice(0, start)),
    markHighlight(text.slice(start, end), color),
    document.createTextNode(text.slice(end)),
  );
  return row;
}

function markHighlight(text: string, color: string) {
  const span = document.createElement('span');
  span.className = 'snd-rec-hl';
  span.style.color = color;
  span.style.background = rgba(color, 0.18);
  span.textContent = text;
  return span;
}

/** The edit result as a raw code box, padded back to the source window: the
 *  annotation's range in *source* is replaced by *text*, so the untouched lines
 *  of a cross-line window stay visible.  Insertions get the source's colour;
 *  lost runs leave a gap above. */
function editRow(text: string, source: string,
  range: { start: number; end: number } | null, color: string) {
  const start = range ? Math.max(0, Math.min(range.start, source.length)) : null;
  const end = range ? Math.max(0, Math.min(range.end, source.length)) : null;
  const modified = start !== null && end !== null && end >= start
    ? source.slice(0, start) + text + source.slice(end)
    : text;
  return sourceRow(
    modified, aboveMarks(source, modified), noDel(modified.length), color, color,
  );
}

/** One row: the unrendered raw code box above its metadata and actions.  The
 *  row's main colour tints the source box border. */
function recordRow(kind: string, raw: HTMLElement, meta: HTMLElement, color: string) {
  const row = document.createElement('div');
  row.className = `snd-rec snd-rec-${kind}`;
  row.style.setProperty('--rec-color', color);
  row.append(raw, meta);
  return row;
}

function timeLine(text?: string | null) {
  const meta = document.createElement('div');
  meta.className = 'snd-rec-meta-head';
  if (text) {
    const date = document.createElement('time');
    date.className = 'snd-rec-time';
    date.textContent = text;
    meta.appendChild(date);
  }
  return meta;
}

/** Actions appended to a record's comment: delete for every review, edit for
 *  one that is not locked (superseded or untracked). */
function actionsFor(annotation: Annotation | null, opts: RecordOptions) {
  const actions = document.createElement('div');
  actions.className = 'snd-rec-actions';
  if (!annotation) return actions;
  if (!annotation.locked) {
    const edit = document.createElement('button');
    edit.type = 'button';
    edit.textContent = '✎';
    edit.title = 'Edit';
    edit.setAttribute('aria-label', 'Edit');
    edit.addEventListener('click', event => {
      event.stopPropagation();
      opts.onEdit?.(annotation);
    });
    actions.appendChild(edit);
  }
  const remove = document.createElement('button');
  remove.type = 'button';
  remove.textContent = '×';
  remove.title = 'Delete';
  remove.setAttribute('aria-label', 'Delete');
  remove.addEventListener('click', event => {
    event.stopPropagation();
    opts.onDelete?.(annotation);
  });
  actions.appendChild(remove);
  return actions;
}

interface RecordOptions {
  focus?: Annotation | null;
  onOpen?: (annotation: Annotation) => void;
  onEdit?: (annotation: Annotation) => void;
  onDelete?: (annotation: Annotation) => void;
}

export interface RecordSlots {
  rows: Map<Annotation, HTMLElement>;
  raws: Map<Annotation, HTMLElement>;
  comments: Map<Annotation, HTMLElement>;
}

const noDel = (length: number) => ({ del: new Array(length).fill(false), gaps: [] as number[] });

/** Draw *history* into *container* (which is emptied first) as a revision list.
 *  Returns the per-annotation slots so the caller can swap in an inline editor
 *  for the row being edited. */
export function renderRecords(container: HTMLElement, history: History | null,
  opts: RecordOptions = {}): RecordSlots {
  const slots: RecordSlots = {
    rows: new Map(), raws: new Map(), comments: new Map(),
  };
  container.replaceChildren();
  if (!history || !history.layers.length) {
    container.hidden = true;
    return slots;
  }
  container.hidden = false;
  const count = history.layers.length;
  const colorOf = (index: number) =>
    HISTORY_PALETTE[(count - 1 - index) % HISTORY_PALETTE.length];
  for (let index = 0; index < count; index += 1) {
    const text = history.layers[index];
    const above = index > 0
      ? aboveMarks(history.layers[index - 1], text)
      : { ins: new Array(text.length).fill(false), gaps: [] };
    const below = index < count - 1
      ? belowMarks(text, history.layers[index + 1])
      : noDel(text.length);
    // A boundary belongs to the older side: the marks above this row (vs the
    // previous version) and below the previous row carry the previous source's
    // colour; the marks below this row carry its own colour.
    container.appendChild(recordRow(
      'source',
      sourceRow(
        text, above, below,
        colorOf(Math.max(index - 1, 0)), colorOf(index),
      ),
      sourceMeta(history.before[index]),
      colorOf(index),
    ));
    for (const entry of history.entries[index] || []) {
      container.appendChild(entryRow(entry, text, colorOf(index), opts, slots));
    }
  }
  placeFocus(container, slots, opts.focus);
  return slots;
}

function sourceMeta(before: string | null) {
  const meta = document.createElement('div');
  meta.className = 'snd-rec-meta';
  if (before) meta.append(timeLine(`valid before: ${before}`));
  return meta;
}

function entryRow(entry: HistoryEntry, source: string, color: string,
  opts: RecordOptions, slots: RecordSlots) {
  const annotation = entry.annotation;
  const raw = entry.kind === 'edit'
    ? editRow(entry.text, source, entry.highlightRange, color)
    : highlightRow(source, entry.highlightRange, color);
  const meta = document.createElement('div');
  meta.className = 'snd-rec-meta';
  meta.appendChild(timeLine(entry.time));
  const body = document.createElement('div');
  body.className = 'snd-rec-comment';
  body.textContent = entry.comment || '';
  meta.appendChild(body);
  meta.appendChild(actionsFor(annotation, opts));
  if (opts.onOpen) {
    // A click on the row focuses its review, but one inside the inline editor
    // (or an action) must not re-render and discard the edit.
    const open = (event: Event) => {
      const target = event.target as HTMLElement | null;
      if (target?.closest('textarea, button, .snd-md-source, .snd-md-comment')) return;
      opts.onOpen?.(annotation);
    };
    raw.addEventListener('click', open);
    body.addEventListener('click', open);
  }
  const row = recordRow(entry.kind, raw, meta, color);
  slots.rows.set(annotation, row);
  slots.raws.set(annotation, raw);
  slots.comments.set(annotation, body);
  return row;
}

/** Move the focused review's row to the very bottom, so the one that was
 *  clicked sits below the other current reviews (which keep time order). */
function placeFocus(container: HTMLElement, slots: RecordSlots,
  focus: Annotation | null | undefined) {
  if (!focus) return;
  const row = slots.rows.get(focus);
  if (!row) return;
  const superseded = !!focus.record?.coveredAt.length;
  if (superseded) return;
  container.appendChild(row);
}
