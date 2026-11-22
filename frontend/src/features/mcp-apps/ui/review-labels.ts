/**
 * Texts of the review cards (flip-card.tsx, question-card.tsx): sv and en with equal keys. The card's own words
 * (the reveal button, the hidden lead of the answer, the result line) come from here by the room's locale; what a card
 * shows of the item (the prompt, the answer, the options) and what its buttons do arrive as props. `again`, `good`,
 * `next` and `retry` are offered to the caller for the grade and action buttons, so every room says them alike.
 */
const reviewEn = {
  /** The card as a group, for assistive technology. */
  card: "Review card",
  /** The front's one action. */
  reveal: "Show the answer",
  /** Read before the answer when it takes the focus; not drawn. */
  answer: "Answer:",
  /** The group of grade buttons. */
  grades: "How did it go?",
  /** The two grades of a review (FSRS Again and Good). */
  again: "Again",
  good: "Got it",
  /** The card while it loads: the photo is a skeleton and the reveal is held. */
  loading: "Loading the card",
  question: {
    /** The group of answer options. */
    options: "Answers",
    /** The chosen option while the server checks it. */
    checking: "Checking…",
    /** The result line opens with one of these, then the explanation. */
    correct: "Right.",
    wrong: "Not quite.",
    /** The action after a right answer, and after a wrong one (the question is asked again). */
    next: "Next",
    retry: "Try again",
  },
};

export type ReviewLabels = typeof reviewEn;

const reviewSv: ReviewLabels = {
  card: "Repetitionskort",
  reveal: "Visa svaret",
  answer: "Svar:",
  grades: "Hur gick det?",
  again: "Igen",
  good: "Kunde",
  loading: "Kortet laddas",
  question: {
    options: "Svarsalternativ",
    checking: "Rättas…",
    correct: "Rätt.",
    wrong: "Inte riktigt.",
    next: "Nästa",
    retry: "Försök igen",
  },
};

/** The review cards' texts for a room's locale ("sv-SE" or "en-GB"); Swedish unless the locale is English. */
export function reviewLabelsFor(locale: string): ReviewLabels {
  return locale.startsWith("en") ? reviewEn : reviewSv;
}

export { reviewEn, reviewSv };
