const SVG_NS = 'http://www.w3.org/2000/svg';

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

/** Character-level alignment of *original* and *modified* used by the
 *  modification review. Returns run slots: ``equal`` (both sides), ``del``
 *  (original only) and ``ins`` (modified only); adjacent same-kind runs are
 *  merged. The DP is capped so very long texts degrade to whole-vs-whole. */
function diffText(original: string, modified: string) {
  const n = original.length;
  const m = modified.length;
  if (n * m > 1000000) {
    return original === modified
      ? [{ kind: 'equal', orig: original, mod: modified }]
      : [{ kind: 'del', orig: original, mod: '' },
      { kind: 'ins', orig: '', mod: modified }];
  }
  const dp = Array.from({ length: n + 1 }, () => new Uint32Array(m + 1));
  for (let i = n - 1; i >= 0; i -= 1) {
    for (let j = m - 1; j >= 0; j -= 1) {
      dp[i][j] = original[i] === modified[j]
        ? dp[i + 1][j + 1] + 1
        : Math.max(dp[i + 1][j], dp[i][j + 1]);
    }
  }
  const cells: { kind: string; orig: string; mod: string }[] = [];
  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    if (original[i] === modified[j]) {
      cells.push({ kind: 'equal', orig: original[i], mod: modified[j] });
      i += 1;
      j += 1;
    } else if (dp[i + 1][j] >= dp[i][j + 1]) {
      cells.push({ kind: 'del', orig: original[i], mod: '' });
      i += 1;
    } else {
      cells.push({ kind: 'ins', orig: '', mod: modified[j] });
      j += 1;
    }
  }
  while (i < n) {
    cells.push({ kind: 'del', orig: original[i], mod: '' });
    i += 1;
  }
  while (j < m) {
    cells.push({ kind: 'ins', orig: '', mod: modified[j] });
    j += 1;
  }
  const slots: { kind: string; orig: string; mod: string }[] = [];
  for (const cell of cells) {
    const last = slots[slots.length - 1];
    if (last && last.kind === cell.kind) {
      last.orig += cell.orig;
      last.mod += cell.mod;
    } else {
      slots.push({ kind: cell.kind, orig: cell.orig, mod: cell.mod });
    }
  }
  return slots;
}

/** The changed part of an alignment, in baseline coordinates. Uses the same
 *  character alignment as the diff highlighting, so a range drawn from it
 *  spans exactly the runs that get highlighted; *revised* is the added text
 *  (the modified side of the non-equal runs). */
function diffInfo(original: string, modified: string) {
  let offset = 0;
  let start = -1;
  let end = 0;
  let revised = '';
  for (const slot of diffText(original, modified)) {
    if (slot.kind === 'equal') {
      offset += slot.orig.length;
      continue;
    }
    if (start === -1) start = offset;
    if (slot.kind === 'del') {
      offset += slot.orig.length;
      end = offset;
    } else {
      end = offset;
      revised += slot.mod;
    }
  }
  return { start, end, revised };
}

/** A red vertical bar marking where the baseline lost characters. The element
 *  has a net zero width (2px with flanking -1px margins) so in the overlay
 *  fill it does not shift the text that follows. */
function delMark() {
  const span = document.createElement('span');
  span.className = 'snd-diff-del-mark';
  return span;
}

/** A zero-width marker where one row misses content the other row carries: a
 *  red bar with a v above and a ^ below, all outside the text flow and
 *  pointing at the gap between the neighbouring characters. It reserves no
 *  inline space, so the two rows are no longer width-aligned. */
function gapMark() {
  const span = document.createElement('span');
  span.className = 'snd-diff-gap';
  span.innerHTML = '<i class="snd-diff-gap-bar"></i>'
    + '<i class="snd-diff-gap-tri snd-diff-gap-top"></i>'
    + '<i class="snd-diff-gap-tri snd-diff-gap-bottom"></i>';
  return span;
}

