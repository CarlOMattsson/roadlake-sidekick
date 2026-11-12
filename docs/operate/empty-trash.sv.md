# Töm papperskorgen

[English](empty-trash.md)

<!-- description: Att ta bort något flyttar det bara till papperskorgen. Här tömmer du den för gott med ett kommando, och ser vad som blir kvar ändå. -->

Att ta bort något flyttar det bara till papperskorgen. Här tömmer du den för gott med ett kommando, och ser vad som blir kvar ändå.

Att ta bort en post i appen eller via Claude flyttar den bara till papperskorgen, där den går att återställa. Ingenting
tömmer papperskorgen av sig självt: den som kör servern gör det med ett kommando. Utan `--yes` räknar det bara och
raderar ingenting:

```bash
docker compose --env-file selfhost.env run --rm -T api sidekick-admin empty-trash
docker compose --env-file selfhost.env run --rm -T api sidekick-admin empty-trash --yes
docker compose --env-file selfhost.env run --rm -T api sidekick-admin empty-trash --yes --older-than 30
```

Det första kommandot skriver ut hur många poster av varje typ som ligger i papperskorgen, för alla användare. Det andra
tar bort dem för gott; `--older-than DAYS` behåller det som lades i papperskorgen senare än så. Aktiva och arkiverade
poster rörs aldrig. En post som fortfarande har underordnade poster eller kopplingar (till exempel en kontakt med
smeknamn) behålls och räknas som kvarlämnad; en inköpspost eller en dagbokspost går inte att ta bort för gott och räknas alltid som kvarlämnad. Ta bort de
underordnade och kör kommandot igen. Utskriften innehåller bara antal och posttyper, aldrig titlar eller text, och varje
borttagning skrivs i granskningsloggen som en borttagning i appen. Det är säkert att köra igen. Ta en
[säkerhetskopia](backup-and-restore.sv.md) först om du kan vilja ha tillbaka posterna.

Vad som tas bort och vad som blir kvar. Kommandot raderar själva posten med de kopplingar och etiketter som hänger på
den, och köar, när minnet är på, borttagning av dess minneskopia. Det skriver inte om historiken. Aktivitetsflödet och ändringsloggen är
append-only: de behåller den titel eller det namn som skrevs vid varje ändring, och för uppgifter också beskrivning och
fältvärden, även när posten är borta. Granskningsloggen behåller en rad med posttyp och id, utan text. En dagbokspost tas
aldrig bort för gott, och inte heller dess källa: källor är oföränderliga och kan inte läggas i papperskorgen, och
posten räknas som kvarlämnad (om dagboksposter någonsin ska få raderas är öppet). Tidigare säkerhetskopior behåller allt tills du raderar dem. När papperskorgen töms, och om historiken
ska rensas, är ditt beslut som driftansvarig; Sidekick tömmer inte papperskorgen och rensar inte historik av sig självt.
