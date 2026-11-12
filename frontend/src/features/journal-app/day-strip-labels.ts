/**
 * Labels for the journal week strip. Kept in this file, not in labels.ts and not in @/i18n, so the
 * MCP App bundle does not pull in the Sidekick app catalogue. The Swedish and English key sets must
 * stay identical; journal-day-strip.test.tsx checks that.
 */
export const dayStripLabelsEn = {
  dateLocale: "en-GB",
  group: "Week",
  previousWeek: "Previous week",
  nextWeek: "Next week",
  today: "Today",
  todayMarker: "Today",
  selected: "selected",
  withEntries: "has entries",
};

export type DayStripLabels = typeof dayStripLabelsEn;

export const dayStripLabelsSv: DayStripLabels = {
  dateLocale: "sv-SE",
  group: "Veckan",
  previousWeek: "Föregående vecka",
  nextWeek: "Nästa vecka",
  today: "Idag",
  todayMarker: "Idag",
  selected: "vald",
  withEntries: "har anteckningar",
};
