/** The 0-based half-open ``L``/``C`` coordinate grammar of review records.
 *
 * Mirrors ``snakedone/review/_span.py``: the grammar is 1-based but a span
 * stores 0-based ``[start, end)`` positions, so a whole line ``L5`` ends at the
 * next line's start and a point ``L5C3+0`` has ``start == end``.
 */

export class Span {
  sl: number; sc: number; el: number; ec: number;

  constructor(sl: number, sc: number, el: number, ec: number) {
    this.sl = sl; this.sc = sc; this.el = el; this.ec = ec;
  }
  static parse(text: string) {
    const value = text.trim();
    if (!value) throw new Error('empty coordinate');
    if (value.includes('+')) {
      const [point, length] = partition(value, '+');
      const { line, col } = parsePoint(point);
      if (col === null || !/^\d+$/.test(length)) {
        throw new Error('invalid coordinate: ' + text);
      }
      return new Span(line - 1, col - 1, line - 1, col + Number(length) - 1);
    }
    const [startText, separator, endText] = partition(value, '-');
    if (!separator) {
      const { line, col } = parsePoint(startText);
      if (col === null) return new Span(line - 1, 0, line, 0);
      return new Span(line - 1, col - 1, line - 1, col);
    }
    const start = parsePoint(startText);
    const end = parsePoint(endText);
    return new Span(
      start.line - 1,
      start.col === null ? 0 : start.col - 1,
      end.col === null ? end.line : end.line - 1,
      end.col === null ? 0 : end.col
    );
  }
  format() {
    const { sl, sc, el, ec } = this;
    const sl1 = sl + 1;
    if (sl === el) return `L${sl1}C${sc + 1}+${ec - sc}`;
    if (sc === 0 && ec === 0 && el === sl1) return `L${sl1}`;
    const start = sc === 0 ? `L${sl1}` : `L${sl1}C${sc + 1}`;
    const end = ec === 0 ? `L${el}` : `L${el + 1}C${ec}`;
    return start + '-' + end;
  }
}

function parsePoint(text: string): { line: number; col: number | null } {
  const trimmed = text.trim();
  if (!trimmed.startsWith('L')) throw new Error('invalid coordinate: ' + text);
  const [lineText, mark, colText] = partition(trimmed.slice(1), 'C');
  if (!/^\d+$/.test(lineText)) throw new Error('invalid coordinate: ' + text);
  if (mark && !/^\d+$/.test(colText)) throw new Error('invalid coordinate: ' + text);
  return { line: Number(lineText), col: mark ? Number(colText) : null };
}

function partition(text: string, separator: string): [string, string, string] {
  const index = text.indexOf(separator);
  if (index === -1) return [text, '', ''];
  return [text.slice(0, index), separator, text.slice(index + separator.length)];
}
