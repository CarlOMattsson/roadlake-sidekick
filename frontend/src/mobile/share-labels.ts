import type { AppLocale } from "@/features/mcp-apps/app-locale";

/**
 * The texts of the share sheet (share-sheet.tsx): what appears when another app shares text or a link to Sidekick. The
 * types make the Swedish and English sets identical (locale parity); Swedish is the default. Headings and buttons end
 * without a full stop, sentences end with one (designsystem §1.6).
 */
export type ShareLabels = {
  title: string;
  /** The name of the choice between a task and the journal, for assistive technology. */
  kindLabel: string;
  kindTask: string;
  kindJournal: string;
  titleLabel: string;
  titleRequired: string;
  /** The heading over the shared text. */
  sharedLabel: string;
  save: string;
  saving: string;
  cancel: string;
  /** The line that says the save failed; the sheet keeps what was typed and Save sends it again. */
  failed: string;
  savedTask: string;
  savedJournal: string;
  done: string;
  /** Shown on the pairing screen while a share waits: the text is kept until the phone is paired. */
  needsPairing: string;
};

export const shareLabelsSv: ShareLabels = {
  title: "Dela till Sidekick",
  kindLabel: "Spara som",
  kindTask: "Uppgift",
  kindJournal: "Dagens dagbok",
  titleLabel: "Titel",
  titleRequired: "Skriv en titel.",
  sharedLabel: "Delad text",
  save: "Spara",
  saving: "Sparar…",
  cancel: "Avbryt",
  failed: "Det gick inte att spara. Texten finns kvar.",
  savedTask: "Sparad som uppgift.",
  savedJournal: "Tillagd i dagens dagbok.",
  done: "Klar",
  needsPairing:
    "Du delade en text till Sidekick. Koppla telefonen först, så kan du spara den.",
};

export const shareLabelsEn: ShareLabels = {
  title: "Share to Sidekick",
  kindLabel: "Save as",
  kindTask: "Task",
  kindJournal: "Today’s journal",
  titleLabel: "Title",
  titleRequired: "Enter a title.",
  sharedLabel: "Shared text",
  save: "Save",
  saving: "Saving…",
  cancel: "Cancel",
  failed: "Couldn’t save. Your text is still here.",
  savedTask: "Saved as a task.",
  savedJournal: "Added to today’s journal.",
  done: "Done",
  needsPairing:
    "You shared text to Sidekick. Connect the phone first, then you can save it.",
};

export function shareLabelsFor(locale: AppLocale): ShareLabels {
  return locale === "en" ? shareLabelsEn : shareLabelsSv;
}
