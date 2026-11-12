# Modellservern

[English](model-server.md)

<!-- description: Minnet på jobbdatorn använder företagets egen modellserver. Här står vad servern behöver klara och hur du ställer in den. -->

Minnet på jobbdatorn använder företagets egen modellserver. Här står vad servern behöver klara och hur du ställer in den.

- Hindsights utvinning kan använda verktygsanrop, så vLLM bör köra modellen med automatiskt verktygsval:
  `--enable-auto-tool-choice --tool-call-parser <parser>`. Parsern ska passa modellfamiljen, till exempel `glm45` eller
  `glm47` för GLM och `deepseek_v31` för DeepSeek V3.1 enligt vLLM-dokumentationen
  ([tool calling](https://docs.vllm.ai/en/latest/features/tool_calling/)). Rätt parser för GLM 5.3 och DeepSeek V4.1
  Flash gick inte att verifiera här: läs modellkortet och kontrollera din vLLM-version.
- Strukturerade JSON-svar (Hindsights faktautvinning) använder `response_format`, som vLLM stödjer
  utan extra flaggor. Om en svag modell ger trasig JSON i Hindsights logg: sätt `HINDSIGHT_API_LLM_STRICT_SCHEMA=true`
  för tjänsten `hindsight`.
- Hindsight använder providervärdet **`openai`** för varje OpenAI-kompatibel server med egen bas-URL
  (`HINDSIGHT_API_LLM_PROVIDER=openai`, `HINDSIGHT_API_LLM_BASE_URL`, `HINDSIGHT_API_LLM_MODEL`; nyckeln krävs men kan
  vara valfri text om servern inte kontrollerar den). Källa: Hindsight v1.1.0,
  `hindsight-docs/docs/developer/configuration.mdx` och
  [`docker/docker-compose/local-llm/docker-compose.yaml`](https://github.com/vectorize-io/hindsight/blob/v1.1.0/docker/docker-compose/local-llm/docker-compose.yaml).
  `ollama` och `lmstudio` är egna providervärden för de två servrarna.
- Inbäddningar och omrankning körs som standard inne i Hindsight-avbildningen (modellerna ligger i avbildningen,
  inget laddas ner). För att i stället använda en `/embeddings`-endpoint på samma vLLM: sätt
  `SIDEKICK_WORK_EMBEDDINGS_PROVIDER=openai` och `SIDEKICK_WORK_EMBEDDINGS_MODEL` före första starten (Hindsight:
  `HINDSIGHT_API_EMBEDDINGS_PROVIDER=openai`, `HINDSIGHT_API_EMBEDDINGS_OPENAI_BASE_URL`,
  `HINDSIGHT_API_EMBEDDINGS_OPENAI_MODEL`, samma konfigurationssida). Vektorer från olika modeller kan inte blandas,
  så byt inte på en databas som redan har minnen.
