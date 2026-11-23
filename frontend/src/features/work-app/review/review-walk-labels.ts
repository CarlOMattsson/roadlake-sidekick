import { agendaLabelsEn, agendaLabelsSv } from "../agenda/agenda-labels";
import { workEn, workSv } from "../shared/labels";

/**
 * Words of the review card (review-walk-card.tsx): the walk through the review queue one Task at a time. Swedish comes
 * first and is the default; the English key set must stay identical to it (review-walk-labels test). The date choices
 * and Ångra are the agenda's own words, so a Task is moved with the same names in every view.
 */
export const reviewWalkSv = {
  dateLocale: "sv-SE",
  /** The card's kicker: the app, then what the card is. */
  appName: "Sidekick",
  kind: "Genomgång",
  /** Where the walk stands: the Task shown is `n` of `total`. */
  position: (n: number, total: number) => `${n} av ${total}`,
  /** Passes the Task by without a decision; it stays in the queue. */
  skip: "Hoppa över",
  /** The group of decision buttons, for assistive technology. */
  decisions: "Vad ska hända med uppgiften?",
  /** The group of date choices after Flytta. */
  moveChoices: "Flytta till",
  done: "Klar",
  keep: "Behåll",
  move: "Flytta",
  /** Moves the Task to the trash; Ångra takes it back, and so does Borttaget in Kontroll. */
  trash: "Ta bort",
  tomorrow: agendaLabelsSv.triageTomorrow,
  nextWeek: agendaLabelsSv.triageNextWeek,
  cancel: "Avbryt",
  /** On the chosen button while the decision is saved. */
  saving: "Sparar…",
  undo: workSv.agendaUndo,
  /** The receipt's word before the title, per decision. */
  receipt: {
    done: "Klar",
    keep: "Behållen",
    tomorrow: "Flyttad till imorgon",
    next_week: "Flyttad till nästa vecka",
    trash: "Borttagen",
  },
  /** Why the Task is in the queue, by bucket; `date` is the day as the agenda writes it ("3 nov", "igår"). */
  reason: {
    likelyDone: "Alla steg klara",
    overdue: (date: string) => `Försenad sedan ${date}`,
    followUp: (date: string) => `Följ upp, sedan ${date}`,
    due: (date: string) => `Förfaller ${date}`,
    noDue: "Inget datum",
  },
  /** The walk is through: what was decided here. */
  finished: "Genomgången är klar",
  finishedSummary: (decided: number, skipped: number) =>
    [
      `${decided} beslut`,
      skipped > 0
        ? `${skipped} ${skipped === 1 ? "hoppad" : "hoppade"} över`
        : "",
    ]
      .filter(Boolean)
      .join(" · "),
  empty: "Inget att gå igenom",
  emptyHint: "Alla öppna uppgifter är genomgångna den här veckan.",
  /** While the next page of the queue is read. */
  loadingMore: "Hämtar fler uppgifter…",
  conflict: "Uppgiften ändrades nyss någon annanstans.",
  reread: "Läs in den igen",
  failed: "Beslutet kunde inte sparas.",
  undoFailed: "Det gick inte att ångra.",
  gone: "Uppgiften finns inte längre.",
  forbidden: workSv.forbiddenWrite,
  retry: workSv.retry,
  /** Read out when a new Task comes up. */
  announce: (n: number, total: number, title: string) =>
    `${n} av ${total}: ${title}`,
  /** What the host model is told after each decision or undo, so the conversation knows what the card did. */
  modelNote: (counts: ReviewCounts, left: number) =>
    `Genomgång i kortet: ${counts.decided} beslut sparade (${counts.done} klara, ${counts.kept} behållna, ${counts.moved} flyttade, ${counts.trashed} borttagna), ${counts.skipped} överhoppade, ${left} kvar.`,
};

export type ReviewWalkLabels = typeof reviewWalkSv;

/** What the card has done so far, for the model note. */
export type ReviewCounts = {
  decided: number;
  done: number;
  kept: number;
  moved: number;
  trashed: number;
  skipped: number;
};

export const reviewWalkEn: ReviewWalkLabels = {
  dateLocale: "en-GB",
  appName: "Sidekick",
  kind: "Review",
  position: (n, total) => `${n} of ${total}`,
  skip: "Skip",
  decisions: "What should happen to the task?",
  moveChoices: "Move to",
  done: "Done",
  keep: "Keep",
  move: "Move",
  trash: "Delete",
  tomorrow: agendaLabelsEn.triageTomorrow,
  nextWeek: agendaLabelsEn.triageNextWeek,
  cancel: "Cancel",
  saving: "Saving…",
  undo: workEn.agendaUndo,
  receipt: {
    done: "Done",
    keep: "Kept",
    tomorrow: "Moved to tomorrow",
    next_week: "Moved to next week",
    trash: "Deleted",
  },
  reason: {
    likelyDone: "All steps done",
    overdue: (date) => `Overdue since ${date}`,
    followUp: (date) => `Follow up, since ${date}`,
    due: (date) => `Due ${date}`,
    noDue: "No due date",
  },
  finished: "The review is done",
  finishedSummary: (decided, skipped) =>
    [
      `${decided} ${decided === 1 ? "decision" : "decisions"}`,
      skipped > 0 ? `${skipped} skipped` : "",
    ]
      .filter(Boolean)
      .join(" · "),
  empty: "Nothing to review",
  emptyHint: "Every open task has been reviewed this week.",
  loadingMore: "Loading more tasks…",
  conflict: "The task was just changed somewhere else.",
  reread: "Read it again",
  failed: "The decision couldn’t be saved.",
  undoFailed: "Couldn’t undo.",
  gone: "The task no longer exists.",
  forbidden: workEn.forbiddenWrite,
  retry: workEn.retry,
  announce: (n, total, title) => `${n} of ${total}: ${title}`,
  modelNote: (counts, left) =>
    `Review in the card: ${counts.decided} decisions saved (${counts.done} done, ${counts.kept} kept, ${counts.moved} moved, ${counts.trashed} deleted), ${counts.skipped} skipped, ${left} left.`,
};

/** The words for the app's locale; Swedish unless it is English. */
export function reviewWalkLabelsFor(locale: string): ReviewWalkLabels {
  return locale.startsWith("sv") ? reviewWalkSv : reviewWalkEn;
}
