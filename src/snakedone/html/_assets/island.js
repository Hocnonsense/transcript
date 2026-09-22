(function () {
  const island = document.getElementById('snakedone-source');
  if (!island) return;
  let source;
  try { source = JSON.parse(island.textContent); } catch (error) { return; }
  if (typeof source !== 'string') return;

  function setView(block, toggle, showSource) {
    block.dataset.sndView = showSource ? 'source' : 'rendered';
    toggle.textContent = showSource ? 'Rendered' : 'Source';
    toggle.setAttribute('aria-pressed', String(showSource));
  }

  document.querySelectorAll('.report-block[data-snd-start]').forEach(block => {
    const start = Number(block.dataset.sndStart);
    const end = Number(block.dataset.sndEnd);
    const first = Number(block.dataset.sndLine);
    const textLines = source.slice(start, end).split('\n');
    const pre = document.createElement('pre');
    pre.className = 'snd-source';
    textLines.forEach((text, index) => {
      const line = document.createElement('span');
      line.className = 'snd-line';
      line.dataset.line = String(first + index);
      line.textContent = text;
      pre.appendChild(line);
    });
    const toggle = document.createElement('button');
    toggle.type = 'button';
    toggle.className = 'snd-view-toggle';
    toggle.textContent = 'Source';
    toggle.setAttribute('aria-pressed', 'false');
    toggle.addEventListener('click', () =>
      setView(block, toggle, block.dataset.sndView !== 'source'));
    block.appendChild(toggle);
    block.appendChild(pre);
  });

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

  const toolbar = document.createElement('div');
  toolbar.className = 'snd-toolbar';
  const sndButton = document.createElement('button');
  sndButton.type = 'button';
  sndButton.textContent = 'Export .snd';
  sndButton.addEventListener('click', () =>
    download(document.title + '.snd', source, 'text/plain'));
  toolbar.appendChild(sndButton);
  document.body.appendChild(toolbar);
})();
