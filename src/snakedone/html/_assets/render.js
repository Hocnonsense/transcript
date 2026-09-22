(function () {
  /*
   * Render the parts of the page that are derived from the embedded source:
   * Markdown prose, statement code, and the surrounding script regions. The
   * server only emits placeholders carrying character offsets into the island
   * (`#snakedone-source`), so nothing here is a second copy of the source.
   * Renderer libraries are loaded once and cached (see `download`).
   */
  const sourceNode = document.getElementById('snakedone-source');
  const configNode = document.getElementById('snakedone-renderers');
  if (!sourceNode || !configNode) return;

  let source;
  let config;
  try {
    source = JSON.parse(sourceNode.textContent);
    config = JSON.parse(configNode.textContent);
  } catch (error) {
    return;
  }
  if (typeof source !== 'string' || !Array.isArray(config.resources)) return;

  const encoder = new TextEncoder();

  function base64(bytes) {
    let binary = '';
    bytes.forEach(byte => { binary += String.fromCharCode(byte); });
    return btoa(binary);
  }

  async function verified(resource, text) {
    // Check a library against the SRI hash recorded in the page config, so a
    // tampered CDN response or cache entry is never executed.
    const [algorithm, expected] = resource.integrity.split('-', 2);
    if (algorithm !== 'sha384' || !expected) return false;
    const digest = await crypto.subtle.digest('SHA-384', encoder.encode(text));
    return base64(new Uint8Array(digest)) === expected;
  }

  async function download(resource) {
    // Cache first, then the CDN. Both paths go through `verified`, so a stale
    // or tampered cache entry is dropped and refetched instead of trusted.
    let cache;
    if ('caches' in window) {
      try { cache = await caches.open(config.cache); } catch (error) { cache = null; }
    }
    if (cache) {
      const found = await cache.match(resource.url);
      if (found) {
        const text = await found.text();
        if (await verified(resource, text)) return text;
        await cache.delete(resource.url);
      }
    }
    const response = await fetch(resource.url, { mode: 'cors', credentials: 'omit' });
    if (!response.ok) throw new Error(`${resource.url}: HTTP ${response.status}`);
    const text = await response.text();
    if (!await verified(resource, text)) {
      throw new Error(`${resource.url}: SHA-384 integrity check failed`);
    }
    if (cache) {
      await cache.put(resource.url, new Response(text, {
        headers: { 'Content-Type': resource.type === 'style'
          ? 'text/css; charset=utf-8' : 'text/javascript; charset=utf-8' }
      }));
    }
    return text;
  }

  function install(resource, text) {
    // A stylesheet is inlined; a script runs from a blob URL, which keeps the
    // CSP at `blob:` instead of allowing each CDN host to run code directly.
    if (resource.type === 'style') {
      const style = document.createElement('style');
      style.dataset.sndLibrary = resource.name;
      style.textContent = text;
      document.head.appendChild(style);
      return Promise.resolve();
    }
    return new Promise((resolve, reject) => {
      const blob = new Blob([text], { type: 'text/javascript' });
      const url = URL.createObjectURL(blob);
      const script = document.createElement('script');
      script.src = url;
      script.dataset.sndLibrary = resource.name;
      script.onload = () => { URL.revokeObjectURL(url); resolve(); };
      script.onerror = () => {
        URL.revokeObjectURL(url);
        reject(new Error(`could not execute ${resource.name}`));
      };
      document.head.appendChild(script);
    });
  }

  function dedent(text) {
    // Reproduce `textwrap.dedent(...).strip()`: remove the longest common
    // leading whitespace, normalise whitespace-only lines, then trim.
    const lines = text.split('\n');
    const indents = lines
      .filter(line => /\S/.test(line))
      .map(line => (line.match(/^[ \t]*/) || [''])[0]);
    let prefix = indents.shift() || '';
    for (const indent of indents) {
      let size = 0;
      while (size < prefix.length && prefix[size] === indent[size]) size += 1;
      prefix = prefix.slice(0, size);
    }
    return lines.map(line => line.trim() ? line.slice(prefix.length) : '').join('\n').trim();
  }

  function markdownLiteral(raw) {
    // Extract the prose from a Markdown string literal. Prefixes (r/u) are
    // ignored and only the delimiter escapes `\\`, `\'`, `\"` are decoded;
    // every other backslash stays literal (design §6). CommonMark then applies
    // its own punctuation escapes to the result.
    const match = raw.match(/^[rRuU]*("""|'''|"|')/);
    if (!match) throw new Error('invalid markdown string literal');
    const delimiter = match[1];
    const end = raw.endsWith(delimiter) ? raw.length - delimiter.length : raw.length;
    const body = raw.slice(match[0].length, end);
    let decoded = '';
    for (let index = 0; index < body.length; index += 1) {
      const char = body[index];
      const next = body[index + 1];
      if (char === '\\' && (next === '\\' || next === '"' || next === "'")) {
        decoded += next;
        index += 1;
      } else {
        decoded += char;
      }
    }
    return dedent(decoded);
  }

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

  function codeLines(node) {
    // Rebuild one physical statement from the island. Shared indentation is
    // stripped before highlighting, except on continuation lines of a multiline
    // string, which keep their indentation and drop the `>>>` prompt. The
    // server precomputes which lines those are (`data-snd-string-lines`).
    const start = Number(node.dataset.sndStart);
    const end = Number(node.dataset.sndEnd);
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

  function scriptSource(node) {
    // Semicolons between adjacent document expressions are only separators, so
    // a region that holds nothing else is dropped instead of showing an empty
    // toggle.
    const start = Number(node.dataset.sndStart);
    const end = Number(node.dataset.sndEnd);
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

  function externalLinks(root) {
    // Open online links in a new tab without leaking the referrer; this is the
    // browser counterpart of the removed server-side `external_links`.
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

  function renderMarkdown(node, markdown) {
    // Render with the same settings the server used before: CommonMark, no raw
    // HTML, tables enabled.
    const start = Number(node.dataset.sndMdStart);
    const end = Number(node.dataset.sndMdEnd);
    node.innerHTML = markdown.render(markdownLiteral(source.slice(start, end)));
    externalLinks(node);
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

  function outline() {
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
          entries.push({ type: 'labels', level: Math.min(level + 1, 6),
            text: caption || node.id, id: node.id });
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
      for (const resource of config.resources) {
        if (resource.global && window[resource.global]) continue;
        await install(resource, await download(resource));
      }
      if (typeof window.markdownit !== 'function' || !window.hljs) {
        throw new Error('renderer libraries did not expose their browser globals');
      }
      const markdown = window.markdownit('commonmark', { html: false }).enable('table');
      document.querySelectorAll('.doc-md[data-snd-md-start]').forEach(node =>
        renderMarkdown(node, markdown));
      document.querySelectorAll('.doc-code[data-snd-start]').forEach(renderCode);
      document.querySelectorAll('.script-block[data-snd-start]').forEach(renderScript);
      outline();
      document.documentElement.dataset.sndRendered = 'true';
      document.dispatchEvent(new CustomEvent('snakedone-rendered'));
    } catch (error) {
      showError(error instanceof Error ? error : new Error(String(error)));
    }
  }

  render();
})();