function mergeBands(rects: DOMRect[], origin: DOMRect) {
  const bands: { l: number; r: number; t: number; b: number }[] = [];
  for (const rect of rects) {
    if (!rect.width && !rect.height) continue;
    const top = rect.top - origin.top;
    const bottom = rect.bottom - origin.top;
    const left = rect.left - origin.left;
    const right = rect.right - origin.left;
    const band = bands.find(item => Math.abs(item.t - top) < 1);
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
  entries: any[] = [];
  annotations: any[] = [];
  view = 'rendered';
  selection: { start: number; end: number } | null = null;
  editing: any = null;
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
  comment: HTMLLabelElement;
  commentInput: HTMLTextAreaElement;
  svg: SVGSVGElement;
  controls: HTMLDivElement;
  actions: HTMLDivElement;
  editAction: HTMLButtonElement;
  deleteAction: HTMLButtonElement;

  constructor(node: any, literal: string) {
    this.node = node;
    this.literal = literal;
    // The popup has exactly two boxes: the original text is edited in place
    // (transparent textarea over the diff highlight) and the comment below.
    this.sourceFill = element('pre', 'snd-diff-fill');
    this.sourceInput = element('textarea', 'snd-diff-input',
      { rows: 1, spellcheck: false });
    this.source = element('div', 'snd-md-source', { hidden: true },
      this.sourceFill, this.sourceInput);
    this.alignOriginal = element('pre', 'snd-diff-row');
    this.alignModified = element('pre', 'snd-diff-row');
    // the rows are filled by renderAlign() per session
    this.alignRows = element('div', 'snd-diff-align', { hidden: true },
      this.alignOriginal, this.alignModified);
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
      this.actions, this.source, this.alignRows, this.comment);
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
  displayRange(annotation: any) {
    if (!annotation.modified) return annotation.chosen;
    // The baseline (`annotation.original`) is the whole source line(s); the
    // diff runs are relative to that, so anchor them at the line start. This
    // uses the same alignment as the highlighting, so the box spans exactly
    // the runs drawn in the edit box.
    const line = fullLines(this.literal, annotation.chosen.start, annotation.chosen.end);
    const info = diffInfo(annotation.original || '', annotation.text || '');
    const start = line.start + Math.max(info.start, 0);
    const end = line.start + info.end;
    if (end > start) return { start, end };
    // A pure insertion has no width in the baseline; mark the insertion point.
    const point = Math.min(Math.max(start, line.start), Math.max(line.end - 1, line.start));
    return { start: point, end: point + 1 };
  }

  showRendered() {
    this.view = 'rendered';
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
      const bands = this.drawBox(range, 'snd-md-box');
      if (!bands) return;
      annotation.bands = bands;
      this.addBadge(annotation, bands);
    });
  }

  addBadge(annotation: any, bands: { l: number; r: number; t: number; b: number }[]) {
    const right = Math.max(...bands.map(band => band.r));
    const top = Math.min(...bands.map(band => band.t));
    const badge = document.createElement('button');
    badge.type = 'button';
    badge.className = 'snd-md-badge';
    badge.textContent = '⋯';
    // Hovering shows what the annotation carries: its comment, else the added
    // text of the change runs, as found by the same alignment as the box.
    const revised = annotation.modified
      ? diffInfo(annotation.original || '', annotation.text || '').revised : '';
    badge.title = annotation.body || revised || annotation.text || 'Mark Up';
    badge.sndAnnotation = annotation;
    badge.addEventListener('click', event => {
      event.stopPropagation();
      this.openAnnotation(annotation);
    });
    this.controls.appendChild(badge);
    const width = badge.offsetWidth;
    const height = badge.offsetHeight;
    badge.style.left = `${Math.max(0, right - width)}px`;
    badge.style.top = `${Math.max(0, top - height + 2)}px`;
    badge.hidden = true;
  }

  /** Open the read view: the diff (when the text changed) plus the comment,
   *  with modify/delete in the popup's top-right. */
  openAnnotation(annotation: any) {
    this.editing = annotation;
    this.openSource(annotation.chosen.start, annotation.chosen.end,
      this.anchorTopForRange(annotation.chosen.start, annotation.chosen.end),
      'view');
  }

  beginEdit() {
    const annotation = this.editing;
    if (!annotation) return;
    this.openSource(annotation.chosen.start, annotation.chosen.end,
      this.anchorTopForRange(annotation.chosen.start, annotation.chosen.end),
      'edit');
  }

  deleteEditing() {
    const index = this.annotations.indexOf(this.editing);
    if (index !== -1) this.annotations.splice(index, 1);
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

  openSource(start: number | null, end: number | null, anchorTop: number, mode = 'edit') {
    this.view = 'source';
    this.node.dataset.sndMdView = 'source';
    this.popup.hidden = false;
    this.selection = start === null || end === null ? null : { start, end };
    this.controls.replaceChildren();
    this.svg.replaceChildren();
    this.initSession(start, end, mode);
    this.placePopup(anchorTop);
    // Focus after the popup is placed, without letting the browser scroll the
    // page. Edit sessions focus the box so the pre-selected range is painted
    // between the delimiters; a fresh Show Source keeps the comment box; the
    // read view stays unfocused.
    if (this.session && this.session.mode === 'edit') {
      if (!this.session.whole) {
        this.sourceInput.focus({ preventScroll: true });
      } else if (!this.session.annotation) {
        this.commentInput.focus({ preventScroll: true });
      }
    }
  }

  /** Open an annotation session. The box holds the full source line(s) the
   *  chosen range spans; the range itself is pre-selected and delimited while
   *  the text stays unchanged. The committed comment (`session.committed`,
   *  the "已编辑" state) starts from the annotation; typing edits an
   *  uncommitted draft on top of it. */
  initSession(start: number | null, end: number | null, mode: string) {
    const whole = start === null || end === null;
    const editing = this.editing;
    const chosen = whole ? null : { start, end };
    const line = chosen ? fullLines(this.literal, chosen.start, chosen.end) : null;
    let original = '';
    let chosenLocal = null;
    let lineStart = null;
    if (editing && chosen) {
      original = typeof editing.original === 'string' ? editing.original : '';
      chosenLocal = { start: chosen.start - line.start, end: chosen.end - line.start };
      lineStart = line.start;
    } else if (whole) {
      original = this.literal;
    } else if (chosen) {
      lineStart = line.start;
      original = this.literal.slice(line.start, line.end);
      chosenLocal = { start: chosen.start - line.start, end: chosen.end - line.start };
    }
    const committed = editing && typeof editing.body === 'string'
      ? editing.body : '';
    this.session = {
      annotation: editing,
      whole,
      chosen,
      chosenLocal,
      lineStart,
      original,
      text: editing && typeof editing.text === 'string'
        ? editing.text : original,
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
    if (!whole && chosenLocal && this.session.text === this.session.original
      && chosenLocal.start < chosenLocal.end
      && chosenLocal.end <= this.session.text.length) {
      this.sourceInput.setSelectionRange(chosenLocal.start, chosenLocal.end);
    }
    // A new annotation opens ready to comment on the selection. Focusing
    // happens after the popup is placed (see openSource) so it cannot scroll.
  }

  /** Renders the current box text under the transparent textarea. The common
   *  prefix and suffix with the baseline stay plain; the middle (the
   *  unchanged runs stay plain, so only what was actually added or removed is
   *  highlighted. A deletion has no character to draw, so a red bar marks its
   *  position. */
  renderSourceFill() {
    const session = this.session;
    if (!session) return;
    const text = this.sourceInput.value;
    this.sourceFill.replaceChildren();
    // `replaceChildren` drops any previous markers from the DOM; forget the
    // cached references so `updateMarkers` rebuilds instead of restyling
    // detached nodes.
    this.markers = null;
    if (session.text === session.original) {
      this.sourceFill.append(document.createTextNode(text));
    } else {
      for (const slot of diffText(session.original, text)) {
        if (slot.kind === 'equal') {
          this.sourceFill.append(document.createTextNode(slot.mod));
        } else if (slot.kind === 'del') {
          this.sourceFill.appendChild(delMark());
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
    this.updateMarkers();
  }

  /** The original box grows with its content instead of staying at three rows;
   *  past 40vh it is capped and the textarea scrolls. */
  autosizeSource() {
    const input = this.sourceInput;
    input.style.height = 'auto';
    const max = Math.round(window.innerHeight * 0.4);
    input.style.height = `${Math.min(input.scrollHeight, max)}px`;
  }

  /** Delimiters marking the reviewed range while the box text stays
   *  unmodified. Each is a zero-width anchor in the text flow with a bar and
   *  two triangles drawn outside the line, so it never covers a glyph.
   *  Dragging an end, or re-selecting in the box, adjusts the range. */
  clearMarkers() {
    if (this.markers) {
      if (this.markers.left) this.markers.left.remove();
      if (this.markers.right) this.markers.right.remove();
      this.markers = null;
    }
    this.sourceFill.querySelectorAll('.snd-diff-mark').forEach(node => node.remove());
  }

  updateMarkers() {
    const session = this.session;
    if (!session || session.whole || !session.chosenLocal) { this.clearMarkers(); return; }
    if (session.text !== session.original) { this.clearMarkers(); return; }
    const node = this.sourceFill.firstChild;
    if (!node || node.nodeType !== Node.TEXT_NODE) { this.clearMarkers(); return; }
    const text = node.nodeValue as string;
    const start = Math.max(0, session.chosenLocal.start);
    const end = Math.min(text.length, session.chosenLocal.end);
    if (start >= end) { this.clearMarkers(); return; }
    const origin = this.sourceFill.getBoundingClientRect();
    const pointAt = (offset: number, atEnd: boolean) => {
      const range = document.createRange();
      range.setStart(node, offset);
      range.setEnd(node, offset + 1);
      const rect = range.getBoundingClientRect();
      return {
        x: (atEnd ? rect.right : rect.left) - origin.left + this.sourceFill.scrollLeft,
        y: rect.top - origin.top + this.sourceFill.scrollTop,
        h: rect.height || 0,
      };
    };
    const ensure = (side: string, point: { x: number; y: number; h: number }) => {
      if (!this.markers) this.markers = {};
      let el = this.markers[side];
      if (!el) {
        el = document.createElement('span');
        el.className = `snd-diff-mark snd-diff-mark-${side}`;
        el.innerHTML =
          '<i class="snd-diff-mark-tri snd-diff-mark-top"></i>'
          + '<i class="snd-diff-mark-body"></i>'
          + '<i class="snd-diff-mark-tri snd-diff-mark-bottom"></i>';
        this.sourceFill.appendChild(el);
        this.markers[side] = el;
      }
      el.style.left = `${point.x}px`;
      el.style.top = `${point.y}px`;
      el.style.height = `${point.h}px`;
    };
    try {
      ensure('left', pointAt(start, false));
      ensure('right', pointAt(end - 1, true));
    } catch (error) { /* empty range on a broken edge */ }
  }

  /** Per-character screen rectangles of the box text, for hit testing a drag
   *  position when the caret API does not resolve into the textarea. */
  rectsOfText() {
    const node = this.sourceFill.firstChild;
    if (!node || node.nodeType !== Node.TEXT_NODE) return null;
    const rects: { x: number; y: number }[] = [];
    for (let index = 0; index < (node.nodeValue as string).length; index += 1) {
      const range = document.createRange();
      range.setStart(node, index);
      range.setEnd(node, Math.min(index + 1, (node.nodeValue as string).length));
      const rect = range.getBoundingClientRect();
      rects.push({ x: (rect.left + rect.right) / 2, y: (rect.top + rect.bottom) / 2 });
    }
    return rects;
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

  /** The marker (if any) under the pointer, hit-tested on the textarea. */
  markerHitSide(x: number, y: number) {
    if (!this.markers) return null;
    const pad = 5;
    for (const side of ['left', 'right']) {
      const el = this.markers[side];
      if (!el) continue;
      const rect = el.getBoundingClientRect();
      if (x >= rect.left - pad && x <= rect.right + pad
        && y >= rect.top - 6 && y <= rect.bottom + 6) return side;
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
        this.alignModified.appendChild(gapMark());
      } else {
        this.alignOriginal.appendChild(gapMark());
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
    const modified = !!(session.annotation && session.annotation.modified);
    // Read view: the diff (only when modified) plus the comment, no editing.
    // Edit view: the original box plus the comment.
    this.source.hidden = view;
    this.alignRows.hidden = !(view && modified);
    this.comment.hidden = false;
    this.commentInput.readOnly = view;
    this.editAction.hidden = !view;
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
    const chosen = this.currentChosen();
    if (!chosen || chosen.end <= chosen.start) return;
    const modified = text !== session.original;
    if (session.annotation) {
      session.annotation.chosen = chosen;
      session.annotation.original = session.original;
      session.annotation.text = text;
      session.annotation.body = body;
      session.annotation.modified = modified;
    } else if (body || modified) {
      this.annotations.push({
        selection: this.selection,
        chosen,
        original: session.original,
        text,
        body,
        modified,
      });
    }
  }

  sessionDirty() {
    const session = this.session;
    if (!session) return false;
    if (this.isEmptyAnnotation()) return false;
    const text = this.sourceInput.value;
    const body = session.committed || '';
    if (session.annotation) {
      return text !== (session.annotation.text || session.original)
        || body !== (session.annotation.body || '');
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

  showTrigger(point: { x: number; y: number }, mapped: { start: number; end: number } | null) {
    this.clearTransient();
    const origin = this.node.getBoundingClientRect();
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'snd-md-trigger';
    button.textContent = mapped ? 'Mark Up' : 'Show Source';
    button.addEventListener('mousedown', event => event.preventDefault());
    button.addEventListener('click', () => {
      if (mapped) {
        this.openSource(mapped.start, mapped.end,
          this.anchorTopForRange(mapped.start, mapped.end));
      } else {
        this.openSource(null, null, point.y - origin.top);
      }
    });
    this.controls.appendChild(button);
    const width = button.offsetWidth;
    const height = button.offsetHeight;
    const max = this.node.clientWidth;
    const x = point.x - origin.left;
    const y = point.y - origin.top;
    let left = x + 10;
    if (left + width > max) left = x - width - 10;
    const top = mapped ? y - height - 6 : y;
    button.style.left = `${Math.max(0, left)}px`;
    button.style.top = `${Math.max(0, top)}px`;
  }

  /** Bind review/annotation interaction events. */
  wire() {
    this.node.addEventListener('mousemove', (event: MouseEvent) => {
      const origin = this.node.getBoundingClientRect();
      const x = event.clientX - origin.left;
      const y = event.clientY - origin.top;
      this.controls.querySelectorAll<HTMLButtonElement>('.snd-md-badge').forEach(badge => {
        const bands = badge.sndAnnotation && (badge.sndAnnotation as any).bands;
        const overBox = !!bands && bands.some((band: any) =>
          x >= band.l - 2 && x <= band.r + 2 &&
          y >= band.t - 2 && y <= band.b + 2);
        const overBadge = !badge.hidden && insideRect(badge, x, y, origin);
        badge.hidden = !(overBox || overBadge);
      });
    });
    this.node.addEventListener('mouseleave', () => {
      this.controls.querySelectorAll<HTMLButtonElement>('.snd-md-badge')
        .forEach(badge => { badge.hidden = true; });
    });
    this.rendered.addEventListener('mousedown', () => {
      if (this.view === 'source') this.dismissPopup();
      else this.clearTransient();
    });
    this.rendered.addEventListener('click', event => {
      if (event.detail >= 3) {
        this.showTrigger({ x: event.clientX, y: event.clientY }, null);
      }
    });
    this.rendered.addEventListener('mouseup', event => {
      const mapped = this.selectionToLiteral(window.getSelection());
      if (mapped) this.showTrigger({ x: event.clientX, y: event.clientY }, mapped);
    });
    document.addEventListener('keydown', event => {
      if (event.key === 'Escape' && this.view === 'source') this.cancelSession();
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
      if (!session || session.whole || session.text !== session.original) return;
      const side = this.markerHitSide(event.clientX, event.clientY);
      if (!side) return;
      event.preventDefault();
      this.markerDrag = { side, rects: null };
      try { this.sourceInput.setPointerCapture(event.pointerId); } catch (error) { /* synthetic */ }
    });
    this.sourceInput.addEventListener('pointermove', event => {
      const session = this.session;
      if (this.markerDrag) {
        if (!session || session.whole || !session.chosenLocal
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
      const dragCursor = session && !session.whole && session.text === session.original
        ? this.markerHitSide(event.clientX, event.clientY) : null;
      this.sourceInput.style.cursor = dragCursor ? 'ew-resize' : '';
    });
    const endMarkerDrag = () => { this.markerDrag = null; };
    this.sourceInput.addEventListener('pointerup', endMarkerDrag);
    this.sourceInput.addEventListener('pointercancel', endMarkerDrag);
    // As the range is (re)selected in the box, the delimiters follow; a
    // collapsed caret clears them until something is selected again. This must
    // listen to `selectionchange` (a real click-collapse does not fire
    // `select`), restricted to the focused box.
    document.addEventListener('selectionchange', () => {
      if (document.activeElement !== this.sourceInput) return;
      const session = this.session;
      if (!session || session.whole || this.markerDrag) return;
      if (session.text !== session.original) return;
      const start = this.sourceInput.selectionStart;
      const end = this.sourceInput.selectionEnd;
      if (end <= start) { this.clearMarkers(); return; }
      if (session.chosenLocal
        && start === session.chosenLocal.start && end === session.chosenLocal.end) return;
      session.chosenLocal = { start, end };
      this.updateMarkers();
    });
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
