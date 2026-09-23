(function () {
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

  async function loadResources(resources) {
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
          headers: {
            'Content-Type': resource.type === 'style'
              ? 'text/css; charset=utf-8' : 'text/javascript; charset=utf-8'
          }
        }));
      }
      return text;
    }

    async function install(resource, text) {
      // resource.type in 'style|script'
      if (resource.type === 'style') {
        // A stylesheet is inlined
        const style = document.createElement('style');
        style.dataset.sndLibrary = resource.name;
        style.textContent = text;
        document.head.appendChild(style);
        return Promise.resolve();
      }
      // a script runs from a blob URL, which keeps the CSP at `blob:`
      //  instead of allowing each CDN host to run code directly.
      return new Promise((resolve, reject) => {
        const blob = new Blob([text], { type: 'text/javascript' });
        const url = URL.createObjectURL(blob);
        const script = document.createElement('script');
        script.src = url;
        script.dataset.sndLibrary = resource.name;
        script.onload = () => { URL.revokeObjectURL(url); resolve(); };
        script.onerror = () => { URL.revokeObjectURL(url); reject(new Error(`could not execute ${resource.name}`)); };
        document.head.appendChild(script);
      });
    }

    for (const resource of resources) {
      if (resource.global && window[resource.global]) return;
      await install(resource, await download(resource));
    }
    if (typeof window.markdownit !== 'function' || !window.hljs) {
      throw new Error('renderer libraries did not expose their browser globals');
    }
  }

  function dedent(text) {
    // Reproduce `textwrap.dedent(...).strip()`: remove the longest common
    // leading whitespace, normalise whitespace-only lines, then trim.
    if (!text) return '';
    const lines = text.split('\n');
    const length = lines.length;

    // Skip leading blank lines; if the whole string is blank, we're done.
    let first = 0;
    while (first < length && !/\S/.test(lines[first])) first += 1;
    if (first === length) return '';

    // Skip trailing blank lines.
    let last = length;
    while (last > first && !/\S/.test(lines[last - 1])) last -= 1;

    // Longest common leading whitespace across the non-blank lines.
    let prefix = null;
    for (let index = first; index < last; index += 1) {
      const line = lines[index];
      if (!/\S/.test(line)) continue;
      const leading = line.match(/^[ \t]*/)[0];
      if (prefix === null) {
        prefix = leading;
      } else {
        const max = Math.min(prefix.length, leading.length);
        let size = 0;
        while (size < max && prefix.charCodeAt(size) === leading.charCodeAt(size)) size += 1;
        prefix = prefix.slice(0, size);
      }
      if (prefix.length === 0) break; // nothing left to shrink
    }
    const cut = prefix ? prefix.length : 0;

    // Build the result in one pass.
    const output = [];
    for (let index = first; index < last; index += 1) {
      const line = lines[index];
      output.push(/\S/.test(line) ? line.slice(cut) : '');
    }
    return output.join('\n');
  }

  /** Extract the prose from a Markdown string literal.
   *  Ignore prefixes (r/u), only escape `\\`, `\'`, `\"`.
   *  CommonMark then applies its own punctuation escapes to the result. */
  function markdownLiteral(raw) {
    const match = raw.match(/^[rRuU]*("""|'''|"|')/);
    if (!match) throw new Error('invalid markdown string literal');
    const delimiter = match[1];
    const body = raw.endsWith(delimiter)
      ? raw.slice(match[0].length, raw.length - delimiter.length)
      : raw.slice(match[0].length);

    let index = body.indexOf('\\');
    if (index === -1) return dedent(body);  // no backslashes to unescape
    // Walk from one backslash to the next, splicing whole runs at a time.
    let decoded = '';
    let start = 0;
    while (index !== -1) {
      const next = body[index + 1];
      if (next === '\\' || next === '"' || next === "'") {
        decoded += body.slice(start, index) + next;
        index += 2;
      } else {
        index += 1;
      }
      start = index;
      index = body.indexOf('\\', index);
    }
    return dedent(decoded + body.slice(start));
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

  // Markdown source view and inline review selection (front-end prototype).
  // Annotations live in memory only; nothing is persisted or exported yet.

  const SVG_NS = 'http://www.w3.org/2000/svg';

  function lineIndex(text, offset) {
    let line = 0;
    for (let index = 0; index < offset && index < text.length; index += 1) {
      if (text.charCodeAt(index) === 10) line += 1;
    }
    return line;
  }

  function escapeRegExp(text) {
    return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  }

  function searchLiteral(literal, needle, from) {
    // Locate a rendered text node in the literal, tolerating collapsed
    // whitespace (markdown joins soft line breaks with a space).
    const trimmed = needle.trim();
    if (!trimmed) return null;
    const pattern = trimmed.split(/\s+/).map(escapeRegExp).join('\\s+');
    const match = new RegExp(pattern).exec(literal.slice(from));
    if (!match) return null;
    const start = from + match.index;
    return { start, end: start + match[0].length };
  }

  function alignMarkdown(state) {
    // Map every rendered text node to a literal offset, in document order, so
    // selections and annotations can be translated both ways.
    const entries = [];
    const walker = document.createTreeWalker(state.rendered, NodeFilter.SHOW_TEXT);
    let cursor = 0;
    let node;
    while ((node = walker.nextNode())) {
      const text = node.nodeValue;
      if (!text || !/\S/.test(text)) continue;
      const found = searchLiteral(state.literal, text, cursor)
        || searchLiteral(state.literal, text, 0);
      if (!found) continue;
      const lead = (text.match(/^\s*/) || [''])[0].length;
      entries.push({ node, start: found.start, end: found.end, lead });
      cursor = found.end;
    }
    state.entries = entries;
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
    const last = [...state.entries].reverse().find(entry => entry.start < end);
    if (!first || !last) return null;
    const range = document.createRange();
    range.setStart(first.node, Math.min(
      literalToDomOffset(state, first, start), first.node.nodeValue.length));
    range.setEnd(last.node, Math.min(
      literalToDomOffset(state, last, end), last.node.nodeValue.length));
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

  function ribbon(bands) {
    // One connected outline around stacked line bands, so a wrapped range reads
    // as a single box instead of one box per line.
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

  function wavePath(left, right, y) {
    // Wavy underline along the bottom edge of an annotation box.
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

  function clearControls(state) {
    state.controls.replaceChildren();
  }

  function clearTransient(state) {
    // Keep the per-annotation badges; drop only the floating trigger and menu.
    state.controls.querySelectorAll('.snd-md-trigger, .snd-md-menu')
      .forEach(node => node.remove());
  }

  function initMarkdownRegion(node, start, end, renderFn) {
    // A markdown region is either a docstring (rendered here from the island)
    // or a server-rendered `markdown()` output (its children are kept as is).
    const literal = source.slice(start, end);
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
      svg: document.createElementNS(SVG_NS, 'svg'),
      controls: document.createElement('div'),
    };
    state.rendered.className = 'snd-md-rendered';
    if (renderFn) {
      state.rendered.innerHTML = renderFn(literal);
      externalLinks(state.rendered);
    } else {
      while (node.firstChild) state.rendered.appendChild(node.firstChild);
    }

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

  function markdownBodySpan(slotStart, slotEnd) {
    // Locate the `snakedone-output markdown` fence body inside a slot literal,
    // so a server-rendered markdown() output can be annotated against its source.
    const text = source.slice(slotStart, slotEnd);
    const header = /^[ \t]*(`{3,})snakedone-output[ \t]+markdown\b[^\n]*\n/m.exec(text);
    if (!header) return null;
    const bodyStart = header.index + header[0].length;
    // The closing fence has exactly the opening run of backticks, so a fenced
    // code block inside the Markdown body cannot terminate it early.
    const close = new RegExp(`^[ \\t]*${header[1]}[ \\t]*\\r?\\n?$`, 'm')
      .exec(text.slice(bodyStart));
    if (!close) return null;
    let end = slotStart + bodyStart + close.index;
    while (end > slotStart + bodyStart
      && (source[end - 1] === '\n' || source[end - 1] === '\r')) {
      end -= 1;
    }
    return { start: slotStart + bodyStart, end };
  }

  function initMarkdownOutputs() {
    document.querySelectorAll(
      '.snakedone-report[data-snd-renderer="markdown"]').forEach(node => {
        const slot = node.closest('[data-snd-slot-start]');
        if (!slot || node.sndMdState) return;
        const span = markdownBodySpan(
          Number(slot.dataset.sndSlotStart), Number(slot.dataset.sndSlotEnd));
        if (span) initMarkdownRegion(node, span.start, span.end, null);
      });
  }

  function showRendered(state) {
    state.view = 'rendered';
    state.node.dataset.sndMdView = 'rendered';
    state.rendered.hidden = false;
    state.source.hidden = true;
    state.selection = null;
    state.editing = null;
    state.drag = null;
    clearControls(state);
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
    return x >= rect.left - origin.left && x <= rect.right - origin.left
      && y >= rect.top - origin.top && y <= rect.bottom - origin.top;
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

  function openSource(state, start, end, anchorTop) {
    const whole = start === null || end === null;
    const firstIndex = whole ? 0 : lineIndex(state.literal, start);
    const lastIndex = whole
      ? state.lines.length - 1
      : lineIndex(state.literal, Math.max(start, end - 1));
    state.view = 'source';
    state.node.dataset.sndMdView = 'source';
    state.source.hidden = false;
    Array.from(state.source.children).forEach((line, index) => {
      line.hidden = index < firstIndex || index > lastIndex;
    });
    state.selection = whole ? null : { start, end };
    clearControls(state);
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

  function preselectSource(state, start, end) {
    const range = sourceRange(state, start, end);
    if (!range) return;
    const selection = window.getSelection();
    selection.removeAllRanges();
    selection.addRange(range);
  }

  function hideSourceStyle(state) {
    // While the user is dragging a fresh selection, keep only the native
    // selection highlight; the annotation box/handles return on mouseup.
    state.svg.replaceChildren();
    clearControls(state);
  }

  function drawSourceSelection(state) {
    if (state.view !== 'source' || state.selecting) return;
    state.svg.replaceChildren();
    clearControls(state);
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
    const rects = Array.from(range.getClientRects()).filter(
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
    if (doc.caretRangeFromPoint) {
      range = doc.caretRangeFromPoint(x, y);
    } else if (doc.caretPositionFromPoint) {
      const position = doc.caretPositionFromPoint(x, y);
      if (position) {
        range = doc.createRange();
        range.setStart(position.offsetNode, position.offset);
      }
    }
    if (!range || !state.source.contains(range.startContainer)) return null;
    return { node: range.startContainer, offset: range.startOffset };
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

  function wireMarkdown(state) {
    state.node.addEventListener('mousemove', event => {
      const origin = state.node.getBoundingClientRect();
      const x = event.clientX - origin.left;
      const y = event.clientY - origin.top;
      state.controls.querySelectorAll('.snd-md-badge').forEach(badge => {
        const bands = badge.sndAnnotation && badge.sndAnnotation.bands;
        const overBox = !!bands && bands.some(band =>
          x >= band.l - 2 && x <= band.r + 2 && y >= band.t - 2 && y <= band.b + 2);
        const overBadge = !badge.hidden && insideRect(badge, x, y, origin);
        badge.hidden = !(overBox || overBadge);
      });
    });
    state.node.addEventListener('mouseleave', () => {
      state.controls.querySelectorAll('.snd-md-badge').forEach(badge => {
        badge.hidden = true;
      });
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
      await loadResources(config.resources);

      const markdown = window.markdownit('commonmark', { html: false }).enable('table');
      document.querySelectorAll('.doc-md[data-snd-md-start]').forEach(node =>
        initMarkdownRegion(node, Number(node.dataset.sndMdStart), Number(node.dataset.sndMdEnd),
          literal => markdown.render(markdownLiteral(literal))));
      initMarkdownOutputs();
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
