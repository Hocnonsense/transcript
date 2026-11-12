document.querySelectorAll<HTMLImageElement>('main img').forEach(image => {
  image.tabIndex = 0;
  image.setAttribute('role', 'button');
  image.setAttribute('aria-pressed', 'false');
  image.title = 'Click to expand to text width';
  function toggleImage() {
    const expanded = image.classList.toggle('image-expanded');
    image.setAttribute('aria-pressed', String(expanded));
    image.title = expanded
      ? 'Click to restore preview' : 'Click to expand to text width';
  }
  image.addEventListener('click', toggleImage);
  image.addEventListener('keydown', (event: KeyboardEvent) => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      toggleImage();
    }
  });
});

document.querySelectorAll<HTMLElement>('.doctest-code[data-boxed]').forEach(block => {
  const toggle = block.querySelector<HTMLButtonElement>(':scope > .output-box-toggle');
  if (!toggle) return;
  function setBoxed(boxed) {
    block.dataset.boxed = String(boxed);
    toggle.setAttribute('aria-expanded', String(boxed));
    toggle.title = boxed ? 'Hide code and frame' : 'Show code and frame';
  }
  toggle.addEventListener('click', () => setBoxed(block.dataset.boxed !== 'true'));
  setBoxed(block.dataset.boxed === 'true');
});
