/**
 * Texts of the insight line (insight-line.tsx): sv and en with equal keys, picked by the room's locale. The sentence
 * itself comes from the server in the app's language and is not here.
 */
const insightEn = {
  /** Under a sentence: opens the view that says more ("Show more ›"), or the sentence in place (no ›). */
  more: "Show more",
  /** The sentence opened in place, to close it again. */
  less: "Show less",
};

const insightSv: typeof insightEn = {
  more: "Visa mer",
  less: "Visa mindre",
};

/** The insight line's texts for a room's locale; Swedish unless the locale is English. */
export function insightLabelsFor(locale: string): typeof insightEn {
  return locale.startsWith("en") ? insightEn : insightSv;
}

export { insightEn, insightSv };
