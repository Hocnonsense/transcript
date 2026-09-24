import { markdownLiteral } from './literal';
import { lineIndex, wireMarkdown } from './review';
import { loadResources } from './resources';

function lineRanges(text) {
  // Decode `data-snd-string-lines` (e.g. "1,4-5") into a set of 1-based lines.
  const result = new Set();
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
  const page = main.parentElement;
  page.querySelector(':scope > .navigate')?.remove();
  if (!entries.length) {
    page.className = 'page';
    return;
  }
  const types = ['contents', 'labels'].filter(type =>
    entries.some(entry => entry.type === type));
  const shown = types[0];
  const nav = document.createElement('nav');
  nav.className = 'navigate';
  nav.setAttribute('aria-label', 'Document outline');
  nav.dataset.collapsed = 'false';
  const tabs = document.createElement('div');
  tabs.className = 'navigate-tabs';
  const titles = { contents: 'Contents', labels: 'Labels' };
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
  for (const entry of entries) {
    const item = document.createElement('li');
    item.className = entry.type === 'contents'
      ? `toc-heading toc-l${entry.level}` : 'toc-label';
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

  /** Map every rendered text node to a literal offset, in document order,
   *  so selections and annotations can be translated both ways. */
  const alignMarkdown = (() => {
    function escapeRegExp(text) {
      return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    }
    /** Search given text in the source markdown text, starting from the specified offset.
     *
     * tolerating collapsed whitespace (markdown joins soft line breaks with a space).
    */
    function findInSource(source, text, from) {
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

    return (state) => {
      const entries = [];
      const walker = document.createTreeWalker(state.rendered, NodeFilter.SHOW_TEXT);
      let cursor = 0;
      let node;
      while ((node = walker.nextNode())) {
        const text = node.nodeValue;
        if (!text || !/\S/.test(text)) continue;
        const found = findInSource(state.literal, text, cursor);
        if (!found) continue;
        const lead = (text.match(/^\s*/) || [''])[0].length;
        entries.push({ node, start: found.start, end: found.end, lead });
        cursor = found.end;
      }
      state.entries = entries;
    }
  })()

  function initMarkdownRegion(node, markdown) {
    // A markdown region is either a docstring or a `markdown()` output; both are
    // sliced from the island, decoded to the exact string, and rendered here.
    const [start, end] = sourceSpan(node)
    const literal = markdownLiteral(source.slice(start, end));
    const state = {
      node,
      mdStart: start,
      mdEnd: end,
      literal,
      lines: literal.split('\n'),
      mdLine: lineIndex(source, start) + 1,
      entries: [],
      annotations: [],
      view: 'rendered',
      selection: null,
      editing: null,
      drag: null,
      selecting: false,
      rendered: document.createElement('div'),
      source: document.createElement('pre'),
      svg: document.createElementNS('http://www.w3.org/2000/svg', 'svg'),
      controls: document.createElement('div'),
    };
    state.rendered.className = 'snd-md-rendered';
    state.rendered.innerHTML = markdown.render(literal);
    externalLinks(state.rendered);

    state.source.className = 'snd-md-source';
    state.source.hidden = true;
    state.lines.forEach((text, index) => {
      const line = document.createElement('span');
      line.className = 'snd-line';
      line.dataset.line = String(state.mdLine + index);
      line.textContent = text;
      state.source.appendChild(line);
    });

    state.svg.setAttribute('class', 'snd-md-overlay');
    state.controls.className = 'snd-md-controls';
    node.style.position = 'relative';
    node.replaceChildren(state.rendered, state.source, state.svg, state.controls);
    node.dataset.sndMdView = 'rendered';
    node.sndMdState = state;
    alignMarkdown(state);
    wireMarkdown(state);
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
