/** Map rendered Markdown text nodes to offsets in the decoded literal, and
 *  back, so selections and annotations translate both ways.  Owns the
 *  per-region alignment; no store or review state. */

import type { Range as LiteralRange } from './annotation';

/** One rendered text node and the range of the decoded literal it came from. */
export interface LiteralEntry {
  node: Text;
  start: number;
  end: number;
  /** The node's leading whitespace, which lies before the literal text. */
  lead: number;
}

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
  if (container.nodeType === Node.TEXT_NODE) return { node: container as Text, offset };
  let child = container.childNodes[isEnd ? offset - 1 : offset];
  while (child && child.nodeType !== Node.TEXT_NODE) {
    child = isEnd ? child.lastChild : child.firstChild;
  }
  if (!child) return null;
  return { node: child as Text, offset: isEnd ? child.nodeValue.length : 0 };
}

/** The rendered-DOM ↔ decoded-literal mapping for one Markdown region. */
export class LiteralMap {
  literal: string;
  entries: LiteralEntry[] = [];

  constructor(literal: string) {
    this.literal = literal;
  }

  /** Map every rendered text node to a literal offset, in document order. */
  align(root: Node) {
    const entries: LiteralEntry[] = [];
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    let cursor = 0;
    let node: Node | null;
    while ((node = walker.nextNode())) {
      const text = node.nodeValue;
      if (!text || !/\S/.test(text)) continue;
      const found = findInSource(this.literal, text, cursor);
      if (!found) continue;
      const lead = (text.match(/^\s*/) || [''])[0].length;
      entries.push({ node: node as Text, start: found.start, end: found.end, lead });
      cursor = found.end;
    }
    this.entries = entries;
  }

  literalToDomOffset(entry: LiteralEntry, offset: number) {
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

  domToLiteralOffset(node: Text, offset: number) {
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

  trimRange(start: number, end: number): LiteralRange {
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

  selectionToLiteral(rendered: Node, selection: Selection | null): LiteralRange | null {
    if (!selection || selection.isCollapsed || !selection.rangeCount) return null;
    const range = selection.getRangeAt(0);
    if (!rendered.contains(range.startContainer)
      || !rendered.contains(range.endContainer)) return null;
    const startPoint = boundaryText(range.startContainer, range.startOffset, false);
    const endPoint = boundaryText(range.endContainer, range.endOffset, true);
    if (!startPoint || !endPoint) return null;
    const start = this.domToLiteralOffset(startPoint.node, startPoint.offset);
    const end = this.domToLiteralOffset(endPoint.node, endPoint.offset);
    if (start === null || end === null || end <= start) return null;
    const trimmed = this.trimRange(start, end);
    return trimmed.end > trimmed.start ? trimmed : null;
  }
}
