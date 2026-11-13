# Compose-profiler och filer

[English](selfhost-profiles.md)

<!-- description: Vilka tjänster varje Compose-profil startar, och vad filerna i självhostpaketet är till för. -->

Vilka tjänster varje Compose-profil startar, och vad filerna i självhostpaketet är till för.

## Profiler

Bastacken behöver ingen profil. Lägg profilerna på samma kommandorad som `docker compose --env-file selfhost.env`.

| Profil | Tjänster den lägger till | Vad den är till för |
| --- | --- | --- |
| ingen | `postgres`, `migrate`, `api`, `automation-worker` | API:t, databasen, migreraren som körs en gång och workern som kör schemalagda processer. Bara API:t är publicerat, på `127.0.0.1:8000`. |
| `vps` | `caddy` | TLS på portarna 80 och 443 med automatiskt certifikat. Lämna den utanför på en hemdator bakom en tunnel. |
| `memory` | `hindsight`, `memory-worker` | Härlett minne. Kräver `hindsight.env` och inställningarna `SIDEKICK_MEMORY_*`; se [Slå på minnet](../operate/memory.sv.md). |
| `backup` | `backup` | Krypterade backuper. Kräver `SIDEKICK_BACKUP_ENCRYPTION_KEY` i `selfhost.env`; se [Backup och återställning](../operate/backup-and-restore.sv.md). |
| `push` | `push`, `ntfy` | Påminnelser till Android-appen. Kräver `SIDEKICK_PUSH_ENABLED=true`. Den egna ntfy-servern publiceras genom Caddy, så den kräver profilen `vps`; `up -d push` ensam startar bara workern, som då levererar genom ntfy.sh. Se [Påminnelser via ntfy](../operate/push-reminders.sv.md). |

## Filer i `deploy/selfhost`

| Fil | Vad den är till för |
| --- | --- |
| `compose.yaml` | Hela stacken, med varje tjänst och profil beskriven i sina kommentarer. |
| `selfhost.env.example` | Inställningarna för API:t och workerna. Kopiera till `selfhost.env` och håll den filen på läge 600. |
| `db.env.example` | Databaslösenorden. Kopiera till `db.env`. PostgreSQL läser den bara vid första starten av en tom volym. |
| `hindsight.env.example` | Leverantör, modell och nyckel för profilen `memory`. Kopiera till `hindsight.env`. |
| `ntfy.env.example` | Inställningarna för den egna ntfy-servern, för profilen `push`. |
| `Caddyfile.example` | Caddys konfiguration för profilen `vps`. Kopiera till `Caddyfile`. |
| `ntfy/server.yml` | Den härdade ntfy-serverns konfiguration. |
| `ntfy-init.sh` | Engångsinställning av ntfy-kontona. Den skriver inte ut någon hemlighet. |
| `secrets-to-files.sh` | Flyttar hemligheterna i `selfhost.env` till filer i `secrets/` och skriver inte ut något värde. Se [Hemligheter som filer](../operate/limits-and-secrets.sv.md#hemligheter-som-filer). |
| `postgres-init.sh` | Skapar databasrollerna vid första starten av en tom volym. |
| `update.sh` | Uppdaterar till en signerad, digest-låst image, med en krypterad ögonblicksbild först. Se [Uppdatera](../operate/update.sv.md). Kontrollen av ledigt utrymme och rensningen av ögonblicksbilder körs från `tools/workctl` i samma utcheckning (`python3`). |
| `restore.sh` | Återställer en ägare från en krypterad backup eller en vanlig export. Se [Backup och återställning](../operate/backup-and-restore.sv.md). |
| `restore-ownership.sql` | Ger varje objekt tillbaka sin ägare efter att en vanlig SQL-dump har återställts. |
| `snapshot_crypto.py` | Krypterar och dekrypterar de databasögonblicksbilder som `update.sh` tar. |
| `update_policy.py` | Besluten i `update.sh` (versioner, migreringsklass, återställning, återupptagning). Kräver värdens `python3` (3.9 eller nyare, bara standardbiblioteket). |
| `min-upgrade-from.txt` | Den äldsta version som en ny release kan uppdateras från. |
