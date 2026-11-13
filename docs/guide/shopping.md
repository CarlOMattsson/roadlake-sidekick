# Shopping

[Svenska](shopping.sv.md)

<!-- description: The Shopping room shows a list grouped by store. How to add items, tick off what you bought, undo and change quantities. -->

Shopping (Inköp) is the room for shopping lists. A list shows the items grouped by store and how much you have bought.

![The Shopping room showing a list grouped by store, with quantities and purchase progress.](../images/rooms/shopping-list.png)

*Simulated host, fictitious data*

## What the room shows

- **How far you have come**, for example "1 av 8 köpta" (1 of 8 bought).
- **The items** grouped by store, with quantity and unit.
- **Köpta** (Bought), a folded row with what you have already ticked off.

## Add an item

1. Tap "+ Lägg till vara" (Add item) at the top of the list.
2. Type the item.
3. Press Return. The field stays open, so you can type the next one straight away.

## Tick off what you bought

Tap the ring in front of the item. The item moves to Bought.

## Undo a purchase

Tap "Ångra" (Undo) on the row right after you ticked it off. Later, open Bought and tap the ring again.

## Change quantity or store

Tap the item's row, next to the ring. This opens the item's form, where you change the name, quantity and store. "Fler fält" (More fields) holds the rest, such as a note, an offer price and a gift recipient.

## Mark an item as a gift

Under "Fler fält", "Presentmottagare (valfritt)" (Gift recipient, optional) links the item to one of your contacts. Search for the contact with "Sök kontakt" (Find contact) and choose it. The form shows the recipient's name when the session may read contacts (`contacts:read`); otherwise it says "Nuvarande mottagare" (Current recipient). The search needs the Contacts room and is not in the Android app, which keeps a recipient that is already set.

## Create, rename or archive a list

Tap + next to Lists (Listor) to create a new list. In full screen, ⋯ and "Redigera lista" (Edit list) renames the list, and "Arkivera lista" (Archive list) archives it.

## What you would rather ask Claude for

- Adding many items at once, for example from a recipe.
- Marking everything you bought in one store as bought.

## Shopping in the Android app

The Android app shows the same lists. There you can create lists, add, edit, tick off and undo. [Read about the Android app](android-app.md).

## Scopes the room needs

A scope is a permission that the server checks on every call.

| To | Scopes |
| --- | --- |
| Read | `shopping:read` |
| Add, edit and tick off | `shopping:write` |
| Find and name a gift recipient | `contacts:read` as well |
