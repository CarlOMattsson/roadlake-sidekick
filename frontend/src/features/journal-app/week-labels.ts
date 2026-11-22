/**
 * The Journal room's week view: the switch between a day and a calendar week, the week's heading and its empty days.
 * Spread into journalEn and journalSv (labels.ts).
 */
export const weekEn = {
  /** The name of the switch and its two choices. */
  viewSwitch: "View",
  viewDay: "Day",
  viewWeek: "Week",
  /** The week view's heading: the ISO week number, then the days it spans ("Week 47 · 16–22 Nov"). */
  weekTitle: (number: number, range: string): string =>
    `Week ${number} · ${range}`,
  weekPrevious: "Previous week",
  weekNext: "Next week",
  weekThis: "This week",
  /** A day of the week with no entry and no summary. */
  weekDayEmpty: "Nothing written",
  /** A run of days with nothing, one quiet line ("Nothing written Mon–Wed"), and a whole week of them. */
  weekGapNothing: (range: string): string => `Nothing written ${range}`,
  weekGapWeek: (number: number): string => `Nothing written week ${number}`,
  /** The link of that line: opens the day view on the first empty day, where the owner writes. */
  weekGapWrite: "Write for a day",
  weekLoading: "Loading the week…",
};

export const weekSv: typeof weekEn = {
  viewSwitch: "Visning",
  viewDay: "Dag",
  viewWeek: "Vecka",
  weekTitle: (number: number, range: string): string =>
    `Vecka ${number} · ${range}`,
  weekPrevious: "Föregående vecka",
  weekNext: "Nästa vecka",
  weekThis: "Denna vecka",
  weekDayEmpty: "Inget skrivet",
  weekGapNothing: (range: string): string => `Inget skrivet ${range}`,
  weekGapWeek: (number: number): string => `Inget skrivet vecka ${number}`,
  weekGapWrite: "Skriv för en dag",
  weekLoading: "Läser in veckan…",
};
