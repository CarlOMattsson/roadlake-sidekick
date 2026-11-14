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
  addPhone: "Telefon",
  addEmail: "E-post",
  addRelationship: "Relation",
  /** The accessible names of the three: what they open. */
  addPhoneLabel: "Lägg till telefon",
  addEmailLabel: "Lägg till e-post",
  addRelationshipLabel: "Lägg till relation",
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
  addPhone: "Phone",
  addEmail: "Email",
  addRelationship: "Relationship",
  addPhoneLabel: "Add phone",
  addEmailLabel: "Add email",
  addRelationshipLabel: "Add relationship",
};

export function contactsRoomLabelsFor(locale: string): ContactsRoomLabels {
  return locale.startsWith("sv") ? contactsRoomLabelsSv : contactsRoomLabelsEn;
}
