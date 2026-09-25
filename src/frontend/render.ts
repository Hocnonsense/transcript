import { markdownMap } from './literal';
import { MarkdownReview } from './review';
import { ReviewStore } from './reviewstore';
import { loadResources } from './resources';

/**
 * Decode `data-snd-string-lines` (e.g. "1,4-5") into a set of 1-based lines.
 */
function lineRanges(text) {
  const result: Set<number> = new Set();
  for (const part of (text || '').split(',')) {
    if (!part) continue;
    const [first, last = first] = part.split('-').map(Number);
    for (let line = first; line <= last; line += 1) result.add(line);
  }
  return result;
}

function sourceSpan(node) {
  // `data-snd-span` is the source range `start,end` the server recorded.
  const [start, end] = node.dataset.sndSpan.split(',');
  return [Number(start), Number(end)];
}

function slug(text) {
  // Mirror `html/_navigate.py::_slug`: keep unicode letters/digits, collapse
  // whitespace and hyphens, and trim. `toLowerCase` (not the locale-aware
  // variant) matches Python's `str.lower`.
  return text.toLowerCase()
    .replace(/[^\p{L}\p{N}_\- ]+/gu, '')
    .replace(/[\s\-]+/g, '-')
    .replace(/^-|-$/g, '');
}

function outline(document: Document) {
  // Rebuild the document outline from the rendered DOM. Slugs, dedup order,
  // and label levels mirror `html/_navigate.py` so the runtime outline matches
  // the server-rendered fallback: labels reserve their ids first, duplicate
  // slugs are numbered from `-1`, and a label takes the level of the heading
  // it follows (capped at 6).
  const main = document.querySelector('main');
  if (!main) return;
  const labels = Array.from(main.querySelectorAll('figure.snakedone-label[id]'));
  const seen = new Map(labels.map(label => [label.id, 0]));
  const entries = [];
  let level = 0;
  main.querySelectorAll('h1,h2,h3,h4,h5,h6,figure.snakedone-label[id]')
    .forEach(node => {
      if (node.matches('figure.snakedone-label')) {
        const caption = node.querySelector(':scope > figcaption')?.textContent?.trim();
        entries.push({
          type: 'labels', level: Math.min(level + 1, 6),
          text: caption || node.id, id: node.id
        });
        return;
      }
      level = Number(node.tagName.slice(1));
      const text = node.textContent.trim();
      let id = node.id || slug(text) || `section-${entries.length}`;
      if (seen.has(id)) {
        const base = id;
        let count = seen.get(base);
        do { count += 1; id = `${base}-${count}`; } while (seen.has(id));
        seen.set(base, count);
      }
      seen.set(id, 0);
      node.id = id;
      entries.push({ type: 'contents', level, text, id });
    });
  const reviewStore = window.snakedoneReviewStore;
  if (reviewStore) {
    let index = 0;
    for (const record of reviewStore.records) {
      if (record.type !== 'review') continue;
      entries.push({
        type: 'reviews', level: 0,
        text: record.comment || record.edit || 'Review',
        id: `snd-review-${index}`,
      });
      index += 1;
    }
  }
  const page = main.parentElement;
  page.querySelector(':scope > .navigate')?.remove();
  if (!entries.length) {
    page.className = 'page';
    return;
  }
  const types = ['contents', 'labels', 'reviews'].filter(type =>
    entries.some(entry => entry.type === type));
  const shown = types[0];
  const nav = document.createElement('nav');
  nav.className = 'navigate';
  nav.setAttribute('aria-label', 'Document outline');
  nav.dataset.collapsed = 'false';
  const tabs = document.createElement('div');
  tabs.className = 'navigate-tabs';
  const titles = { contents: 'Contents', labels: 'Labels', reviews: 'Reviews' };
  for (const type of types) {
    const tab = document.createElement('div');
    tab.className = 'navigate-tab';
    tab.dataset.sndType = type;
    tab.dataset.active = String(type === shown);
    tab.innerHTML =
      `<button class="navigate-tab-body" type="button">${titles[type]}</button>` +
      `<button class="navigate-tab-toggle" type="button" aria-pressed="${type === shown}" ` +
      `aria-label="Add or remove ${titles[type]}"><span aria-hidden="true">◉</span></button>`;
    tabs.appendChild(tab);
  }
  const list = document.createElement('ol');
  list.className = 'navigate-list';
  list.dataset.sndShow = shown;
  const css = {
    contents: entry => `toc-heading toc-l${entry.level}`,
    labels: () => 'toc-label',
    reviews: () => 'toc-review',
  };
  for (const entry of entries) {
    const item = document.createElement('li');
    item.className = css[entry.type](entry);
    item.dataset.sndType = entry.type;
    item.hidden = entry.type !== shown;
    const link = document.createElement('a');
    link.href = `#${entry.id}`;
    link.textContent = entry.text;
    item.appendChild(link);
    list.appendChild(item);
  }
  nav.append(tabs, list);
  page.className = 'page page--navigate';
  page.insertBefore(nav, main);
  window.snakedoneInitNavigate?.();
}

