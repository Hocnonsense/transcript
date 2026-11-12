import { loadResources } from '../chrome/resources';
import { configureDiff } from '../review/text/diff';
import { MarkdownReview } from '../review/review';
import { ReviewStore } from '../review/reviewstore';
import { initMarkdownRegion, renderCode, renderScript } from './code';
import { outline } from './outline';

/** Show a load/render failure without discarding the embedded source. */
function showError(error: Error) {
  const message = document.createElement('div');
  message.className = 'tmd-render-error';
  message.setAttribute('role', 'alert');
  message.textContent = `Could not load browser renderers: ${error.message}`;
  document.querySelector('main')?.prepend(message);
}

(() => {
  /*
   * Render the parts of the page that are derived from the embedded source:
   * Markdown prose, statement code, and the surrounding script regions. The
   * server only emits placeholders carrying character offsets into the island
   * (`#transcript-source`), so nothing here is a second copy of the source.
   * Renderer libraries are loaded once and cached (see `download`).
   */
  const sourceNode = document.getElementById('transcript-source');  // _island.source_island
  const configNode = document.getElementById('transcript-renderers');  // _resources._renderer_config
  if (!sourceNode || !configNode) return;

  let source, config;
  try {
    source = JSON.parse(sourceNode.textContent);
    config = JSON.parse(configNode.textContent);
    if (typeof source !== 'string' || !Array.isArray(config.resources)) return;
  } catch (error) { return; }

  // The parsed review records and the body hash.
  // The archive itself is still the source island above;
  // this only spares the runtime from parsing Python,
  // and lets `Export .tmd.py` rewrite the block.
  window.transcriptReviewStore = ((reviewNode) => {
    let reviewIsland = { records: [], hash: '' };
    if (reviewNode) {
      try {
        const parsed = JSON.parse(reviewNode.textContent);
        if (parsed && Array.isArray(parsed.records)) reviewIsland = parsed;
      } catch (error) { /* treat as no records */ }
    }
    return new ReviewStore(source, reviewIsland.records, reviewIsland.hash)
  })(document.getElementById('transcript-reviews'));

  async function render() {
    // Load the libraries first, then fill the placeholders. The outline runs
    // last so it sees every heading the Markdown pass produced.
    try {
      await loadResources(config.resources, config.cache);
      configureDiff(window.Diff);

      const markdown = window.markdownit('commonmark', { html: false }).enable('table');
      const regions: MarkdownReview[] = [];
      document.querySelectorAll(
        '.doc-md[data-tmd-span], ' +
        '.transcript-report[data-tmd-renderer="markdown"][data-tmd-span]'
      ).forEach(node => regions.push(initMarkdownRegion(node, markdown, source)));
      // Every region is in: distribute the records once, then draw the badges.
      window.transcriptReviewStore?.buildAnnotations();
      regions.forEach(region => region.showRendered());

      document.querySelectorAll('.doc-code[data-tmd-span]')
        .forEach(node => renderCode(node, source));
      document.querySelectorAll('.script-block[data-tmd-span]')
        .forEach(node => renderScript(node, source));
      outline(document);
      document.documentElement.dataset.tmdRendered = 'true';
      document.dispatchEvent(new CustomEvent('transcript-rendered'));
    } catch (error) {
      showError(error instanceof Error ? error : new Error(String(error)));
    }
  }
  render();
})();
