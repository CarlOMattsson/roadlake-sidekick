# Kontakter

[English](contacts.md)

<!-- description: Rummet Kontakter visar personer och organisationer i sitt sammanhang. Så söker du, lägger till, ändrar och kopplar kontakter. -->

Kontakter är rummet för personer och organisationer. Varje kontakt visas tillsammans med de uppgifter, anteckningar och projekt som hör till den.

![Rummet Kontakter med en påhittad leverantör, med roll, organisation och anteckningar.](../images/rooms/contact.png)

*Simulerad värd, påhittade data*

## Det här visar rummet

- **Listan** med dina kontakter och ett sökfält överst.
- **Kontakten**: namn, en rad med relation, roll och organisation, och en anteckning om personen.
- **Även kallad**, en rad under namnet med kontaktens andra namn. Den visas bara när kontakten har några.
- **Kontaktvägar**, en hopfälld rad med e-post och telefon. Den visas bara när det finns något att visa.
- **Taggar**, små brickor under kontaktvägarna. Listans rader visar de två första.
- **Uppgifter, Anteckningar och Projekt** som är kopplade till kontakten. En projektrad visar sin status när projektet inte är aktivt, och hur långt det har kommit, till exempel "3 av 5 klara".

## Sök en kontakt

Skriv i sökfältet överst i rummet. Listan visar träffarna medan du skriver.

## Tagga en kontakt och filtrera på tagg

Öppna kontakten och tryck på "Lägg till tagg", eller "Ändra taggar" om den redan har några. Skriv en tagg och tryck på Retur, eller tryck på någon av "Dina taggar" för att återanvända en tagg du har använt förut. Varje bricka har sin egen borttagsknapp, och "Klar" stänger redigeringen. En arkiverad kontakt visar sina taggar men kan inte ändras.

När någon kontakt har en tagg visar listan raden "Filtrera på tagg". Tryck på en eller flera taggar, högst fem åt gången, för att begränsa listan till de kontakter som har alla. "Rensa (N)", där N är antalet valda taggar, tar dig tillbaka.

## Lägg till en kontakt

1. Tryck på + uppe till höger.
2. Skriv namnet.
3. Tryck på Retur.

Resten fyller du i efteråt, eller ber Claude om.

## Ändra en kontakt

Öppna kontakten, välj ⋯ och sedan "Redigera". Du kan också trycka på namnet. I formuläret lägger du också till andra namn under "Även kallad", så att Claude hittar rätt person när du använder ett.

"Arkivera" i samma ⋯-meny döljer en kontakt som du inte längre vill se i listan, efter att du har bekräftat. En arkiverad kontakt har "Återställ" där i stället.

## Öppna e-post eller telefon

Öppna kontakten och tryck på "Kontaktvägar". Ett tryck på en adress eller ett nummer lämnar över till värden, som öppnar länken.

## Ta bort en koppling

Öppna kontakten och tryck och håll på projektet under Projekt (på en dator högerklickar du eller trycker Skift+F10), och välj "Ta bort koppling". Raden står kvar en kort stund med "Kopplingen borttagen" och "Ångra". En kontakt under en uppgift tar du bort på samma sätt i uppgiften.

## Det här ber du hellre Claude om

- Lägga till en kontakt med roll, organisation och anteckning i ett svep.
- Koppla en kontakt till ett projekt eller en uppgift.
- Tagga en kontakt (till exempel "familj") och lista kontakter efter tagg. `list_contacts` filtrerar med `tags` och `tag_match` (`any` eller `all`); Claude återanvänder befintliga taggar med `list_tags`, som kräver `projects:read` och bara visar de sorters poster du får läsa.

## Scopes som rummet behöver

En scope är en behörighet som servern kontrollerar vid varje anrop.

| För att | Scopes |
| --- | --- |
| Läsa | `contacts:read` |
| Lägga till och ändra | `contacts:write` |

:::note[Kontakter och minnet]
Har du slagit på minnet kan kontakter vara en av källorna. E-post, telefon och adress skickas aldrig till minnet. [Läs om Kontroll och minnet](control-and-memory.sv.md).
:::
