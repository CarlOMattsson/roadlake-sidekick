# The model server

[Svenska](model-server.sv.md)

<!-- description: Memory on the work laptop uses your company's own model server. This page explains what the server has to support and how to configure it. -->

Memory on the work laptop uses your company's own model server. This page explains what the server has to support and how to configure it.

The model server is optional and only needed for the memory. With `SIDEKICK_WORK_MEMORY=off` in `work.env` (the default; `bash tools/work.sh setup` asks) Hindsight and the memory worker are not started, and `status` shows the memory as off.

- Hindsight's extraction may use tool calls, so vLLM should run the model with automatic tool choice:
  `--enable-auto-tool-choice --tool-call-parser <parser>`. The parser must match the model family, for example
  `glm45` or `glm47` for GLM and `deepseek_v31` for DeepSeek V3.1 in the vLLM documentation
  ([tool calling](https://docs.vllm.ai/en/latest/features/tool_calling/)). The exact parser for GLM 5.3 and
  DeepSeek V4.1 Flash was not verifiable here: check the model card and your vLLM version.
- Structured JSON answers (Hindsight's fact extraction) use `response_format`, which vLLM
  supports without extra flags. If a weak model returns broken JSON in Hindsight's logs, set
  `HINDSIGHT_API_LLM_STRICT_SCHEMA=true` for the `hindsight` service.
- Hindsight uses its provider value **`openai`** for any OpenAI-compatible server with its own base URL
  (`HINDSIGHT_API_LLM_PROVIDER=openai`, `HINDSIGHT_API_LLM_BASE_URL`, `HINDSIGHT_API_LLM_MODEL`; the key is required
  but may be any text for a server that checks nothing). Source: Hindsight v1.1.0, `hindsight-docs/docs/developer/configuration.mdx`
  and `docker/docker-compose/local-llm/docker-compose.yaml`
  ([GitHub](https://github.com/vectorize-io/hindsight/blob/v1.1.0/docker/docker-compose/local-llm/docker-compose.yaml)).
  `ollama` and `lmstudio` are separate provider values for those two servers.
- Embeddings and reranker run inside the Hindsight image by default (models are baked in, nothing is downloaded).
  To use an `/embeddings` endpoint on the same vLLM instead, set `SIDEKICK_WORK_EMBEDDINGS_PROVIDER=openai` and
  `SIDEKICK_WORK_EMBEDDINGS_MODEL` before the first start (Hindsight: `HINDSIGHT_API_EMBEDDINGS_PROVIDER=openai`,
  `HINDSIGHT_API_EMBEDDINGS_OPENAI_BASE_URL`, `HINDSIGHT_API_EMBEDDINGS_OPENAI_MODEL`, same configuration page).
  Vectors from different models cannot be mixed, so do not switch on a database that already holds memories.
