import {
  everyEn,
  everySv,
  weekdayNamesEn,
  weekdayNamesSv,
  type RuleWords,
} from "./repeat-words";

/**
 * Words of the Task's place chip (the `place` label and the place's name), the repeat chip and its picker, and the `unsortedHeading`
 * picker. The place picker's own words are in group-select-labels.ts. The Swedish and English key sets must stay identical.
 */
export const taskPlaceLabelsSv = {
  /** The chip's accessible name, before the place: `changePlace` and the place. */
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
  /** The picker's accessible name: the place label and the Task title. */
  pickerFor: (task: string) => `Plats för ${task}`,
  /** The `unsortedHeading` row's button that unfolds the picker. */
  choosePlace: "Välj plats…",
  /** Replaces the `unsortedHeading` intro: the Domain buttons and the picker. */
  unsortedIntro:
    "Ingen plats än. Tryck på en domän, eller välj ett projekt eller en process.",
  /** The repeat chip's accessible name, before its text: the change-repeat label and the repeat text. */
  changeRepeat: "Ändra upprepning",
  /** The repeat chip of a Task that does not repeat (only drawn where the host can set a rule). */
  repeatsNot: "Upprepas inte",
  /** The repeat picker's accessible name: the repeat label and the Task title. */
  repeatPickerFor: (task: string) => `Upprepning för ${task}`,
  /** The weekday buttons' group, when the rule is weekly: the label and the Task title. */
  repeatWeekdaysFor: (task: string) => `Veckodagar för ${task}`,
  /** The weekday buttons: the short name on the button, the full name as its accessible name. */
  weekdayNames: weekdayNamesSv,
  /** The picker's options: no rule, then the named rules. */
  repeatOptions: {
    none: "Upprepas inte",
    daily: "Varje dag",
    weekly: "Varje vecka",
    biweekly: "Varannan vecka",
    monthly: "Varje månad",
    lastWeekday: "Sista vardagen i månaden",
    yearly: "Varje år",
  },
  /** The option that keeps a rule the picker has no word for (every 2nd week, chosen weekdays, an end date). */
  repeatCurrent: (rule: string) => `${rule} (nuvarande)`,
  /** The rule in a list row's meta line, after the repeat glyph: the rule in words. */
  repeatsShort: (rule: RuleWords) => everySv(rule),
  /** The repeat chip's text: the rule in words. */
  repeats: (rule: RuleWords) => `Upprepas ${everySv(rule)}`,
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
  repeatWeekdaysFor: (task) => `Repeat days for ${task}`,
  weekdayNames: weekdayNamesEn,
  repeatOptions: {
    none: "Doesn’t repeat",
    daily: "Every day",
    weekly: "Every week",
    biweekly: "Every other week",
    monthly: "Every month",
    lastWeekday: "Last weekday of the month",
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
