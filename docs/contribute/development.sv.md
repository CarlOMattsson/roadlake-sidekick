# Utvecklingsguide

[English](development.md)

Hur du bygger, kontrollerar och släpper Roadlake Sidekick lokalt. Pull requests är välkomna men hanteras i begränsad omfattning (se CONTRIBUTING.md); det här är kontrollerna som underhållarna tillämpar på varje ändring.

## Utvecklingsmiljö

Python 3.13 med `uv`, Node.js 22 med npm 10 och Docker (för PostgreSQL). Alla steg finns i
[Kör Sidekick lokalt som utvecklare](../start/first-contribution.sv.md). I korthet, från repots rot:

```bash
[ -f .env ] || cp .env.example .env
uv sync --project backend --all-groups
npm --prefix frontend ci
docker compose -f deploy/compose.dev.yaml up -d db
```

Checka aldrig in `.env` eller någon fil med riktiga hemligheter.

## Kontroller och tester

```bash
# Backend: stil och typer
(cd backend && uv run ruff format --check . && uv run ruff check --no-cache . && uv run pyright)

# Frontend: stil, typer och enhetstester
npm --prefix frontend run format:check
npm --prefix frontend run check            # eslint + tsc -b + vitest

# Backendtester (kräver engångsdatabasen PostgreSQL på port 55433 nedan, "Kör testerna")
(cd backend && uv run pytest --full)
# Bara repots regler (skanning av källkod, dokument och konfiguration; CI kör dem som eget steg, ingen databas)
(cd backend && uv run pytest --full -m policy)

# Webbläsartester för MCP-appen (Playwright med Chromium: `npx playwright install chromium` i frontend/)
npm --prefix frontend run build:mcp-app
npm --prefix frontend run test:mcp-app
(cd frontend && npx playwright test --config playwright.mobile-audit.config.ts)
```

För att köra hela den lokala sviten som ska vara grön före en push i ett svep finns `tools/check-all.sh`. Den kör
backendtesterna parallellt på en egen plats i testdatabasen (`--slot`, 1 till 20; se `tools/test-db-pool.md`), därefter
ruff och pyright, versions- och migrationskontrollerna, shellcheck, gitleaks, frontendkontrollerna, bygget och
webbläsartesterna för MCP-appen och Androids Gradle-bygge. Backendtesterna körs med CI:s täckningsgräns (90 %), och
mobilpaketet byggs före frontendkontrollerna eftersom `mobile-csp.test.ts` läser det. Den rör
ingen annan databas än testcontainern på port 55433. Varje del har en `--skip-...`-flagga, och `--dry-run` skriver ut
kommandona utan att köra dem:

```bash
bash tools/check-all.sh --slot 3                  # allt
bash tools/check-all.sh --slot 3 --skip-android   # utan Android-bygget
bash tools/check-all.sh --help                    # alla flaggor
```

shellcheck och gitleaks måste vara installerade lokalt. Saknas ett av dem skriver steget `SKIPPED: <verktyg> missing
(install: ...)` och redovisas som SKIPPED i sammanfattningen, aldrig som ok; `--strict` gör det till ett fel.

Den kör inte Playwrights mobilgranskning, frontendens täckningsgräns, beroendegranskningarna, kontrollen av
kontraktsögonblicksbilder eller emulatortestet; det gör CI, så kör de nedan som hör till det du har
ändrat.

CI kör mer än kommandona ovan. Kör dem som hör till det du har ändrat:

```bash
# Kontraktsfiler: generera om (se "Kodstil") och kontrollera att `git diff --exit-code -- contracts` är ren.

# Migreringar: en ny fil under migrations/ får bara innehålla expand-satser om den inte är märkt
# `# migration-class: contract` (se tools/check-migration-policy.py)
python3 tools/check-migration-policy.py --base origin/main

# Android-skalet: JVM-enhetstester (kräver JDK 21 och Node.js 22; ingen emulator, ingen signering)
npm --prefix frontend run build:mobile
(cd frontend && npx cap sync android)
(cd frontend/android && ./gradlew test)

