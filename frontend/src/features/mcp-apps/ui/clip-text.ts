const ELLIPSIS = "…";
// Sentence and clause punctuation that would sit against the ellipsis ("garanti.…").
const TRAILING_PUNCTUATION = /[\s.,;:!?\-–—]+$/;

/**
 * The longest run of whole words of `text` that still fits when "…" is added, cut at a word boundary with the
 * punctuation before the ellipsis dropped. `fits` answers for a candidate string whether it takes no more room than
 * allowed (the caller measures it); `text` itself is returned when it fits whole. A single word that is too long for
 * the room gives just the ellipsis.
 */
export function clipAtWord(
  text: string,
  fits: (candidate: string) => boolean,
): string {
  if (fits(text)) return text;
  // The end of every word: each position where a run of whitespace begins.
  const ends = [...text.matchAll(/\s+/g)].map((match) => match.index ?? 0);
  const candidate = (end: number) =>
    text.slice(0, end).replace(TRAILING_PUNCTUATION, "") + ELLIPSIS;
  let low = 0;
  let high = ends.length - 1;
  let best = ELLIPSIS;
  while (low <= high) {
    const middle = (low + high) >> 1;
    const clipped = candidate(ends[middle] ?? 0);
    if (fits(clipped)) {
      best = clipped;
      low = middle + 1;
    } else {
      high = middle - 1;
    }
  }
  return best;
}
