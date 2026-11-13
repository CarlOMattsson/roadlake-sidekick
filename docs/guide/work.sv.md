# Arbete

[English](work.md)

<!-- description: Rummet Arbete visar agenda, statustavla och projekt. Så skapar du uppgifter, bockar av, byter datum och delar upp i steg. -->

Arbete är rummet för uppgifter och projekt. Det har tre flikar: Agenda, Status och Projekt.

![Rummet Arbete med statustavlan i mörkt läge och en grupp med påhittade uppgifter att göra.](../images/rooms/work-status-board-dark.png)

*Simulerad värd, påhittade data*

## Det här visar rummet

- **Agenda** visar uppgifter med datum: försenade, idag, kommande och senare.
- **Status** visar uppgifterna grupperade efter läge: Att göra, Pågår, Blockerad och Klar.
- **Projekt** visar dina projekt och uppgifterna i dem.

## Skapa en uppgift

1. Tryck på + uppe till höger.
2. Skriv uppgiften.
3. Tryck på Retur. Fältet är kvar, så du kan skriva nästa direkt.

## Bocka av en uppgift

Tryck på ringen framför uppgiften. Raden ligger kvar en kort stund med knappen "Ångra", ifall du tryckte fel.

## Byt status eller datum

1. Håll inne en uppgift i listan. På dator högerklickar du eller trycker Shift+F10.
2. Välj ny status, eller ett datum: idag, imorgon, nästa vecka eller en dag du väljer.

Du kan också öppna uppgiften och trycka på datumet eller statusen under titeln.

## Flytta försenade uppgifter till imorgon

När agendan har försenade uppgifter finns raden "Flytta … försenade till imorgon" under rubriken Försenade. Tryck på den och bekräfta frågan "Flytta N till imorgon?" med "Flytta"; "Avbryt" lämnar den. Uppgifterna flyttas tillsammans, och en rad "N flyttade till imorgon" med "Ångra" ligger kvar en kort stund, så att du kan lägga tillbaka dem.

## Dela upp en uppgift i steg

1. Öppna uppgiften.
2. Tryck på "+ Lägg till steg".
3. Skriv steget och tryck på Retur.

Steg bockar du av i uppgiften, ett i taget. Tryck och håll på ett steg (på en dator högerklickar du eller trycker Skift+F10) för att flytta det upp eller ned eller arkivera det.

## Åtgärder på ett steg

Ett steg kan ha åtgärder, mindre saker att göra inom steget. Ett steg som har åtgärder visar hur många under sin titel, till exempel "2 åtgärder", och när någon är klar "1 av 2 åtgärder klara". Tryck på den raden för att visa eller dölja åtgärderna.

- Bocka i rutan framför en åtgärd för att markera den som klar, och bocka ur den för att öppna den igen. Raden står kvar en kort stund med "Ångra".
- Under titeln visar en åtgärd sin förfallodag, röd när den har passerat, och sin anteckning.
- Tryck och håll på en åtgärd (på en dator högerklickar du eller trycker Skift+F10) för att flytta den upp eller ned eller arkivera den.

Åtgärder lägger du till, och sätter deras förfallodag och anteckning, genom att be Claude.

## Taggar och taggfilter

Uppgifter och projekt kan ha taggar. Brickor visas på raderna, och under titeln på en öppen uppgift eller ett öppet projekt trycker du på "Lägg till tagg", eller "Ändra taggar" om det redan har några, för att ändra dem på plats. Skriv en tagg och tryck på Retur, eller tryck på någon av "Dina taggar" för att återanvända en.

När någon uppgift eller något projekt har en tagg visar Agenda och Status raden "Filtrera på tagg". Tryck på en eller flera taggar, högst fem åt gången, för att begränsa listan till det som har alla. "Rensa (N)", där N är antalet valda taggar, tar dig tillbaka.

## Sparade vyer

I fullskärmsläget av Arbete är "Sparade vyer" första valet i menyn ⋯ ("Fler val") sist i flikraden. "Spara nuvarande vy" sparar de filter som listan visar just nu, också de taggar du valt, under ett namn på högst 120 tecken. En vy kan du senare öppna, byta namn på och arkivera, och de arkiverade visas igen med "Visa arkiverade". Ett enskilt projekts bräde kan inte sparas som vy.

## Ändra en uppgift, dess plats eller hur den upprepas

Öppna uppgiften och välj ⋯ och sedan "Redigera" för att ändra titel, beskrivning, prioritet och datum. Du kan också trycka på titeln. Under titeln flyttar chippet "Plats" uppgiften till ett projekt, en process eller en domän, och upprepningschippet låter den upprepas varje dag, vecka, månad eller år.

## Koppla en kontakt till en uppgift

Öppna uppgiften och tryck på "+ Koppla kontakt". Kopplingen syns sedan både i uppgiften och hos kontakten.

## Det här ber du hellre Claude om

- Skapa flera uppgifter på en gång, till exempel från en lista eller ett foto av en whiteboard.
- Lägga upp projekt, domäner och processer.
- Upprepa på vissa veckodagar eller med andra intervall.
- Sätta taggar och tidsuppskattningar.
- Lägga till åtgärder på ett steg, med förfallodag eller anteckning.
- Flytta många uppgifter till ett visst datum.
- Hitta en uppgift när du bara minns ungefär vad den handlade om.

## Scopes som rummet behöver

En scope är en behörighet som servern kontrollerar vid varje anrop.

| För att | Scopes |
| --- | --- |
| Läsa | `tasks:read`, `projects:read` |
| Ändra uppgifter och steg | `tasks:write` |
| Ändra projekt och domäner | `projects:write` |

Alla verktyg och deras scopes står i [MCP-verktygsreferensen](../reference/mcp/index.md), som är på engelska.