# Skalskript (CI kontrollerar också filer utan ändelse som börjar med sh- eller bash-shebang)
git ls-files -z '*.sh' | xargs -0 shellcheck --severity=warning

# Beroenden (.github/workflows/audit.yml): pip-audit över alla låsta Python-grupper, `npm audit --audit-level=high --omit=dev`
# över de levererade frontend-beroendena och OSV-Scanner över Androids Gradle-låsfiler (kräver Docker)
bash .github/audit/pip-audit.sh
bash .github/audit/osv-gradle.sh
```

CI söker också efter incheckade hemligheter (gitleaks) och bygger API-imagen (`backend/Dockerfile`). Flera
jobb körs bara när filerna de täcker har ändrats.

Backendtesterna tömmer databasen de använder. Kör dem bara mot engångsdatabasen som beskrivs under
"Kör testerna" nedan, aldrig mot en databas med riktig data.

### Genererade filer som är incheckade

`backend/src/sidekick/mcp/apps/sidekick.html` (MCP-appen som en enda fil) och `contracts/mcp-tools.generated.json`
(verktygskontraktet) är byggresultat, men de checkas in med avsikt: backenden levererar HTML-filen som den är, så att en
ny klon eller en Docker-avbild fungerar utan Node-verktyg, och det incheckade kontraktet gör varje ändring av ett verktyg
synlig i granskningen. Bygg om dem efter ändringar i MCP-appens källkod eller verktygsdefinitionerna och checka in
resultatet:

```bash
npm --prefix frontend run build:mcp-app
uv run --project backend python -m sidekick.mcp.export_contract --output contracts/mcp-tools.generated.json
```

`tools/check-all.sh` bygger om MCP-appens HTML och misslyckas när den incheckade bunten skiljer sig. Den jämför inte
kontraktsfilen; det gör CI, så generera om den med det andra kommandot när du ändrar ett verktyg.

## Webbplats

Den publika webbplatsen är ett Astro Starlight-projekt i `website/`. Den visar dokumenten i det här repot (de
listas i `website/content-map.mjs`) på svenska och engelska, vid sidan av några handskrivna sidor, och byggs till
statiska filer i `website/dist/`. Den kräver Node.js 22.23.4 eller senare (`website/.node-version`).

```bash
npm --prefix website ci --ignore-scripts   # en gång; låsfilen är exakt, kör aldrig vanlig npm install
npm --prefix website test                  # enhetstester av synkskriptet
npm --prefix website run build             # synka dokumenten och bygg sedan till website/dist/
npm --prefix website run preview           # förhandsvisa på http://localhost:4321
npm --prefix website run check             # länkar, tillgänglighet, priser, integritet och sidbudget
```

`SITE_URL` och `SITE_BASE` anger adressen webbplatsen byggs för (förval `https://roadlake.com`, ingen
basväg). Sidorna för dokumenten genereras ur källorna av `website/scripts/sync-docs.mjs` och checkas inte in.
Vill du ändra vilka dokument som visas ändrar du `website/content-map.mjs`, inte skriptet.

Kontroller som vaktar webbplatsen:

- `backend/tests/policy/test_docs_language_parity.py`: varje publicerat dokument har en engelsk och en svensk
  tvilling med samma struktur, och de handskrivna sidorna och gränssnittstexterna stämmer i båda språken.
- Det extra steget i `tools/check-all.sh` (finns bara i underhållarnas utcheckning; en
  publicerad klon hoppar över det): exporterar repot och kontrollerar sedan att varje källa i innehållskartan finns
  i exporten.
- `tools/check-all.sh`: steget `website` kör testerna, bygget och webbplatskontrollerna; det hoppas över (och
  fäller med `--strict`) när `website/node_modules` saknas. `--skip-website` utesluter det.
- `.github/workflows/pages.yml`: bygger, kontrollerar och publicerar webbplatsen när en release publiceras eller
  vid manuell körning. Den använder inga hemligheter.

## Kodstil

- Python: `ruff format` och `ruff check` (radlängd och regler står i `backend/pyproject.toml`), typat med
  `pyright`.
