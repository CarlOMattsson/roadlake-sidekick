# Kontroll och minnet

[English](control-and-memory.md)

<!-- description: Kontroll samlar papperskorgen, historiken och Sidekicks minne. Så återställer du, ser vad som ändrats och styr vad minnet får innehålla. -->

Kontroll är platsen där du ser vad som hänt och bestämmer över minnet. Du öppnar Kontroll sist i menyn ⋯ i varje rum. Det har tre flikar: Borttaget, Historik och Sidekicks minne.

## Återställ något ur papperskorgen

1. Öppna Kontroll och välj fliken Borttaget.
2. Tryck på "Återställ" på raden.

Att ta bort något, i ett rum eller genom Claude, flyttar det bara till papperskorgen. Där ligger det kvar tills den som sköter servern tömmer den.

## Se vad som ändrats

Fliken Historik visar ändringarna och det Claude har gjort, de senaste först. På raderna finns "Ångra" eller "Återställ" där det går.

## Så fungerar minnet

Minnet är valfritt och avstängt från början. Den som sköter servern slår på det. [Läs hur du slår på minnet](../operate/memory.sv.md).

Minnet är härlett ur dina poster. Dina poster i PostgreSQL är det som gäller, och minnet går att bygga om från dem. När Claude frågar minnet kontrollerar Sidekick svaret mot det som finns i databasen just nu, så att något du har tagit bort inte kommer tillbaka.

Minnet byggs av tjänsten Hindsight, som anropar en språkmodell hos den leverantör du själv har ställt in. Text ur de källor du har slagit på skickas dit. Kontakters e-post, telefon och adress skickas aldrig.

## Pausa minnet

Öppna fliken Sidekicks minne och tryck på "Pausa minnet". Tryck på "Återuppta minnet" för att sätta igång det igen.

## Stäng av en källa

Under Källor finns ett reglage per källa: dagbok, kontakter, projekt och uppgifter. När du stänger av en källa tas det som minnet har härlett ur den bort.

## Se vad minnet innehåller

Under varje källa som är på trycker du på "Visa vad Sidekick minns" för ett urval av vad minnet innehåller. Sökfältet frågar hela minnet.

## Håll en enskild post utanför minnet

Tryck på "Glöm anteckningen" (för en kontakt, ett projekt eller en uppgift heter knappen efter den posten) vid ett faktum. Allt minnet har från hela den posten, inte bara det faktumet, tas bort, och posten själv ändras inte. Du kan också be Claude, till exempel: "Håll det här dagboksinlägget utanför minnet." Posten finns kvar i rummet men används inte av minnet. Du kan be Claude ta in den igen.

## Ange en licensnyckel

Licensraden står längst ned i Kontroll. Välj "Ange licensnyckel", klistra in nyckeln och välj "Spara". [Läs mer om att ange en licensnyckel](../operate/license-key.sv.md).

## Det här går inte härifrån

Permanent radering är inte ett publikt verktyg. Varken Claude eller rummen kan radera något för gott. Den som sköter servern tömmer papperskorgen med ett kommando. [Läs hur du tömmer papperskorgen](../operate/empty-trash.sv.md).

## Scopes som Kontroll behöver

En scope är en behörighet som servern kontrollerar vid varje anrop. Kontroll och minnet har inga egna scopes. De följer de områden du har gett tillgång till.

| För att | Scopes |
| --- | --- |
| Se papperskorgen, historiken och minnets status | läs-scope för området, till exempel `tasks:read` |
| Lägga i papperskorgen och återställa | skriv-scope för området, till exempel `tasks:write` |
| Pausa minnet, stänga av en källa, undanta en post | skriv-scope för området, till exempel `journal:write` |
