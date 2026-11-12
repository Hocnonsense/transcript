/** The source box of the review editor: a transparent textarea over a
 *  highlight fill, with draggable range delimiters.  Owns the marker/drag
 *  state; the session itself is supplied by the region. */

import type { Range as LiteralRange } from './annotation';
import { markDel } from './render/marks';
import type { MarkerDrag, MarkerSet, ReviewSession } from './session';
import { diffText } from './text/diff';

export class SourceView {
  fill: HTMLPreElement;
  input: HTMLTextAreaElement;
  markers: MarkerSet | null = null;
  drag: MarkerDrag | null = null;
  private session: () => ReviewSession | null;

  constructor(
    fill: HTMLPreElement,
    input: HTMLTextAreaElement,
    session: () => ReviewSession | null,
  ) {
    this.fill = fill;
    this.input = input;
    this.session = session;
  }

  /** Renders the current box text under the transparent textarea. While the
   *  text equals the baseline the reviewed range is delimited by two inline
   *  anchors; once it is edited, only the added or removed runs are highlighted
   *  (an addition gets a background, a deletion a red bar). */
  render() {
    const session = this.session();
    if (!session) return;
    const text = this.input.value;
    this.fill.replaceChildren();
    this.markers = null;
    if (session.text === session.original) {
      this.appendDelimited(text, session.chosenLocal);
    } else {
      for (const slot of diffText(session.original, text)) {
        if (slot.orig === slot.mod) {
          this.fill.append(document.createTextNode(slot.mod));
        } else if (slot.mod === '') {
          this.fill.appendChild(markDel('|'));
        } else {
          if (slot.orig !== '') this.fill.appendChild(markDel('|'));
          const span = document.createElement('span');
          span.className = 'tmd-diff-ins';
          span.textContent = slot.mod;
          this.fill.appendChild(span);
        }
      }
    }
    this.fill.scrollTop = this.input.scrollTop;
    this.fill.scrollLeft = this.input.scrollLeft;
  }

  /** Append *text* with the reviewed range highlighted. The range carries a
   *  background; each end gets one zero-width chevron (start above, end below),
   *  so the fill still mirrors the textarea exactly and the two sides are told
   *  apart without a vertical bar. */
  private appendDelimited(text: string, chosenLocal: LiteralRange) {
    const start = chosenLocal ? Math.max(0, chosenLocal.start) : 0;
    const end = chosenLocal ? Math.min(text.length, chosenLocal.end) : 0;
    if (start >= end) {
      this.fill.append(document.createTextNode(text));
      return;
    }
    const left = markDel('v');
    const right = markDel('^');
    const range = document.createElement('span');
    range.className = 'tmd-diff-range';
    range.append(left, document.createTextNode(text.slice(start, end)), right);
    this.fill.append(
      document.createTextNode(text.slice(0, start)),
      range,
      document.createTextNode(text.slice(end)),
    );
    this.markers = { left, right };
  }

  /** The original box grows with its content instead of staying at three rows;
   *  past 40vh it is capped and the textarea scrolls. */
  autosize() {
    this.input.style.height = 'auto';
    const max = Math.round(window.innerHeight * 0.4);
    this.input.style.height = `${Math.min(this.input.scrollHeight, max)}px`;
  }

  /** Drop the range delimiters and highlight while keeping the text in place. */
  clearMarkers() {
    this.markers = null;
    this.fill.querySelectorAll('.tmd-diff-anchor').forEach(node => node.remove());
    this.fill.querySelectorAll('.tmd-diff-range').forEach(node => {
      node.replaceWith(...Array.from(node.childNodes));
    });
  }

  /** Re-place the delimiters after the selection changed inside the box. The
   *  fill is rebuilt, which only repaints the two inline anchors. */
  updateMarkers() {
    const session = this.session();
    if (!session) return;
    if (session.text !== session.original) { this.clearMarkers(); return; }
    this.render();
  }

