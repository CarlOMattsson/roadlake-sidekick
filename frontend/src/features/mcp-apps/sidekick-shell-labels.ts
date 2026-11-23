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
  /** Room names. The strip shows work, journal and shopping, then Mer with contacts; Control is named by its own title. */
  rooms: Record<RoomId, string>;
  /**
   * The strip's last cell, "Mer ⌄", and the name of its menu. While a room of Mer is open the cell shows that room's
   * name, and `moreWith` is its accessible name (the visible name first).
   */
  more: string;
  moreMenu: string;
  moreWith: (room: string) => string;
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
  /** The keyboard help (`?`, ui/shortcut-help.tsx) and the shell's own keys in it. */
  shortcuts: {
    /** The help's title, and the row in each room's ⋯ that opens it. */
    title: string;
    close: string;
    /** The group of the keys that work in every room. */
    everywhere: string;
    help: string;
    /** `g 1`–`g 4`: the room in the strip's order. */
    goTo: (room: string) => string;
    /** `g 5`: opens Mer. */
    openMore: string;
    /** Esc, which every own layer (a menu, the help, a search field) closes on. */
    escape: string;
    /** The switch for single-character keys (WCAG 2.1.4). */
    charKeys: string;
    /** The rooms' own keys in the help (j/k, x, [ ], t). */
    nextRow: string;
    previousRow: string;
    toggleDone: string;
    /** The four status keys of a chosen task, with the four status names. */
    setStatus: (names: string) => string;
    previousDay: string;
    nextDay: string;
    previousWeek: string;
    nextWeek: string;
    today: string;
    thisWeek: string;
  };
  /** A wide frame's list beside its detail (ui/split-layout.tsx, desktop spec 2.1). */
  split: {
    /** The kind of what the detail shows, by "room:view", in its head when it has no Back ("Uppgift"). */
    kinds: Record<string, string>;
    /** The ×, closing what the detail shows, by "room:view" ("Stäng uppgiften"); `closeOther` for any other view. */
    close: Record<string, string>;
    closeOther: string;
    /** The sentence of the empty detail, by the list's room ("Välj en uppgift för att se den här"). */
    pick: Record<string, string>;
    pickOther: string;
    /** The keys listed under it. */
    keysLabel: string;
    rows: string;
    open: string;
    add: string;
    help: string;
  };
};

export const sidekickShellLabelsSv: SidekickShellLabels = {
  stripLabel: "Rum",
  more: "Mer",
  moreMenu: "Fler rum",
  moreWith: (room) => `${room}, Mer`,
  rooms: {
    start: "Start",
    work: "Arbete",
    journal: "Dagbok",
    contacts: "Kontakter",
    shopping: "Inköp",
    control: "Kontroll",
  },
  viewNames: {
    "start:suggestions": "Förslag",
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
  shortcuts: {
    title: "Kortkommandon",
    close: "Stäng",
    everywhere: "Överallt",
    help: "Visa kortkommandon",
    goTo: (room) => `Gå till ${room}`,
    openMore: "Öppna Mer",
    escape: "Stäng meny, ruta eller sökning",
    charKeys: "Kortkommandon med en tangent",
    nextRow: "Nästa rad",
    previousRow: "Föregående rad",
    toggleDone: "Klar eller inte klar",
    setStatus: (names) => `Status: ${names}`,
    previousDay: "Föregående dag",
    nextDay: "Nästa dag",
    previousWeek: "Föregående vecka",
    nextWeek: "Nästa vecka",
    today: "Idag",
    thisWeek: "Den här veckan",
  },
  split: {
    kinds: {
      "start:suggestion": "Förslag",
      "work:task": "Uppgift",
      "work:project": "Projekt",
      "work:process": "Process",
      "contacts:contact": "Kontakt",
      "journal:entry": "Anteckning",
      "journal:draft": "Utkast",
    },
    close: {
      "start:suggestion": "Stäng förslaget",
      "work:task": "Stäng uppgiften",
      "work:project": "Stäng projektet",
      "work:process": "Stäng processen",
      "contacts:contact": "Stäng kontakten",
      "journal:entry": "Stäng anteckningen",
      "journal:draft": "Stäng utkastet",
    },
    closeOther: "Stäng",
    pick: {
      start: "Välj ett förslag för att se det här",
      work: "Välj en uppgift för att se den här",
      contacts: "Välj en kontakt för att se den här",
      journal: "Välj en anteckning för att se den här",
    },
    pickOther: "Välj en rad för att se den här",
    keysLabel: "Kortkommandon",
    rows: "Välj rad",
    open: "Öppna",
    add: "Ny",
    help: "Alla kortkommandon",
  },
};

export const sidekickShellLabelsEn: SidekickShellLabels = {
  stripLabel: "Rooms",
  more: "More",
  moreMenu: "More rooms",
  moreWith: (room) => `${room}, More`,
  rooms: {
    start: "Home",
    work: "Work",
    journal: "Journal",
    contacts: "Contacts",
    shopping: "Shopping",
    control: "Control",
  },
  viewNames: {
    "start:suggestions": "Suggestions",
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
  shortcuts: {
    title: "Keyboard shortcuts",
    close: "Close",
    everywhere: "Everywhere",
    help: "Show keyboard shortcuts",
    goTo: (room) => `Go to ${room}`,
    openMore: "Open More",
    escape: "Close a menu, dialog or search",
    charKeys: "Single-key shortcuts",
    nextRow: "Next row",
    previousRow: "Previous row",
    toggleDone: "Done or not done",
    setStatus: (names) => `Status: ${names}`,
    previousDay: "Previous day",
    nextDay: "Next day",
    previousWeek: "Previous week",
    nextWeek: "Next week",
    today: "Today",
    thisWeek: "This week",
  },
  split: {
    kinds: {
      "start:suggestion": "Suggestion",
      "work:task": "Task",
      "work:project": "Project",
      "work:process": "Process",
      "contacts:contact": "Contact",
      "journal:entry": "Entry",
      "journal:draft": "Draft",
    },
    close: {
      "start:suggestion": "Close the suggestion",
      "work:task": "Close the task",
      "work:project": "Close the project",
      "work:process": "Close the process",
      "contacts:contact": "Close the contact",
      "journal:entry": "Close the entry",
      "journal:draft": "Close the draft",
    },
    closeOther: "Close",
    pick: {
      start: "Choose a suggestion to see it here",
      work: "Choose a task to see it here",
      contacts: "Choose a contact to see it here",
      journal: "Choose an entry to see it here",
    },
    pickOther: "Choose a row to see it here",
    keysLabel: "Keyboard shortcuts",
    rows: "Choose a row",
    open: "Open",
    add: "New",
    help: "All shortcuts",
  },
};

export function sidekickShellLabelsFor(locale: AppLocale): SidekickShellLabels {
  return locale === "en" ? sidekickShellLabelsEn : sidekickShellLabelsSv;
}

/**
 * The shell's labels for a room that knows only its date locale ("sv-SE", "en-GB"): the help's texts and the room
 * names, for the keys a room lists in the keyboard help (useRoomShortcuts).
 */
export function shellLabelsForDateLocale(
  dateLocale: string,
): SidekickShellLabels {
  return sidekickShellLabelsFor(dateLocale.startsWith("sv") ? "sv" : "en");
}
