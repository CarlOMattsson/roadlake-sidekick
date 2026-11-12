# Drift

[English](README.md)

<!-- description: En karta över det du gör som driftar en Sidekick-server – ansluta Claude, uppdatera, ta backup, slå på minnet och para ihop Android. -->

Här finns guiderna för dig som sköter en Sidekick-server. Varje guide gör en sak. Har du inte startat servern än börjar du i [Första starten på en server](../start/self-hosted-server.sv.md).

:::note[Första versionen]
Sidekick 0.1.0 är den första versionen och körs dagligen på Linux. macOS är ännu inte provat. Ta en backup innan du ändrar något.
:::

## Ansluta

- [Anslut Claude](connect-claude.sv.md): registrera inloggningen, lägg till connectorn och bestäm vad sessionen får göra.
- [Bygg, installera och para ihop Android](pair-android.sv.md): ladda ner den signerade appen eller bygg den ur källkoden, och koppla telefonen med en engångskod.
- [Påminnelser via ntfy](push-reminders.sv.md): slå på påminnelser till telefonen, via den publika ntfy-servern eller en egen.

## Sköta

- [Uppdatera](update.sv.md): hämta ny kod och kör migreringarna, från källkod eller till en signerad avbild.
- [Backup och återställning](backup-and-restore.sv.md): ta krypterade backuper, förvara nyckeln på annat håll och läs tillbaka.
- [Resursgränser och hemligheter per container](limits-and-secrets.sv.md): ändra minnes- och processgränserna och se vilka inställningar varje container får.
- [Töm papperskorgen](empty-trash.sv.md): radera för gott det som ligger i papperskorgen, med ett kommando.
- [Flytta data mellan installationer](move-data.sv.md): ta med dina poster till en ny server eller en tom databas.

## Lägga till

- [Slå på minnet](memory.sv.md): starta Hindsight och välj vilken modellleverantör som får texten.
- [Ange en licensnyckel](license-key.sv.md): spara en nyckel i ett rum, i Android-appen eller från kommandoraden.

## Jobbdatorn

Jobbpaketet har egna guider, eftersom det körs lokalt mot Claude Desktop och har ett stängt nätverk.

- [Drift av jobbpaketet](work-laptop/README.sv.md): nätverket, start vid inloggning, backup och uppdatering, modellservern och avinstallation.

## Slå upp

- [Compose-profiler och filer](../reference/selfhost-profiles.sv.md)
- [Säkerhet och integritet i klartext](../explanation/security-and-privacy.sv.md)
