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
  weekLoading: "Läser in veckan…",
};
