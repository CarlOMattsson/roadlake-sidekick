import type { AppLocale } from "@/features/mcp-apps/app-locale";
import type { RoomId } from "@/features/mcp-apps/router";

/**
 * Labels of the Sidekick shell (room strip, Back, Fäll ihop, the model-context line and the reserve
 * message). Kept next to the shell, not in @/i18n, so the MCP App bundle does not pull in the Sidekick
 * app catalogue. The type makes the Swedish and English sets identical. Swedish is the default.
 */
export type SidekickShellLabels = {
  /** Accessible name of the room strip. */
  stripLabel: string;
  /** Room names. The strip shows work, journal, contacts and shopping; Control is named by its own title. */
  rooms: Record<RoomId, string>;
  /**
   * Names of views a Back can return to, keyed "room:view" ("work:board" is the `status` view). A view without a name
   * is named by its room.
   */
  viewNames: Record<string, string>;
  /** Accessible name of a Back button: the back label and the view name. */
  backTo: (parent: string) => string;
  /** Folds the expanded view back into the card, when the host did not make it fullscreen. */
  collapse: string;
  /** Start of the model-context line: "Visar Kontakter › Anna". */
  viewing: string;
  /** The user message the reserve strip sends to Claude when the host cannot proxy tools. */
  openRoomMessage: (room: string) => string;
  /** The quiet note shown after the host accepted that message. */
  askedNote: (room: string) => string;
  /** A room whose first read the server refused (a missing scope): a calm line, no retry. */
  noAccess: (room: string) => string;
  /** The question before a Back that would drop edits not yet saved, and its two answers. */
  unsavedAsk: string;
  unsavedDiscard: string;
  unsavedKeep: string;
};

export const sidekickShellLabelsSv: SidekickShellLabels = {
  stripLabel: "Rum",
  rooms: {
    work: "Arbete",
    journal: "Dagbok",
    contacts: "Kontakter",
    shopping: "Inköp",
    control: "Kontroll",
  },
  viewNames: {
    "work:agenda": "Agenda",
    "work:board": "Status",
    "work:hierarchy": "Projekt",
    "work:task": "Uppgift",
    "work:project": "Projekt",
    "work:process": "Process",
    "contacts:list": "Kontakter",
    "journal:entry": "Anteckning",
    "shopping:lists": "Listor",
  },
  backTo: (parent) => `Tillbaka till ${parent}`,
  collapse: "Fäll ihop",
  viewing: "Visar",
  openRoomMessage: (room) => `Öppna ${room}`,
  askedNote: (room) => `Bad Claude öppna ${room}`,
  noAccess: (room) => `Sidekick-anslutningen har inte tillgång till ${room}.`,
  unsavedAsk: "Släng ändringarna?",
  unsavedDiscard: "Släng",
  unsavedKeep: "Fortsätt redigera",
};

export const sidekickShellLabelsEn: SidekickShellLabels = {
  stripLabel: "Rooms",
  rooms: {
    work: "Work",
    journal: "Journal",
    contacts: "Contacts",
    shopping: "Shopping",
    control: "Control",
  },
  viewNames: {
    "work:agenda": "Agenda",
    "work:board": "Status",
    "work:hierarchy": "Projects",
    "work:task": "Task",
    "work:project": "Project",
    "work:process": "Process",
    "contacts:list": "Contacts",
    "journal:entry": "Entry",
    "shopping:lists": "Lists",
  },
  backTo: (parent) => `Back to ${parent}`,
  collapse: "Collapse",
  viewing: "Viewing",
  openRoomMessage: (room) => `Open ${room}`,
  askedNote: (room) => `Asked Claude to open ${room}`,
  noAccess: (room) => `The Sidekick connection doesn’t have access to ${room}.`,
  unsavedAsk: "Discard your changes?",
  unsavedDiscard: "Discard",
  unsavedKeep: "Keep editing",
};

export function sidekickShellLabelsFor(locale: AppLocale): SidekickShellLabels {
  return locale === "en" ? sidekickShellLabelsEn : sidekickShellLabelsSv;
}
