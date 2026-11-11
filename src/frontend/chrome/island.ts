function download(name, content, mime) {
  const blob = new Blob([content], { type: mime });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = name;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 0);
}

/** Serialize the live page with the current annotations written into the
 *  ``transcript-reviews`` island. The source island is left exactly as the page
 *  was generated with, so extraction still sees the reviewed archive. */
function pageHtml() {
  const clone = document.documentElement.cloneNode(true) as HTMLElement;
  clone.querySelectorAll('.tmd-toolbar, .navigate, [data-tmd-library]')
    .forEach(node => node.remove());
  const store = window.transcriptReviewStore;
  if (store) {
    const script = document.createElement('script');
    script.id = 'transcript-reviews';
    script.type = 'application/json';
    script.textContent = store.exportIsland();
    const existing = clone.querySelector('#transcript-reviews');
    if (existing) existing.replaceWith(script);
    else clone.querySelector('#transcript-source')?.after(script);
  }
  return '<!doctype html>\n' + clone.outerHTML;
}

(function () {
  const island = document.getElementById('transcript-source');
  if (!island) return;
  let source;
  try { source = JSON.parse(island.textContent); } catch (error) { return; }
  if (typeof source !== 'string') return;

  const toolbar = document.createElement('div');
  toolbar.className = 'tmd-toolbar';
  const tmdButton = document.createElement('button');
  tmdButton.type = 'button';
  tmdButton.textContent = 'Export .tmd.py';
  tmdButton.addEventListener('click', () => {
    const store = window.transcriptReviewStore;
    const content = store ? store.exportSource() : source;
    download(document.title + '.tmd.py', content, 'text/plain');
  });
  const htmlButton = document.createElement('button');
  htmlButton.type = 'button';
  htmlButton.textContent = 'Save .html';
  htmlButton.addEventListener('click', () => {
    download(document.title + '.html', pageHtml(), 'text/html');
  });
  toolbar.append(tmdButton, htmlButton);
  document.body.appendChild(toolbar);
})();
