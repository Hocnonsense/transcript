(function () {
  function wire(navigate: HTMLElement) {
    if (navigate.dataset.sndWired === 'true') return;
    navigate.dataset.sndWired = 'true';
    const tabs = Array.from(navigate.querySelectorAll<HTMLElement>('.navigate-tab'));
    const list = navigate.querySelector<HTMLElement>('.navigate-list');
    if (!list) return;
    const entries = Array.from(list.querySelectorAll<HTMLElement>('[data-snd-type]'));
    function enabled() {
      return (list.dataset.sndShow || '').split(/\s+/).filter(Boolean);
    }
    function setEnabled(names: string[]) {
      list.dataset.sndShow = names.join(' ');
      entries.forEach(entry => {
        entry.hidden = !names.includes(entry.dataset.sndType);
      });
      tabs.forEach(tab => {
        const on = names.includes(tab.dataset.sndType);
        tab.dataset.active = String(on);
        tab.querySelector('.navigate-tab-toggle')
          ?.setAttribute('aria-pressed', String(on));
      });
      navigate.dataset.collapsed = String(names.length === 0);
    }
    tabs.forEach(tab => {
      const type = tab.dataset.sndType;
      tab.querySelector('.navigate-tab-toggle')?.addEventListener('click', () => {
        const names = enabled();
        setEnabled(names.includes(type)
          ? names.filter(name => name !== type) : [...names, type]);
      });
      tab.querySelector('.navigate-tab-body')?.addEventListener('click', () => {
        setEnabled([type]);
      });
    });
    if (!tabs.length) return;
    const narrow = window.matchMedia('(max-width: 920px)');
    const firstType = tabs[0].dataset.sndType;
    function sync(event: MediaQueryList | MediaQueryListEvent) {
      setEnabled(event.matches ? [] : [firstType]);
    }
    sync(narrow);
    narrow.addEventListener('change', sync);
    document.addEventListener('click', event => {
      if (narrow.matches && event.target instanceof Node
        && !navigate.contains(event.target)) setEnabled([]);
    });
  }

  function initialize() {
    document.querySelectorAll<HTMLElement>('.navigate').forEach(wire);
  }

  window.snakedoneInitNavigate = initialize;
  initialize();
})();
