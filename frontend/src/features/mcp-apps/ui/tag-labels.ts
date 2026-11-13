/**
 * Texts of the shared tag parts (tags.tsx): sv and en with equal keys. They follow the room's date locale, so
 * the parts carry no app catalogue of their own.
 */
const tagEn = {
  /** Read before the tags of a row or a card. */
  tags: "Tags",
  /** "+2" read out. */
  more: (n: number) => `${n} more`,
  /** The closed field's button when the record has no tag yet. */
  add: "Add tag",
  /** The closed field's button when it has tags. */
  edit: "Edit tags",
  editFor: (name: string) => `Edit tags for ${name}`,
  remove: (tag: string) => `Remove tag ${tag}`,
  input: "New tag",
  placeholder: "Type a tag",
  addButton: "Add",
  done: "Done",
  /** The heading of the suggestion chips under the field. */
  suggested: "Your tags",
  suggest: (tag: string) => `Add tag ${tag}`,
  tooLong: (max: number) => `A tag can be at most ${max} characters.`,
  full: (max: number) => `At most ${max} tags.`,
  /** The filter row. */
  filter: "Filter by tag",
  clear: (n: number) => `Clear (${n})`,
  clearLabel: "Clear tag filter",
  filterFull: (max: number) => `At most ${max} tags at once.`,
  /** Read after a filtered list: what it is narrowed to (every tag, "all" match). */
  filtered: (tags: string[]) =>
    `Showing items tagged ${new Intl.ListFormat("en-GB", { type: "conjunction" }).format(tags)}`,
};

const tagSv: typeof tagEn = {
  tags: "Taggar",
  more: (n) => `${n} till`,
  add: "Lägg till tagg",
  edit: "Ändra taggar",
  editFor: (name) => `Ändra taggar för ${name}`,
  remove: (tag) => `Ta bort taggen ${tag}`,
  input: "Ny tagg",
  placeholder: "Skriv en tagg",
  addButton: "Lägg till",
  done: "Klar",
  suggested: "Dina taggar",
  suggest: (tag) => `Lägg till taggen ${tag}`,
  tooLong: (max) => `En tagg får vara högst ${max} tecken.`,
  full: (max) => `Högst ${max} taggar.`,
  filter: "Filtrera på tagg",
  clear: (n) => `Rensa (${n})`,
  clearLabel: "Rensa taggfiltret",
  filterFull: (max) => `Högst ${max} taggar åt gången.`,
  filtered: (tags) =>
    `Visar det som har ${tags.length === 1 ? "taggen" : "taggarna"} ${new Intl.ListFormat("sv-SE", { type: "conjunction" }).format(tags)}`,
};

export type TagLabels = typeof tagEn;

/** The tag texts for a room's date locale ("sv-SE" or "en-GB"); Swedish unless the locale is English. */
export function tagLabelsFor(locale: string): TagLabels {
  return locale.startsWith("en") ? tagEn : tagSv;
}

export { tagEn, tagSv };
