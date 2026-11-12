import { Annotation } from './annotation';
import type { Range as LiteralRange } from './annotation';
import {
  addBadge, bandsOf, displayRange, drawBands, hideBadge, revealBadge, selectBadges,
} from './boxes';
import { renderRecords } from './history/historyrender';
import { LiteralMap } from './mapping';
import { fullLines } from './model/span';
import type { Band } from './render/overlay';
import { ReviewSession } from './session';
import { SourceView } from './source';
import { markdownMap } from './text/literal';
import type { ReviewStore } from './reviewstore';

const SVG_NS = 'http://www.w3.org/2000/svg';

/** The region owning each review box, for the shared document handlers below. */
const inputRegions = new WeakMap<HTMLElement, MarkdownReview>();
/** Regions whose popup is open, so one Escape closes them all. */
const openRegions = new Set<MarkdownReview>();

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

/** In-place review of one Markdown region: the annotation boxes, the two-box
 *  popup (editable original text + comment), and the compare view. The DOM and
 *  all mutable state live on the instance; `align()` maps the rendered text
 *  back to the literal, and `wire()` binds the interactions. */
export class MarkdownReview {
  node: HTMLElement;
  map: LiteralMap;
  store: ReviewStore;
  annotations: Annotation[] = [];
  view = 'rendered';
  selection: LiteralRange | null = null;
  editing: Annotation | null = null;
  session: ReviewSession | null = null;
  sourceView: SourceView;

  rendered: HTMLDivElement;
  popup: HTMLFormElement;
  list: HTMLDivElement;
  source: HTMLDivElement;
  sourceFill: HTMLPreElement;
  sourceInput: HTMLTextAreaElement;
  comment: HTMLLabelElement;
  commentInput: HTMLTextAreaElement;
  svg: SVGSVGElement;
  controls: HTMLDivElement;

  constructor(node: HTMLElement, raw: string, rawStart = 0, rawEnd = 0) {
    this.node = node;
    this.store = window.transcriptReviewStore!;
    const { text, map } = markdownMap(raw);
    this.map = new LiteralMap(text);
    this.annotations = this.store.addRegion(this, rawStart, rawEnd, text, map);
    // The popup holds the revision record list (existing annotations) or the
    // two-box editor (a new annotation): the original text is edited in place
    // (transparent textarea over the diff highlight) and the comment below.
    this.sourceFill = element('pre', 'tmd-diff-fill');
    this.sourceInput = element('textarea', 'tmd-diff-input',
      { rows: 1, spellcheck: false });
    inputRegions.set(this.sourceInput, this);
    this.source = element('div', 'tmd-md-source', { hidden: true },
      this.sourceFill, this.sourceInput);
    this.sourceView = new SourceView(this.sourceFill, this.sourceInput, () => this.session);
    this.list = element('div', 'tmd-rec-list', { hidden: true });
    this.commentInput = element('textarea', '', {
      placeholder: 'comment (Ctrl+Enter to submit) . . .', rows: 2,
    });
    this.comment = element('label', 'tmd-md-comment', { hidden: true },
      this.commentInput);
    this.popup = element('form', 'tmd-md-popup',
      { hidden: true, noValidate: true },
      this.list, this.source, this.comment);
    this.popup.addEventListener('submit', event => event.preventDefault());
    this.rendered = element('div', 'tmd-md-rendered');
    this.svg = svgElement('tmd-md-overlay');
    this.controls = element('div', 'tmd-md-controls');

    node.style.position = 'relative';
    node.replaceChildren(this.rendered, this.popup, this.svg, this.controls);
    node.dataset.tmdMdView = 'rendered';
  }

  get literal() {
    return this.map.literal;
  }

  /** Map every rendered text node to a literal offset, in document order. */
  align() {
    this.map.align(this.rendered);
  }

  clearTransient() {
    // Keep the per-annotation badges; drop only the floating trigger.
    this.controls.querySelectorAll('.tmd-md-trigger').forEach(node => node.remove());
  }

