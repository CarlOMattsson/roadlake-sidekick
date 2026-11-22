# Android-appen

[English](android-app.md)

<!-- description: Android-appen visar Arbete, Dagbok och Inköp ur samma server som Claude. Det här gör appen, det här gör den inte, och så kommer du igång. -->

Android-appen är en andra yta mot samma Sidekick-server, bredvid Claude. Den visar samma poster ur samma databas. Från och med första releasen har varje release på GitHub Releases en signerad APK, `sidekick-X.Y.Z.apk`, som du installerar direkt. Du kan också bygga appen själv ur källkoden.

:::note[Första versionen]
Appen används dagligen på en riktig telefon mot en riktig server. Den byggs och testas också automatiskt, bland annat i en emulator.
:::

## Det här gör appen

- **Arbete:** dagens agenda, projekt, uppgifter och steg. Du kan läsa dem, bocka av dem och öppna dem igen, lägga till en uppgift med + och ändra en uppgifts titel, anteckning, datum, plats och prioritet, samt ändra ett projekts titel, status, beskrivning och datum. Claude är fortfarande huvudvägen; formulären är till för när du inte kan prata.
- **Inköp:** listor och varor. Du kan skapa listor, lägga till, ändra, bocka av och ångra.
- **Dagbok:** läs dagar och inlägg, och skriv eller ändra inlägg för hand.
- **Papperskorgen:** du kan flytta en uppgift, ett dagboksinlägg eller en vara till papperskorgen och ångra direkt. Under Inställningar ser du vad som ligger där, och du kan återställa det. Där kan du också radera en uppgift för gott, efter bekräftelse, om telefonen har fått den separata rättigheten för det. En uppgift med steg eller länkar tar du bort i Claude först. Dagboksinlägg och varor kan aldrig raderas för gott, varken i appen eller i Claude. Radering för gott kräver nät.
- **Idag-widgeten:** dagens uppgifter på hemskärmen. [Läs om widgeten och påminnelserna](today-widget.sv.md).
- **Inställningar:** status för aviseringar, en testavisering, appens språk, vad rumsraden visar, telefonens anslutning, valet att koppla från telefonen och licensnyckeln.

## Det här gör appen inte

- Den skapar inte projekt, domäner eller processer. Den raderar dem inte heller, och den raderar inte kontakter eller steg. Det gör du i Claude.
- En telefon som parades före den här ändringen behöver den nya rättigheten en gång: `python -m sidekick.companion.cli grant --device-id ID --scope companion:work:write`. Nya parningar med `--preset app` har den. Att radera för gott och tömma papperskorgen kräver ytterligare en rättighet, som en telefon som parades tidigare inte får av sig själv: `python -m sidekick.companion.cli grant --device-id ID --scope companion:work:erase`. Utan den visar papperskorgen ingen knapp för att radera för gott.
- Den kör ingen AI och pratar inte med Claude.
- Den visar inte Kontakter eller Kontroll.
- Den ändrar inte taggar och har inget taggfilter, och den visar inte åtgärderna på ett steg.
- Den har ingen QR-läsare och ber inte om kameran.
- Den säkerhetskopierar inte sin anslutning och flyttar den inte till en ny telefon.

Det finns ingen iOS-app.

## Det här behöver du

- En telefon med Android 7.0 eller senare och en uppdaterad Android System WebView, version 123 eller senare.
- En Sidekick-server som telefonen når över HTTPS på en publik adress.
- Den signerade APK:n från en release, eller en dator där du bygger appen själv.

Jobbpaketet har ingen väg till telefonen.

## Kom igång

1. Ladda ner APK:n från releasen, eller bygg den själv, och installera den på telefonen.
2. Slå på appens anslutning på servern.
3. Skapa en kopplingskod på servern. Koden fungerar en gång och i tio minuter.
4. Öppna appen, ange serverns adress och koden, och tryck på "Koppla".

Alla kommandon står i driftsguiden. [Läs hur du installerar och parar ihop Android-appen](../operate/pair-android.sv.md). [Läs hur du kontrollerar en releases filer](../maintainers/release.sv.md#verifiera-en-release).

## Hitta Inställningar

Inställningar ligger sist i menyn ⋯ i varje rum. Där ser du om aviseringarna fungerar, och där kan du skicka en testavisering. En rad om låsskärmen, att den visar titlar bara om telefonen tillåter känsligt innehåll där, visas bara när aviseringarna är på.

## Koppla från en telefon

Välj "Koppla från den här telefonen" i Inställningar. Har du tappat bort telefonen återkallar du den från servern i stället. Då får appen börja om med en ny kopplingskod nästa gång den kontaktar servern.

## Telefonens anslutning

När du parar ihop telefonen får den en egen behörighet som bara gäller där. Den går att återkalla och gäller i 30 dagar om inget annat ställs in. Så länge du använder appen förnyas den av sig själv.

## Språk

Appens språk är en egen inställning och följer inte telefonens språk. Svenska är förval. Du väljer Svenska eller English på kopplingsskärmen eller i Inställningar. [Läs mer om språk](../reference/languages.sv.md).

## Rumsraden

Raden överst visar rummens namn. Under Rumsraden i Inställningar kan du välja Båda, en ikon före namnet på rummet du är i och ikoner för de andra, eller Ikoner, bara ikonerna. Text är förval. Valet sparas på telefonen. I Claude är samma val serverinställningen `SIDEKICK_MCP_APP_NAV_ICONS` (`off`, `label` eller `only`).

## Licens i appen

Utan licensnyckel visar Idag-widgeten ett litet mynt som påminnelse om gratisversionen. Du anger en nyckel längst ned i Inställningar. [Läs vad nyckeln gör](../explanation/licensing.sv.md).
