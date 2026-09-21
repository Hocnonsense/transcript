document.querySelectorAll('.navigate').forEach(navigate => {
  const tabs = Array.from(navigate.querySelectorAll('.navigate-tab'));
  const list = navigate.querySelector('.navigate-list');
  if (!list || tabs.length < 2) return;
  const entries = Array.from(list.querySelectorAll('[data-snakedone-type]'));
  function enabled() {
    return list.dataset.snakedoneShow.split(/\s+/).filter(Boolean);
  }
  function setEnabled(names) {
    list.dataset.snakedoneShow = names.join(' ');
    entries.forEach(entry => {
      entry.hidden = !names.includes(entry.dataset.snakedoneType);
    });
    tabs.forEach(tab => {
      const on = names.includes(tab.dataset.snakedoneType);
      tab.dataset.active = String(on);
      const toggle = tab.querySelector('.navigate-tab-toggle');
      toggle.setAttribute('aria-pressed', String(on));
    });
    navigate.dataset.collapsed = String(names.length === 0);
  }
  tabs.forEach(tab => {
    const type = tab.dataset.snakedoneType;
    tab.querySelector('.navigate-tab-toggle').addEventListener('click', () => {
      const names = enabled();
      setEnabled(names.includes(type)
        ? names.filter(name => name !== type) : [...names, type]);
    });
    tab.querySelector('.navigate-tab-body').addEventListener('click', () => {
      setEnabled([type]);
    });
  });
  // Below M + 3u the navigate floats over the text, so it opens automatically
  // above that width and starts collapsed below it. The same breakpoint also
  // lets a click on the page collapse the floating navigate again.
  const narrow = window.matchMedia('(max-width: 920px)');
  const firstType = tabs[0].dataset.snakedoneType;
  function sync(event) {
    setEnabled(event.matches ? [] : [firstType]);
  }
  sync(narrow);
  narrow.addEventListener('change', sync);
  document.addEventListener('click', event => {
    if (narrow.matches && !navigate.contains(event.target)) setEnabled([]);
  });
});
