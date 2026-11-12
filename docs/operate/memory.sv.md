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

**Hindsight-version.** Profilen `memory` pinnar Hindsight 0.8.4 med digest (`ghcr.io/vectorize-io/hindsight@sha256:2c60f233...`).
Version 1.1.0 är vald i `contracts/reviewed/hindsight-memory/hindsight-memory-sources.yaml` men levereras inte här ännu:
de skarpa retain- och recall-kontrollerna måste först klaras, och en befintlig minnesvolym skulle migreras vid
flytten. Ändra inte digesten för hand.

Minnesinställningarna heter `SIDEKICK_MEMORY_*`.
