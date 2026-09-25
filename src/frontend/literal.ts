function hasContent(text: string) {
  for (let index = 0; index < text.length; index += 1) {
    const code = text.charCodeAt(index);
    // Treat anything outside ASCII indentation whitespace as content.
    if (code !== 32 && code !== 9 && code !== 13) return true;
  }
  return false;
}

function dedentWithMap(text: string, offsets: number[]) {
  if (!text) return { text: '', map: [] };
  const lines = text.split('\n');
  const starts = [];
  let cursor = 0;
  for (const line of lines) {
    starts.push(cursor);
    cursor += line.length + 1;
  }
  let first = 0;
  while (first < lines.length && !hasContent(lines[first])) first += 1;
  if (first === lines.length) return { text: '', map: [] };
  let last = lines.length;
  while (last > first && !hasContent(lines[last - 1])) last -= 1;

  const out = [];
  const map = [];
  for (let index = first; index < last; index += 1) {
    if (index > first) {
      out.push('\n');
      map.push(offsets[starts[index] - 1]);
    }
    const line = lines[index];
    if (!hasContent(line)) continue;
    const from = line.startsWith('    ') ? 4 : 0;
    for (let column = from; column < line.length; column += 1) {
      out.push(line[column]);
      map.push(offsets[starts[index] + column]);
    }
  }
  return { text: out.join(''), map };
}

function isHexPair(text: string) {
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

function decodeEscapesWithMap(raw: string) {
  const out: string[] = [];
  const offsets: number[] = [];  // raw offset ror every decoded char in out
  let index = 0;
  while (index < raw.length) {
    const char = raw[index];
    if (char === '\\' && index + 1 < raw.length) {
      const next = raw[index + 1];
      let replacement = null;
      let advance = 2;
      if (next === '\\' || next === '"' || next === "'") {
        replacement = next;
      } else if (next === 'r') {
        replacement = '\r';
      } else if (next === 't') {
        replacement = '\t';
      } else if (next === 'x' && isHexPair(raw.slice(index + 2, index + 4))) {
        replacement = String.fromCharCode(parseInt(raw.slice(index + 2, index + 4), 16));
        advance = 4;
      }
      if (replacement !== null) {
        out.push(replacement);
        offsets.push(index);
        index += advance;
        continue;
      }
    }
    out.push(char);
    offsets.push(index);
    index += 1;
  }
  return { text: out.join(''), offsets };
}

/** Decode and dedent a markdown region while recording, for every decoded
 *  character, the raw offset it came from. The map is monotonic, so a raw
 *  offset can be searched back to a decoded index. */
export function markdownMap(raw: string) {
  const { text, offsets } = decodeEscapesWithMap(raw);
  return dedentWithMap(text, offsets);
}