  showRendered() {
    this.view = 'rendered';
    openRegions.delete(this);
    this.node.dataset.tmdMdView = 'rendered';
    this.rendered.hidden = false;
    this.popup.hidden = true;
    this.selection = null;
    this.editing = null;
    this.session = null;
    this.controls.replaceChildren();
    this.svg.replaceChildren();
    // Only the outer annotations get a box and badge: an annotation whose range
    // a newer (possibly superseded) visible annotation covers has none.
    const visible = new Set(this.store.visible(this));
    const candidates: { annotation: Annotation; bands: Band[] }[] = [];
    this.annotations.filter(annotation => visible.has(annotation)).forEach(annotation => {
      const display = displayRange(this.literal, annotation);
      const range = this.map.literalToRange(display.start, display.end);
      const bands = bandsOf(this.node, range);
      if (!bands) return;
      candidates.push({ annotation, bands });
    });
    // Two annotations whose badges anchor on the same line cannot both show:
    // the badge sits on the first line's right edge, so the one with the larger
    // line range contains the other — keep its badge only; both boxes stay so
    // the highlight still covers every reviewed range.
    const keep = selectBadges(this.literal, candidates);
    for (const { annotation, bands } of candidates) {
      annotation.bands = bands;
      drawBands(
        this.svg, bands,
        annotation.locked ? 'tmd-md-box tmd-md-locked' : 'tmd-md-box');
      if (keep.has(annotation)) {
        addBadge(this.controls, annotation, bands, a => this.openAnnotation(a));
      }
    }
  }

  /** Open the revision record list for *annotation*: every source version and
   *  review in its window, oldest first, with the clicked review at the bottom. */
  openAnnotation(annotation: Annotation) {
    this.editing = annotation;
    this.view = 'list';
    openRegions.add(this);
    this.node.dataset.tmdMdView = 'source';
    this.popup.hidden = false;
    this.selection = { start: annotation.chosen.start, end: annotation.chosen.end };
    this.controls.replaceChildren();
    this.svg.replaceChildren();
    this.session = null;
    this.renderList();
    this.placePopup(
      this.anchorTopForRange(annotation.chosen.start, annotation.chosen.end)
    );
  }

  /** Turn a review's row into an inline editor (its raw becomes editable). */
  beginEdit(edit?: Annotation) {
    const annotation = edit || this.editing;
    if (!annotation || annotation.locked) return;
    this.editing = annotation;
    this.openSource(annotation.chosen.start, annotation.chosen.end,
      this.anchorTopForRange(annotation.chosen.start, annotation.chosen.end),
      'edit');
  }

  /** Draw the record list. While editing an existing review, that row's raw and
   *  comment are replaced by the persistent inline editor elements. */
  renderList() {
    this.view = 'list';
    this.list.hidden = false;
    this.source.hidden = true;
    this.comment.hidden = true;
    const history = this.editing ? this.store.history(this, this.editing) : null;
    const slots = renderRecords(this.list, history, {
      focus: this.editing,
      onOpen: other => this.openAnnotation(other),
      onEdit: other => this.beginEdit(other),
      onDelete: other => this.deleteAnnotation(other),
    });
    const editing = this.session && this.session.mode === 'edit' && this.session.annotation
      ? this.session.annotation as Annotation : null;
    if (editing) {
      const raw = slots.raws.get(editing);
      const body = slots.comments.get(editing);
      if (raw) raw.replaceChildren(this.source);
      if (body) body.replaceChildren(this.comment);
      this.source.hidden = false;
      this.comment.hidden = false;
    }
  }

  deleteAnnotation(annotation: Annotation) {
    this.store.remove(this, annotation);
    if (annotation === this.editing) { this.showRendered(); return; }
    this.renderList();
  }

  deleteEditing() {
    if (this.editing) this.deleteAnnotation(this.editing);
  }

