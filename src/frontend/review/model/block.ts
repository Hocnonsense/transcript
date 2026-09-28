/** Serialize the trailing ``snakedone.review`` block and its island form.
 *  Pure: the store supplies the source body, records, and body hash. */

import type { RecordEntry } from './records';

function escapeSlot(content: string) {
  let text = content.replace(/\\/g, '\\\\').replace(/\r/g, '\\r').replace(/\t/g, '\\t');
  text = text.replace(
    /[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]/g,
    char => '\\x' + char.charCodeAt(0).toString(16).padStart(2, '0'));
  return text.replace(/"{3,}|"+$/g, match => match.replace(/"/g, '\\"'));
}

/** The archive body plus the newline-separated review block, ready to export
 *  as a ``.snd``.  With no records the body is returned unchanged. */
export function exportSource(source: string, records: RecordEntry[], hash: string) {
  const body = source.replace(/\n+$/, '') + '\n';
  if (!records.length) return body;
  return body + '\n' + renderBlock(records, hash) + '\n';
}

/** The ``if "snakedone.review=<hash>": \"\"\"[...]\"\"\"`` block. */
export function renderBlock(records: RecordEntry[], hash: string) {
  const lines = records.map(record => JSON.stringify(record.data()));
  const inner = lines.length
    ? '[\n' + lines.map(line => '    ' + line).join(',\n') + '\n    ]'
    : '[]';
  const marker = hash ? `snakedone.review=${hash}` : 'snakedone.review';
  return `if "${marker}":\n    """${escapeSlot(inner)}"""`;
}

/** Serialize the current records for the ``snakedone-reviews`` island, so a
 *  saved page reloads with the annotations the user added. The source island
 *  holds only the archive body and is never rewritten. */
export function exportIsland(records: RecordEntry[], hash: string) {
  const payload = { records: records.map(record => record.data()), hash };
  return JSON.stringify(payload)
    .replace(/</g, '\\u003c')
    .replace(/>/g, '\\u003e');
}
