/** Shared zero-width diff marks used by the source fill and the revision list.
 *
 *  - `v`: `last-del`, above the line (a run the last version had and this row lost),
 *  - `^`: `next-ins`, below it (a run the next version adds and this row lacks),
 *  - `|`: `edit-del`, the edit-box deletion bar
 *
 *  The reviewed range reuses the two chevrons for its ends.  An optional
 *  `color` sets the anchor's `currentColor`. */

/** The zero-width anchor every diff mark is built on. It holds no inline space,
 *  so the overlay fill stays aligned with the textarea. */
function markAnchor(inner: string) {
  const span = document.createElement('span');
  span.className = 'tmd-diff-anchor';
  span.innerHTML = inner;
  return span;
}

const markDelMap = { 'v': 'last-del', '^': 'next-ins', '|': 'edit-del' } as const;

export function markDel(kind: 'v' | '^' | '|', color?: string) {
  const mark = markAnchor(`<i class="tmd-diff-${markDelMap[kind]}"></i>`);
  if (color) mark.style.color = color;
  return mark;
}
