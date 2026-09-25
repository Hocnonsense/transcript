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
    const content = store ? store.exportSource() : source; download(document.title + '.snd', content, 'text/plain');
  });
  toolbar.appendChild(sndButton);
  document.body.appendChild(toolbar);
})();
