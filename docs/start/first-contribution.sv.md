# Kör Sidekick lokalt som utvecklare

[English](first-contribution.md)

<!-- description: Kör Sidekick lokalt från källkoden, med en egen databas och påhittade data. Du kan prova verktygen från Claude Desktop eller direkt mot MCP-servern. -->

Kör Sidekick lokalt från källkoden, med en egen databas och påhittade data. Du kan prova verktygen från Claude Desktop eller direkt mot MCP-servern.

Så kör du Roadlake Sidekick från en färsk klon för utveckling
(`git clone https://github.com/CarlOMattsson/roadlake-sidekick.git && cd roadlake-sidekick`). Alla kommandon körs från **repots rot**.
Vill du köra Sidekick på riktigt, se [README.sv.md](../../README.sv.md#kör-sidekick) i stället.

## Förutsättningar

- Python 3.13 med [`uv`](https://docs.astral.sh/uv/)
- Node.js 22 och npm 10
- Docker med Compose v2 (för lokal PostgreSQL)

```bash
uv --version && node --version && npm --version && docker compose version
```

## 1. Engångsinstallation

```bash
[ -f .env ] || cp .env.example .env     # fyll sedan i lokala hemligheter; checka aldrig in filen
uv sync --project backend --all-groups
npm --prefix frontend ci
```

`SIDEKICK_CURSOR_SIGNING_SECRET` och `SIDEKICK_TOKEN_PEPPER` i `.env` måste vara minst 32 tecken vardera (till
exempel `openssl rand -hex 32`) och bör skilja sig från varandra. Markörsigneringshemligheten signerar listmarkörer.
Pepparn blandas in i de lagrade tokenhasharna, så om du byter den senare slutar alla redan utfärdade token
att gälla. Förvalen är säkra: de använder deterministiska låtsasleverantörer och håller extern AI avstängd,
så du behöver inga API-nycklar för att komma igång. [.env.example](../../.env.example) innehåller de inställningar
en lokal utvecklare behöver, inte hela listan: den fullständiga uppsättningen är klassen `Settings` i
`backend/src/sidekick/shared/config/`, och
[deploy/selfhost/selfhost.env.example](../../deploy/selfhost/selfhost.env.example) visar uppsättningen för drift.
Miljövariabler går före `.env`, och odeklarerade `SIDEKICK_*`-inställningar avvisas.

## 2. Starta PostgreSQL och kör migreringarna

```bash
docker compose -f deploy/compose.dev.yaml up -d db
docker compose -f deploy/compose.dev.yaml ps          # vänta tills tjänsten db är frisk

uv run --project backend yoyo apply --batch \
  --database postgresql+psycopg://sidekick_migrator:sidekick_migrator@127.0.0.1:55440/sidekick migrations
```

`yoyo apply --batch` skriver ingenting när det lyckas. Se resultatet med `uv run --project backend yoyo list --database <samma adress> migrations`;
varje migrering är markerad `A` (tillämpad).

Databasen lyssnar på `127.0.0.1:55440`. För att ändra det sätter du variabeln bara framför compose-kommandot, till
exempel `SIDEKICK_DEV_DB_BIND=127.0.0.1:55441 docker compose -f deploy/compose.dev.yaml up -d db`, och ändrar också
porten i `yoyo`-adressen ovan och i `SIDEKICK_DATABASE_URL` i `.env`. Exportera den inte i skalet och lägg den inte i
`.env`: den är en compose-inställning, inte en Sidekick-inställning, och backend vägrar starta på en
`SIDEKICK_`-variabel som inte är deklarerad. `deploy/postgres-init.sql` skapar rollerna `sidekick_owner`, `sidekick_migrator` och `sidekick_app`, den sista med minsta möjliga
rättigheter. Bara migreringsrollen kör DDL; applikationen gör det aldrig. Kör `yoyo apply` igen varje gång
det kommer nya filer under `migrations/`.

## 3. Starta backend

```bash
uv run --project backend uvicorn sidekick.api.app:create_app --factory --reload --no-access-log
```

- MCP (Streamable HTTP): `http://127.0.0.1:8000/mcp/`
- Hälsokontroll: `http://127.0.0.1:8000/health/live` och `/health/ready`
- Med `SIDEKICK_COMPANION_ENABLED=true` (Android-appen, se [Bygg, installera och para ihop Android](../operate/pair-android.sv.md)) finns
  companion-API:et under `/companion/v1/`.

Det finns inget REST-API för ett webbskal: produktens yta är MCP. `--no-access-log` håller förfrågningarnas
URL:er, som kan innehålla söktext, borta från loggarna, precis som självhostingpaketet gör.

**Starta från repots rot.** `.env` söks i processens arbetskatalog, inte i repot. Startar du från `backend/`
hittas filen inte, utan något felmeddelande, och varje inställning faller tillbaka på sitt förval (även
låtsasleverantören för minne). Startposten `config_dotenv_file` visar vad som hände: `found` betyder att
filen lästes, `missing` att den aldrig hittades. `config_environment_only` namnger (men skriver aldrig ut
värdena för) inställningar som kom från processens miljö.

## 4. Skapa en användare och en MCP-token med scopes

```bash
uv run --project backend sidekick-admin create-user --login local-user --display-name "Local User"

uv run --project backend sidekick-admin create-token --user-id <USER_UUID> --label "Local MCP" \
  --scope projects:read --scope tasks:read --expires-in-days 30
```

`create-user` frågar inte efter något (ingen terminal behövs; Sidekick har inga lösenord) och skriver ut den nya användarens UUID, som `create-token` och inställningarna nedan använder. `create-token` visar det råa bearer-värdet **en gång**;
spara det i klientens hemlighetslager. `--scope` krävs (inget scope följer med av sig självt) och en token gäller 90 dagar om inte `--expires-in-days` (högst 365) eller `--never-expires` anger annat. MCP-ändpunkten över HTTP har ingen väg förbi autentiseringen: varje
förfrågan behöver `Authorization: Bearer <token>` med scopes som täcker verktyget. Det tokenläget (`pat`,
förvalet) passar klienter som kan skicka en bearer-header, till exempel MCP Inspector eller Claude Code. Den
kurerade verktygslistan finns i [contracts/mcp-tools.generated.json](../../contracts/mcp-tools.generated.json); en läsbar
verktygsreferens (på engelska) finns i [docs/reference/mcp/index.md](../reference/mcp/index.md).

**Töm papperskorgen.** Att ta bort flyttar bara en post till papperskorgen. Från en klon skriver `uv run --project backend sidekick-admin empty-trash` ut hur många poster av varje typ som ligger i den, och `--yes` raderar dem för gott. Flaggorna och vad som ändå behålls står i [Töm papperskorgen](../operate/empty-trash.sv.md).

**Anslut Claude.** Claude Desktop på samma dator kan starta Sidekick själv över stdio, utan token: sätt
`SIDEKICK_MCP_STDIO_OWNER_ID=<USER_UUID>` i `.env`, lägg till den här servern under `mcpServers` i
`claude_desktop_config.json` (använd absoluta sökvägar, och den absoluta sökvägen till `uv` om Claude Desktop
inte hittar det) och starta om Claude Desktop:

```json
{ "command": "uv", "args": ["run", "--project", "/ABSOLUTE/PATH/backend", "python", "-m", "sidekick.mcp.stdio", "--env-file", "/ABSOLUTE/PATH/.env"] }
```

Claudes fjärranslutning (claude.ai och mobilapparna) kräver ett **publikt HTTPS-ursprung** och inloggning med
GitHub (`SIDEKICK_MCP_AUTH_MODE=github_oauth`), inte en bearer-token: se
[Anslut Claude](../operate/connect-claude.sv.md).

## 5. Se det fungera

Lägg påhittad data i databasen, anslut Claude Desktop och ställ en fråga. Steget använder användaren från steg 4
(seedaren återanvänder inloggningen `local-user` och ändrar aldrig en befintlig användare), så kör det efter steg 4:

```bash
uv run --project backend python -m tools.seed --confirm
```

Seedaren skriver påhittad data för Arbete, Kontakter och Dagbok till den lokala utvecklingsdatabasen och vägrar
köra mot drift och mot varje databas som inte är lokal. Den läser valfria inloggningsinställningar från `.env.seed`
(se [.env.seed.example](../../.env.seed.example)). Anslut sedan Claude Desktop över stdio enligt **Anslut Claude** i steg 4
(det kräver `SIDEKICK_MCP_STDIO_OWNER_ID` och att Claude Desktop startas om), starta en ny chatt och fråga:

> Vad står på min agenda i dag?

Claude anropar `get_work_agenda` och visar Arbetes agenda som ett inbäddat kort: daterade uppgifter grupperade som
försenade, i dag och kommande, byggda av den påhittade datan. Öppna kortet för hela rummet och gå vidare till
Kontakter eller Dagbok från dess meny.

En klient som skickar en bearer-token, till exempel MCP Inspector eller Claude Code, behöver en token som täcker
alla rum. Kommandot nedan ger de tio standard-scopes som en personlig token kan ha (de två `automation:*`-scopes är opt-in och utelämnade) (`create-token` har ingen genväg för
"alla"):

```bash
uv run --project backend sidekick-admin create-token --user-id <USER_UUID> --label "Local full" \
  --scope projects:read --scope projects:write --scope tasks:read --scope tasks:write \
  --scope contacts:read --scope contacts:write --scope journal:read --scope journal:write \
  --scope shopping:read --scope shopping:write \
  --expires-in-days 30
```


**Utan Claude Desktop: MCP Inspector.** Inspector är ett webbläsarverktyg som listar en servers verktyg och visar vad varje verktyg svarar. Det ritar inte rummen; det gör Claude och Android-appen. När backend körs (steg 3) och du har en token från kommandot ovan, starta det:

```bash
npx @modelcontextprotocol/inspector
```

På sidan som öppnas väljer du transporten **Streamable HTTP**, sätter URL:en till `http://127.0.0.1:8000/mcp/`, lägger till rubriken `Authorization` med värdet `Bearer <token>` och trycker på Connect. Under **Tools** kör du `get_work_agenda` och ser samma data som Claude gör om till agendakortet.

## 6. Bygg MCP-appen

Det finns inget webbskal och ingen Vite-utvecklingsserver. Rummen som Claude och Android-appen visar är
MCP-appar som byggs från React-källkod:

```bash
npm --prefix frontend run build:mcp-app    # skriver backend/src/sidekick/mcp/apps/sidekick.html
```

Den filen är ett incheckat byggresultat. Redigera den aldrig för hand: bygg om den och checka in resultatet
tillsammans med källkodsändringen (CI fallerar på en inaktuell kopia).

## Stäng ner

Stoppa Uvicorn med `Ctrl+C` och kör sedan:

```bash
docker compose -f deploy/compose.dev.yaml down       # behåller datavolymen
docker compose -f deploy/compose.dev.yaml down -v    # raderar också den lokala databasen; bara om du menar det
```

## Felsökning

- **`db` blir aldrig frisk:** `docker compose -f deploy/compose.dev.yaml logs db`; port 55440 kan vara upptagen
  (sätt `SIDEKICK_DEV_DB_BIND` på compose-kommandot, som ovan).
- **En inställning i `.env` har ingen verkan:** exporterade `SIDEKICK_*`-variabler går före filen (lista namnen med `env | grep -o '^SIDEKICK_[A-Z_]*'`),
  eller så startades backend från en annan katalog (se steg 3).
- **Migreringsfel:** kontrollera att databasen är frisk och att anslutningssträngen pekar på rätt port.
- **`password authentication failed for user "sidekick_migrator"` vid första körningen:** rollerna i
  `deploy/postgres-init.sql` skapades aldrig, eftersom databasvolymen initierades av en misslyckad första start och
  PostgreSQL hoppar över initieringen vid varje senare start. Kör `docker compose -f deploy/compose.dev.yaml down -v`
  (det raderar den lokala databasen) och starta om. Compose-filen kopierar filen som root, så en sträng `umask`
  (`077`) på utcheckningen är inte längre en orsak; för att se vad containern läste:
  `docker compose -f deploy/compose.dev.yaml exec db ls -l /docker-entrypoint-initdb.d/` listar rollfilen som containern kopierade (heter 001-roles och slutar på .sql).
- **Två kloner på samma maskin:** compose-projektet heter `sidekick-dev` i båda, så de delar en databasvolym. Ge den
  andra ett eget projektnamn: `docker compose -p sidekick-dev-2 -f deploy/compose.dev.yaml ...` med en annan
  `SIDEKICK_DEV_DB_BIND`.
