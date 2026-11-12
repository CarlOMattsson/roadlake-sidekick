/**
 * Labels for the new-Task field of the fullscreen Work tabs. Kept in this file, not in labels.ts and not in @/i18n,
 * so the MCP App bundle does not pull in the Sidekick app catalogue. The type makes the Swedish and English key sets
 * identical.
 */
export type NewTaskInputLabels = {
  /** The accessible name of + in the tab row and of the field; the field shows only the placeholder. */
  field: string;
  placeholder: string;
  /** The field's square while it has text: + adds the Task. */
  add: string;
  /** The field's square while it is empty: × closes the field. */
  close: string;
  /** Announced (and on Status and Projekt shown) after a create; `title` is the new Task's title, `place` where it went (a Domain, Project or Process title, or `unsorted`). */
  added: (title: string, place: string) => string;
  /** The place a Task without one waits in: the To sort list. */
  unsorted: string;
  /** The name of the place row under the field; it is the accessible name of the picker. */
  place: string;
  /** Shown under the field when create_task failed for a reason a retry can fix; `title` is what was typed. */
  failed: (title: string) => string;
  /** Heading of the Agenda group that lists the Tasks added here, with their count. */
  recentHeading: (count: number) => string;
  /** The meta line of a new Task: it has no due date. */
  undated: string;
};

export const newTaskInputLabelsSv: NewTaskInputLabels = {
  field: "Ny uppgift",
  placeholder: "Ny uppgift, t.ex. ring Anna",
  add: "Lägg till uppgift",
  close: "Stäng",
  added: (title, place) => `${title} tillagd i ${place}`,
  unsorted: "Att sortera",
  place: "Plats",
  failed: (title) => `Det gick inte att lägga till ”${title}”.`,
  recentHeading: (count) => `Nyss tillagda (${count})`,
  undated: "Utan datum",
};

export const newTaskInputLabelsEn: NewTaskInputLabels = {
  field: "New task",
  placeholder: "New task, e.g. call Anna",
  add: "Add task",
  close: "Close",
  added: (title, place) => `${title} added to ${place}`,
  unsorted: "Unsorted",
  place: "Place",
  failed: (title) => `Couldn’t add “${title}”.`,
  recentHeading: (count) => `Just added (${count})`,
  undated: "No date",
};

/** The labels for a date locale such as "sv-SE" or "en-GB"; English for anything not Swedish. */
export function newTaskInputLabelsFor(dateLocale: string): NewTaskInputLabels {
  return dateLocale.toLowerCase().startsWith("sv")
    ? newTaskInputLabelsSv
    : newTaskInputLabelsEn;
}