  /** Per-character screen rectangles of the box text, for hit testing a drag
   *  position when the caret API does not resolve into the textarea. Every text
   *  node is walked in order; the inline marks hold no text, so the character
   *  indices stay aligned with the box value. */
  rectsOfText(): { x: number; y: number }[] | null {
    const rects: { x: number; y: number }[] = [];
    const walker = document.createTreeWalker(this.fill, NodeFilter.SHOW_TEXT);
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
  localCharAt(x: number, y: number, rects: { x: number; y: number }[] | null) {
    const input = this.input;
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
  markerHitSide(x: number, y: number): 'left' | 'right' | null {
    if (!this.markers) return null;
    const pad = 5;
    for (const side of ['left', 'right'] as const) {
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
  currentChosen(): LiteralRange | null {
    const session = this.session();
    if (!session || !session.chosen) return null;
    if (!session.chosenLocal) return session.chosen;
    const start = session.lineStart + session.chosenLocal.start;
    const end = session.lineStart + session.chosenLocal.end;
    if (end <= start) return session.chosen;
    return { start, end };
  }

  setText(text: string) {
    const session = this.session();
    if (!session) return;
    session.text = text;
    if (this.input.value !== text) this.input.value = text;
    this.render();
    this.autosize();
  }

  /** Follow the box's selection while it is the focused element. Called from
   *  the region's document-level `selectionchange` handler. */
  trackSelection() {
    const session = this.session();
    if (!session || this.drag) return;
    if (session.text !== session.original) return;
    const start = this.input.selectionStart;
    const end = this.input.selectionEnd;
    if (end <= start) { this.clearMarkers(); return; }
    if (session.chosenLocal
      && start === session.chosenLocal.start && end === session.chosenLocal.end) return;
    session.chosenLocal = { start, end };
    this.updateMarkers();
  }

  /** Bind the textarea's own listeners (typing, scroll, delimiter drag). The
   *  region binds the remaining session keys. */
  wire() {
    this.input.addEventListener('input', () => this.setText(this.input.value));
    this.input.addEventListener('scroll', () => {
      this.fill.scrollTop = this.input.scrollTop;
      this.fill.scrollLeft = this.input.scrollLeft;
    });
    this.input.addEventListener('pointerdown', event => this.pointerDown(event));
    this.input.addEventListener('pointermove', event => this.pointerMove(event));
    const endDrag = () => { this.drag = null; };
    this.input.addEventListener('pointerup', endDrag);
    this.input.addEventListener('pointercancel', endDrag);
  }

  private pointerDown(event: PointerEvent) {
    const session = this.session();
    if (!session || session.text !== session.original) return;
    const side = this.markerHitSide(event.clientX, event.clientY);
    if (!side) return;
    event.preventDefault();
    this.drag = { side, rects: null };
    try { this.input.setPointerCapture(event.pointerId); } catch (error) { /* synthetic */ }
  }

  private pointerMove(event: PointerEvent) {
    const session = this.session();
    if (this.drag) {
      if (!session || !session.chosenLocal
        || session.text !== session.original) return;
      if (!this.drag.rects) this.drag.rects = this.rectsOfText();
      const at = this.localCharAt(event.clientX, event.clientY, this.drag.rects);
      if (at === null) return;
      let start = session.chosenLocal.start;
      let end = session.chosenLocal.end;
      if (this.drag.side === 'left') start = Math.min(at, end - 1);
      else end = Math.max(at + 1, start + 1);
      if (start === session.chosenLocal.start && end === session.chosenLocal.end) return;
      session.chosenLocal = { start, end };
      this.input.setSelectionRange(start, end);
      this.updateMarkers();
      return;
    }
    const dragCursor = session && session.text === session.original
      ? this.markerHitSide(event.clientX, event.clientY) : null;
    this.input.style.cursor = dragCursor ? 'ew-resize' : '';
  }
}
