const ELLIPSIS = "…";
// Sentence and clause punctuation that would sit against the ellipsis ("garanti.…").
const TRAILING_PUNCTUATION = /[\s.,;:!?\-–—]+$/;

/**
 * A word longer than this (a URL, a hash) may be cut inside, when whole words leave a line mostly empty because the
 * next one cannot fit on it. Ordinary words are never cut.
 */
const LONG_WORD = 24;

/**
 * The longest run of whole words of `text` that still fits when "…" is added, cut at a word boundary with the
 * punctuation before the ellipsis dropped. `fits` answers for a candidate string whether it takes no more room than
 * allowed (the caller measures it); `text` itself is returned when it fits whole. When the word that does not fit is
 * longer than LONG_WORD, the cut falls inside it, as far as it fits. A shorter word that is too long for the room
 * gives just the ellipsis.
 */
export function clipAtWord(
  text: string,
  fits: (candidate: string) => boolean,
): string {
  if (fits(text)) return text;
  // The end of every word: each position where a run of whitespace begins, and where the next word starts.
  const gaps = [...text.matchAll(/\s+/g)].map((match) => ({
    end: match.index ?? 0,
    next: (match.index ?? 0) + match[0].length,
  }));
  const candidate = (end: number) =>
    text.slice(0, end).replace(TRAILING_PUNCTUATION, "") + ELLIPSIS;
  let low = 0;
  let high = gaps.length - 1;
  let best = ELLIPSIS;
  let fitted = -1;
  while (low <= high) {
    const middle = (low + high) >> 1;
    const clipped = candidate(gaps[middle]?.end ?? 0);
    if (fits(clipped)) {
      best = clipped;
      fitted = middle;
      low = middle + 1;
    } else {
      high = middle - 1;
    }
  }
  // The word that did not fit: from after the last gap that did, to the next gap or the end of the text.
  const from = fitted >= 0 ? (gaps[fitted]?.next ?? 0) : 0;
  const to = gaps[fitted + 1]?.end ?? text.length;
  if (to - from <= LONG_WORD) return best;
  let inside = from;
  low = from + 1;
  high = to - 1;
  while (low <= high) {
    const middle = (low + high) >> 1;
    if (fits(candidate(middle))) {
      inside = middle;
      low = middle + 1;
    } else {
      high = middle - 1;
    }
  }
  return inside > from ? candidate(inside) : best;
}
