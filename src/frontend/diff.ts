/** Character-level alignment shared by the two-row comparison and the
 *  multi-version history stack.  Pure: no DOM.
 *
 *  With jsdiff configured (``configureDiff``) a change is grouped by word and
 *  refined character by character inside each replacement, so untouched
 *  characters in a changed word stay plain.  Without it a plain character DP
 *  is used, which is also the fallback when the library is unavailable. */

/** One run of an alignment: its text on the original and modified sides.  A
 *  side not carrying text is empty, so the run's kind (equal / deleted /
 *  inserted / replaced) is derived, not stored. */
export interface DiffSlot { orig: string; mod: string; }

/** One jsdiff change: ``added``/``removed`` are both absent for an equal run. */
interface Change { value: string; added?: boolean; removed?: boolean; }
export type Changes = (original: string, modified: string) => Change[];
function push(slots: DiffSlot[], orig: string, mod: string) {
  const last = slots[slots.length - 1];
  if (last && (last.orig === last.mod) === (orig === mod)) {
    last.orig += orig;
    last.mod += mod;
  } else {
    slots.push({ orig, mod });
  }
}

/** Character-level DP, used when jsdiff is not configured. */
function dpSlots(original: string, modified: string) {
  const n = original.length;
  const m = modified.length;
  if (n * m > 1000000) {
    return original === modified
      ? [{ orig: original, mod: modified }]
      : [{ orig: original, mod: '' }, { orig: '', mod: modified }];
  }
  const dp = Array.from({ length: n + 1 }, () => new Uint32Array(m + 1));
  for (let i = n - 1; i >= 0; i -= 1) {
    for (let j = m - 1; j >= 0; j -= 1) {
      dp[i][j] = original[i] === modified[j]
        ? dp[i + 1][j + 1] + 1
        : Math.max(dp[i + 1][j], dp[i][j + 1]);
    }
  }
  const slots: DiffSlot[] = [];
  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    if (original[i] === modified[j]) {
      push(slots, original[i], modified[j]);
      i += 1;
      j += 1;
    } else if (dp[i + 1][j] >= dp[i][j + 1]) {
      push(slots, original[i], '');
      i += 1;
    } else {
      push(slots, '', modified[j]);
      j += 1;
    }
  }
  while (i < n) { push(slots, original[i], ''); i += 1; }
  while (j < m) { push(slots, '', modified[j]); j += 1; }
  return slots;
}

/** The active backend: plain characters until jsdiff is configured. */
const engine = { words: dpSlots, chars: dpSlots };
/** Use an external diff engine (jsdiff): *words* groups the text, *chars*
 *  refines each replacement.  Without it ``diffText`` stays self-contained. */
export function configureDiff(options: Window['Diff']) {
  if (!options) return;
  engine.words = (original, modified) => mergeSlots(refine(slotsFromChanges(options.diffWordsWithSpace(original, modified))));
  engine.chars = (original, modified) => mergeSlots(slotsFromChanges(options.diffChars(original, modified)));
}

function mergeSlots(slots: DiffSlot[]) {
  const merged: DiffSlot[] = [];
  for (const slot of slots) push(merged, slot.orig, slot.mod);
  return merged;
}

function slotsFromChanges(changes: Change[]) {
  const slots: DiffSlot[] = [];
  for (const change of changes) {
    // const kind = change.removed ? 'del' : change.added ? 'ins' : 'equal';
    push(
      slots,
      change.removed ? '' : change.value,
      change.added ? '' : change.value,
    );
  }
  return slots;
}

/** Alignment of *original* and *modified* as equal/deleted/inserted/replaced
 *  run slots with adjacent same-kind runs merged.  Word groups when jsdiff is
 *  configured, plain characters otherwise. */
export function diffText(original: string, modified: string): DiffSlot[] {
  return engine.words(original, modified);
}

/** Re-diff every removed+added replacement at the character level. */
function refine(slots: DiffSlot[]) {
  const out: DiffSlot[] = [];
  let index = 0;
  while (index < slots.length) {
    const slot = slots[index];
    const next = slots[index + 1];
    if (next && slot.mod === '' && next.orig === '') {
      out.push(...engine.chars(slot.orig, next.mod));
      index += 2;
    } else if (next && slot.orig === '' && next.mod === '') {
      out.push(...engine.chars(next.orig, slot.mod));
      index += 2;
    } else {
      out.push(slot);
      index += 1;
    }
  }
  return out;
}