(() => {
  /*
   * Render the parts of the page that are derived from the embedded source:
   * Markdown prose, statement code, and the surrounding script regions. The
   * server only emits placeholders carrying character offsets into the island
   * (`#snakedone-source`), so nothing here is a second copy of the source.
   * Renderer libraries are loaded once and cached (see `download`).
   */
  const sourceNode = document.getElementById('snakedone-source');  // _island.source_island
  const configNode = document.getElementById('snakedone-renderers');  // _resources._renderer_config
  if (!sourceNode || !configNode) return;

  let source, config;
  try {
    source = JSON.parse(sourceNode.textContent);
    config = JSON.parse(configNode.textContent);
    if (typeof source !== 'string' || !Array.isArray(config.resources)) return;
  } catch (error) { return; }

  // The parsed review records and the body hash.
  // The archive itself is still the source island above;
  // this only spares the runtime from parsing Python,
  // and lets `Export .snd` rewrite the block.
  window.snakedoneReviewStore = ((reviewNode) => {
    let reviewIsland = { records: [], hash: '' };
    if (reviewNode) {
      try {
        const parsed = JSON.parse(reviewNode.textContent);
        if (parsed && Array.isArray(parsed.records)) reviewIsland = parsed;
      } catch (error) { /* treat as no records */ }
    }
    return new ReviewStore(source, reviewIsland.records, reviewIsland.hash)
  })(document.getElementById('snakedone-reviews'));

  /** Rebuild one physical statement from the island. Shared indentation is
   * stripped before highlighting, except on continuation lines of a multiline
   * string, which keep their indentation and drop the `>>>` prompt. The
   * server precomputes which lines those are (`data-snd-string-lines`). */
  function codeLines(node) {
    const [start, end] = sourceSpan(node);
    const raw = source.slice(start, end);
    const lines = raw.split('\n');
    const indent = (lines.find(line => line.trim()) || '').match(/^[ \t]*/)[0];
    const interior = lineRanges(node.dataset.sndStringLines);
    return lines.map((line, index) => ({
      interior: interior.has(index + 1),
      text: interior.has(index + 1) ? line : line.startsWith(indent)
        ? line.slice(indent.length) : line
    }));
  }

  function renderCode(node) {
    const lines = codeLines(node);
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

  /** Semicolons between adjacent document expressions are only separators,
   *  so a region that holds nothing else is dropped instead of showing an empty toggle. */
  function scriptSource(node) {
    const [start, end] = sourceSpan(node);
    return source.slice(start, end).replace(/^[\r\n]+|[\r\n]+$/g, '');
  }

  function renderScript(node) {
    const code = scriptSource(node);
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

  /** Open online links in a new tab without leaking the referrer */
  function externalLinks(root) {
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

  /** A markdown region is either a docstring or a `markdown()` output;
   *  both are sliced from the island, decoded to the exact string, and rendered here.
   *
   * - builds the popup DOM,
   * - maps the rendered text to the literal,
   * - binds its own interactions.
   * */
  function initMarkdownRegion(node, markdown) {
    const [start, end] = sourceSpan(node)
    const raw = source.slice(start, end);
    const region = new MarkdownReview(node, raw, start, end);
    region.rendered.innerHTML = markdown.render(region.literal);
    externalLinks(region.rendered);
    region.align();
    region.wire();
    region.showRendered();
  }

  function showError(error) {
    const message = document.createElement('div');
    message.className = 'snd-render-error';
    message.setAttribute('role', 'alert');
    message.textContent = `Could not load browser renderers: ${error.message}`;
    document.querySelector('main')?.prepend(message);
  }

  async function render() {
    // Load the libraries first, then fill the placeholders. The outline runs
    // last so it sees every heading the Markdown pass produced.
    try {
      await loadResources(config.resources, config.cache);

      const markdown = window.markdownit('commonmark', { html: false }).enable('table');
      document.querySelectorAll(
        '.doc-md[data-snd-span], ' +
        '.snakedone-report[data-snd-renderer="markdown"][data-snd-span]'
      ).forEach(node => initMarkdownRegion(node, markdown));

      document.querySelectorAll('.doc-code[data-snd-span]').forEach(renderCode);
      document.querySelectorAll('.script-block[data-snd-span]').forEach(renderScript);
      outline(document);
      document.documentElement.dataset.sndRendered = 'true';
      document.dispatchEvent(new CustomEvent('snakedone-rendered'));
    } catch (error) {
      showError(error instanceof Error ? error : new Error(String(error)));
    }
  }
  render();
})();
