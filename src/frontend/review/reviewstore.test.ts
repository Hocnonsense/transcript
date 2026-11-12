/** ReviewStore mapping tests: pure node (esbuild-bundled), no DOM.
 *
 *  Each case builds a store from a hand-written record set and pins where a
 *  review written in an old version lands in the live text.  ``cover`` joins
 *  an old span to the ``before`` boundary of the version it lived in, which pins the
 *  predecessor; a review's ``coveredAt`` names the version it was written in,
 *  which pins the anchor.  Run by ``tools/test_frontend.py``. */

import { ReviewStore } from './reviewstore';
import { Annotation } from './annotation';
import { ReviewRecord } from './model/records';
import { At } from './model/span';

declare const process: { exit(code?: number): void };

let failures = 0;
let checked = 0;

function is(name: string, got: string | number, want: string | number) {
  checked += 1;
  if (got !== want) {
    failures += 1;
    console.error(`FAIL ${name}: got ${got}, want ${want}`);
  }
}

function review(store: ReviewStore, at: string, coveredAt: string[]) {
  const record = new ReviewRecord({ type: 'review', time: '2026-09-01T00:00:00.000Z', at, coveredAt });
  return store.currentSpan(record).format();
}

const v1 = '2026-09-10T00:00:00.000Z';
const v2 = '2026-09-15T00:00:00.000Z';

const parsed = At.parse(`L2@${v1}`);
is('cover:span', parsed.span.format(), 'L2');
is('cover:format', parsed.format(), `L2@${v1}`);

// A line inserted above a reviewed line shifts it down; the chain links the
// frozen line to its live successor.
{
  const store = new ReviewStore('x\nn\na\ny\n', [
    { type: 'source', at: 'L2', source: 'a\n', before: v1 },
    { type: 'source', at: 'L3', cover: `L2@${v1}` },
  ] as any, '');
  is('shift', review(store, 'L2', [`L2@${v1}`]), 'L3');
}

// An unchanged line keeps its exact character range (review still live).
{
  const store = new ReviewStore('keep\n', [
    { type: 'source', at: 'L1' },
  ] as any, '');
  is('identity', review(store, 'L1C1+2', []), 'L1C1+2');
}

// A line split into two: the review bounds both live lines.
{
  const store = new ReviewStore('a\nb\n', [
    { type: 'source', at: 'L1', source: 'ab\n', before: v1 },
    { type: 'source', at: 'L1', cover: `L1C1+1@${v1}` },
    { type: 'source', at: 'L2', cover: `L1C2-L1@${v1}` },
  ] as any, '');
  is('split', review(store, 'L1', [`L1@${v1}`]), 'L1-L2');
  const index = (store as any).index();
  is('split:succ', index.successors.get(v1).get(0).length, 2);
}

// Two lines merged into one: both predecessors project onto the same live line.
{
  const store = new ReviewStore('ab\n', [
    { type: 'source', at: 'L1', source: 'a\n', before: v1 },
    { type: 'source', at: 'L2', source: 'b\n', before: v1 },
    { type: 'source', at: 'L1', cover: `L1-L2@${v1}` },
  ] as any, '');
  is('merge:L1', review(store, 'L1', [`L1@${v1}`]), 'L1C1+1');
  is('merge:L2', review(store, 'L2', [`L2@${v1}`]), 'L1C2-L1');
  const index = (store as any).index();
  const merged = index.byVersion.get(null).get(0);
  is('merge:cover', merged.cover.span.lastLine(), 1);
}

// A same-line replacement maps a partial range by column.
{
  const store = new ReviewStore('aXc\n', [
    { type: 'source', at: 'L1', source: 'abc\n', before: v1 },
    { type: 'source', at: 'L1', cover: `L1@${v1}` },
  ] as any, '');
  is('replace', review(store, 'L1C2+1', [`L1@${v1}`]), 'L1C2+1');
}

// Records may be serialized out of version order; ordering comes from the
// stamps, not the array.
{
  const store = new ReviewStore('D\n', [
    { type: 'source', at: 'L1', cover: `L1@${v2}` },
    { type: 'source', at: 'L1', source: 'A\n', before: v1 },
    { type: 'source', at: 'L1', source: 'B\n', cover: `L1@${v1}`, before: v2 },
  ] as any, '');
  is('scrambled', review(store, 'L1', [`L1@${v1}`]), 'L1');
}

// A line inserted by a migration carries a zero-length cover stamping when it
// appeared: older layers omit it (they never fabricate the live text), and its
// own reviews still locate their run in the version they were written against.
{
  const source = 'a\nnew\nb\n';
  const store = new ReviewStore(source, [
    { type: 'source', at: 'L2', source: 'b\n', before: v1 },
    { type: 'source', at: 'L3', cover: `L2@${v1}` },
    { type: 'source', at: 'L2', cover: `L2C1+0@${v1}` },
  ] as any, '');
  const region: any = {};
  const map = source.split('').map((_, index) => index);
  store.addRegion(region, 0, source.length, source, map);
  const old = new Annotation({
    chosen: { start: 0, end: source.length }, original: source,
    edit: source, comment: '', modified: false,
    record: new ReviewRecord({ type: 'review', time: '2026-09-05T00:00:00.000Z', at: 'L2' }),
  });
  const live = new Annotation({
    chosen: { start: 0, end: source.length }, original: source,
    edit: source, comment: '', modified: false,
    record: new ReviewRecord({ type: 'review', time: v1, at: 'L3' }),
  });
  store.annotations.get(region)!.push(old, live);

  const history = store.history(region, old)!;
  is('history:layers', history.layers.join('|'), 'a\nb|a\nnew\nb');
  is('history:old-highlight', history.entries[0][0].highlight ?? '', 'b');
  is('history:live-highlight', history.entries[1][0].highlight ?? '', 'b');
}

if (failures) {
  console.error(`${failures}/${checked} frontend review tests failed`);
  process.exit(1);
}
console.log(`${checked} frontend review tests passed`);
