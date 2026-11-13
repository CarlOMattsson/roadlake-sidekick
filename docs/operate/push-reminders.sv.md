# Påminnelser via ntfy

[English](push-reminders.md)

<!-- description: Slå på påminnelser till telefonen. Servern skickar väckningar utan innehåll genom ntfy, och telefonen hämtar själv det som ska visas. -->

Slå på påminnelser till telefonen. Servern skickar väckningar utan innehåll genom ntfy, och telefonen hämtar själv det som ska visas.

1. API:et och push-workern körs båda med `SIDEKICK_PUSH_ENABLED=true`. Workern är en egen process:
   `sidekick-push-worker` (självhostat: `docker compose --env-file selfhost.env --profile push up -d`; från en
   utcheckning: `uv run --project backend sidekick-push-worker`). Den måste vara igång hela tiden.
2. Appen ntfy är installerad på telefonen. När appen är parkopplad och aviseringar är tillåtna registrerar
   den telefonens UnifiedPush-ändpunkt hos servern. Servern godtar bara en `https`-ändpunkt på port 443 vars
   värd står i `SIDEKICK_PUSH_ALLOWED_HOSTS`.
3. Workern skickar en liten väckning utan innehåll till den ändpunkten. Telefonen vaknar, hämtar det som är
   aktuellt från servern och visar aviseringen. Låsskärmen följer telefonens inställning för känsligt innehåll.
4. Kontrollera i appen: Inställningar, "Skicka testavisering" (högst 5 i timmen).

Morgonsammanfattningen köas från den inställda tiden och under ett fönster på två timmar, och bara om något
ska göras idag eller är försenat. En påminnelse om en uppgift skickas `SIDEKICK_PUSH_DUE_LEAD_MINUTES` före
uppgiftens klockslag. Under de tysta timmarna aviseras ingenting. Var workern nere längre än fönstret hoppas
sammanfattningen över.

Som förval använder telefonens ntfy-app den publika ntfy-servern (ntfy.sh), vars gratisnivå tillåter ungefär 250 meddelanden per
dygn och avsändare. Servern håller därför minst 20 sekunder mellan väckningarna till en och samma telefon
(`SIDEKICK_PUSH_WAKE_MIN_INTERVAL_SECONDS`).

**Egen ntfy-server.** Självhostingpaketet innehåller en (profilen `vps` med `--profile push`). Den nekar anonym läsning,
så telefonen måste logga in:

1. En gång, från `deploy/selfhost`: `sh ntfy-init.sh`. Det skriver `ntfy.env`, `ntfy-secrets/sidekick-token` och
   `ntfy-secrets/phone-password` (läge 600) och skriver bara ut var de ligger.
2. Avkommentera i `selfhost.env` de tre raderna under "Own ntfy server" i `selfhost.env.example`: tillåtelselistan
   `SIDEKICK_PUSH_ALLOWED_HOSTS=<din-domän>,ntfy.sh`, `SIDEKICK_PUSH_AUTH_HOST=<din-domän>` och
   `SIDEKICK_PUSH_AUTH_TOKEN` med innehållet i `ntfy-secrets/sidekick-token`. Skapa om API:et och starta workern:
   `docker compose --env-file selfhost.env --profile vps --profile push up -d`.
3. Lägg i telefonens ntfy-app till `https://<din-domän>` som server med användaren `phone` och lösenordet från
   `ntfy-secrets/phone-password`, och gör den till standardserver. Öppna Sidekick igen så att den registrerar sig mot
   den servern.
4. I Sidekick: Inställningar, "Skicka testavisering". Om inget kommer fram, se Felsökning.
