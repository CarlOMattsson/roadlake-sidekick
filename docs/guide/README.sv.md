# Samtalet och rummen

[English](README.md)

<!-- description: Så fungerar Sidekick. Claude gör det mesta när du frågar, och rummen visar resultatet och låter dig klicka direkt. -->

Sidekick har inget eget webbgränssnitt. Du använder det i ett samtal med Claude, och rummen öppnas i samtalet när du vill se och ändra något själv.

## Claude gör det mesta

Du ber Claude om det du vill ha gjort, med vanliga ord. Claude anropar då verktyg på din server genom MCP (Model Context Protocol), protokollet som låter Claude använda verktyg utanför samtalet. Du behöver inte kunna verktygens namn.

Många ändringar gör du lättast genom att fråga. Be om en ny uppgift, ett dagboksinlägg eller tio varor på en lista, så sköter Claude det. Vad Claude får läsa och ändra bestäms av de scopes, alltså behörigheter, som du har gett connectorn.

## Rummen visar och låter dig klicka

Det finns fyra rum, Arbete, Dagbok, Kontakter och Inköp, och dessutom Kontroll. Ett rum är en vy som Claude visar inne i samtalet. Där bockar du av, byter datum, skriver för hand och bläddrar mellan poster.

Överst i varje rum finns en remsa med de fyra rummen, så du kan byta rum utan att fråga Claude. Kontroll ligger sist i menyn ⋯ i varje rum.

## Kort i samtalet och helskärm

Ett svar från Claude kan innehålla ett kort: en kompakt ruta med några få rader. Kortet slutar med en länk som öppnar hela rummet, till exempel "Öppna Status". I helskärm ser du hela listan och alla kontroller.

## Ändringar utan nytt svar från Claude

När du trycker i ett rum går ändringen direkt till servern. Du behöver inte vänta på att Claude svarar, och du behöver inte skriva något. När något har ändrats läser de rum som kan visa ändringen om sina data.

Servern kontrollerar varje ändring, oavsett om den kommer från Claude eller från ett rum. Samma regler gäller för båda.

## Vad som sparas

Det som sparas är dina poster: uppgifter, inlägg, kontakter och varor. Samtalets text sparas inte automatiskt i Sidekick. Vill du ha kvar något ur samtalet ber du Claude skriva det i dagboken.

:::note[Förhandsversion]
Rummen är byggda och testade i en simulerad värd. De är inte provade i riktiga Claude-anslutningar än.
:::

## Språk i rummen

Rummens etiketter är svenska som förval. Sätt `SIDEKICK_MCP_APP_LOCALE=en` på servern för engelska.

| Svenska | Engelska |
| --- | --- |
| Arbete | Work |
| Dagbok | Journal |
| Kontakter | Contacts |
| Inköp | Shopping |
| Kontroll | Control |

Android-appen har en egen språkinställning. [Läs mer om språk i rummen, appen och servern](../reference/languages.sv.md).

## Rummen ett i taget

- [Arbete](work.sv.md)
- [Dagbok](journal.sv.md)
- [Kontakter](contacts.sv.md)
- [Inköp](shopping.sv.md)
- [Kontroll och minnet](control-and-memory.sv.md)
- [Android-appen](android-app.sv.md)
- [Idag-widgeten och påminnelserna](today-widget.sv.md)
