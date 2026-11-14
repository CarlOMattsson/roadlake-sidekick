# Slå på minnet

[English](memory.md)

<!-- description: Slå på Sidekicks minne med profilen `memory`. Ingenting härleds eller skickas förrän du har gjort det, och texten går till den modellleverantör du väljer. -->

Slå på Sidekicks minne med profilen `memory`. Ingenting härleds eller skickas förrän du har gjort det, och texten går till den modellleverantör du väljer.

Profilen `memory` lägger till Hindsight och en worker som matar det från din dagbok, dina kontakter, projekt
och uppgifter. Inget härleds eller skickas förrän du slår på det, och materialet går till den
språkmodellsleverantör du väljer.

1. `cp hindsight.env.example hindsight.env && chmod 600 hindsight.env`. Fyll i leverantör, bas-URL, modell och
   nyckel (`HINDSIGHT_API_LLM_*`) och en tenant-nyckel (`HINDSIGHT_API_TENANT_API_KEY`, `openssl rand -base64 48`).
   Inbäddningar och omrankning körs lokalt i containern. **Det som lämnar din maskin:** texten som Hindsight
   utvinner fakta ur, skickad till den leverantören med den nyckeln. Fyll i filen först när du har bestämt dig
   för det. För en leverantör i ditt eget nät: använd en OpenAI-kompatibel server och sätt
   `HINDSIGHT_API_LLM_PROVIDER=openai` med dess bas-URL. Tjänsten körs offline med skrivskyddat rotfilsystem, så de
   lokala inbäddnings- och omrankningsmodellerna måste vara de som redan finns i imagen: väljer du en annan
   `HINDSIGHT_API_EMBEDDINGS_*`- eller `HINDSIGHT_API_RERANKER_*`-modell laddar Hindsight inte ner den och startar inte.
2. Avkommentera blocket `SIDEKICK_MEMORY_*` i `selfhost.env`: `SIDEKICK_MEMORY_PROVIDER=hindsight`,
   `SIDEKICK_MEMORY_HINDSIGHT_BASE_URL=http://hindsight:8888`, `SIDEKICK_MEMORY_HINDSIGHT_API_TOKEN` (samma värde som
   tenant-nyckeln i `hindsight.env`), `SIDEKICK_MEMORY_ID_DERIVATION_KEY`, och sätt `SIDEKICK_MEMORY_ENABLED=true`.
3. `docker compose --env-file selfhost.env --profile memory up -d` (lägg till `--profile vps` på en VPS).
   Hindsight vägrar starta om `HINDSIGHT_API_RETAIN_CHUNK_SIZE` inte är lägre än
   `HINDSIGHT_API_RETAIN_MAX_COMPLETION_TOKENS`.

**Hindsight-version.** Profilen `memory` pinnar Hindsight 1.2.1 med digest (`ghcr.io/vectorize-io/hindsight:1.2.1@sha256:d2bc230a...`).
Utgåvan beskrivs i `contracts/reviewed/hindsight-memory/hindsight-memory-sources.yaml`. Ändra inte digesten för hand.

**Flytta en befintlig minnesvolym till en ny Hindsight-version.** Hindsight migrerar databasen i sin volym när den startar
på en nyare version, och steget kan inte ångras: en äldre Hindsight startar inte på en migrerad volym. Arkivera volymen
först (se [Säkerhetskopiering och återställning](backup-and-restore.sv.md), "Hindsight-minnet"), uppdatera sedan; för att
gå tillbaka återställer du arkivet med den tidigare avbilden. Flytten från 0.8.4 till 1.2.1 kördes mot en volym med
banker, dokument och fakta: allt fanns kvar efteråt, och sökning, lagring och radering fungerade på de migrerade
uppgifterna. Sidekick kontrollerar vid start att varje bank fortfarande har sina dokument och skickar på nytt det som saknas.

Minnesinställningarna heter `SIDEKICK_MEMORY_*`.
