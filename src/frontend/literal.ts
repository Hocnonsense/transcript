function hasContent(text) {
  for (let index = 0; index < text.length; index += 1) {
    const code = text.charCodeAt(index);
    // Treat anything outside ASCII indentation whitespace as content.
    if (code !== 32 && code !== 9 && code !== 13) return true;
  }
  return false;
}

/** Strip the fixed report-block indent and trim blank edges, unlike `textwrap.dedent`. */
function dedent(text, REPORT_INDENT = '    ') {
  if (!text) return '';
  const lines = text.split('\n');
  let first = 0;
  while (first < lines.length && !hasContent(lines[first])) first += 1;
  if (first === lines.length) return '';
  let last = lines.length;
  while (last > first && !hasContent(lines[last - 1])) last -= 1;

  const indent = REPORT_INDENT.length;
  const output = [];
  for (let index = first; index < last; index += 1) {
    const line = lines[index];
    if (!hasContent(line)) {
      output.push('');
    } else if (line.startsWith(REPORT_INDENT)) {
      output.push(line.slice(indent));
    } else {
      output.push(line);
    }
  }
  return output.join('\n');
}

function isHexPair(text) {
  if (text.length !== 2) return false;
  for (let index = 0; index < 2; index += 1) {
    const code = text.charCodeAt(index);
    const ok = (code >= 48 && code <= 57)  // 0-9
      || (code >= 65 && code <= 70)        // A-F
      || (code >= 97 && code <= 102);      // a-f
    if (!ok) return false;
  }
  return true;
}

/** Recover the exact string from its Python literal form.
 *  Both the machine escaping used for slots (`_escape_slot`)
 *   and hand-written docstrings use the same set here:
 *  `\\`, `\"`, `\'`, `\r`, `\t`, `\xNN`; LF stays literal. */
function decodeEscapes(raw) {
  // Fast path: nothing to unescape.
  if (raw.indexOf('\\') === -1) return raw;

  let out = '';
  let start = 0;
  let index = raw.indexOf('\\');
  while (index !== -1) {
    if (index + 1 >= raw.length) break; // trailing backslash stays literal
    const next = raw[index + 1];
    let replacement = null;
    let advance = 2;
    if (next === '\\' || next === '"' || next === "'") {
      replacement = next;
    } else if (next === 'r') {
      replacement = '\r';
    } else if (next === 't') {
      replacement = '\t';
    } else if (next === 'x') {
      const hex = raw.slice(index + 2, index + 4);
      if (isHexPair(hex)) {
        replacement = String.fromCharCode(parseInt(hex, 16));
        advance = 4;
      }
    }
    if (replacement === null) {
      // Unknown escape: keep the backslash verbatim, advance one char.
      index += 1;
    } else {
      out += raw.slice(start, index) + replacement;
      index += advance;
      start = index;
    }
    index = raw.indexOf('\\', index);
  }
  out += raw.slice(start);
  return out;
}

/** Recover the string passed to `markdown()` from its archived fence body. */
export function markdownLiteral(raw) { return dedent(decodeEscapes(raw)) };
