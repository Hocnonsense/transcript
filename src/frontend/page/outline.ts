/** Rebuild the document outline from the rendered DOM and install the
 *  navigation panel.  Mirrors ``html/_navigate.py`` so the browser outline
 *  matches the server-rendered fallback. */

/** Slug a heading's text the same way `html/_navigate.py::_slug` does: keep
 *  unicode letters/digits, collapse whitespace and hyphens, and trim.
 *  `toLowerCase` (not the locale-aware variant) matches Python's `str.lower`. */
export function slug(text: string) {
  return text.toLowerCase()
    .replace(/[^\p{L}\p{N}_\- ]+/gu, '')
    .replace(/[\s\-]+/g, '-')
    .replace(/^-|-$/g, '');
}

export function outline(document: Document) {
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
