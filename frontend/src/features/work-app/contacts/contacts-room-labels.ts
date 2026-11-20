/**
 * Words of the Contacts room's first steps: the empty list and a new Contact with
 * nothing saved yet. Each example is one sentence the user could say to Claude, and also the message that is sent.
 */
export const contactsRoomLabelsSv = {
  /** The empty list's second line: what the room holds. */
  emptyHint: "Namn, hur ni känner varandra och hur du når dem.",
  emptyAsk: "Spara Anna Andersson som kontakt – hon är min revisor",
  /** A Contact with nothing saved but the name. */
  bareTitle: (first: string) => `Inget sparat om ${first} än.`,
  bareAsk: (name: string) =>
    `Jag vill berätta vad jag vet om ${name} så att det sparas på kontakten.`,
  /** The empty list's own way to start, next to the empty state's ask-Claude line: it opens the create field as + does. */
  addContact: "Lägg till en kontakt",
  /** A search with no match: the row that creates a Contact with the searched name. */
  createNamed: (name: string) => `Skapa kontakt ”${name}”`,
  /** What a search with no match says to Claude: one sentence, also the message that is sent. */
  createNamedAsk: (name: string) => `Spara ${name} som kontakt`,
  /** Tags are chosen in the filter and no Contact has them: not an empty room, so no first steps. */
  noContactsWithTags: (tags: string[], search: string) =>
    `Ingen kontakt${search ? ` som matchar ”${search}”` : ""} har ${tags.length === 1 ? "taggen" : "alla taggarna"} ${new Intl.ListFormat("sv-SE", { type: "conjunction" }).format(tags)}.`,
  /** A new Contact whose name another Contact already has: the warning, its two ways on. */
  sameName: (name: string) => `Det finns redan en kontakt som heter ”${name}”.`,
  openExisting: (profile: string) => `Öppna ${profile}`,
  createAnyway: "Skapa ändå",
  addPhone: "Telefon",
  addEmail: "E-post",
  addRelationship: "Relation",
  /** The accessible names of the three: what they open. */
  addPhoneLabel: "Lägg till telefon",
  addEmailLabel: "Lägg till e-post",
  addRelationshipLabel: "Lägg till relation",
  /** The Contact's own "new Task" action: the + beside Tasks, or the row where the section would stand. */
  newTaskFor: (first: string) => `Ny uppgift för ${first}`,
  /** The Contact card's standing line: who you wait on and for how long (`days` null when the wait has no date). */
  waitingOn: (first: string, days: number | null) =>
    days === null
      ? `Du väntar på ${first}`
      : days === 0
        ? `Du väntar på ${first} sedan idag`
        : `Du väntar på ${first} sedan ${days} ${days === 1 ? "dag" : "dagar"}`,
  /** The meta line under it: the Task waited on, and how many more wait on her. */
  waitingTask: (title: string, more: number) =>
    more > 0 ? `${title} · ${more} till` : title,
  /** The newest linked journal entry's day: when you last had contact, as far as the journal knows. */
  lastInJournal: (day: string) => `Senast i dagboken ${day}`,
  /** The receipt bar's messages after a Contact write (no closing full stop). */
  receiptArchived: "Kontakten är arkiverad",
  receiptRestored: "Kontakten är återställd",
  receiptSaved: "Kontakten sparades",
  /** The inline card's one main link. */
  openContact: "Öppna kontakten",
  /** A next page that could not be read while the first is shown: the message box's title (its button is Try again). */
  moreFailed: "Det gick inte att läsa fler",
  /** A search with no match: empties the search field. */
  clearSearch: "Rensa sökningen",
  /** A search with no match among the listed Contacts, but some among the archived: the row that shows them. */
  showArchivedMatches: (count: number) =>
    `Visa ${count} ${count === 1 ? "arkiverad som matchar" : "arkiverade som matchar"}`,
  /** A Slack workspace link has no readable name, so the row says what it does. */
  openInSlack: "Öppna i Slack",
};

export type ContactsRoomLabels = typeof contactsRoomLabelsSv;

export const contactsRoomLabelsEn: ContactsRoomLabels = {
  emptyHint: "Names, how you know each other, and how to reach them.",
  emptyAsk: "Save Anna Andersson as a contact – she’s my accountant",
  bareTitle: (first) => `Nothing saved about ${first} yet.`,
  bareAsk: (name) =>
    `I’d like to tell you what I know about ${name} so you can save it on the contact.`,
  addContact: "Add a contact",
  createNamed: (name) => `Create contact “${name}”`,
  createNamedAsk: (name) => `Save ${name} as a contact`,
  noContactsWithTags: (tags, search) =>
    `No contact${search ? ` matching “${search}”` : ""} has ${tags.length === 1 ? "the tag" : "all of the tags"} ${new Intl.ListFormat("en-GB", { type: "conjunction" }).format(tags)}.`,
  sameName: (name) => `You already have a contact named “${name}”.`,
  openExisting: (profile) => `Open ${profile}`,
  createAnyway: "Create anyway",
  addPhone: "Phone",
  addEmail: "Email",
  addRelationship: "Relationship",
  addPhoneLabel: "Add phone",
  addEmailLabel: "Add email",
  addRelationshipLabel: "Add relationship",
  newTaskFor: (first) => `New task for ${first}`,
  waitingOn: (first, days) =>
    days === null
      ? `You are waiting on ${first}`
      : days === 0
        ? `You are waiting on ${first} since today`
        : `You are waiting on ${first} for ${days} ${days === 1 ? "day" : "days"}`,
  waitingTask: (title, more) => (more > 0 ? `${title} · ${more} more` : title),
  lastInJournal: (day) => `Last in the journal ${day}`,
  receiptArchived: "Contact archived",
  receiptRestored: "Contact restored",
  receiptSaved: "Contact saved",
  openContact: "Open contact",
  moreFailed: "Couldn’t load more",
  clearSearch: "Clear search",
  showArchivedMatches: (count) =>
    `Show ${count} archived ${count === 1 ? "match" : "matches"}`,
  openInSlack: "Open in Slack",
};

export function contactsRoomLabelsFor(locale: string): ContactsRoomLabels {
  return locale.startsWith("sv") ? contactsRoomLabelsSv : contactsRoomLabelsEn;
}
