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
# Bara repots regler (skanning av källkod, dokument och konfiguration; release-CI kör dem som eget steg, ingen databas)
(cd backend && uv run pytest --full -m policy)

# Webbläsartester för MCP-appen, i den Playwright-avbild som CI använder (tools/ci-images.sh; kräver Docker).
# Typsnitt avgör kortens höjd, så en körning med en annan webbläsarbygge kan skilja sig från CI:
# `npm --prefix frontend run test:mcp-app` med din egen Chromium är en snabb loop, inte kontrollen.
npm --prefix frontend run build:mcp-app
bash tools/playwright-docker.sh npx playwright test --config playwright.mcp-app.config.ts
bash tools/playwright-docker.sh npx playwright test --config playwright.mobile-audit.config.ts
```

För att köra hela den lokala sviten som ska vara grön före en push i ett svep finns `tools/check-all.sh`. Den kör
backendtesterna parallellt på en egen plats i testdatabasen (`--slot`, 1 till 20; se `tools/test-db-pool.md`), därefter
ruff och pyright, versions- och migrationskontrollerna, shellcheck, gitleaks, frontendkontrollerna, bygget och
webbläsartesterna för MCP-appen, en kontroll av den publika exporten (`published-tree`: exporten byggs i en temporär
katalog och lintas, typkontrolleras och testas där som den publicerade CI kommer att göra) och Androids Gradle-bygge.
Backendtesterna körs med CI:s täckningsgräns (90 %), testerna körs i UTC som på CI-runnern (frontendens enhetstester
även en gång i `America/Los_Angeles`), och mobilpaketet byggs före frontendkontrollerna eftersom `mobile-csp.test.ts`
läser det. Den rör ingen annan databas än testcontainern på port 55433. Varje del har en `--skip-...`-flagga, och `--dry-run` skriver ut
kommandona utan att köra dem:

```bash
bash tools/check-all.sh --slot 3                  # allt
bash tools/check-all.sh --slot 3 --skip-android   # utan Android-bygget
bash tools/check-all.sh --slot 3 --release        # plus resten av releasegrinden
bash tools/check-all.sh --help                    # alla flaggor
```

Docker behövs för shellcheck, gitleaks och Playwright-testerna: de körs i de avbilder som är fastnålade i
`tools/ci-images.sh`, samma som CI använder, så versioner, webbläsare och typsnitt stämmer. Saknas Docker skriver steget
`SKIPPED: docker missing ...` och redovisas som SKIPPED i sammanfattningen, aldrig som ok; `--strict` gör det till ett
fel.

Som standard kör den inte Playwrights mobilgranskning, frontendens täckningsgräns, beroendegranskningarna eller
kontraktsdiffen. Lägg till `--release` för att köra dem också, och drillen, i samma ordning som release-CI (se
[releasechecklistan](../maintainers/release.sv.md)); beroendegranskningen kräver nätverk och rapporteras som `SKIPPED`
när det inte nås. Emulatortestet, avbildsbygget och Compose-röktestet lämnas åt release-CI, så kör de nedan som hör
till det du har ändrat. Före varje release: kör `bash tools/check-all.sh --slot K --release` och starta sedan `ci.yml`
för hand i det publika repot.

CI körs inte för pull requests, sammanslagningar eller pushar; det är en grind vid varje release (och kan startas för
hand). Kontrollerna kör alltså du själv innan du pushar: installera hookarna med `pre-commit install --hook-type
pre-commit --hook-type pre-push` och kör kommandona som hör till det du har ändrat. Release-CI kör mer än kommandona ovan:

```bash
# Kontraktsfiler: generera om (se "Kodstil") och kontrollera att `git diff --exit-code -- contracts` är ren.

# Migreringar: en ny fil under migrations/ får bara innehålla expand-satser om den inte är märkt
# `# migration-class: contract` (se tools/check-migration-policy.py)
python3 tools/check-migration-policy.py --base origin/main

# Android-skalet: JVM-enhetstester (kräver JDK 21 och Node.js 22; ingen emulator, ingen signering)
npm --prefix frontend run build:mobile
(cd frontend && npx cap sync android)
(cd frontend/android && ./gradlew test)

# Skalskript (CI kontrollerar också filer utan ändelse som börjar med sh- eller bash-shebang), i CI:s avbild
bash tools/shellcheck-ci.sh

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

`tools/check-all.sh` bygger om MCP-appens HTML och misslyckas när den incheckade bunten skiljer sig. Med `--release` jämför den
dessutom kontraktsfilerna; generera om verktygskontraktet med det andra kommandot när du ändrar ett verktyg.

### Androids beroendelås

Varje Gradle-konfiguration i Android-skalet är låst (`dependencyLocking` i `frontend/android/build.gradle`), och låsfilerna
ligger i `frontend/android/gradle/locks/<projekt>.lockfile`. Skriv om dem efter en beroendeändring genom att köra de
uppgifter CI kör, så att varje konfiguration som används hamnar i ett lås:

```bash
cd frontend/android
./gradlew :app:ktlintCheck :app:testDebugUnitTest :app:lintDebug :app:assembleRelease :app:assembleDebugAndroidTest --write-locks
```

Granska diffen av `gradle/locks/` som en beroendeändring. Ett beroende som saknas i ett lås gör bygget rött i stället för att
tyst välja en nyare version.

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
  utgår från baslinjen 0.1.0 (`100_schema_baseline_0_1_0.py`), och nya filer får nästa nummer efter det högsta där. Numren `101` till `105` används aldrig: äldre databaser
  har dem redan i sin migreringslogg (`backend/tests/policy/test_migration_numbering.py`). Hur data flyttas mellan
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

En liten separat svit kör samma byggda app mot en riktig server, så att kontraktet mellan appen och serverns verktyg
prövas på riktigt: värden är fortfarande simulerad, men varje verktygsanrop går till en Sidekick-server (FastAPI och
FastMCP på en ledig loopback-port) som sviten startar mot en testdatabasplats, med en användare och en token som bara
skapas för körningen. Den täcker att skapa och avsluta en uppgift i Agendan, taggfiltret och att sätta en tagg, att
skriva en dagboksanteckning och inköpslistan. Den kräver backend-miljön och testdatabasen
([Testdatabaspoolen](../../tools/test-db-pool.md)); sviten tömmer databasen den får, så använd en egen plats:

```bash
bash tools/test-db-pool.sh create K
pool_env=$(bash tools/test-db-pool.sh env K) && eval "$pool_env"
npm --prefix frontend run test:real-backend
```

`E2E_BACKEND_PYTHON` anger backend-miljöns Python när den inte är `backend/.venv/bin/python`. Sviten ingår inte i CI.

Håll de genererade kontraktsfilerna i synk efter en ändring i API eller MCP:

```bash
uv run --project backend python -m sidekick.api.export_openapi --output contracts/openapi.generated.json
uv run --project backend python -m sidekick.mcp.export_contract --output contracts/mcp-tools.generated.json
uv run --project backend python -m sidekick.mcp.export_tool_reference
uv run --project backend python -m sidekick.export_reference
uv run --project backend python -m sidekick.api.export_companion_contract --output contracts/companion-api.generated.json
```
