# Contacts

[Svenska](contacts.sv.md)

<!-- description: The Contacts room shows people and organisations in context. How to search, add, edit and link contacts. -->

Contacts (Kontakter) is the room for people and organisations. Each contact is shown together with the tasks, notes and projects that belong to it.

![The Contacts room showing a fictitious supplier with role, organisation and notes.](../images/rooms/contact.png)

*Simulated host, fictitious data*

## What the room shows

- **The list** of your contacts, with a search field at the top.
- **The contact**: name, one line with relation, role and organisation, and a note about the person.
- **Även kallad** (Nicknames), a line under the name with the contact's other names. It only shows when the contact has any.
- **Kontaktvägar** (Contact details), a folded row with email and phone. It only shows when there is something to show.
- **Tags** (Taggar), small chips under the contact details. The list rows show the first two.
- **Tasks, Notes and Projects** linked to the contact. A project row shows its status when it is not active, and how far it has come, for example "3 av 5 klara" (3 of 5 done).

## Find a contact

Type in the search field at the top of the room. The list shows the matches as you type.

## Tag a contact and filter by tag

Open the contact and tap "Lägg till tagg" (Add tag), or "Ändra taggar" (Edit tags) if it already has some. Type a tag and press Return, or tap one of "Dina taggar" (Your tags) to reuse a tag you have used before. Each chip has its own remove button, and "Klar" (Done) closes the editor. An archived contact shows its tags but cannot be changed.

When any contact has a tag, the list shows a row "Filtrera på tagg" (Filter by tag). Tap one or more tags, at most five at once, to narrow the list to the contacts that have all of them. "Rensa (N)" (Clear (N)), where N is the number of tags chosen, takes you back.

## Add a contact

1. Tap + at the top right.
2. Type the name.
3. Press Return.

You fill in the rest afterwards, or ask Claude to.

## Edit a contact

Open the contact, choose ⋯ and then "Redigera" (Edit). You can also tap the name. In the form you also add other names under "Även kallad" (Nicknames), so that Claude finds the right person when you use one.

"Arkivera" (Archive) in the same ⋯ menu hides a contact you no longer want to see in the list. It happens at once, without a question. The page then says "Kontakten är arkiverad." (The contact is archived.) with "Ångra" (Undo), which brings the contact back. An archived contact is read-only and has "Återställ" (Restore) in the menu instead.

## Open an email address or phone number

Open the contact and tap "Kontaktvägar". A tap on an address or a number hands over to the host, which opens the link.

## Remove a link

Open the contact and press and hold the project under Projects (on a computer, right-click or press Shift+F10), then choose "Ta bort koppling" (Remove link). The row stays with "Kopplingen borttagen" (Link removed) and "Ångra" (Undo) for a short while. A contact under a task is unlinked the same way in the task.

## What you would rather ask Claude for

- Adding a contact with role, organisation and a note in one go.
- Linking a contact to a project or a task.
- Asking who someone is and what you have going on together.
- Tagging a contact (for example "familj") and listing contacts by tag. `list_contacts` filters with `tags` and `tag_match` (`any` or `all`); Claude reuses existing tags with `list_tags`, which needs `projects:read` and shows only the kinds of record you may read.

## Scopes the room needs

A scope is a permission that the server checks on every call.

| To | Scopes |
| --- | --- |
| Read | `contacts:read` |
| Add and edit | `contacts:write` |

:::note[Contacts and memory]
If you have turned memory on, contacts can be one of its sources. Email, phone and address are never sent to memory. [Read about Control and memory](control-and-memory.md).
:::
