/** Render the source-derived parts of the page from the embedded archive:
 *  statement code, script regions, external-link hardening, and Markdown
 *  regions (which delegate to ``MarkdownReview``).  The server emits only
 *  placeholders carrying character offsets into the source island. */

import { MarkdownReview } from '../review/review';

/** Decode `data-tmd-string-lines` (e.g. "1,4-5") into a set of 1-based lines. */
export function lineRanges(text: string) {
  const result: Set<number> = new Set();
  for (const part of (text || '').split(',')) {
    if (!part) continue;
    const [first, last = first] = part.split('-').map(Number);
    for (let line = first; line <= last; line += 1) result.add(line);
  }
  return result;
}

/** `data-tmd-span` is the source range `start,end` the server recorded. */
export function sourceSpan(node): [number, number] {
  const [start, end] = node.dataset.tmdSpan.split(',');
  return [Number(start), Number(end)];
}

/** Rebuild one physical statement from the island. Shared indentation is
 *  stripped before highlighting, except on continuation lines of a multiline
 *  string, which keep their indentation and drop the `>>>` prompt. The server
 *  precomputes which lines those are (`data-tmd-string-lines`). */
function codeLines(node, source: string) {
  const [start, end] = sourceSpan(node);
  const raw = source.slice(start, end);
  const lines = raw.split('\n');
  const indent = (lines.find(line => line.trim()) || '').match(/^[ \t]*/)[0];
  const interior = lineRanges(node.dataset.tmdStringLines);
  return lines.map((line, index) => ({
    interior: interior.has(index + 1),
    text: interior.has(index + 1) ? line : line.startsWith(indent)
      ? line.slice(indent.length) : line
  }));
}

export function renderCode(node, source: string) {
  const lines = codeLines(node, source);
  node.replaceChildren(...lines.map(lineData => {
    const line = document.createElement('span');
    line.className = 'doc-line' + (lineData.interior ? ' multiline-string' : '');
    if (lineData.interior) {
      // Interior lines are string content, but highlight.js cannot see the
      // opening delimiter on an earlier line, so mark them as strings here.
      const string = document.createElement('span');
      string.className = 'hljs-string';
      string.textContent = lineData.text;
      line.appendChild(string);
    } else {
      line.innerHTML = window.hljs.highlight(
        lineData.text, { language: 'python' }
      ).value;
    }
    return line;
  }));
}

/** Semicolons between adjacent document expressions are only separators, so a
 *  region that holds nothing else is dropped instead of showing an empty
 *  toggle. */
function scriptSource(node, source: string) {
  const [start, end] = sourceSpan(node);
  return source.slice(start, end).replace(/^[\r\n]+|[\r\n]+$/g, '');
}

export function renderScript(node, source: string) {
  const code = scriptSource(node, source);
  if (!code.replace(/[ \t\r\n\f;]/g, '')) {
    node.remove();
    return;
  }
  const summary = document.createElement('summary');
  summary.className = 'script-toggle';
  summary.title = 'Show or hide script';
  summary.setAttribute('aria-label', 'Toggle script block');
  summary.innerHTML = '<span aria-hidden="true">&lt;/&gt;</span>';
  const pre = document.createElement('pre');
  pre.className = 'script-code';
  const child = document.createElement('code');
  child.className = 'language-python';
  child.innerHTML = window.hljs.highlight(code, { language: 'python' }).value;
  pre.appendChild(child);
  node.replaceChildren(summary, pre);
}

/** Open online links in a new tab without leaking the referrer. */
export function externalLinks(root) {
  root.querySelectorAll('a[href]').forEach(link => {
    try {
      const url = new URL(link.getAttribute('href'), document.baseURI);
      if (url.protocol === 'http:' || url.protocol === 'https:') {
        link.target = '_blank';
        link.rel = 'noopener noreferrer';
      }
    } catch (error) { /* markdown-it already sanitized the attribute */ }
  });
}

/** A markdown region is either a docstring or a `markdown()` output; both are
 *  sliced from the island, decoded to the exact string, and rendered here.
 *  Builds the popup DOM, maps rendered text to the literal, binds its own
 *  interactions. */
export function initMarkdownRegion(node, markdown, source: string) {
  const [start, end] = sourceSpan(node);
  const raw = source.slice(start, end);
  const region = new MarkdownReview(node as HTMLElement, raw, start, end);
  region.rendered.innerHTML = markdown.render(region.literal);
  externalLinks(region.rendered);
  region.align();
  region.wire();
  return region;
}
