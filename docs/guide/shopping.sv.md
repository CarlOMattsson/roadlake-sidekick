# Inköp

[English](shopping.md)

<!-- description: Rummet Inköp visar en lista grupperad per butik. Så lägger du till varor, bockar av det du köpt, ångrar och ändrar antal. -->

Inköp är rummet för inköpslistor. En lista visar varorna grupperade per butik och hur mycket du har köpt.

![Rummet Inköp med en lista grupperad per butik, med antal och hur mycket som är köpt.](../images/rooms/shopping-list.png)

*Simulerad värd, påhittade data*

## Det här visar rummet

- **Hur långt du har kommit**, till exempel "1 av 8 köpta".
- **Varorna** grupperade per butik, med antal och enhet.
- **Köpta**, en hopfälld rad med det du redan har bockat av.

## Lägg till en vara

1. Tryck på "+ Lägg till vara" överst i listan.
2. Skriv varan.
3. Tryck på Retur. Fältet är kvar, så du kan skriva nästa direkt.

## Bocka av det du köpt

Tryck på ringen framför varan. Varan flyttas till Köpta.

## Ångra ett köp

Tryck på "Ångra" på raden direkt efter att du bockat av. Senare öppnar du Köpta och trycker på ringen igen.

## Ändra antal eller butik

Tryck på varans rad, bredvid ringen. Då öppnas varans formulär, där du ändrar namn, antal och butik.

## Skapa, byt namn på eller arkivera en lista

Tryck på + bredvid Listor för att skapa en ny lista. I helskärm byter du namn på listan med ⋯ och "Redigera lista", och "Arkivera lista" arkiverar den.

## Det här ber du hellre Claude om

- Lägga till många varor på en gång, till exempel från ett recept.
- Markera allt du köpte i en butik som köpt.

## Inköp i Android-appen

Android-appen visar samma listor. Där kan du skapa listor, lägga till, ändra, bocka av och ångra. [Läs om Android-appen](android-app.sv.md).

## Scopes som rummet behöver

En scope är en behörighet som servern kontrollerar vid varje anrop.

| För att | Scopes |
| --- | --- |
| Läsa | `shopping:read` |
| Lägga till, ändra och bocka av | `shopping:write` |
