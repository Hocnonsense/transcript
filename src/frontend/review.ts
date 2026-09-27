import { Annotation, Band } from './annotation';
import { diffInfo, diffText } from './diff';
import { renderHistory, markDel } from './historyrender';
import { markdownMap } from './literal';
import type { ReviewStore } from './reviewstore';

const SVG_NS = 'http://www.w3.org/2000/svg';

/** The region owning each review box, for the shared document handlers below. */
const inputRegions = new WeakMap<HTMLElement, MarkdownReview>();
/** Regions whose popup is open, so one Escape closes them all. */
const openRegions = new Set<MarkdownReview>();

function escapeRegExp(text: string) {
  return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

/** Search given text in the source markdown text, starting from the specified
 *  offset, tolerating collapsed whitespace (markdown joins soft line breaks
 *  with a space). */
function findInSource(source: string, text: string, from: number) {
  const trimmed = text.trim();
  if (!trimmed) return null;
  const pattern = trimmed.split(/\s+/).map(escapeRegExp).join('\\s+');
  const re = new RegExp(pattern, 'g');
  re.lastIndex = from; let match = re.exec(source);
  if (!match) {
    if (from !== 0) { re.lastIndex = 0; match = re.exec(source); }
    if (!match) return null;
  }
  return { start: match.index, end: match.index + match[0].length };
}

/** Create an element with its class, IDL properties, and children set at once,
 *  so a region's DOM is described entirely by its construction. */
function element<K extends keyof HTMLElementTagNameMap>(
  tag: K, className = '', props: Record<string, unknown> = {},
  ...children: (Node | string)[]
) {
  const el = document.createElement(tag);
  if (className) el.className = className;
  Object.assign(el, props);
  el.append(...children);
  return el;
}

function svgElement(className: string) {
  const el = document.createElementNS(SVG_NS, 'svg');
  el.setAttribute('class', className);
  return el;
}

/** Remove trailing whitespace and empty lines when a comment or a proposed
 *  replacement is committed, so a trailing Enter does not accumulate blank
 *  lines. */
function trimEnd(text: string) {
  return text.replace(/[ \t\r\n]+$/, '');
}

function nonSpaceBefore(text: string, offset: number) {
  let count = 0;
  for (let index = 0; index < offset && index < text.length; index += 1) {
    if (!/\s/.test(text[index])) count += 1;
  }
  return count;
}

function skipNonSpace(text: string, count: number) {
  let seen = 0;
  let index = 0;
  while (index < text.length && seen < count) {
    if (!/\s/.test(text[index])) seen += 1;
    index += 1;
  }
  return index;
}

function boundaryText(container: Node, offset: number, isEnd: boolean) {
  if (container.nodeType === Node.TEXT_NODE) return { node: container, offset };
  let child = container.childNodes[isEnd ? offset - 1 : offset];
  while (child && child.nodeType !== Node.TEXT_NODE) {
    child = isEnd ? child.lastChild : child.firstChild;
  }
  if (!child) return null;
  return { node: child, offset: isEnd ? (child as Text).nodeValue.length : 0 };
}


function mergeBands(rects: DOMRect[], origin: DOMRect) {
  const bands: { l: number; r: number; t: number; b: number }[] = [];
  for (const rect of rects) {
    if (!rect.width && !rect.height) continue;
    const top = rect.top - origin.top;
    const bottom = rect.bottom - origin.top;
    const left = rect.left - origin.left;
    const right = rect.right - origin.left;
    // Group by vertical overlap as well as equal tops: inline <code> spans can
    // report a slightly different top or height than the surrounding text on
    // the same line, which would otherwise leave a broken ribbon.
    const center = (top + bottom) / 2;
    const band = bands.find(item =>
      Math.abs(item.t - top) < 1
      || Math.abs((item.t + item.b) / 2 - center)
      < Math.max(item.b - item.t, bottom - top) * 0.5);
    if (band) {
      band.l = Math.min(band.l, left);
      band.r = Math.max(band.r, right);
      band.b = Math.max(band.b, bottom);
    } else {
      bands.push({ l: left, r: right, t: top, b: bottom });
    }
  }
  bands.sort((a, b) => a.t - b.t);
  return bands;
}

/** Creates a path that outlines the given bands. One connected outline around
 *  stacked line bands, so a wrapped range reads as a single box instead of one
 *  box per line. */
function ribbon(bands: { l: number; r: number; t: number; b: number }[]) {
  if (!bands.length) return '';
  const points: [number, number][] = [];
  const first = bands[0];
  points.push([first.l, first.t], [first.r, first.t]);
  for (let index = 1; index < bands.length; index += 1) {
    const previous = bands[index - 1];
    const current = bands[index];
    points.push([previous.r, current.t]);
    if (current.r !== previous.r) points.push([current.r, current.t]);
  }
  const last = bands[bands.length - 1];
  points.push([last.r, last.b], [last.l, last.b]);
  for (let index = bands.length - 2; index >= 0; index -= 1) {
    const below = bands[index + 1];
    const current = bands[index];
    points.push([below.l, current.b]);
    if (current.l !== below.l) points.push([current.l, current.b]);
  }
  return 'M' + points.map(
    point => `${point[0].toFixed(1)} ${point[1].toFixed(1)}`).join('L') + 'Z';
}

/** Wavy underline along the bottom edge of an annotation box. */
function wavePath(left: number, right: number, y: number) {
  const width = right - left;
  if (width <= 0) return '';
  const step = 6;
  const amplitude = 1.5;
  let d = `M${left.toFixed(1)} ${y.toFixed(1)}`;
  let x = left;
  let up = true;
  while (x < right) {
    const next = Math.min(x + step, right);
    const mid = (x + next) / 2;
    d += `Q${mid.toFixed(1)} ${(up ? y - amplitude : y + amplitude).toFixed(1)}`
      + ` ${next.toFixed(1)} ${y.toFixed(1)}`;
    x = next;
    up = !up;
  }
  return d;
}

/** Literal range covering the whole source line(s) the selection spans: from
 *  the line start of *start* to the line end of *end* (no newline). */
function fullLines(literal: string, start: number, end: number) {
  const before = literal.lastIndexOf('\n', start - 1);
  const lineStart = before === -1 ? 0 : before + 1;
  const lineEnd = literal.indexOf('\n', end);
  return { start: lineStart, end: lineEnd === -1 ? literal.length : lineEnd };
}

/** In-place review of one Markdown region: the annotation boxes, the two-box
 *  popup (editable original text + comment), and the compare view. The DOM and
 *  all mutable state live on the instance; `align()` maps the rendered text
 *  back to the literal, and `wire()` binds the interactions. */
export class MarkdownReview {
  node: any;
  literal: string;
  store: ReviewStore;
  entries: any[] = [];
  annotations: Annotation[] = [];
  view = 'rendered';
  selection: { start: number; end: number } | null = null;
  editing: Annotation | null = null;
  session: any = null;
  markers: Record<string, HTMLElement> | null = null;
  markerDrag: { side: string; rects: any[] | null } | null = null;

  rendered: HTMLDivElement;
  popup: HTMLFormElement;
  source: HTMLDivElement;
  sourceFill: HTMLPreElement;
  sourceInput: HTMLTextAreaElement;
  alignRows: HTMLDivElement;
  alignOriginal: HTMLPreElement;
  alignModified: HTMLPreElement;
  history: HTMLDivElement;
  comment: HTMLLabelElement;
  commentInput: HTMLTextAreaElement;
  svg: SVGSVGElement;
  controls: HTMLDivElement;
  actions: HTMLDivElement;
  editAction: HTMLButtonElement;
  deleteAction: HTMLButtonElement;

  constructor(node: any, raw: string, rawStart = 0, rawEnd = 0) {
    this.store = window.snakedoneReviewStore!;
    this.node = node;
    const { text, map } = markdownMap(raw);
    this.literal = text;
    this.annotations = this.store.addRegion(this, rawStart, rawEnd, text, map);
    // The popup has exactly two boxes: the original text is edited in place
    // (transparent textarea over the diff highlight) and the comment below.
    this.sourceFill = element('pre', 'snd-diff-fill');
    this.sourceInput = element('textarea', 'snd-diff-input',
      { rows: 1, spellcheck: false });
    inputRegions.set(this.sourceInput, this);
    this.source = element('div', 'snd-md-source', { hidden: true },
      this.sourceFill, this.sourceInput);
    this.alignOriginal = element('pre', 'snd-diff-row');
    this.alignModified = element('pre', 'snd-diff-row');
    // the rows are filled by renderAlign() per session
    this.alignRows = element('div', 'snd-diff-align', { hidden: true },
      this.alignOriginal, this.alignModified);
    this.history = element('div', 'snd-history', { hidden: true });
    this.commentInput = element('textarea', '', {
      placeholder: 'comment (Ctrl+Enter to submit) . . .', rows: 2,
    });
    this.comment = element('label', 'snd-md-comment', { hidden: true },
      this.commentInput);
    // The popup's top-right corner carries the modify/delete actions.
    this.editAction = element('button', '', { type: 'button', textContent: 'Edit' });
    this.deleteAction = element('button', '', { type: 'button', textContent: 'Delete' });
    this.editAction.addEventListener('click', () => this.beginEdit());
    this.deleteAction.addEventListener('click', () => this.deleteEditing());
    this.actions = element('div', 'snd-md-actions', {},
      this.editAction, this.deleteAction);
    this.popup = element('form', 'snd-md-popup',
      { hidden: true, noValidate: true },
      this.actions, this.source, this.alignRows, this.history, this.comment);
    this.popup.addEventListener('submit', event => event.preventDefault());
    this.rendered = element('div', 'snd-md-rendered');
    this.svg = svgElement('snd-md-overlay');
    this.controls = element('div', 'snd-md-controls');

    node.style.position = 'relative';
    node.replaceChildren(this.rendered, this.popup, this.svg, this.controls);
    node.dataset.sndMdView = 'rendered';
    node.sndMdState = this;
  }

  /** Map every rendered text node to a literal offset, in document order, so
   *  selections and annotations can be translated both ways. */
  align() {
    const entries: any[] = [];
    const walker = document.createTreeWalker(this.rendered, NodeFilter.SHOW_TEXT);
    let cursor = 0;
    let node: Node | null;
    while ((node = walker.nextNode())) {
      const text = node.nodeValue;
      if (!text || !/\S/.test(text)) continue;
      const found = findInSource(this.literal, text, cursor);
      if (!found) continue;
      const lead = (text.match(/^\s*/) || [''])[0].length;
      entries.push({ node, start: found.start, end: found.end, lead });
      cursor = found.end;
    }
    this.entries = entries;
  }

  literalToDomOffset(entry: any, offset: number) {
    let seen = 0;
    for (let index = entry.start; index < offset && index < entry.end; index += 1) {
      if (!/\s/.test(this.literal[index])) seen += 1;
    }
    // `entry.start` is the literal's first non-space character, which sits after
    // the node's own leading whitespace, so skip it before counting.
    const text = entry.node.nodeValue;
    let position = entry.lead + skipNonSpace(text.slice(entry.lead), seen);
    // When the literal offset sits on a word, skip the node's whitespace so the
    // range starts at the word rather than the preceding space.
    if (offset < this.literal.length && !/\s/.test(this.literal[offset])) {
      while (position < text.length && /\s/.test(text[position])) position += 1;
    }
    return position;
  }

  domToLiteralOffset(node: any, offset: number) {
    const entry = this.entries.find(item => item.node === node);
    if (!entry) return null;
    const count = nonSpaceBefore(node.nodeValue, offset);
    let index = entry.start;
    let seen = 0;
    while (index < entry.end && seen < count) {
      if (!/\s/.test(this.literal[index])) seen += 1;
      index += 1;
    }
    // Symmetrically, a DOM offset on a word maps past the literal's whitespace.
    if (offset < node.nodeValue.length && !/\s/.test(node.nodeValue[offset])) {
      while (index < entry.end && /\s/.test(this.literal[index])) index += 1;
    }
    return index;
  }

  trimRange(start: number, end: number) {
    // Selections should not carry the whitespace around the chosen words.
    while (start < end && /\s/.test(this.literal[start])) start += 1;
    while (end > start && /\s/.test(this.literal[end - 1])) end -= 1;
    return { start, end };
  }

  literalToRange(start: number, end: number) {
    const first = this.entries.find(entry => entry.end > start);
    if (!first) return null;
    const last = [...this.entries].reverse().find(entry => entry.start < end);
    if (!last) return null;
    const range = document.createRange();
    range.setStart(first.node,
      Math.min(this.literalToDomOffset(first, start), first.node.nodeValue.length));
    range.setEnd(last.node,
      Math.min(this.literalToDomOffset(last, end), last.node.nodeValue.length));
    return range;
  }

  drawBox(range: Range | null, className: string) {
    if (!range || typeof range.getClientRects !== 'function') return null;
    const origin = this.node.getBoundingClientRect();
    const bands = mergeBands(Array.from(range.getClientRects()), origin);
    if (!bands.length) return null;
    const path = document.createElementNS(SVG_NS, 'path');
    path.setAttribute('d', ribbon(bands));
    path.setAttribute('class', className);
    this.svg.appendChild(path);
    const last = bands[bands.length - 1];
    const wave = document.createElementNS(SVG_NS, 'path');
    wave.setAttribute('d', wavePath(last.l, last.r, last.b));
    wave.setAttribute('class', 'snd-md-wave');
    this.svg.appendChild(wave);
    return bands;
  }

  clearTransient() {
    // Keep the per-annotation badges; drop only the floating trigger.
    this.controls.querySelectorAll('.snd-md-trigger').forEach(node => node.remove());
  }

  /** The range an annotation is drawn at. A modified annotation is shown only
   *  over the region that actually changed — its baseline range minus the
   *  common prefix and suffix with the edited text. */
  displayRange(annotation: Annotation) {
    if (!annotation.modified) return annotation.chosen;
    // The baseline (`annotation.original`) is the whole source line(s); the
    // diff runs are relative to that, so anchor them at the line start. This
    // uses the same alignment as the highlighting, so the box spans exactly
    // the runs drawn in the edit box.
    const line = fullLines(this.literal, annotation.chosen.start, annotation.chosen.end);
    const info = diffInfo(annotation.original || '', annotation.edit || '');
    const start = line.start + Math.max(info.start, 0);
    const end = line.start + info.end;
    if (end > start) return { start, end };
    // A pure insertion has no width in the baseline; mark the insertion point.
    const point = Math.min(Math.max(start, line.start), Math.max(line.end - 1, line.start));
    return { start: point, end: point + 1 };
  }

  showRendered() {
    this.view = 'rendered';
    openRegions.delete(this);
    this.node.dataset.sndMdView = 'rendered';
    this.rendered.hidden = false;
    this.popup.hidden = true;
    this.selection = null;
    this.editing = null;
    this.session = null;
    this.controls.replaceChildren();
    this.svg.replaceChildren();
    this.annotations.forEach(annotation => {
      const display = this.displayRange(annotation);
      const range = this.literalToRange(display.start, display.end);
      if (!range) return;
      const bands = this.drawBox(
        range, annotation.locked ? 'snd-md-box snd-md-locked' : 'snd-md-box');
      if (!bands) return;
      annotation.bands = bands;
      this.addBadge(annotation, bands);
    });
  }

  addBadge(annotation: Annotation, bands: Band[]) {
    // Anchor the tab on the topmost band, not the bounding box: a wrapped run
    // whose lower line is the widest would otherwise float the tab to the
    // right of the top line, leaving a gap the pointer hides in.
    const first = bands[0];
    const badge = document.createElement('button');
    badge.type = 'button';
    badge.className = annotation.locked
      ? 'snd-md-badge snd-md-locked' : 'snd-md-badge';
    badge.textContent = '⋯';
    // Hovering shows what the annotation carries: its comment, else the added
    // text of the change runs, as found by the same alignment as the box.
    const revised = annotation.modified
      ? diffInfo(annotation.original || '', annotation.edit || '').revised : '';
    const hint = annotation.locked ? '[superseded: delete only] ' : '';
    badge.title = hint
      + (annotation.comment || revised || annotation.edit || 'Mark Up');
    badge.sndAnnotation = annotation;
    badge.addEventListener('click', event => {
      event.stopPropagation();
      this.openAnnotation(annotation);
    });
    // Entering the tab keeps it open, so the pointer can cross the gap between
    // the box and the tab without the tab vanishing under it.
    badge.addEventListener('mouseenter', () => this.revealBadge(badge));
    badge.addEventListener('mouseleave', () => this.hideBadge(badge));
    this.controls.appendChild(badge);
    const width = badge.offsetWidth;
    const height = badge.offsetHeight;
    badge.style.left = `${Math.max(0, first.r - width)}px`;
    badge.style.top = `${Math.max(0, first.t - height + 2)}px`;
    badge.hidden = true;
  }

  /** Show a badge and cancel any pending hide, so a pointer crossing the gap
   *  between the box and the tab has time to reach it. */
  revealBadge(badge: HTMLButtonElement) {
    if (badge.sndHideTimer !== undefined) {
      clearTimeout(badge.sndHideTimer);
      badge.sndHideTimer = undefined;
    }
    badge.hidden = false;
  }

  /** Hide a badge after a short grace period, unless the pointer comes back. */
  hideBadge(badge: HTMLButtonElement) {
    if (badge.sndHideTimer !== undefined) return;
    badge.sndHideTimer = window.setTimeout(() => {
      badge.sndHideTimer = undefined;
      badge.hidden = true;
    }, 220);
  }

  /** Open the read view: the diff (when the text changed) plus the comment,
   *  with modify/delete in the popup's top-right. */
  openAnnotation(annotation: Annotation) {
    this.editing = annotation;
    this.openSource(annotation.chosen.start, annotation.chosen.end,
      this.anchorTopForRange(annotation.chosen.start, annotation.chosen.end),
      'view');
  }

  beginEdit() {
    const annotation = this.editing;
    if (!annotation || annotation.locked) return;
    this.openSource(annotation.chosen.start, annotation.chosen.end,
      this.anchorTopForRange(annotation.chosen.start, annotation.chosen.end),
      'edit');
  }

  deleteEditing() {
    if (this.editing) this.store.remove(this, this.editing);
    this.showRendered();
  }

  anchorTopForRange(start: number, end: number) {
    const range = this.literalToRange(start, end);
    if (!range || typeof range.getClientRects !== 'function') return 0;
    const rects = Array.from(range.getClientRects());
    if (!rects.length) return 0;
    const origin = this.node.getBoundingClientRect();
    return rects[0].top - origin.top;
  }

  placePopup(anchorTop: number) {
    const origin = this.node.getBoundingClientRect();
    const anchor = Number.isFinite(anchorTop) ? anchorTop : 0;
    const height = this.popup.offsetHeight;
    const margin = 8;
    // Prefer above the anchor; fall back below it, then clamp so the whole
    // popup stays inside the viewport (opening must not scroll the page).
    let top = anchor - height - 6;
    if (origin.top + top < margin) top = anchor + 6;
    const bottom = origin.top + top + height;
    if (bottom > window.innerHeight - margin) {
      top = Math.max(margin, window.innerHeight - margin - height) - origin.top;
    }
    this.popup.style.top = `${top}px`;
  }

  openSource(start: number, end: number, anchorTop: number, mode = 'edit') {
    this.view = 'source';
    openRegions.add(this);
    this.node.dataset.sndMdView = 'source';
    this.popup.hidden = false;
    this.selection = { start, end };
    this.controls.replaceChildren();
    this.svg.replaceChildren();
    this.initSession(start, end, mode);
    if (this.session && this.session.mode === 'view' && this.editing) {
      renderHistory(
        this.history,
        this.store.history(this, this.editing),
        other => this.openAnnotation(other),
      );
    }
    this.placePopup(anchorTop);
    // Focus after the popup is placed, without letting the browser scroll the
    // page. Edit sessions focus the box so the pre-selected range is painted
    // between the delimiters; the read view stays unfocused.
    if (this.session && this.session.mode === 'edit') {
      this.sourceInput.focus({ preventScroll: true });
    }
  }

  /** Open an annotation session. The box holds the full source line(s) the
   *  chosen range spans; the range itself is pre-selected and delimited while
   *  the text stays unchanged. The committed comment (`session.committed`,
   *  the "已编辑" state) starts from the annotation; typing edits an
   *  uncommitted draft on top of it. */
  initSession(start: number, end: number, mode: string) {
    const editing = this.editing;
    const chosen = { start, end };
    const line = fullLines(this.literal, chosen.start, chosen.end);
    let original = '';
    let chosenLocal = null;
    if (editing) {
      original = typeof editing.original === 'string' ? editing.original : '';
      chosenLocal = { start: chosen.start - line.start, end: chosen.end - line.start };
    } else {
      original = this.literal.slice(line.start, line.end);
      chosenLocal = { start: chosen.start - line.start, end: chosen.end - line.start };
    }
    const committed = editing && typeof editing.comment === 'string'
      ? editing.comment : '';
    // The baseline is the whole literal range the box holds; a modification
    // replaces all of it, so the record's range must cover these lines rather
    // than follow a narrower re-selection made inside the box.
    const baseline = { start: line.start, end: line.start + original.length };
    this.session = {
      annotation: editing,
      chosen,
      chosenLocal,
      lineStart: line.start,
      baseline,
      original,
      text: editing && typeof editing.edit === 'string'
        ? editing.edit : original,
      body: committed,
      committed,
      mode: mode || 'edit',
    };
    this.sourceInput.value = this.session.text;
    this.commentInput.value = this.session.body;
    // Show the right boxes before measuring: the end markers need a laid-out
    // fill, otherwise they collapse to a zero-size point at the origin.
    this.modVisibility();
    this.renderSourceFill();
    this.renderAlign();
    this.autosizeSource();
    // Pre-select the reviewed range while the text is unmodified.
    if (this.session.text === this.session.original
      && chosenLocal.start < chosenLocal.end
      && chosenLocal.end <= this.session.text.length) {
      this.sourceInput.setSelectionRange(chosenLocal.start, chosenLocal.end);
    }
    // A new annotation opens ready to comment on the selection. Focusing
    // happens after the popup is placed (see openSource) so it cannot scroll.
  }

  /** Renders the current box text under the transparent textarea. While the
   *  text equals the baseline the reviewed range is delimited by two inline
   *  anchors; once it is edited, only the added or removed runs are highlighted
   *  (an addition gets a background, a deletion a red bar). */
  renderSourceFill() {
    const session = this.session;
    if (!session) return;
    const text = this.sourceInput.value;
    this.sourceFill.replaceChildren();
    this.markers = null;
    if (session.text === session.original) {
      this.appendDelimited(text, session.chosenLocal);
    } else {
      for (const slot of diffText(session.original, text)) {
        if (slot.kind === 'equal') {
          this.sourceFill.append(document.createTextNode(slot.mod));
        } else if (slot.kind === 'del') {
          this.sourceFill.appendChild(markDel('|'));
        } else {
          const span = document.createElement('span');
          span.className = 'snd-diff-ins';
          span.textContent = slot.mod;
          this.sourceFill.appendChild(span);
        }
      }
    }
    this.sourceFill.scrollTop = this.sourceInput.scrollTop;
    this.sourceFill.scrollLeft = this.sourceInput.scrollLeft;
  }

  /** Append *text* with the reviewed range highlighted. The range carries a
   *  background; each end gets one zero-width chevron (start above, end below),
   *  so the fill still mirrors the textarea exactly and the two sides are told
   *  apart without a vertical bar. */
  appendDelimited(text: string, chosenLocal: any) {
    const start = chosenLocal ? Math.max(0, chosenLocal.start) : 0;
    const end = chosenLocal ? Math.min(text.length, chosenLocal.end) : 0;
    if (start >= end) {
      this.sourceFill.append(document.createTextNode(text));
      return;
    }
    const left = markDel('v');
    const right = markDel('^');
    const range = document.createElement('span');
    range.className = 'snd-diff-range';
    range.append(left, document.createTextNode(text.slice(start, end)), right);
    this.sourceFill.append(
      document.createTextNode(text.slice(0, start)),
      range,
      document.createTextNode(text.slice(end)),
    );
    this.markers = { left, right };
  }

  /** The original box grows with its content instead of staying at three rows;
   *  past 40vh it is capped and the textarea scrolls. */
  autosizeSource() {
    const input = this.sourceInput;
    input.style.height = 'auto';
    const max = Math.round(window.innerHeight * 0.4);
    input.style.height = `${Math.min(input.scrollHeight, max)}px`;
  }

  /** Drop the range delimiters and highlight while keeping the text in place. */
  clearMarkers() {
    this.markers = null;
    this.sourceFill.querySelectorAll('.snd-diff-anchor').forEach(node => node.remove());
    this.sourceFill.querySelectorAll('.snd-diff-range').forEach(node => {
      node.replaceWith(...Array.from(node.childNodes));
    });
  }

  /** Re-place the delimiters after the selection changed inside the box. The
   *  fill is rebuilt, which only repaints the two inline anchors. */
  updateMarkers() {
    const session = this.session;
    if (!session) return;
    if (session.text !== session.original) { this.clearMarkers(); return; }
    this.renderSourceFill();
  }

  /** Per-character screen rectangles of the box text, for hit testing a drag
   *  position when the caret API does not resolve into the textarea. Every text
   *  node is walked in order; the inline marks hold no text, so the character
   *  indices stay aligned with the box value. */
  rectsOfText() {
    const rects: { x: number; y: number }[] = [];
    const walker = document.createTreeWalker(this.sourceFill, NodeFilter.SHOW_TEXT);
    let node: Node | null;
    while ((node = walker.nextNode())) {
      const value = node.nodeValue || '';
      for (let index = 0; index < value.length; index += 1) {
        const range = document.createRange();
        range.setStart(node, index);
        range.setEnd(node, Math.min(index + 1, value.length));
        const rect = range.getBoundingClientRect();
        rects.push({ x: (rect.left + rect.right) / 2, y: (rect.top + rect.bottom) / 2 });
      }
    }
    return rects.length ? rects : null;
  }

  /** Box-local character index nearest the pointer. */
  localCharAt(x: number, y: number, rects: any[] | null) {
    const input = this.sourceInput;
    const doc = document as any;
    let range = null;
    if (doc.caretRangeFromPoint) range = doc.caretRangeFromPoint(x, y);
    if (!range && doc.caretPositionFromPoint) {
      const caret = doc.caretPositionFromPoint(x, y);
      if (caret) range = { startContainer: caret.offsetNode, startOffset: caret.offset };
    }
    if (range && range.startContainer === input) {
      return Math.max(0, Math.min(range.startOffset, input.value.length));
    }
    if (!rects) rects = this.rectsOfText();
    if (!rects) return null;
    let best = -1;
    let score = Infinity;
    for (let index = 0; index < rects.length; index += 1) {
      const point = rects[index];
      if (!point) continue;
      const dy = Math.abs(point.y - y);
      if (dy > 14) continue;
      const d = Math.abs(point.x - x) + dy * 2;
      if (d < score) { score = d; best = index; }
    }
    return best;
  }

  /** The marker (if any) under the pointer. The anchor box is zero-sized, so
   *  hit test its bar and chevrons. */
  markerHitSide(x: number, y: number) {
    if (!this.markers) return null;
    const pad = 5;
    for (const side of ['left', 'right']) {
      const el = this.markers[side];
      if (!el) continue;
      const hit = [el, ...Array.from(el.children)].some(part => {
        const rect = part.getBoundingClientRect();
        return x >= rect.left - pad && x <= rect.right + pad
          && y >= rect.top - 6 && y <= rect.bottom + 6;
      });
      if (hit) return side;
    }
    return null;
  }

  /** The range the delimiters currently point at, as literal offsets. */
  currentChosen() {
    const session = this.session;
    if (!session || !session.chosen) return null;
    if (!session.chosenLocal) return session.chosen;
    const start = session.lineStart + session.chosenLocal.start;
    const end = session.lineStart + session.chosenLocal.end;
    if (end <= start) return session.chosen;
    return { start, end };
  }

  /** Two-row comparison of the committed modification: original on top with
   *  deleted runs underlined and inserted gaps marked; modified below with
   *  inserted runs marked and deleted gaps marked. */
  renderAlign() {
    const session = this.session;
    if (!session) return;
    const slots = diffText(session.original, session.text);
    this.alignOriginal.replaceChildren();
    this.alignModified.replaceChildren();
    for (const slot of slots) {
      if (slot.kind === 'equal') {
        this.alignOriginal.append(document.createTextNode(slot.orig));
        this.alignModified.append(document.createTextNode(slot.mod));
      } else if (slot.kind === 'del') {
        const span = document.createElement('span');
        span.className = 'snd-diff-del';
        span.textContent = slot.orig;
        this.alignOriginal.appendChild(span);
        this.alignModified.appendChild(markDel('v'));
      } else {
        this.alignOriginal.appendChild(markDel('^'));
        const span = document.createElement('span');
        span.className = 'snd-diff-ins';
        span.textContent = slot.mod;
        this.alignModified.appendChild(span);
      }
    }
  }

  setSourceValue(text: string) {
    if (!this.session) return;
    this.session.text = text;
    if (this.sourceInput.value !== text) this.sourceInput.value = text;
    this.renderSourceFill();
    this.autosizeSource();
  }

  modVisibility() {
    const session = this.session;
    if (!session) return;
    const view = session.mode === 'view';
    // Read view: the version history plus the comment, no editing.
    // Edit view: the original box plus the comment.
    const locked = !!(session.annotation && session.annotation.locked);
    this.source.hidden = view;
    // The read view shows the version history stack instead of the two-row
    // comparison; editing keeps the single original-text box.
    this.alignRows.hidden = true;
    this.history.hidden = !view;
    this.comment.hidden = false;
    this.commentInput.readOnly = view || locked;
    this.editAction.hidden = !view || locked;
    this.deleteAction.hidden = !session.annotation;
  }

  /** True when a fresh annotation would carry neither a comment nor a text
   *  change, so committing it would leave a meaningless empty annotation. */
  isEmptyAnnotation() {
    const session = this.session;
    if (!session || session.annotation) return false;
    return !(session.committed || '') && this.sourceInput.value === session.original;
  }

  /** Write the live session back into the committed annotation. The comment
   *  body comes from `session.committed` (已编辑) only: an uncommitted draft
   *  is discarded unless this is an explicit Ctrl+Enter submit. A fresh
   *  annotation with neither a comment nor a change is dropped. */
  saveAnnotation(trimmed: boolean) {
    const session = this.session;
    if (!session) return;
    const text = trimmed ? trimEnd(this.sourceInput.value) : this.sourceInput.value;
    const body = session.committed || '';
    const modified = text !== session.original;
    // A modification replaces the whole baseline the box holds, so it anchors
    // the annotation at the baseline lines even if the caret inside the box
    // was re-selected to a narrower range.
    let chosen = this.currentChosen();
    if (!chosen || chosen.end <= chosen.start) return;
    if (modified) chosen = session.baseline;
    let annotation = session.annotation;
    if (annotation) {
      annotation.chosen = chosen;
      annotation.original = session.original;
      annotation.edit = text;
      annotation.comment = body;
      annotation.modified = modified;
    } else if (body || modified) {
      annotation = new Annotation({
        selection: this.selection,
        chosen,
        original: session.original,
        edit: text,
        comment: body,
        modified,
      });
      session.annotation = annotation;
    }
    if (annotation) this.store.save(this, annotation);
  }

  sessionDirty() {
    const session = this.session;
    if (!session) return false;
    if (this.isEmptyAnnotation()) return false;
    const text = this.sourceInput.value;
    const body = session.committed || '';
    if (session.annotation) {
      return text !== (session.annotation.edit || session.original)
        || body !== (session.annotation.comment || '');
    }
    return text !== session.original || body !== '';
  }

  confirmAnnotation() {
    const session = this.session;
    if (session) session.committed = trimEnd(this.commentInput.value);
    this.saveAnnotation(true);
    window.getSelection()?.removeAllRanges();
    this.showRendered();
  }

  /** Closing without Esc keeps the committed state; an uncommitted comment
   *  draft is discarded (see saveAnnotation). */
  dismissPopup() {
    if (this.sessionDirty()) this.saveAnnotation(false);
    window.getSelection()?.removeAllRanges();
    this.showRendered();
  }

  cancelSession() {
    window.getSelection()?.removeAllRanges();
    this.showRendered();
  }

  selectionToLiteral(selection: Selection | null) {
    if (!selection || selection.isCollapsed || !selection.rangeCount) return null;
    const range = selection.getRangeAt(0);
    if (!this.rendered.contains(range.startContainer)
      || !this.rendered.contains(range.endContainer)) return null;
    const startPoint = boundaryText(range.startContainer, range.startOffset, false);
    const endPoint = boundaryText(range.endContainer, range.endOffset, true);
    if (!startPoint || !endPoint) return null;
    const start = this.domToLiteralOffset(startPoint.node, startPoint.offset);
    const end = this.domToLiteralOffset(endPoint.node, endPoint.offset);
    if (start === null || end === null || end <= start) return null;
    const trimmed = this.trimRange(start, end);
    return trimmed.end > trimmed.start ? trimmed : null;
  }

  showTrigger(point: { x: number; y: number }, mapped: { start: number; end: number }) {
    this.clearTransient();
    const origin = this.node.getBoundingClientRect();
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'snd-md-trigger';
    button.textContent = '✎';
    button.addEventListener('mousedown', event => event.preventDefault());
    button.addEventListener('click', () => {
      this.openSource(mapped.start, mapped.end,
        this.anchorTopForRange(mapped.start, mapped.end));
    });
    this.controls.appendChild(button);
    const width = button.offsetWidth;
    const height = button.offsetHeight;
    const max = this.node.clientWidth;
    const x = point.x - origin.left;
    const y = point.y - origin.top;
    let left = x + 10;
    if (left + width > max) left = x - width - 10;
    const top = y - height - 6;
    button.style.left = `${Math.max(0, left)}px`;
    button.style.top = `${Math.max(0, top)}px`;
  }

  /** Follow the box's selection while it is the focused element.
   *
   *  Called from the single document-level `selectionchange` handler: as the
   *  range is (re)selected in the box the delimiters follow, and a collapsed
   *  caret clears them until something is selected again. */
  trackSelection() {
    const session = this.session;
    if (!session || this.markerDrag) return;
    if (session.text !== session.original) return;
    const start = this.sourceInput.selectionStart;
    const end = this.sourceInput.selectionEnd;
    if (end <= start) { this.clearMarkers(); return; }
    if (session.chosenLocal
      && start === session.chosenLocal.start && end === session.chosenLocal.end) return;
    session.chosenLocal = { start, end };
    this.updateMarkers();
  }

  /** Bind review/annotation interaction events. */
  wire() {
    this.node.addEventListener('mousemove', (event: MouseEvent) => {
      const origin = this.node.getBoundingClientRect();
      const x = event.clientX - origin.left;
      const y = event.clientY - origin.top;
      this.controls.querySelectorAll<HTMLButtonElement>('.snd-md-badge').forEach(badge => {
        const bands = badge.sndAnnotation?.bands;
        const overBox = !!bands && bands.some((band: any) =>
          x >= band.l - 2 && x <= band.r + 2 &&
          y >= band.t - 2 && y <= band.b + 2);
        const overBadge = !badge.hidden && insideRect(badge, x, y, origin);
        if (overBox || overBadge) this.revealBadge(badge);
        else this.hideBadge(badge);
      });
    });
    this.node.addEventListener('mouseleave', () => {
      this.controls.querySelectorAll<HTMLButtonElement>('.snd-md-badge')
        .forEach(badge => this.hideBadge(badge));
    });
    this.rendered.addEventListener('mousedown', () => {
      if (this.view === 'source') this.dismissPopup();
      else this.clearTransient();
    });
    this.rendered.addEventListener('mouseup', event => {
      const mapped = this.selectionToLiteral(window.getSelection());
      if (mapped) this.showTrigger({ x: event.clientX, y: event.clientY }, mapped);
    });
    this.sourceInput.addEventListener('input', () => {
      this.setSourceValue(this.sourceInput.value);
    });
    this.sourceInput.addEventListener('scroll', () => {
      this.sourceFill.scrollTop = this.sourceInput.scrollTop;
      this.sourceFill.scrollLeft = this.sourceInput.scrollLeft;
    });
    this.sourceInput.addEventListener('pointerdown', event => {
      const session = this.session;
      if (!session || session.text !== session.original) return;
      const side = this.markerHitSide(event.clientX, event.clientY);
      if (!side) return;
      event.preventDefault();
      this.markerDrag = { side, rects: null };
      try { this.sourceInput.setPointerCapture(event.pointerId); } catch (error) { /* synthetic */ }
    });
    this.sourceInput.addEventListener('pointermove', event => {
      const session = this.session;
      if (this.markerDrag) {
        if (!session || !session.chosenLocal
          || session.text !== session.original) return;
        if (!this.markerDrag.rects) this.markerDrag.rects = this.rectsOfText();
        const at = this.localCharAt(event.clientX, event.clientY, this.markerDrag.rects);
        if (at === null) return;
        let start = session.chosenLocal.start;
        let end = session.chosenLocal.end;
        if (this.markerDrag.side === 'left') start = Math.min(at, end - 1);
        else end = Math.max(at + 1, start + 1);
        if (start === session.chosenLocal.start && end === session.chosenLocal.end) return;
        session.chosenLocal = { start, end };
        this.sourceInput.setSelectionRange(start, end);
        this.updateMarkers();
        return;
      }
      const dragCursor = session && session.text === session.original
        ? this.markerHitSide(event.clientX, event.clientY) : null;
      this.sourceInput.style.cursor = dragCursor ? 'ew-resize' : '';
    });
    const endMarkerDrag = () => { this.markerDrag = null; };
    this.sourceInput.addEventListener('pointerup', endMarkerDrag);
    this.sourceInput.addEventListener('pointercancel', endMarkerDrag);
    this.sourceInput.addEventListener('keydown', event => {
      if (event.isComposing) return;
      if (!this.session || this.session.mode !== 'edit') return;
      if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') {
        event.preventDefault();
        this.confirmAnnotation();
      }
    });
    this.commentInput.addEventListener('input', () => {
      if (this.session) this.session.body = this.commentInput.value;
    });
    this.commentInput.addEventListener('keydown', event => {
      if (event.isComposing) return;
      if (!this.session || this.session.mode !== 'edit') return;
      if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') {
        event.preventDefault();
        this.confirmAnnotation();
      } else if (event.key === 'Enter' && !event.shiftKey && !event.altKey
        && !event.ctrlKey && !event.metaKey) {
        // Commit the draft as 已编辑, then the default keypress appends a
        // new line while staying in edit mode.
        this.session.committed = trimEnd(this.commentInput.value);
      }
    });
  }
}

function insideRect(element: Element, x: number, y: number, origin: DOMRect) {
  const rect = element.getBoundingClientRect();
  return x >= rect.left - origin.left
    && x <= rect.right - origin.left
    && y >= rect.top - origin.top
    && y <= rect.bottom - origin.top;
}

// One document-level handler shared by every region, instead of one
// `keydown`/`selectionchange` listener per region.  Escape closes every open
// popup; a selection change is routed to the region that owns the focused box.
document.addEventListener('keydown', event => {
  if (event.key !== 'Escape') return;
  for (const region of [...openRegions]) region.cancelSession();
});

// A mousedown outside an open region closes its popup; clicks inside the
// region (rendered text, popup, badges) are handled by the region itself.
document.addEventListener('mousedown', event => {
  const target = event.target as Node;
  for (const region of [...openRegions]) {
    if (!region.node.contains(target)) region.dismissPopup();
  }
});

document.addEventListener('selectionchange', () => {
  const element = document.activeElement;
  if (element instanceof HTMLElement) inputRegions.get(element)?.trackSelection();
});
