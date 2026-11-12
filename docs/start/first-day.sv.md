# Din första dag med Sidekick

[English](first-day.md)

<!-- description: En genomgång i åtta steg av alla fyra rum, från dagens läge till papperskorgen, när Claude väl är ansluten till din server. -->

När connectorn är ansluten kan du prova alla fyra rum i ett enda samtal. En connector är kopplingen mellan Claude och din server. Följ stegen i ordning, de bygger på varandra.

Frågorna nedan är förslag. Skriv med egna ord. Claude väljer verktyg efter vad du ber om, och svaren ser inte likadana ut varje gång.

:::note[Innan du börjar: ge Claude rätt behörigheter]
En scope är en behörighet som servern kontrollerar vid varje anrop. Exempelkonfigurationen ger Claude bara läsrätt till projekt, uppgifter, kontakter och inköp. För att följa hela guiden behöver sessionen också `tasks:write`, `contacts:write`, `shopping:write`, `journal:read` och `journal:write`. [Läs hur du ändrar vad sessionen får göra](../operate/connect-claude.sv.md).
:::

## 1. Fråga hur dagen ser ut

Du kan till exempel fråga:

> Hur ser min dag ut?

Claude hämtar dagens läge från Sidekick: det som ska göras idag och det som är försenat. I en ny installation finns inget än, så svaret blir kort.

## 2. Skapa en uppgift

Du kan till exempel skriva:

> Lägg till en uppgift: ring tandläkaren på fredag.

Claude skapar uppgiften i rummet Arbete. Be sedan Claude visa agendan. Då kan rummet öppnas i samtalet, som ett kort eller i helskärm.

## 3. Bocka av och ångra i rummet

Tryck på ringen framför uppgiften för att markera den som klar. Raden ligger kvar en kort stund med knappen "Ångra". Tryck på den för att få tillbaka uppgiften.

Det här händer i rummet. Du behöver inte vänta på ett nytt svar från Claude.

## 4. Skriv i dagboken

Du kan till exempel skriva:

> Skriv i dagboken att jag äntligen bokade tandläkaren.

Claude sparar ett inlägg på dagens datum i rummet Dagbok. Du kan också skriva för hand: öppna Dagbok och tryck på + bredvid datumet.

## 5. Lägg till en kontakt

Du kan till exempel skriva:

> Lägg till min tandläkare Anna som kontakt och koppla henne till uppgiften.

Claude skapar kontakten i rummet Kontakter och kopplar den till uppgiften. Öppna kontakten för att se kopplingen under Uppgifter.

## 6. Gör en inköpslista

Du kan till exempel skriva:

> Gör en inköpslista för helgen med mjölk, kaffe och två liter filmjölk.

Claude skapar listan i rummet Inköp. I rummet trycker du på ringen framför en vara när du har köpt den.

## 7. Se vad som ändrats

Du kan till exempel fråga:

> Vad har jag ändrat idag?

Du kan också öppna Kontroll, som ligger sist i menyn ⋯ i varje rum. Fliken Historik visar ändringarna, de senaste först.

## 8. Lägg något i papperskorgen

Du kan till exempel skriva:

> Lägg uppgiften om tandläkaren i papperskorgen.

Verktyget ber Claude att fråga dig först och vänta på ett ja. Det är en instruktion till Claude, inte en spärr i servern. Inget raderas för gott: öppna Kontroll, välj fliken Borttaget och tryck på "Återställ" för att få tillbaka uppgiften.

## Det här kan Claude läsa

Claude läser det som connectorns scopes tillåter. Har du lagt till `journal:read` gäller det också dagbokstext. Det Claude läser lämnar din server och delas med Claude.

[Läs vem som ser vad](../explanation/security-and-privacy.sv.md)

## Byt språk i rummen

Rummens etiketter är svenska som förval. Sätt `SIDEKICK_MCP_APP_LOCALE=en` på servern för engelska. [Läs mer om språk](../reference/languages.sv.md).

## Nästa steg

- [Läs hur samtalet och rummen hänger ihop](../guide/README.sv.md)
- [Slå på minnet](../operate/memory.sv.md)
- [Bygg och para ihop Android-appen](../operate/pair-android.sv.md)
