# Android-appen

[English](android-app.md)

<!-- description: Android-appen visar Arbete, Dagbok och Inköp ur samma server som Claude. Det här gör appen, det här gör den inte, och så kommer du igång. -->

Android-appen är en andra yta mot samma Sidekick-server, bredvid Claude. Den visar samma poster ur samma databas. Det finns ingen färdig APK: du bygger appen själv ur källkoden.

:::note[Förhandsversion]
Appen byggs och testas automatiskt, bland annat i en emulator. Den är inte provad på en riktig telefon mot en riktig server.
:::

## Det här gör appen

- **Arbete:** dagens agenda, projekt, uppgifter och steg. Du kan läsa dem, bocka av dem och öppna dem igen.
- **Inköp:** listor och varor. Du kan lägga till, ändra, bocka av och ångra.
- **Dagbok:** läs dagar och inlägg, och skriv eller ändra inlägg för hand.
- **Idag-widgeten:** dagens uppgifter på hemskärmen. [Läs om widgeten och påminnelserna](today-widget.sv.md).
- **Inställningar:** status för aviseringar, en testnotis, telefonens anslutning och valet att koppla från telefonen.

## Det här gör appen inte

- Den skapar inte uppgifter eller projekt. Det gör du i Claude.
- Den kör ingen AI och pratar inte med Claude.
- Den visar inte Kontakter eller Kontroll.
- Den har ingen QR-läsare och ber inte om kameran.
- Den säkerhetskopierar inte sin anslutning och flyttar den inte till en ny telefon.

Det finns ingen iOS-app.

## Det här behöver du

- En telefon med Android 7.0 eller senare och en uppdaterad Android System WebView, version 123 eller senare.
- En Sidekick-server som telefonen når över HTTPS på en publik adress.
- En dator där du kan bygga appen.

Jobbpaketet har ingen väg till telefonen.

## Kom igång

1. Bygg appen och installera den på telefonen.
2. Slå på appens anslutning på servern.
3. Skapa en kopplingskod på servern. Koden fungerar en gång och i tio minuter.
4. Öppna appen, ange serverns adress och koden, och tryck på "Koppla".

Alla kommandon står i driftsguiden. [Läs hur du bygger, installerar och parar ihop Android-appen](../operate/pair-android.sv.md).

## Hitta Inställningar

Inställningar ligger sist i menyn i rummet Arbete. Där ser du om aviseringarna fungerar, och där kan du skicka en testnotis.

## Koppla från en telefon

Välj "Koppla från den här telefonen" i Inställningar. Har du tappat bort telefonen återkallar du den från servern i stället. Då får appen börja om med en ny kopplingskod nästa gång den kontaktar servern.

## Telefonens anslutning

När du parar ihop telefonen får den en egen behörighet som bara gäller där. Den går att återkalla och gäller i 30 dagar om inget annat ställs in. Så länge du använder appen förnyas den av sig själv.

## Språk

Appens språk är en egen inställning och följer inte telefonens språk. Svenska är förval. Språket väljs när appen byggs. [Läs mer om språk](../reference/languages.sv.md).

## Licens i appen

Utan licensnyckel visar Idag-widgeten ett litet mynt som påminnelse om gratisversionen. Du anger en nyckel längst ned i Inställningar. [Läs vad nyckeln gör](../explanation/licensing.sv.md).
