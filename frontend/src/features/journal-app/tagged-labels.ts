/**
 * The Journal room's own tag sentences: the tagged list under the filter, the Tags heading of a draft, and the failures
 * of a tag write. The pills, the field and the filter row speak through the shared tag labels (mcp-apps/ui/tag-labels.ts).
 * Spread into journalEn and journalSv (labels.ts).
 */
export const taggedEn = {
  taggedEntries: "Tagged entries",
  taggedWindow: "The last 12 months, newest first",
  taggedEmpty: (tags: number): string =>
    tags === 1
      ? "No entry from the last 12 months has this tag."
      : "No entry from the last 12 months has all of these tags.",
  taggedCapped: (n: number) =>
    `Showing the oldest ${n}. Choose another tag to narrow the list.`,
  draftTags: "Tags",
  tagsConflict:
    "This entry was changed elsewhere. The latest version is loaded. Check the tags and try again.",
  tagsInvalid: "The tags weren’t accepted. Check them and try again.",
  tagsFailed: "Couldn’t save the tags. Try again.",
};

export const taggedSv: typeof taggedEn = {
  taggedEntries: "Taggade anteckningar",
  taggedWindow: "De senaste 12 månaderna, nyast först",
  taggedEmpty: (tags) =>
    tags === 1
      ? "Ingen anteckning de senaste 12 månaderna har den här taggen."
      : "Ingen anteckning de senaste 12 månaderna har alla de här taggarna.",
  taggedCapped: (n) =>
    `Visar de äldsta ${n}. Välj en tagg till för att begränsa listan.`,
  draftTags: "Taggar",
  tagsConflict:
    "Anteckningen ändrades någon annanstans. Den senaste versionen är inläst. Kontrollera taggarna och försök igen.",
  tagsInvalid: "Taggarna godtogs inte. Kontrollera dem och försök igen.",
  tagsFailed: "Det gick inte att spara taggarna. Försök igen.",
};
