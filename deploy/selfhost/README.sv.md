# Självhostad Sidekick

[English](README.md)

Den här katalogen är Docker Compose-paketet för att köra Sidekick på en maskin du själv styr över. Det startar
Sidekicks API, PostgreSQL, en migrerare som körs en gång, automationsworkern och, beroende på profil, Caddy
(TLS), Hindsight (minne), krypterade backuper och push-workern (ntfy). Det finns med avsikt ingen webbtjänst med eget
gränssnitt: produktens gränssnitt är MCP-appar inne i din LLM-klient.

Allt beskrivs i kommentarerna i `compose.yaml`. Guiderna ligger i `docs/`, i den ordning du behöver dem:

- [Första starten på en server](../../docs/start/self-hosted-server.sv.md)
- [Anslut Claude](../../docs/operate/connect-claude.sv.md)
- [Bygg, installera och para ihop Android](../../docs/operate/pair-android.sv.md)
- [Slå på minnet](../../docs/operate/memory.sv.md)
- [Uppdatera](../../docs/operate/update.sv.md)
- [Backup och återställning](../../docs/operate/backup-and-restore.sv.md)
- [Töm papperskorgen](../../docs/operate/empty-trash.sv.md)
- [Compose-profiler och filer](../../docs/reference/selfhost-profiles.sv.md): vad varje profil startar och vad varje fil i den här katalogen används till.
