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
 *  ``snakedone-reviews`` island. The source island is left exactly as the page
 *  was generated with, so extraction still sees the reviewed archive. */
function pageHtml() {
  const clone = document.documentElement.cloneNode(true) as HTMLElement;
  clone.querySelectorAll('.snd-toolbar, .navigate, [data-snd-library]')
    .forEach(node => node.remove());
  const store = window.snakedoneReviewStore;
  if (store) {
    const script = document.createElement('script');
    script.id = 'snakedone-reviews';
    script.type = 'application/json';
    script.textContent = store.exportIsland();
    const existing = clone.querySelector('#snakedone-reviews');
    if (existing) existing.replaceWith(script);
    else clone.querySelector('#snakedone-source')?.after(script);
  }
  return '<!doctype html>\n' + clone.outerHTML;
}

(function () {
  const island = document.getElementById('snakedone-source');
  if (!island) return;
  let source;
  try { source = JSON.parse(island.textContent); } catch (error) { return; }
  if (typeof source !== 'string') return;

  const toolbar = document.createElement('div');
  toolbar.className = 'snd-toolbar';
  const sndButton = document.createElement('button');
  sndButton.type = 'button';
  sndButton.textContent = 'Export .snd';
  sndButton.addEventListener('click', () => {
    const store = window.snakedoneReviewStore;
    const content = store ? store.exportSource() : source;
    download(document.title + '.snd', content, 'text/plain');
  });
  const htmlButton = document.createElement('button');
  htmlButton.type = 'button';
  htmlButton.textContent = 'Save .html';
  htmlButton.addEventListener('click', () => {
    download(document.title + '.html', pageHtml(), 'text/html');
  });
  toolbar.append(sndButton, htmlButton);
  document.body.appendChild(toolbar);
})();
