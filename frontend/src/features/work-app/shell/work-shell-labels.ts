import type { WorkTab } from "./work-shell";

/**
 * Labels for the fullscreen Work shell (the tab strip and its search). Kept in
 * this file, not in labels.ts and not in @/i18n, so the MCP App bundle does not pull in the Sidekick
 * app catalogue. The types make the Swedish and English key sets identical.
 */
export type WorkShellLabels = {
  /** Accessible name of the tab strip. */
  tabsLabel: string;
  /** Tab names, shown in the strip in the order Agenda, Status, Projekt. */
  tabs: Record<WorkTab, string>;
  /** The search icon in the tab row, its field's name and placeholder (Projekt: searchProjects), and the field's ×. */
  search: string;
  searchProjects: string;
  closeSearch: string;
};

export const workShellLabelsEn: WorkShellLabels = {
  tabsLabel: "Views",
  tabs: {
    agenda: "Agenda",
    board: "Status",
    hierarchy: "Projects",
  },
  search: "Search tasks",
  searchProjects: "Search projects",
  closeSearch: "Close search",
};

export const workShellLabelsSv: WorkShellLabels = {
  tabsLabel: "Vyer",
  tabs: {
    agenda: "Agenda",
    board: "Status",
    hierarchy: "Projekt",
  },
  search: "Sök uppgifter",
  searchProjects: "Sök projekt",
  closeSearch: "Stäng sökningen",
};

/** Shell labels for a host locale; anything that is not Swedish gets English, as in the Work app. */
export function workShellLabelsFor(locale: string): WorkShellLabels {
  return locale.startsWith("sv") ? workShellLabelsSv : workShellLabelsEn;
}
