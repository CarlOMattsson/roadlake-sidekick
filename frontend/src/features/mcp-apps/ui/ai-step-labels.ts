/**
 * Texts of the AI Step mark (ai-step-mark.tsx): sv and en with equal keys. They follow the room's date locale, so the
 * mark carries no app catalogue of its own. A done Step says nothing about where it stands: the tick says it.
 */
const aiStepEn = {
  /** Who does the Step. */
  performer: { owner: "You", ai: "AI" },
  /** Where an AI Step stands; absent for a done Step. */
  status: {
    waiting: "waiting",
    ready: "ready",
    running: "running",
    to_review: "to review",
    needs_input: "question",
    failed: "failed",
    stopped: "stopped",
    exhausted: "out of attempts",
  },
  /** Read once for the whole mark: who does the Step and, for an AI Step, where it stands. */
  reading: (performer: string, status?: string) =>
    status
      ? `Performed by ${performer}, ${status}`
      : `Performed by ${performer}`,
};

export type AiStepLabels = typeof aiStepEn;

const aiStepSv: AiStepLabels = {
  performer: { owner: "Du", ai: "AI" },
  status: {
    waiting: "väntar",
    ready: "redo",
    running: "pågår",
    to_review: "att granska",
    needs_input: "fråga",
    failed: "misslyckades",
    stopped: "stoppad",
    exhausted: "försöken slut",
  },
  reading: (performer, status) =>
    status ? `Görs av ${performer}, ${status}` : `Görs av ${performer}`,
};

/** The mark's texts for a room's date locale ("sv-SE" or "en-GB"); Swedish unless the locale is English. */
export function aiStepLabelsFor(locale: string): AiStepLabels {
  return locale.startsWith("en") ? aiStepEn : aiStepSv;
}

export { aiStepEn, aiStepSv };
