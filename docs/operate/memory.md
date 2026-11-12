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
2. In `selfhost.env` uncomment the `SIDEKICK_MEMORY_*` block: `SIDEKICK_MEMORY_PROVIDER=hindsight`,
   `SIDEKICK_MEMORY_HINDSIGHT_BASE_URL=http://hindsight:8888`, `SIDEKICK_MEMORY_HINDSIGHT_API_TOKEN` (the same value as the
   tenant key in `hindsight.env`), `SIDEKICK_MEMORY_ID_DERIVATION_KEY`, and set `SIDEKICK_MEMORY_ENABLED=true`.
3. `docker compose --env-file selfhost.env --profile memory up -d` (add `--profile vps` on a VPS). Hindsight refuses to
   start if `HINDSIGHT_API_RETAIN_CHUNK_SIZE` is not below `HINDSIGHT_API_RETAIN_MAX_COMPLETION_TOKENS`.

**Hindsight version.** The `memory` profile pins Hindsight 0.8.4 by digest (`ghcr.io/vectorize-io/hindsight@sha256:2c60f233...`).
Version 1.1.0 is chosen in `contracts/reviewed/hindsight-memory/hindsight-memory-sources.yaml` but is not yet
delivered here: its live retain and recall checks still have to pass, and an existing memory volume would be
migrated when it moves. Do not change the digest by hand.

The memory settings are `SIDEKICK_MEMORY_*`.