  anchorTopForRange(start: number, end: number) {
    const range = this.map.literalToRange(start, end);
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
    this.node.dataset.tmdMdView = 'source';
    this.popup.hidden = false;
    this.selection = { start, end };
    this.controls.replaceChildren();
    this.svg.replaceChildren();
    this.list.hidden = true;
    // A prior list render may have detached the editor; re-home it so the
    // source box can be measured before it moves into the edited row.
    if (!this.source.isConnected) this.popup.appendChild(this.source);
    if (!this.comment.isConnected) this.popup.appendChild(this.comment);
    this.initSession(start, end, mode);
    if (this.session && this.session.mode === 'edit' && this.session.annotation) {
      // Editing an existing review: keep the record list, swapping the edited
      // row's raw/comment for the inline editor.
      this.renderList();
    } else {
      this.source.hidden = false;
      this.comment.hidden = false;
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
    const original = editing
      ? (typeof editing.original === 'string' ? editing.original : '')
      : this.literal.slice(line.start, line.end);
    const chosenLocal: LiteralRange = {
      start: chosen.start - line.start, end: chosen.end - line.start,
    };
    const committed = editing && typeof editing.comment === 'string'
      ? editing.comment : '';
    // The baseline is the whole literal range the box holds; a modification
    // replaces all of it, so the record's range must cover these lines rather
    // than follow a narrower re-selection made inside the box.
    const baseline = { start: line.start, end: line.start + original.length };
    this.session = new ReviewSession({
      annotation: editing,
      chosen,
      chosenLocal,
      lineStart: line.start,
      baseline,
      original,
      text: editing && typeof editing.edit === 'string'
        ? editing.edit : original,
      committed,
      mode: mode || 'edit',
    });
    this.sourceInput.value = this.session.text;
    this.commentInput.value = this.session.body;
    // Show the right boxes before measuring: the end markers need a laid-out
    // fill, otherwise they collapse to a zero-size point at the origin.
    this.modVisibility();
    this.sourceView.render();
    this.sourceView.autosize();
    // Pre-select the reviewed range while the text is unmodified.
    if (this.session.text === this.session.original
      && chosenLocal.start < chosenLocal.end
      && chosenLocal.end <= this.session.text.length) {
      this.sourceInput.setSelectionRange(chosenLocal.start, chosenLocal.end);
    }
    // A new annotation opens ready to comment on the selection. Focusing
    // happens after the popup is placed (see openSource) so it cannot scroll.
  }

  modVisibility() {
    const session = this.session;
    if (!session) return;
    // Editing (a new annotation, or an inline edit of an existing one): the
    // original box plus the comment. A locked review never reaches here.
    const locked = !!(session.annotation && session.annotation.locked);
    this.source.hidden = false;
    this.comment.hidden = false;
    this.commentInput.readOnly = locked;
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
    let chosen = this.sourceView.currentChosen();
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

  showTrigger(point: { x: number; y: number }, mapped: LiteralRange) {
    this.clearTransient();
    const origin = this.node.getBoundingClientRect();
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'tmd-md-trigger';
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
    this.sourceView.trackSelection();
  }

  /** Bind review/annotation interaction events. */
  wire() {
    this.node.addEventListener('mousemove', (event: MouseEvent) => {
      const origin = this.node.getBoundingClientRect();
      const x = event.clientX - origin.left;
      const y = event.clientY - origin.top;
      this.controls.querySelectorAll<HTMLButtonElement>('.tmd-md-badge').forEach(badge => {
        const bands = badge.tmdAnnotation?.bands;
        const overBox = !!bands && bands.some(band =>
          x >= band.l - 2 && x <= band.r + 2 &&
          y >= band.t - 2 && y <= band.b + 2);
        const overBadge = !badge.hidden && insideRect(badge, x, y, origin);
        if (overBox || overBadge) revealBadge(badge);
        else hideBadge(badge);
      });
    });
    this.node.addEventListener('mouseleave', () => {
      this.controls.querySelectorAll<HTMLButtonElement>('.tmd-md-badge')
        .forEach(badge => hideBadge(badge));
    });
    this.rendered.addEventListener('mousedown', () => {
      if (this.view !== 'rendered') this.dismissPopup();
      else this.clearTransient();
    });
    this.rendered.addEventListener('mouseup', event => {
      const mapped = this.map.selectionToLiteral(this.rendered, window.getSelection());
      if (mapped) this.showTrigger({ x: event.clientX, y: event.clientY }, mapped);
    });
    this.sourceView.wire();
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
