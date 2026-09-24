const SVG_NS = 'http://www.w3.org/2000/svg';

export function lineIndex(text, offset) {
  let line = 0;
  const max = Math.min(offset, text.length);
  for (let index = 0; index < max; index += 1) {
    if (text.charCodeAt(index) === 10) line += 1;  // text[index] === '\n'
  }
  return line;
}

function nonSpaceBefore(text, offset) {
  let count = 0;
  for (let index = 0; index < offset && index < text.length; index += 1) {
    if (!/\s/.test(text[index])) count += 1;
  }
  return count;
}

function skipNonSpace(text, count) {
  let seen = 0;
  let index = 0;
  while (index < text.length && seen < count) {
    if (!/\s/.test(text[index])) seen += 1;
    index += 1;
  }
  return index;
}

function literalToDomOffset(state, entry, offset) {
  let seen = 0;
  for (let index = entry.start; index < offset && index < entry.end; index += 1) {
    if (!/\s/.test(state.literal[index])) seen += 1;
  }
  // `entry.start` is the literal's first non-space character, which sits after
  // the node's own leading whitespace, so skip it before counting.
  const text = entry.node.nodeValue;
  let position = entry.lead + skipNonSpace(text.slice(entry.lead), seen);
  // When the literal offset sits on a word, skip the node's whitespace so the
  // range starts at the word rather than the preceding space.
  if (offset < state.literal.length && !/\s/.test(state.literal[offset])) {
    while (position < text.length && /\s/.test(text[position])) position += 1;
  }
  return position;
}

function domToLiteralOffset(state, node, offset) {
  const entry = state.entries.find(item => item.node === node);
  if (!entry) return null;
  const count = nonSpaceBefore(node.nodeValue, offset);
  let index = entry.start;
  let seen = 0;
  while (index < entry.end && seen < count) {
    if (!/\s/.test(state.literal[index])) seen += 1;
    index += 1;
  }
  // Symmetrically, a DOM offset on a word maps past the literal's whitespace.
  if (offset < node.nodeValue.length && !/\s/.test(node.nodeValue[offset])) {
    while (index < entry.end && /\s/.test(state.literal[index])) index += 1;
  }
  return index;
}

function boundaryText(container, offset, isEnd) {
  if (container.nodeType === Node.TEXT_NODE) return { node: container, offset };
  let child = container.childNodes[isEnd ? offset - 1 : offset];
  while (child && child.nodeType !== Node.TEXT_NODE) {
    child = isEnd ? child.lastChild : child.firstChild;
  }
  if (!child) return null;
  return { node: child, offset: isEnd ? child.nodeValue.length : 0 };
}

function trimRange(state, start, end) {
  // Selections should not carry the whitespace around the chosen words.
  while (start < end && /\s/.test(state.literal[start])) start += 1;
  while (end > start && /\s/.test(state.literal[end - 1])) end -= 1;
  return { start, end };
}

function literalToRange(state, start, end) {
  const first = state.entries.find(entry => entry.end > start);
  if (!first) return null;
  const last = [...state.entries].reverse().find(entry => entry.start < end);
  if (!last) return null;
  const range = document.createRange();
  range.setStart(first.node,
    Math.min(literalToDomOffset(state, first, start), first.node.nodeValue.length));
  range.setEnd(last.node,
    Math.min(literalToDomOffset(state, last, end), last.node.nodeValue.length));
  return range;
}

