/**
 * The Journal room's own tag sentences: the tagged list under the filter, the Tags heading of a draft, and the failures
 * of a tag write. The pills, the field and the filter row speak through the shared tag labels (mcp-apps/ui/tag-labels.ts).
 * Spread into journalEn and journalSv (labels.ts).
 */
export const taggedEn = {
  taggedEntries: "Tagged entries",
  /** What the list holds and how far back it reaches: one window of 12 months, and one more for each "Show more". */
  taggedScope: (tags: string[], years: number): string =>
    `Entries tagged ${new Intl.ListFormat("en-GB", { type: "conjunction" }).format(tags)} from ${
      years === 1 ? "the last 12 months" : `the last ${years} years`
    }, newest first`,
  /** Reads the 12 months before the oldest window read. */
  taggedMore: "Show more",
  /** One window came back empty; "Show more" can still reach further back. */
  taggedNoOlder: (tags: number): string =>
    tags === 1
      ? "No entries with this tag in the 12 months before that."
      : "No entries with all of these tags in the 12 months before that.",
  taggedCapped: (n: number) =>
    `Showing the newest ${n}. Add another tag to narrow the list.`,
  draftTags: "Tags",
  tagsConflict:
    "This entry was changed elsewhere. The latest version is loaded. Check the tags and try again.",
  tagsInvalid: "The tags weren’t accepted. Check them and try again.",
  tagsFailed: "Couldn’t save the tags. Try again.",
};

export const taggedSv: typeof taggedEn = {
  taggedEntries: "Taggade anteckningar",
  taggedScope: (tags, years) =>
    `Anteckningar med ${tags.length === 1 ? "taggen" : "taggarna"} ${new Intl.ListFormat("sv-SE", { type: "conjunction" }).format(tags)} från ${
      years === 1 ? "de senaste 12 månaderna" : `de senaste ${years} åren`
    }, nyast först`,
  taggedMore: "Visa fler",
  taggedNoOlder: (tags) =>
    tags === 1
      ? "Ingen anteckning med den här taggen under de 12 månaderna före det."
      : "Ingen anteckning med alla de här taggarna under de 12 månaderna före det.",
  taggedCapped: (n) =>
    `Visar de nyaste ${n}. Välj en tagg till för att begränsa listan.`,
  draftTags: "Taggar",
  tagsConflict:
    "Anteckningen ändrades någon annanstans. Den senaste versionen är inläst. Kontrollera taggarna och försök igen.",
  tagsInvalid: "Taggarna godtogs inte. Kontrollera dem och försök igen.",
  tagsFailed: "Det gick inte att spara taggarna. Försök igen.",
};
