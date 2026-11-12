/** Review boxes and badges: screen geometry for a range and the badge that
 *  opens its revision list.  DOM-only, driven by explicit arguments. */

import type { Annotation, Range as LiteralRange } from './annotation';
import { fullLines } from './model/span';
import { mergeBands, ribbon, wavePath } from './render/overlay';
import type { Band } from './render/overlay';
import { diffInfo } from './text/diff';

const SVG_NS = 'http://www.w3.org/2000/svg';

/** How many whole lines an annotation covers (its character span breaks ties),
 *  used to keep the larger of two annotations whose badges share a line. */
export function chosenLines(literal: string, annotation: Annotation) {
  const text = literal.slice(annotation.chosen.start, annotation.chosen.end);
  let lines = 1;
  for (const char of text) if (char === '\n') lines += 1;
  return lines;
}

/** The range an annotation is drawn at. A modified annotation is shown only
 *  over the region that actually changed — its baseline range minus the common
 *  prefix and suffix with the edited text. */
export function displayRange(literal: string, annotation: Annotation): LiteralRange {
  if (!annotation.modified) return annotation.chosen;
  // The baseline (`annotation.original`) is the whole source line(s); the diff
  // runs are relative to that, so anchor them at the line start. This uses the
  // same alignment as the highlighting, so the box spans exactly the runs
  // drawn in the edit box.
  const line = fullLines(literal, annotation.chosen.start, annotation.chosen.end);
  const info = diffInfo(annotation.original || '', annotation.edit || '');
  const start = line.start + Math.max(info.start, 0);
  const end = line.start + info.end;
  if (end > start) return { start, end };
  // A pure insertion has no width in the baseline; mark the insertion point.
  const point = Math.min(Math.max(start, line.start), Math.max(line.end - 1, line.start));
  return { start: point, end: point + 1 };
}

/** The screen bands a range covers, in node-local coordinates, or null. */
export function bandsOf(node: HTMLElement, range: Range | null): Band[] | null {
  if (!range || typeof range.getClientRects !== 'function') return null;
  const origin = node.getBoundingClientRect();
  const bands = mergeBands(Array.from(range.getClientRects()), origin);
  return bands.length ? bands : null;
}

export function drawBands(svg: SVGSVGElement, bands: Band[], className: string) {
  const path = document.createElementNS(SVG_NS, 'path');
  path.setAttribute('d', ribbon(bands));
  path.setAttribute('class', className);
  svg.appendChild(path);
  const last = bands[bands.length - 1];
  const wave = document.createElementNS(SVG_NS, 'path');
  wave.setAttribute('d', wavePath(last.l, last.r, last.b));
  wave.setAttribute('class', 'tmd-md-wave');
  svg.appendChild(wave);
}

/** For every badge position, keep only the annotation with the largest line
 *  range (character span breaks a tie); its box covers the dropped ones. */
export function selectBadges(
  literal: string,
  candidates: { annotation: Annotation; bands: Band[] }[],
) {
  const groups = new Map<string, { annotation: Annotation; bands: Band[] }[]>();
  for (const item of candidates) {
    const anchor = item.bands[0];
    // Same position: the first band's top and right edge both match, so
    // whole-line annotations that share a first line land in one group.
    const key = `${Math.round(anchor.t * 2) / 2}:${Math.round(anchor.r * 2) / 2}`;
    const list = groups.get(key);
    if (list) list.push(item); else groups.set(key, [item]);
  }
  const keep = new Set<Annotation>();
  for (const list of groups.values()) {
    let best = list[0];
    for (const item of list) {
      const lines = chosenLines(literal, item.annotation);
      const bestLines = chosenLines(literal, best.annotation);
      const span = item.annotation.chosen.end - item.annotation.chosen.start;
      const bestSpan = best.annotation.chosen.end - best.annotation.chosen.start;
      if (lines > bestLines || (lines === bestLines && span > bestSpan)) best = item;
    }
    keep.add(best.annotation);
  }
  return keep;
}

/** Build a badge for *annotation*, anchored on the first band of its range. */
export function addBadge(
  controls: HTMLElement,
  annotation: Annotation,
  bands: Band[],
  open: (annotation: Annotation) => void,
) {
  const anchor = bands[0];
  const badge = document.createElement('button');
  badge.type = 'button';
  badge.className = annotation.locked
    ? 'tmd-md-badge tmd-md-locked' : 'tmd-md-badge';
  badge.textContent = '⋯';
  // Hovering shows what the annotation carries: its comment, else the added
  // text of the change runs, as found by the same alignment as the box.
  const revised = annotation.modified
    ? diffInfo(annotation.original || '', annotation.edit || '').revised : '';
  const hint = annotation.locked ? '[superseded: delete only] ' : '';
  badge.title = hint
    + (annotation.comment || revised || annotation.edit || 'Mark Up');
  badge.tmdAnnotation = annotation;
  badge.addEventListener('click', event => {
    event.stopPropagation();
    open(annotation);
  });
  // Entering the tab keeps it open, so the pointer can cross the gap between
  // the box and the tab without the tab vanishing under it.
  badge.addEventListener('mouseenter', () => revealBadge(badge));
  badge.addEventListener('mouseleave', () => hideBadge(badge));
  controls.appendChild(badge);
  const width = badge.offsetWidth;
  const height = badge.offsetHeight;
  badge.style.left = `${Math.max(0, anchor.r - width)}px`;
  badge.style.top = `${Math.max(0, anchor.t - height + 2)}px`;
  badge.hidden = true;
}

/** Show a badge and cancel any pending hide, so a pointer crossing the gap
 *  between the box and the tab has time to reach it. */
export function revealBadge(badge: HTMLButtonElement) {
  if (badge.tmdHideTimer !== undefined) {
    clearTimeout(badge.tmdHideTimer);
    badge.tmdHideTimer = undefined;
  }
  badge.hidden = false;
}

/** Hide a badge after a short grace period, unless the pointer comes back. */
export function hideBadge(badge: HTMLButtonElement) {
  if (badge.tmdHideTimer !== undefined) return;
  badge.tmdHideTimer = window.setTimeout(() => {
    badge.tmdHideTimer = undefined;
    badge.hidden = true;
  }, 220);
}
