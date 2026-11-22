/**
 * The texts of the history and trash tables (control-table.tsx), drawn from 48rem: the column heads and the room a
 * record belongs to. Swedish first; the day headings come from the shared date words (day-groups.ts), not from here.
 */
export type TableLabels = {
  columns: {
    what: string;
    room: string;
    event: string;
    who: string;
    when: string;
    deleted: string;
    /** The last column holds Undo or Restore; its head is read, not drawn. */
    action: string;
  };
  /** The room each kind of record lives in, as the shell names it. */
  rooms: Record<"work" | "journal" | "contacts" | "shopping", string>;
};

export const tableEn: TableLabels = {
  columns: {
    what: "What",
    room: "Room",
    event: "Event",
    who: "Who",
    when: "When",
    deleted: "Deleted",
    action: "Action",
  },
  rooms: {
    work: "Work",
    journal: "Journal",
    contacts: "Contacts",
    shopping: "Shopping",
  },
};

export const tableSv: TableLabels = {
  columns: {
    what: "Vad",
    room: "Rum",
    event: "Händelse",
    who: "Vem",
    when: "När",
    deleted: "Borttaget",
    action: "Åtgärd",
  },
  rooms: {
    work: "Arbete",
    journal: "Dagbok",
    contacts: "Kontakter",
    shopping: "Inköp",
  },
};
