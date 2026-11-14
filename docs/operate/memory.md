# Turn on memory

[Svenska](memory.sv.md)

<!-- description: Turn on Sidekick's memory with the `memory` profile. Nothing is derived or sent until you do, and the text goes to the model provider you choose. -->

Turn on Sidekick's memory with the `memory` profile. Nothing is derived or sent until you do, and the text goes to the model provider you choose.

The `memory` profile adds Hindsight and a worker that feeds it from your journal, contacts, projects and tasks. Nothing
is derived or sent until you turn it on, and the material goes to the language model provider you choose.

1. `cp hindsight.env.example hindsight.env && chmod 600 hindsight.env`. Fill in the provider, base URL, model and key
   (`HINDSIGHT_API_LLM_*`) and a tenant key (`HINDSIGHT_API_TENANT_API_KEY`, `openssl rand -base64 48`).
   Embeddings and reranking run locally in the container. **What leaves your machine:** the text Hindsight extracts
   facts from, sent to that provider with that key. Fill the file in only once you have decided that. For a provider on
   your own network use an OpenAI-compatible server and set `HINDSIGHT_API_LLM_PROVIDER=openai` with its base URL.
   The service runs offline with a read-only root filesystem, so the local embedding and reranker models must be the
   ones already in the image: if you set a different `HINDSIGHT_API_EMBEDDINGS_*` or `HINDSIGHT_API_RERANKER_*` model,
   Hindsight does not download it and fails to start.
2. In `selfhost.env` uncomment the `SIDEKICK_MEMORY_*` block: `SIDEKICK_MEMORY_PROVIDER=hindsight`,
   `SIDEKICK_MEMORY_HINDSIGHT_BASE_URL=http://hindsight:8888`, `SIDEKICK_MEMORY_HINDSIGHT_API_TOKEN` (the same value as the
   tenant key in `hindsight.env`), `SIDEKICK_MEMORY_ID_DERIVATION_KEY`, and set `SIDEKICK_MEMORY_ENABLED=true`.
3. `docker compose --env-file selfhost.env --profile memory up -d` (add `--profile vps` on a VPS). Hindsight refuses to
   start if `HINDSIGHT_API_RETAIN_CHUNK_SIZE` is not below `HINDSIGHT_API_RETAIN_MAX_COMPLETION_TOKENS`.

**Hindsight version.** The `memory` profile pins Hindsight 1.2.1 by digest (`ghcr.io/vectorize-io/hindsight:1.2.1@sha256:d2bc230a...`).
The release is described in `contracts/reviewed/hindsight-memory/hindsight-memory-sources.yaml`. Do not change the digest by hand.

**Moving an existing memory volume to a new Hindsight version.** Hindsight migrates the database in its volume when it
starts on a newer version, and that step cannot be undone: an older Hindsight does not start on the migrated volume.
Archive the volume first (see [Backup and restore](backup-and-restore.md), "Hindsight memory"), then update; to go back,
restore the archive with the previous image. The move from 0.8.4 to 1.2.1 was run against a volume with banks,
documents and facts: all of them were still there afterwards, and recall, retain and delete worked on the migrated data.
Sidekick checks at start that every bank still holds its documents and sends again what is missing.

The memory settings are `SIDEKICK_MEMORY_*`.
