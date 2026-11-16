# Självhostad Sidekick

[English](README.md)

Den här katalogen är Docker Compose-paketet för att köra Sidekick på en maskin du själv styr över. Det startar
Sidekicks API, PostgreSQL, en migrerare som körs en gång, automationsworkern och, beroende på profil, Caddy
(TLS) eller Tailscale Funnel (hemdator), Hindsight (minne), krypterade backuper och push-workern (ntfy). Det finns med
avsikt ingen webbtjänst med eget gränssnitt: produktens gränssnitt är MCP-appar inne i din LLM-klient.

Allt beskrivs i kommentarerna i `compose.yaml`. Guiderna ligger i `docs/`, i den ordning du behöver dem:

- [Första starten på en server](../../docs/start/self-hosted-server.sv.md)
- [Anslut Claude](../../docs/operate/connect-claude.sv.md)
- [Bygg, installera och para ihop Android](../../docs/operate/pair-android.sv.md)
- [Slå på minnet](../../docs/operate/memory.sv.md)
- [Uppdatera](../../docs/operate/update.sv.md)
- [Backup och återställning](../../docs/operate/backup-and-restore.sv.md)
- [Töm papperskorgen](../../docs/operate/empty-trash.sv.md)
- [Hemdator med Tailscale Funnel](../../docs/start/self-hosted-server.sv.md#första-start): `docker compose --env-file selfhost.env --profile tailscale up -d` publicerar API:et på ditt `ts.net`-namn; ingen ändring av router eller brandvägg.
- [Compose-profiler och filer](../../docs/reference/selfhost-profiles.sv.md): vad varje profil startar och vad varje fil i den här katalogen används till.

## AI-steg på servern (profilen `ai`, valfri)

Profilen `ai` startar en extra container, `ai-worker`, som kör godkända AI-steg på servern med din egen Anthropic-nyckel.
Den är av tills du slår på den:

1. Lägg nyckeln i en fil som bara du kommer åt, och inget annat i filen:
   `mkdir -p secrets && chmod 700 secrets && printf '%s\n' <din nyckel> > secrets/ai_anthropic_api_key && chmod 644 secrets/ai_anthropic_api_key`
   (läge 644 i en katalog med läge 700 är hur Compose-hemligheter fungerar här, se `selfhost.env.example`). Lägg aldrig nyckeln i `selfhost.env`:
   API:et vägrar starta i produktion om det hittar den där.
2. Sätt `SELFHOST_AI_ANTHROPIC_API_KEY_FILE=./secrets/ai_anthropic_api_key` och `SIDEKICK_AI_RUNNER_ENABLED=true` i
   `selfhost.env`. Välj en annan modell med `SIDEKICK_AI_MODEL` om du vill ha en annan än förvalet.
3. Starta den: `docker compose --env-file selfhost.env --profile ai up -d`. `update.sh` låter den fortsätta köra över
   uppdateringar när den väl kör; en server som aldrig startat profilen påverkas inte.

Nyckeln når bara `ai-worker`, och bara som fil. Den containern är den enda på nätverket `ai`, den enda utgående vägen till
internet (Anthropics API); den delar inget nätverk med Hindsight eller ntfy. Sätt en utgiftsgräns för nyckeln i Anthropic
Console som yttre bälte; Sidekicks egna tak (`SIDEKICK_AI_MONTHLY_CAP_USD` och taket per uppgift) är det inre.
