/** The 0-based half-open ``L``/``C`` coordinate grammar of review records.
 *
 * Mirrors ``snakedone/review/_span.py``: the grammar is 1-based but a span
 * stores 0-based ``[start, end)`` positions, so a whole line ``L5`` ends at the
 * next line's start and a point ``L5C3+0`` has ``start == end``.
 */

export interface Point { line: number; column: number }

function parsePoint(text: string): { line: number; col: number | null } {
  const trimmed = text.trim();
  if (!trimmed.startsWith('L')) throw new Error('invalid coordinate: ' + text);
  const [lineText, mark, colText] = partition(trimmed.slice(1), 'C');
  if (!/^\d+$/.test(lineText)) throw new Error('invalid coordinate: ' + text);
  if (mark && !/^\d+$/.test(colText)) throw new Error('invalid coordinate: ' + text);
  return { line: Number(lineText), col: mark ? Number(colText) : null };
}

export class Span {
  start_line: number; start_column: number; end_line: number; end_column: number;

  constructor(sl: number, sc: number, el: number, ec: number) {
    this.start_line = sl; this.start_column = sc; this.end_line = el; this.end_column = ec;
  }
  static fromPoints(start: Point, end: Point) {
    return new Span(start.line, start.column, end.line, end.column);
  }
  static parse(text: string) {
    const value = text.trim();
    if (!value) throw new Error('empty coordinate');
    if (value.includes('+')) {
      const [point, , length] = partition(value, '+');
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
    const { start_line: sl, start_column: sc, end_line: el, end_column: ec } = this;
    const sl1 = sl + 1;
    if (sl === el) return `L${sl1}C${sc + 1}+${ec - sc}`;
    if (sc === 0 && ec === 0 && el === sl1) return `L${sl1}`;
    const start = sc === 0 ? `L${sl1}` : `L${sl1}C${sc + 1}`;
    const end = ec === 0 ? `L${el}` : `L${el + 1}C${ec}`;
    return start + '-' + end;
  }
  isEmpty() { return this.start_line === this.end_line && this.start_column === this.end_column; }
  lastLine() { return this.end_column === 0 ? this.end_line - 1 : this.end_line; }
  overlap(other: Span) { return this.start_line <= other.lastLine() && other.start_line <= this.lastLine(); }
  start(): Point { return { line: this.start_line, column: this.start_column }; }
  end(): Point { return { line: this.end_line, column: this.end_column }; }

  /** Whether *point* falls inside this span, left-closed and right-open. */
  contains(point: Point) {
    if (point.line < this.start_line) return -1;
    if (this.start_line === point.line && point.column < this.start_column) return -1;
    if (this.start_line < point.line && point.line < this.lastLine()) return 0;
    if (point.line === this.lastLine()) {
      return this.end_column === 0 ? 0 : point.column < this.end_column ? 0 : 1;
    }
    return 1;
  }

  /** Rebase this span so *base* becomes the origin of its coordinates. */
  relativeTo(base = this.start()) {
    const first = this.start_line === base.line
      ? this.start_column - base.column : this.start_column;
    const last = this.end_line === base.line
      ? this.end_column - base.column : this.end_column;
    return new Span(this.start_line - base.line, first, this.end_line - base.line, last);
  }

  /** The offset of *point* inside the selected text *slice*. */
  offsetOf(slice: string, point: Point) {
    const starts = lineStarts(slice);
    const line = point.line - this.start_line;
    const column = line === 0 ? point.column - this.start_column : point.column;
    return Math.min(Math.max(starts[line] + column, 0), slice.length);
  }

  /** The point that *offset* names inside the selected text *slice*. */
  pointAt(slice: string, offset: number): Point {
    const starts = lineStarts(slice);
    let line = starts.length - 1;
    while (line > 0 && starts[line] > offset) line -= 1;
    const column = (line === 0 ? this.start_column : 0) + (offset - starts[line]);
    return { line: this.start_line + line, column };
  }

  /** The substring this span selects in *text*, or ``null`` when out of range. */
  extract(text: string, starts = lineStarts(text)) {
    if (this.start_line < 0 || this.start_line >= starts.length) return null;
    if (this.end_line < 0 || this.end_line >= starts.length) return null;
    const start = starts[this.start_line] + this.start_column;
    const end = starts[this.end_line] + this.end_column;
    if (start < 0 || start > end || end > text.length) return null;
    return text.slice(start, end);
  }
}

/** A source span paired with its version boundary time. */
export class At {
  constructor(public readonly span: Span, public readonly time: string) {
    if (!time || Number.isNaN(Date.parse(time))) {
      throw new Error('at time must be a timestamp');
    }
  }

  static parse(text: string) {
    if (typeof text !== 'string') throw new Error('at must be a span@time string');
    const parts = text.split('@');
    if (parts.length !== 2 || !parts[0] || !parts[1]) {
      throw new Error('at must be a span@time string');
    }
    return new At(Span.parse(parts[0]), parts[1]);
  }

  format() {
    return `${this.span.format()}@${this.time}`;
  }
}

/** The character offset at which each line begins, optionally plus the text end. */
export function lineStarts(text: string) {
  const starts = [0];
  for (let index = 0; index < text.length; index += 1) {
    if (text[index] === '\n') starts.push(index + 1);
  }
  return starts;
}

/** The whole source line(s) a range spans: from the line start of *start* to
 *  the line end of *end* (no trailing newline). */
export function fullLines(text: string, start: number, end: number) {
  const before = text.lastIndexOf('\n', start - 1);
  const lineStart = before === -1 ? 0 : before + 1;
  const lineEnd = text.indexOf('\n', end);
  return { start: lineStart, end: lineEnd === -1 ? text.length : lineEnd };
}

/** One 0-based line of *text* from its precomputed *starts*, newline excluded. */
export function lineAt(text: string, starts: number[], line: number) {
  const start = line < starts.length ? starts[line] : text.length;
  const end = line + 1 < starts.length ? starts[line + 1] - 1 : text.length;
  return text.slice(start, end);
}

function partition(text: string, separator: string): [string, string, string] {
  const index = text.indexOf(separator);
  if (index === -1) return [text, '', ''];
  return [text.slice(0, index), separator, text.slice(index + separator.length)];
}
