/** SVG overlay geometry for review boxes: screen bands, the connected outline
 *  around stacked bands, and the wavy underline.  Pure: no DOM is created. */

/** One screen band of a drawn box, in the region's local coordinates. */
export interface Band { l: number; r: number; t: number; b: number; }

/** Merge the client rectangles of a range into one band per visual line,
 *  grouping by vertical overlap so inline `<code>` spans (which can report a
 *  slightly different top or height) do not break a line into several bands. */
export function mergeBands(rects: DOMRect[], origin: DOMRect): Band[] {
  const bands: Band[] = [];
  for (const rect of rects) {
    if (!rect.width && !rect.height) continue;
    const top = rect.top - origin.top;
    const bottom = rect.bottom - origin.top;
    const left = rect.left - origin.left;
    const right = rect.right - origin.left;
    // Group by vertical overlap as well as equal tops: inline <code> spans can
    // report a slightly different top or height than the surrounding text on
    // the same line, which would otherwise leave a broken ribbon.
    const center = (top + bottom) / 2;
    const band = bands.find(item =>
      Math.abs(item.t - top) < 1
      || Math.abs((item.t + item.b) / 2 - center)
      < Math.max(item.b - item.t, bottom - top) * 0.5);
    if (band) {
      band.l = Math.min(band.l, left);
      band.r = Math.max(band.r, right);
      band.b = Math.max(band.b, bottom);
    } else {
      bands.push({ l: left, r: right, t: top, b: bottom });
    }
  }
  bands.sort((a, b) => a.t - b.t);
  return bands;
}

/** A path that outlines the given bands. One connected outline around stacked
 *  line bands, so a wrapped range reads as a single box instead of one box per
 *  line. */
export function ribbon(bands: Band[]) {
  if (!bands.length) return '';
  const points: [number, number][] = [];
  const first = bands[0];
  points.push([first.l, first.t], [first.r, first.t]);
  for (let index = 1; index < bands.length; index += 1) {
    const previous = bands[index - 1];
    const current = bands[index];
    points.push([previous.r, current.t]);
    if (current.r !== previous.r) points.push([current.r, current.t]);
  }
  const last = bands[bands.length - 1];
  points.push([last.r, last.b], [last.l, last.b]);
  for (let index = bands.length - 2; index >= 0; index -= 1) {
    const below = bands[index + 1];
    const current = bands[index];
    points.push([below.l, current.b]);
    if (current.l !== below.l) points.push([current.l, current.b]);
  }
  return 'M' + points.map(
    point => `${point[0].toFixed(1)} ${point[1].toFixed(1)}`).join('L') + 'Z';
}

/** Wavy underline along the bottom edge of an annotation box. */
export function wavePath(left: number, right: number, y: number) {
  const width = right - left;
  if (width <= 0) return '';
  const step = 6;
  const amplitude = 1.5;
  let d = `M${left.toFixed(1)} ${y.toFixed(1)}`;
  let x = left;
  let up = true;
  while (x < right) {
    const next = Math.min(x + step, right);
    const mid = (x + next) / 2;
    d += `Q${mid.toFixed(1)} ${(up ? y - amplitude : y + amplitude).toFixed(1)}`
      + ` ${next.toFixed(1)} ${y.toFixed(1)}`;
    x = next;
    up = !up;
  }
  return d;
}
