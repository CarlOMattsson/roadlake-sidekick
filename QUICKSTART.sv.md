# Snabbstart för utvecklare

[English](QUICKSTART.md)

Den kortaste vägen från en färsk klon till en körande lokal instans, för utveckling. Alla kommandon körs från
**repo-roten**. Vill du köra Sidekick på riktigt, se [README.sv.md](README.sv.md#kör-sidekick).

Du behöver Python 3.13 med [`uv`](https://docs.astral.sh/uv/), Node.js 22 / npm 10 och Docker med Compose v2.

## 1. Uppsättning, en gång

```bash
git clone https://github.com/CarlOMattsson/roadlake-sidekick.git
cd roadlake-sidekick
[ -f .env ] || cp .env.example .env     # fyll sedan i lokala hemligheter; checka aldrig in filen
uv sync --project backend --all-groups
npm --prefix frontend ci
```

I `.env` måste `SIDEKICK_CURSOR_SIGNING_SECRET` och `SIDEKICK_TOKEN_PEPPER` vara minst 32 tecken var
(till exempel `openssl rand -hex 32`) och skilja sig från varandra. Inga API-nycklar behövs för att komma igång.

## 2. Starta databasen och kör migrationer

```bash
docker compose -f deploy/compose.dev.yaml up -d db
docker compose -f deploy/compose.dev.yaml ps          # vänta tills db-tjänsten är healthy
uv run --project backend yoyo apply --batch \
  --database postgresql+psycopg://sidekick_migrator:sidekick_migrator@127.0.0.1:55440/sidekick migrations
```

## 3. Starta backend

Starta den från repo-roten, i en egen terminal, och låt den stå på:

```bash
uv run --project backend uvicorn sidekick.api.app:create_app --factory --reload --no-access-log
```

Kontrollera att den är uppe: `curl http://127.0.0.1:8000/health/ready`. MCP-adressen är `http://127.0.0.1:8000/mcp/`.

## 4. Skapa en användare och en token

I en ny terminal:

```bash
uv run --project backend sidekick-admin create-user --login local-user --display-name "Local User"
uv run --project backend sidekick-admin create-token --user-id <USER_UUID> --label "Local MCP" \
  --scope projects:read --scope tasks:read --expires-in-days 30
```

`create-user` skriver ut användarens UUID. `create-token` visar token **en enda gång**; spara den i klientens hemlighetslager.

## 5. Valfritt: påhittad data och MCP-appen

```bash
uv run --project backend python -m tools.seed --confirm      # påhittad data i Arbete, Kontakter och Dagbok, bara lokala databaser
npm --prefix frontend run build:mcp-app                       # efter ändringar i frontend/src
```

För att se rummen kopplar du Claude Desktop eller en tokenklient; steg 4 och 5 i
[Kör Sidekick lokalt som utvecklare](docs/start/first-contribution.sv.md) visar hur.

## Stäng ner

Stoppa Uvicorn med `Ctrl+C` och kör sedan:

```bash
docker compose -f deploy/compose.dev.yaml down       # behåller datavolymen
docker compose -f deploy/compose.dev.yaml down -v    # raderar också den lokala databasen; bara om du menar det
```

## Gå vidare

- [Kör Sidekick lokalt som utvecklare](docs/start/first-contribution.sv.md): samma steg med förklaringar, Claude Desktop över stdio, MCP Inspector och felsökning.
- [Utvecklingsguide](docs/contribute/development.sv.md): kontroller, hela testsviten, genererade filer och kodstil.
