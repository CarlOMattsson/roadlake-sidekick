# Shopping

[Svenska](shopping.sv.md)

<!-- description: The Shopping room shows a list grouped by store. How to add items, tick off what you bought, undo and change quantities. -->

Shopping (Inköp) is the room for shopping lists. A list shows the items grouped by store and how much you have bought.

![The Shopping room showing a list grouped by store, with quantities and purchase progress.](../images/rooms/shopping-list.png)

*Simulated host, fictitious data*

## What the room shows

- **How far you have come**, for example "1 av 8 köpta" (1 of 8 bought).
- **The items** grouped by store, with quantity and unit.
- **Köpta** (Bought), a folded row with what you have ticked off. The number counts the items whose "Ångra" time has run out, so it does not change while "Ångra" is offered. The progress line counts every bought item.

## Add an item

1. Tap "+ Lägg till vara" (Add item) at the top of the list.
2. Type the item.
3. Press Return. The field stays open, so you can type the next one straight away.

## Tick off what you bought

Tap the ring in front of the item. The item stays among the open ones for a short while with "Ångra", and then moves to Bought. Under Bought, each item shows the day it was bought ("köpt …"), and the most recently bought is first.

## Undo a purchase

Tap "Ångra" (Undo) on the row right after you ticked it off. Later, open Bought and tap the ring again. In full screen, a tip above the bought items says "Tryck på ringen för att köpa igen." (Tap the ring to buy again) until you have bought an item again once.

## Change quantity or store

Tap the item's row, next to the ring. This opens the item's form, where you change the name, quantity and store. "Fler fält" (More fields) holds the rest, such as a note, an offer and a gift recipient. The offer has a fold of its own there. Closed, it says what is saved, for example "Erbjudande: 199 kr t.o.m. 30 nov" (Offer: 199 kr until 30 Nov). Open it to change "Erbjudandepris" (Offer price) and the other offer fields. Prices are written in the app's language: with a decimal comma in Swedish and a decimal point in English. A price that is not a number gets "Ange ett pris som 19,90." (Swedish) or "Enter a price like 19.90." (English).

## Mark an item as a gift

Under "Fler fält", "Presentmottagare (valfritt)" (Gift recipient, optional) links the item to one of your contacts. Search for the contact with "Sök kontakt" (Find contact) and choose it. The form shows the recipient's name when the session may read contacts (`contacts:read`); otherwise it says "Nuvarande mottagare" (Current recipient). The search needs the Contacts room and is not in the Android app, which keeps a recipient that is already set.

## Create, rename or archive a list

Tap + next to Lists (Listor) to create a new list. In full screen, ⋯ and "Redigera lista" (Edit list) renames the list, and "Arkivera lista" (Archive list) archives it. Archived lists are last among the lists, in a folded row "Arkiverade (N)" (Archived (N)) that you open to see them.

## The card in the chat

In the chat the list shows as a card with the first items. When it leaves some out, the button "Öppna inköpslistan" (Open the shopping list) says how many, for example "Öppna inköpslistan · 2 fler" (Open the shopping list · 2 more).

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
