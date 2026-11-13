import type { RecurrenceRecord } from "../../../lib/mcp/tool-results.generated";

type Rule = Pick<RecurrenceRecord, "frequency" | "interval">;

/** A rule in Swedish words: "varje vecka", "var 2:a vecka", "var 11:e dag". */
function everySv(rule: Rule): string {
  const unit = {
    daily: "dag",
    weekly: "vecka",
    monthly: "månad",
    yearly: "år",
  }[rule.frequency];
  if (rule.interval <= 1) return `varje ${unit}`;
  // Swedish ordinals: 1:a and 2:a (but 11:e, 12:e), every other number :e.
  const tail = rule.interval % 100;
  const suffix =
    (rule.interval % 10 === 1 || rule.interval % 10 === 2) &&
    tail !== 11 &&
    tail !== 12
      ? "a"
      : "e";
  return `var ${rule.interval}:${suffix} ${unit}`;
}

/** A rule in English words: "weekly", "every 2 weeks". */
function everyEn(rule: Rule): string {
  if (rule.interval <= 1)
    return {
      daily: "daily",
      weekly: "weekly",
      monthly: "monthly",
      yearly: "yearly",
    }[rule.frequency];
  const unit = {
    daily: "days",
    weekly: "weeks",
    monthly: "months",
    yearly: "years",
  }[rule.frequency];
  return `every ${rule.interval} ${unit}`;
}

/**
 * Words of the Task's place chip ("Plats: Renovering av köket ⌄"), the repeat chip and its picker, and the "Att sortera"
 * picker. The place picker's own words are in group-select-labels.ts. The Swedish and English key sets must stay identical.
 */
export const taskPlaceLabelsSv = {
  /** The chip's accessible name, before the place: "Ändra plats: Hem". */
  changePlace: "Ändra plats",
  /** The chip's text: the word, then the place's name. */
  chipValue: (place: string) => `Plats: ${place}`,
  /** A Task in no Domain, Project or Process. */
  unsortedName: "Att sortera",
  /** Stand-ins while a place's name cannot be read. */
  domainName: "Domän",
  projectName: "Projekt",
  processName: "Process",
  /** The link to the Project or Process page. */
  open: (place: string) => `Öppna ${place}`,
  /** The picker's accessible name: "Plats för Måla taket". */
  pickerFor: (task: string) => `Plats för ${task}`,
  /** The "Att sortera" row's button that unfolds the picker. */
  choosePlace: "Välj plats…",
  /** Replaces the "Att sortera" intro: the Domain buttons and the picker. */
  unsortedIntro:
    "Ingen plats ännu. Tryck på en domän, eller välj ett projekt eller en process.",
  /** The repeat chip's accessible name, before its text: "Ändra upprepning: Upprepas varje vecka". */
  changeRepeat: "Ändra upprepning",
  /** The repeat chip of a Task that does not repeat (only drawn where the host can set a rule). */
  repeatsNot: "Upprepas inte",
  /** The repeat picker's accessible name: "Upprepning för Måla taket". */
  repeatPickerFor: (task: string) => `Upprepning för ${task}`,
  /** The picker's options: no rule, then the simple rules. */
  repeatOptions: {
    none: "Upprepas inte",
    daily: "Varje dag",
    weekly: "Varje vecka",
    monthly: "Varje månad",
    yearly: "Varje år",
  },
  /** The option that keeps a rule the picker has no word for (every 2nd week, chosen weekdays, an end date). */
  repeatCurrent: (rule: string) => `${rule} (nuvarande)`,
  /** The rule in a list row's meta line, after the repeat glyph: "varje månad", "var 2:a vecka". */
  repeatsShort: (rule: Rule) => everySv(rule),
  /** The repeat chip's text: the rule in words. */
  repeats: (rule: Rule) => `Upprepas ${everySv(rule)}`,
};

export type TaskPlaceLabels = typeof taskPlaceLabelsSv;

export const taskPlaceLabelsEn: TaskPlaceLabels = {
  changePlace: "Change what it’s filed under",
  chipValue: (place) => `Filed under: ${place}`,
  unsortedName: "Unsorted",
  domainName: "Area",
  projectName: "Project",
  processName: "Process",
  open: (place) => `Open ${place}`,
  pickerFor: (task) => `Where ${task} belongs`,
  choosePlace: "Choose where…",
  unsortedIntro: "Not filed yet. Tap an area, or choose a project or process.",
  changeRepeat: "Change how often it repeats",
  repeatsNot: "Doesn’t repeat",
  repeatPickerFor: (task) => `Repeat settings for ${task}`,
  repeatOptions: {
    none: "Doesn’t repeat",
    daily: "Every day",
    weekly: "Every week",
    monthly: "Every month",
    yearly: "Every year",
  },
  repeatCurrent: (rule) => `${rule} (current)`,
  repeatsShort: (rule) => everyEn(rule),
  repeats: (rule) => `Repeats ${everyEn(rule)}`,
};

/** The words for a work locale: Swedish for "sv-SE", English otherwise. */
export function taskPlaceLabelsFor(dateLocale: string): TaskPlaceLabels {
  return dateLocale.toLowerCase().startsWith("sv")
    ? taskPlaceLabelsSv
    : taskPlaceLabelsEn;
}