- TypeScript/React: `eslint` och `prettier`, som körs med `npm --prefix frontend run lint` och `format:check`.
- Följ koden runt omkring. Ingen kopierad kod, ingen död kod, inget nytt beroende utan skäl.
- Lägg till tester tillsammans med ändringen, även tester för behörighet och maskning (redaction) där
  det är relevant. Försvaga eller ta inte bort ett meningsfullt test för att få en körning grön.
- Efter en ändring i API eller MCP: generera om de incheckade artefakterna i stället för att redigera dem
  för hand:

  ```bash
  uv run --project backend python -m sidekick.api.export_openapi --output contracts/openapi.generated.json
  uv run --project backend python -m sidekick.mcp.export_contract --output contracts/mcp-tools.generated.json
  uv run --project backend python -m sidekick.api.export_companion_contract --output contracts/companion-api.generated.json
  npm --prefix frontend run build:mcp-app
  ```

- Redigera inte en migrering som redan har körts; lägg till en ny numrerad fil under `migrations/`. Schemat
  utgår från baslinjen 0.1.0 (`100_baseline_0_1_0.py`), så nya filer fortsätter från `101_`. Hur data flyttas mellan
  0.1.0-installationer (det finns ingen import från tidigare) står i [körboken för baslinjen](../explanation/schema-baseline.sv.md).

## Release

Taggar, versioner och releasestegen står i [Släpp en version](../maintainers/release.sv.md).

## Kör testerna

Statiska kontroller och frontendens enhetstester:

```bash
(cd backend && uv run ruff format --check . && uv run ruff check --no-cache . && uv run pyright)
npm --prefix frontend run format:check
npm --prefix frontend run check            # lint + typkontroll + vitest
npm --prefix frontend run build
```

Backendsviten använder en PostgreSQL **för engångsbruk** på port **55433** och vägrar köra mot någon annan
databas, eftersom den tömmer den data den hittar. Rikta den aldrig mot en databas med riktig data.

```bash
docker compose -f deploy/compose.test.yaml up -d --wait db

uv run --project backend yoyo apply --batch \
  --database postgresql+psycopg://sidekick_migrator:sidekick_migrator@127.0.0.1:55433/sidekick_test migrations

(cd backend && uv run pytest --full)
```

Sviten väljer själv sin databas och bortser från `.env` och vanliga `SIDEKICK_*`-inställningar för körning.
Den behåller och kontrollerar bara uttryckliga testdatabasinställningar (`SIDEKICK_TEST_DATABASE_URL` och de
andra `SIDEKICK_TEST_*`-variablerna, som måste peka ut en engångsdatabas `sidekick_test` på en loopback-testport,
55433 som förval). Med `--full` (och med `CI=true`) misslyckas ett databasberoende test när databasen inte går att nå; bara en snabbkörning
utan `--full` hoppar över sådana tester, och skälet skrivs ut. En körning med många överhoppade tester är ingen
fullständig verifiering. `docker compose -f deploy/compose.test.yaml down`
tar bort databasen igen. Vill du köra flera sviter samtidigt, eller parallellt med `-n`, ger du var och en en
egen databas; se [tools/test-db-pool.md](../../tools/test-db-pool.md).

Webbläsartesterna laddar den byggda MCP-appen i en simulerad värd:

```bash
(cd frontend && npx playwright install chromium)
npm --prefix frontend run build:mcp-app
npm --prefix frontend run test:mcp-app
npm --prefix frontend run test:mobile-audit
```

Håll de genererade kontraktsfilerna i synk efter en ändring i API eller MCP:

```bash
uv run --project backend python -m sidekick.api.export_openapi --output contracts/openapi.generated.json
uv run --project backend python -m sidekick.mcp.export_contract --output contracts/mcp-tools.generated.json
uv run --project backend python -m sidekick.mcp.export_tool_reference
uv run --project backend python -m sidekick.export_reference
uv run --project backend python -m sidekick.api.export_companion_contract --output contracts/companion-api.generated.json
```
