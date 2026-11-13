/**
 * Words of the saved Work views bar (the "Sparade vyer" button and its panel) that no other control
 * shares. The shared words (Archive, Restore, Undo, Read again, Try again, the refusals) stay in
 * manage-labels.ts. Swedish comes first and is the default; the English key set must stay identical
 * to it (tests/saved-views.test.ts checks that).
 */
export const savedViewsLabelsSv = {
  button: "Sparade vyer",
  saveCurrent: "Spara nuvarande vy",
  nameLabel: "Namn på vyn",
  save: "Spara",
  cancel: "Avbryt",
  rename: "Byt namn",
  renameFor: (name: string) => `Byt namn: ${name}`,
  edit: "Ändra",
  editFor: (name: string) => `Ändra: ${name}`,
  opened: "Öppen",
  openingView: "Öppnar vyn…",
  showingView: (name: string) => `Visar vyn ”${name}”`,
  changedFromView: (name: string) => `Ändrad från vyn ”${name}”`,
  showAll: "Visa allt",
  showAllFailed: "Listan kunde inte läsas. Vyn visas kvar.",
  savingNow: (summary: string) => `Det här sparas: ${summary}`,
  allTasks: "Alla uppgifter",
  tagsAll: (tags: string) => `Taggar: ${tags}`,
  tagsAny: (tags: string) => `Någon av taggarna: ${tags}`,
  priorityIs: (priority: string) => `Prioritet: ${priority}`,
  statusIs: (status: string) => `Status: ${status}`,
  queryIs: (query: string) => `Sök: ${query}`,
  openFailed: "Vyn kunde inte öppnas.",
  severalPriorities:
    "Vyn filtrerar på flera prioriteter. Här visas alla prioriteter.",
  nameRequired: "Skriv ett namn.",
  nameTooLong: "Namnet får vara högst 120 tecken.",
  blockedProject: "Ett enskilt projekts bräde kan inte sparas som vy.",
  saved: (name: string) => `Sparade vyn ”${name}”.`,
  renamed: (name: string) => `Bytte namn till ”${name}”.`,
  archivedView: (name: string) => `Arkiverade vyn ”${name}”.`,
  restoredView: (name: string) => `Återställde vyn ”${name}”.`,
  empty: "Inga sparade vyer än.",
  listLoading: "Läser sparade vyer…",
  listFailed: "De sparade vyerna kunde inte läsas.",
  showArchived: "Visa arkiverade",
  noArchived: "Inga arkiverade vyer.",
};
export type SavedViewsLabels = typeof savedViewsLabelsSv;

export const savedViewsLabelsEn: SavedViewsLabels = {
  button: "Saved views",
  saveCurrent: "Save current view",
  nameLabel: "View name",
  save: "Save",
  cancel: "Cancel",
  rename: "Rename",
  renameFor: (name) => `Rename: ${name}`,
  edit: "Edit",
  editFor: (name) => `Edit: ${name}`,
  opened: "Current",
  openingView: "Opening view…",
  showingView: (name) => `Showing view “${name}”`,
  changedFromView: (name) => `Changed from view “${name}”`,
  showAll: "Show all",
  showAllFailed: "Couldn’t load the list. The view is still shown.",
  savingNow: (summary) => `This saves: ${summary}`,
  allTasks: "All tasks",
  tagsAll: (tags) => `Tags: ${tags}`,
  tagsAny: (tags) => `Any of the tags: ${tags}`,
  priorityIs: (priority) => `Priority: ${priority}`,
  statusIs: (status) => `Status: ${status}`,
  queryIs: (query) => `Search: ${query}`,
  openFailed: "Couldn’t open the view.",
  severalPriorities:
    "This view filters by several priorities. All priorities are shown here.",
  nameRequired: "Enter a name.",
  nameTooLong: "The name can be up to 120 characters.",
  blockedProject: "A single project’s board can’t be saved as a view.",
  saved: (name) => `Saved view “${name}”.`,
  renamed: (name) => `Renamed to “${name}”.`,
  archivedView: (name) => `Archived view “${name}”.`,
  restoredView: (name) => `Restored view “${name}”.`,
  empty: "No saved views yet.",
  listLoading: "Loading saved views…",
  listFailed: "Couldn’t load saved views.",
  showArchived: "Show archived",
  noArchived: "No archived views.",
};

/** The saved-views words for a work locale: Swedish for "sv-SE", English otherwise. */
export function savedViewsLabelsFor(dateLocale: string): SavedViewsLabels {
  return dateLocale.toLowerCase().startsWith("sv")
    ? savedViewsLabelsSv
    : savedViewsLabelsEn;
}