function mergeBands(rects, origin) {
  const bands = [];
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

/** Creates a path that outlines the given bands.
 *
 * One connected outline around stacked line bands,
 * so a wrapped range reads as a single box instead of one box per line.
*/
function ribbon(bands) {
  if (!bands.length) return '';
  const points = [];
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
function wavePath(left, right, y) {
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

function drawBox(state, range, className) {
  if (!range || typeof range.getClientRects !== 'function') return null;
  const origin = state.node.getBoundingClientRect();
  const bands = mergeBands(Array.from(range.getClientRects()), origin);
  if (!bands.length) return null;
  const path = document.createElementNS(SVG_NS, 'path');
  path.setAttribute('d', ribbon(bands));
  path.setAttribute('class', className);
  state.svg.appendChild(path);
  const last = bands[bands.length - 1];
  const wave = document.createElementNS(SVG_NS, 'path');
  wave.setAttribute('d', wavePath(last.l, last.r, last.b));
  wave.setAttribute('class', 'snd-md-wave');
  state.svg.appendChild(wave);
  return bands;
}

function literalLineStart(state, index) {
  let offset = 0;
  for (let i = 0; i < index; i += 1) offset += state.lines[i].length + 1;
  return offset;
}

function clearTransient(state) {
  // Keep the per-annotation badges; drop only the floating trigger and menu.
  state.controls.querySelectorAll('.snd-md-trigger, .snd-md-menu').forEach(node => node.remove());
}

function showRendered(state) {
  state.view = 'rendered';
  state.node.dataset.sndMdView = 'rendered';
  state.rendered.hidden = false;
  state.source.hidden = true;
  state.selection = null;
  state.editing = null;
  state.drag = null;
  state.controls.replaceChildren();
  state.svg.replaceChildren();
  state.annotations.forEach(annotation => {
    const range = literalToRange(state, annotation.chosen.start, annotation.chosen.end);
    if (!range) return;
    const bands = drawBox(state, range, 'snd-md-box');
    if (!bands) return;
    annotation.bands = bands;
    addBadge(state, annotation, bands);
  });
}

function addBadge(state, annotation, bands) {
  const right = Math.max(...bands.map(band => band.r));
  const top = Math.min(...bands.map(band => band.t));
  const badge = document.createElement('button');
  badge.type = 'button';
  badge.className = 'snd-md-badge';
  badge.textContent = '⋯';
  badge.title = 'Mark Up';
  badge.sndAnnotation = annotation;
  badge.addEventListener('click', event => {
    event.stopPropagation();
    openMenu(state, annotation, badge);
  });
  state.controls.appendChild(badge);
  const width = badge.offsetWidth;
  const height = badge.offsetHeight;
  badge.style.left = `${Math.max(0, right - width)}px`;
  badge.style.top = `${Math.max(0, top - height + 2)}px`;
  badge.hidden = true;
}

function insideRect(element, x, y, origin) {
  const rect = element.getBoundingClientRect();
  return x >= rect.left - origin.left
    && x <= rect.right - origin.left
    && y >= rect.top - origin.top
    && y <= rect.bottom - origin.top;
}

function openMenu(state, annotation, badge) {
  state.controls.querySelectorAll('.snd-md-menu').forEach(node => node.remove());
  const menu = document.createElement('div');
  menu.className = 'snd-md-menu';
  const edit = document.createElement('button');
  edit.type = 'button';
  edit.textContent = 'edit';
  edit.addEventListener('click', () => {
    menu.remove();
    state.editing = annotation;
    openSource(state, annotation.chosen.start, annotation.chosen.end,
      anchorTopForRange(state, annotation.chosen.start, annotation.chosen.end));
  });
  const remove = document.createElement('button');
  remove.type = 'button';
  remove.textContent = 'delete';
  remove.addEventListener('click', () => {
    const index = state.annotations.indexOf(annotation);
    if (index !== -1) state.annotations.splice(index, 1);
    showRendered(state);
  });
  menu.append(edit, remove);
  menu.style.left = badge.style.left;
  menu.style.top = `calc(${badge.style.top} + 1.4rem)`;
  state.controls.appendChild(menu);
}

function anchorTopForRange(state, start, end) {
  const range = literalToRange(state, start, end);
  if (!range || typeof range.getClientRects !== 'function') return 0;
  const rects = Array.from(range.getClientRects());
  if (!rects.length) return 0;
  const origin = state.node.getBoundingClientRect();
  return rects[0].top - origin.top;
}

function placeSource(state, anchorTop) {
  const origin = state.node.getBoundingClientRect();
  const anchor = Number.isFinite(anchorTop) ? anchorTop : 0;
  const height = state.source.offsetHeight;
  // Prefer above the anchor; drop below when there is no room in the viewport.
  const top = origin.top + anchor - height - 6 >= 0
    ? anchor - height - 6 : anchor + 6;
  state.source.style.top = `${top}px`;
}

function preselectSource(state, start, end) {
  const range = sourceRange(state, start, end);
  if (!range) return;
  const selection = window.getSelection();
  selection.removeAllRanges();
  selection.addRange(range);
}

function openSource(state, start, end, anchorTop) {
  const whole = start === null || end === null;
  const firstIndex = whole ? 0 : lineIndex(state.literal, start);
  const lastIndex = whole
    ? state.lines.length - 1
    : lineIndex(state.literal, Math.max(start, end - 1));
  state.view = 'source';
  state.node.dataset.sndMdView = 'source';
  state.source.hidden = false;
  Array.from(state.source.children as HTMLCollectionOf<HTMLElement>).forEach((line, index) => {
    line.hidden = index < firstIndex || index > lastIndex;
  });
  state.selection = whole ? null : { start, end };
  state.controls.replaceChildren();
  state.svg.replaceChildren();
  placeSource(state, anchorTop);
  if (whole) {
    window.getSelection().removeAllRanges();
  } else {
    preselectSource(state, start, end);
  }
  drawSourceSelection(state);
}

function sourceRange(state, start, end) {
  const firstIndex = lineIndex(state.literal, start);
  const lastIndex = lineIndex(state.literal, Math.max(start, end - 1));
  const first = state.source.children[firstIndex];
  const last = state.source.children[lastIndex];
  if (!first || !last || !first.firstChild || !last.firstChild) return null;
  const range = document.createRange();
  range.setStart(first.firstChild, Math.min(
    start - literalLineStart(state, firstIndex), first.firstChild.length));
  range.setEnd(last.firstChild, Math.min(
    end - literalLineStart(state, lastIndex), last.firstChild.length));
  return range;
}

/**  While the user is dragging a fresh selection, keep only the native
 *   selection highlight; the annotation box/handles return on mouseup.
 */
function hideSourceStyle(state) {
  state.svg.replaceChildren();
  state.controls.replaceChildren();
}

function drawSourceSelection(state) {
  if (state.view !== 'source' || state.selecting) return;
  state.svg.replaceChildren();
  state.controls.replaceChildren();
  const selection = window.getSelection();
  if (!selection || selection.isCollapsed || !selection.rangeCount) return;
  const range = selection.getRangeAt(0);
  if (!state.source.contains(range.startContainer)
    || !state.source.contains(range.endContainer)) return;
  const bands = drawBox(state, range, 'snd-md-box snd-md-box-active');
  if (bands) showConfirm(state, bands);
  showHandles(state, range);
}

function showHandles(state, range) {
  const origin = state.node.getBoundingClientRect();
  const rects = Array.from<DOMRect>(range.getClientRects()).filter(
    rect => rect.width || rect.height);
  if (!rects.length) return;
  const first = rects[0];
  const last = rects[rects.length - 1];
  addHandle(state, 'start', first.left - origin.left,
    (first.top + first.bottom) / 2 - origin.top);
  addHandle(state, 'end', last.right - origin.left,
    (last.top + last.bottom) / 2 - origin.top);
}

function addHandle(state, side, x, y) {
  const handle = document.createElement('div');
  handle.className = 'snd-md-handle';
  handle.dataset.sndHandle = side;
  handle.style.left = `${x}px`;
  handle.style.top = `${y}px`;
  const line = document.createElement('span');
  line.className = 'snd-md-handle-line';
  const top = document.createElement('span');
  top.className = 'snd-md-handle-tri snd-md-handle-top';
  const bottom = document.createElement('span');
  bottom.className = 'snd-md-handle-tri snd-md-handle-bottom';
  handle.append(line, top, bottom);
  handle.addEventListener('mousedown', event => {
    event.preventDefault();
    event.stopPropagation();
    startDrag(state, side);
  });
  state.controls.appendChild(handle);
}

function startDrag(state, side) {
  const current = sourceSelectionLiteral(state, window.getSelection());
  if (!current) return;
  state.drag = { side, start: current.start, end: current.end };
  const move = event => {
    if (!state.drag) return;
    const point = caretPoint(state, event.clientX, event.clientY);
    if (!point) return;
    const literal = sourcePointToLiteral(state, point.node, point.offset, side === 'end');
    if (literal === null) return;
    if (side === 'start') state.drag.start = Math.min(literal, state.drag.end - 1);
    else state.drag.end = Math.max(literal, state.drag.start + 1);
    preselectSource(state, state.drag.start, state.drag.end);
    drawSourceSelection(state);
  };
  const up = () => {
    document.removeEventListener('mousemove', move);
    document.removeEventListener('mouseup', up);
    if (!state.drag) return;
    const range = trimRange(state, state.drag.start, state.drag.end);
    state.drag = null;
    preselectSource(state, range.start, range.end);
    drawSourceSelection(state);
  };
  document.addEventListener('mousemove', move);
  document.addEventListener('mouseup', up);
}

function caretPoint(state, x, y) {
  const doc = document;
  let range = null;
  if (doc.caretPositionFromPoint) {
    const position = doc.caretPositionFromPoint(x, y);
    if (!position) return null;
    range = { node: position.offsetNode, offset: position.offset };
  } else if (doc.caretRangeFromPoint) {
    // Compatibility fallback for older browsers without the standard API.
    const range_ = doc.caretRangeFromPoint(x, y);
    if (!range_) return null;
    range = { node: range_.startContainer, offset: range_.startOffset };
  }
  if (!range || !state.source.contains(range.node)) return null;
  return range;
}

function showConfirm(state, bands) {
  const last = bands[bands.length - 1];
  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'snd-md-confirm';
  button.textContent = '✓';
  button.title = 'confirm';
  button.addEventListener('mousedown', event => event.preventDefault());
  button.addEventListener('click', () => confirmAnnotation(state));
  button.style.left = `${last.r + 2}px`;
  button.style.top = `${last.t - 12}px`;
  state.controls.appendChild(button);
}

function confirmAnnotation(state) {
  const selected = sourceSelectionLiteral(state, window.getSelection());
  if (!selected) return;
  const chosen = trimRange(state, selected.start, selected.end);
  if (chosen.end <= chosen.start) return;
  if (state.editing) {
    state.editing.chosen = chosen;
  } else {
    state.annotations.push({ selection: state.selection, chosen });
  }
  window.getSelection().removeAllRanges();
  showRendered(state);
}

function sourceSelectionLiteral(state, selection) {
  if (!selection || selection.isCollapsed || !selection.rangeCount) return null;
  const range = selection.getRangeAt(0);
  if (!state.source.contains(range.startContainer)
    || !state.source.contains(range.endContainer)) return null;
  const start = sourcePointToLiteral(
    state, range.startContainer, range.startOffset, false);
  const end = sourcePointToLiteral(
    state, range.endContainer, range.endOffset, true);
  if (start === null || end === null || end <= start) return null;
  return { start, end };
}

function sourcePointToLiteral(state, container, offset, isEnd) {
  let node = container;
  let position = offset;
  if (node.nodeType !== Node.TEXT_NODE) {
    const point = boundaryText(node, position, isEnd);
    if (!point) return null;
    node = point.node;
    position = point.offset;
  }
  const line = node.parentNode && node.parentNode.closest
    ? node.parentNode.closest('.snd-line') : null;
  if (!line) return null;
  const index = Number(line.dataset.line) - state.mdLine;
  return literalLineStart(state, index) + position;
}

function selectionToLiteral(state, selection) {
  if (!selection || selection.isCollapsed || !selection.rangeCount) return null;
  const range = selection.getRangeAt(0);
  if (!state.rendered.contains(range.startContainer)
    || !state.rendered.contains(range.endContainer)) return null;
  const startPoint = boundaryText(range.startContainer, range.startOffset, false);
  const endPoint = boundaryText(range.endContainer, range.endOffset, true);
  if (!startPoint || !endPoint) return null;
  const start = domToLiteralOffset(state, startPoint.node, startPoint.offset);
  const end = domToLiteralOffset(state, endPoint.node, endPoint.offset);
  if (start === null || end === null || end <= start) return null;
  const trimmed = trimRange(state, start, end);
  return trimmed.end > trimmed.start ? trimmed : null;
}

function showTrigger(state, point, mapped) {
  clearTransient(state);
  const origin = state.node.getBoundingClientRect();
  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'snd-md-trigger';
  button.textContent = mapped ? 'Mark Up' : 'Show Source';
  button.addEventListener('mousedown', event => event.preventDefault());
  button.addEventListener('click', () => {
    if (mapped) {
      openSource(state, mapped.start, mapped.end,
        anchorTopForRange(state, mapped.start, mapped.end));
    } else {
      openSource(state, null, null, point.y - origin.top);
    }
  });
  state.controls.appendChild(button);
  const width = button.offsetWidth;
  const height = button.offsetHeight;
  const max = state.node.clientWidth;
  const x = point.x - origin.left;
  const y = point.y - origin.top;
  let left = x + 10;
  if (left + width > max) left = x - width - 10;
  const top = mapped ? y - height - 6 : y;
  button.style.left = `${Math.max(0, left)}px`;
  button.style.top = `${Math.max(0, top)}px`;
}

export function wireMarkdown(state) {
  /** Bind review/annotation interaction events. */
  state.node.addEventListener('mousemove', event => {
    const origin = state.node.getBoundingClientRect();
    const x = event.clientX - origin.left;
    const y = event.clientY - origin.top;
    state.controls.querySelectorAll('.snd-md-badge').forEach(badge => {
      const bands = badge.sndAnnotation && badge.sndAnnotation.bands;
      const overBox = !!bands && bands.some(band =>
        x >= band.l - 2 && x <= band.r + 2 &&
        y >= band.t - 2 && y <= band.b + 2);
      const overBadge = !badge.hidden && insideRect(badge, x, y, origin);
      badge.hidden = !(overBox || overBadge);
    });
  });
  state.node.addEventListener('mouseleave', () => {
    state.controls.querySelectorAll('.snd-md-badge').forEach(badge => { badge.hidden = true; });
  });
  state.rendered.addEventListener('mousedown', () => {
    if (state.view === 'source') showRendered(state);
    else clearTransient(state);
  });
  state.rendered.addEventListener('click', event => {
    if (event.detail >= 3) {
      showTrigger(state, { x: event.clientX, y: event.clientY }, null);
    }
  });
  state.rendered.addEventListener('mouseup', event => {
    const mapped = selectionToLiteral(state, window.getSelection());
    if (mapped) showTrigger(state, { x: event.clientX, y: event.clientY }, mapped);
  });
  state.source.addEventListener('mousedown', event => {
    if (event.target.closest && event.target.closest('.snd-md-handle, .snd-md-confirm')) {
      return;
    }
    state.selecting = true;
    hideSourceStyle(state);
  });
  state.source.addEventListener('mouseup', () => {
    state.selecting = false;
    drawSourceSelection(state);
  });
  state.source.addEventListener('keyup', event => {
    if (event.key === 'Shift') drawSourceSelection(state);
  });
  document.addEventListener('selectionchange', () => {
    if (state.view === 'source' && !state.selecting) drawSourceSelection(state);
  });
  document.addEventListener('mouseup', () => {
    // A drag that ends outside the source pre still has to restore the style.
    if (state.view === 'source' && state.selecting) {
      state.selecting = false;
      drawSourceSelection(state);
    }
  });
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && state.view === 'source') showRendered(state);
  });
}
