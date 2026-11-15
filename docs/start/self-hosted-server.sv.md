# Första starten på en server

[English](self-hosted-server.md)

<!-- description: Starta Sidekick på en egen Linux-server med Docker Compose. Guiden går från en ren klon till en server som svarar, i den ordning du behöver stegen. -->

Starta Sidekick på en egen Linux-server med Docker Compose. Guiden går från en ren klon till en server som svarar, i den ordning du behöver stegen.

## Krav

- Linux x86_64 med Docker Engine och pluginet Docker Compose (v2.24 eller nyare, se `docker compose version`), samt
  `git`, `openssl` och `curl`. För uppdateringar till en signerad image senare: `cosign` och `python3` (3.9 eller nyare).
- Antingen en publik domän vars DNS pekar på maskinen, med portarna 80 och 443 nåbara (profilen `vps`: Caddy
  hämtar certifikatet), eller en tunnel som skickar HTTPS vidare till `127.0.0.1:8000` (hemdator). På en hemdator kör
  profilen `tailscale` den tunneln åt dig (ett gratis Tailscale-konto räcker, se "Hemdator med Tailscale Funnel"
  nedan). Claude når
  servern från Anthropics moln, så adressen måste vara publik HTTPS i båda fallen.
- Ett GitHub-konto för inloggningen (du skapar OAuth-appen själv, se [Anslut Claude](../operate/connect-claude.sv.md)).
- Hemligheter som du själv genererar. Inget hemligt ligger i det här repot.

Det finns ingen publicerad image än: första starten bygger API-imagen från den här utcheckningen (några
minuter). Hur du uppdaterar till en signerad, digest-låst image står under [Uppdatera](../operate/update.sv.md).

## Första start

Hämta koden och kör sedan allt från `deploy/selfhost`, som en användare som får köra `docker`:

```bash
git clone https://github.com/CarlOMattsson/roadlake-sidekick.git
cd roadlake-sidekick/deploy/selfhost
```

**1. Kopiera konfigurationen och generera hemligheterna.**

```bash
cp selfhost.env.example selfhost.env && chmod 600 selfhost.env
cp db.env.example db.env && chmod 600 db.env
cp Caddyfile.example Caddyfile            # bara profilen vps

openssl rand -base64 48   # ett värde vardera: SIDEKICK_CURSOR_SIGNING_SECRET, SIDEKICK_TOKEN_PEPPER, SIDEKICK_MCP_OAUTH_SIGNING_KEY
openssl rand -hex 32      # bara hex till databaslösenorden (de ligger inne i URL:er): POSTGRES_PASSWORD, SIDEKICK_DB_APP_PASSWORD, SIDEKICK_DB_MIGRATOR_PASSWORD
```

Redigera båda filerna och byt ut varje värde som börjar med `replace-with-`. Applösenordet ska också in i
`SIDEKICK_DATABASE_URL` (`selfhost.env`) och migrerarens lösenord i `SIDEKICK_MIGRATION_DATABASE_URL` (`db.env`).
Använd ditt publika värdnamn (på en hemdator: tunnelns) som `SELFHOST_DOMAIN=sidekick.example.com` och hela
HTTPS-ursprunget som `SIDEKICK_MCP_PUBLIC_BASE_URL=https://sidekick.example.com`, utan avslutande snedstreck.
PostgreSQL skapar sina roller från `db.env` bara vid första starten av en tom volym, så välj lösenorden före
första starten. Låt GitHubs klient-id, klienthemligheten och identitetsraden vara som de är så länge: steg 3
och 4 fyller i dem.

*Välj språk.* Sätt `SIDEKICK_MCP_APP_LOCALE=sv` (svenska, förvalet) eller `en` (engelska) i `selfhost.env` (ta bort
kommentartecknet). Det styr språket i apparna och i Claudes svar. Om en AI-assistent sätter upp detta åt dig ska den
fråga vilket språk du vill ha (föreslå svenska) och vilka rum (`SIDEKICK_ENABLED_ROOMS`; föreslå alla rum) och inte
fortsätta utan dina svar.

**2. Bygg imagen.** De två variablerna låter appen räkna ut hur gammal koden är, för
påminnelsen om uppdatering. De är valfria.

```bash
export SIDEKICK_BUILD_COMMIT="$(git log -1 --format=%h)" SIDEKICK_BUILD_DATE="$(git log -1 --format=%cI)"
docker compose --env-file selfhost.env build
```

**3. Skapa ägaren och hämta dess id.** `sidekick-admin create-user` skapar den enda användare som din
inloggning kopplas till. Kommandot kräver varken lösenord eller terminal, och det kontrollerar inte
OAuth-inställningarna (en användare måste finnas innan identitetsraden kan peka ut den). Det startar
PostgreSQL, kör migreraren och skriver ut den nya användarens UUID, som är den enda raden på standard ut:

```bash
docker compose --env-file selfhost.env run --rm -T api sidekick-admin create-user --login owner --display-name "Owner"
```

Skriv upp UUID:n. Ditt numeriska GitHub-id (inte användarnamnet) är fältet `id` i
`curl -s https://api.github.com/users/<your-github-login>`.

**4. Skapa GitHubs OAuth-app och fyll i identiteten.** Gör första delen av [Anslut Claude](../operate/connect-claude.sv.md) nu
(registrera appen, kopiera dess klient-id och hemlighet till `selfhost.env`). Sätt sedan identitetsraden till
ditt GitHub-id och UUID:n från steg 3, och kontrollera att ingen platshållare finns kvar (kommandot ska inte
skriva ut något):

```text
SIDEKICK_MCP_OAUTH_ALLOWED_IDENTITIES=github:<numeric GitHub id>=<UUID from step 3>
```

```bash
grep -nE '^[A-Z_]+=.*replace-with-' selfhost.env db.env
```

Valfritt men rekommenderat: håll Sidekicks hemligheter borta från containrarnas miljövariabler genom att flytta dem till filer med `sh secrets-to-files.sh` (se [Hemligheter som filer](../operate/limits-and-secrets.sv.md#hemligheter-som-filer)). Kör det efter kontrollen ovan; en hemlighet som fortfarande säger `replace-with-` lämnas kvar där den är.

**5. Starta.**

```bash
docker compose --env-file selfhost.env --profile vps up -d    # VPS med Caddy och automatisk TLS
docker compose --env-file selfhost.env up -d                  # hemdator bakom en egen tunnel
docker compose --env-file selfhost.env --profile tailscale up -d   # hemdator, Tailscale Funnel i en container
```

Valfria profiler kan läggas till på samma kommandorad: `--profile memory` ([Minne](../operate/memory.sv.md)),
`--profile backup`, `--profile push` (använder `ntfy.env`; engångsinstallation med `sh ntfy-init.sh`; egen
ntfy kräver profilen `vps`). Huvudet i `compose.yaml` visar varje kommando. Bara Caddy (eller din tunnel) är
publik. API:et lyssnar bara på `127.0.0.1:8000`. PostgreSQL har ingen väg ut till internet. API:et, push- och
minnesworkern och Hindsight ligger på ett nät som har det (för GitHub, ntfy och din modelleverantör).

Caddys accesslogg (stdout, roteras som alla containerloggar) innehåller tid, status, metod, värdnamn, varaktighet,
storlek, ett anrops-id och en fast ruttklass (`mcp`, `oauth`, `well-known`, `companion`, `push` eller `unmatched`).
Den innehåller aldrig URL-sökvägen, frågesträngen, headers, klientadressen eller en body: `/mcp/anything` loggas
som `mcp`. Felraden för ett misslyckat proxyförsök får sitt anrop borttaget på samma sätt.

Basstacken startar också `automation-worker` (ingen profil behövs): den kör schemalagda processer och gör varje
förfallen processkörning till uppgifter var 30:e sekund. Utan den körs en schemalagd process aldrig. Den når bara
PostgreSQL (ingen publicerad port, ingen väg ut till internet) och behöver inga egna inställningar. `update.sh`
stoppar och startar om den tillsammans med API:et.

**Hemdator med Tailscale Funnel.** Profilen `tailscale` startar en Tailscale-container som går med i ditt tailnet och
publicerar API:et på `https://<värdnamn>.<tailnet>.ts.net` genom Funnel: ingen ändring av router, brandvägg eller DNS och
ingen Caddy (kombinera den inte med `vps`). Bestäm namnet före steg 1, eftersom det går in i konfigurationen:

1. Slå på MagicDNS och HTTPS-certifikat i Tailscales adminkonsol (sidan DNS) och tillåt Funnel för noden i din
   policyfil (nodattributet `funnel`; se [Tailscales guide till Funnel](https://tailscale.com/kb/1223/funnel)).
   Noden får namnet i `SELFHOST_TAILSCALE_HOSTNAME` (förval `sidekick`), så adressen blir
   `https://sidekick.<ditt-tailnet>.ts.net`, där `<ditt-tailnet>.ts.net` visas på sidan DNS.
2. Skapa en autentiseringsnyckel (Settings, Keys): inte återanvändbar, med kort giltighetstid och taggad om din policy
   kräver det. Skriv den till en fil, aldrig in i `selfhost.env`:

   ```bash
   mkdir -p secrets && chmod 700 secrets
   printf '%s\n' 'tskey-auth-...' > secrets/tailscale_authkey && chmod 644 secrets/tailscale_authkey
   ```

   Lägg sedan `SELFHOST_TAILSCALE_AUTHKEY_FILE=./secrets/tailscale_authkey` i `selfhost.env` (och
   `SELFHOST_TAILSCALE_HOSTNAME` om du inte vill ha förvalda namnet). Nyckeln används bara medan noden ännu inte är
   inloggad. Utan filen skriver `docker compose --env-file selfhost.env --profile tailscale logs tailscale` ut en
   inloggningslänk i stället.
3. Använd exakt det värdnamnet överallt där guiden säger "ditt publika värdnamn":
   `SELFHOST_DOMAIN=sidekick.<ditt-tailnet>.ts.net`, `SIDEKICK_MCP_PUBLIC_BASE_URL=https://sidekick.<ditt-tailnet>.ts.net`
   (det är också OAuth-utfärdaren) och GitHub-OAuth-appens callback
   `https://sidekick.<ditt-tailnet>.ts.net/mcp/auth/callback`. Claudes konnektoradress är den adressen plus `/mcp`.
4. Starta med raden `--profile tailscale` ovan. Nodens tillstånd ligger i volymen `tsstate`, så en omstart behåller
   namnet och certifikatet; profilens `serve.json` (i `tailscale/`) pekar Funnel mot API:et på det interna nätverket.
   Kontrollera med `curl -s https://sidekick.<ditt-tailnet>.ts.net/.well-known/oauth-protected-resource/mcp`.

Genom Funnel besvaras bara de sökvägar som API:ets publika tillåtelselista släpper igenom (MCP, dess OAuth-rutter,
upptäcktsdokumenten och, när de är påslagna, companion-rutterna); allt annat blir 404. Den egna ntfy-servern publiceras
bara av Caddy, så på den här profilen går påminnelserna genom ntfy.sh. Funnel tillåter bara portarna 443, 8443 och 10000
och har bandbreddsgränser som Tailscale inte låter dig ställa in; alla besökare når API:et från en adress, se
"Överbelastning och gissade nycklar" i [Anslut Claude](../operate/connect-claude.sv.md). Med en sträng umask (nedan) kan
containern inte läsa `tailscale/serve.json` om inte filen är läsbar för alla:
`chmod 755 tailscale && chmod 644 tailscale/serve.json`.

**6. Kontrollera.** API:et svarar på sin hälsokontroll när det är uppe (`docker compose --env-file selfhost.env ps`
visar `healthy`). På själva maskinen, innan DNS eller tunneln finns, kontrollerar du så här:

```bash
curl -s http://127.0.0.1:8000/.well-known/oauth-protected-resource/mcp          # 200 och ett JSON-dokument
docker compose --env-file selfhost.env exec -T api python -m sidekick.shared.readiness   # skriver "ok"
```

`/health/live` och `/health/ready` serveras inte av den här stacken: utifrån, och också på `127.0.0.1:8000`, svarar de
404 med flit, eftersom den publika ytan är en tillåtelselista. De finns bara i den lokala utvecklaruppsättningen
([QUICKSTART.md](../../QUICKSTART.md)). Containerns egen hälsokontroll använder modulen `readiness` ovan. När
den publika adressen fungerar lämnar den ut samma upptäcktsdokument:

```bash
curl -s https://<your-domain>/.well-known/oauth-protected-resource/mcp
```

Om api-containern startar om gång på gång pekar `docker compose --env-file selfhost.env logs api` ut den
inställning den vägrar godta (`undeclared SIDEKICK_ setting`, ett OAuth-värde som saknas, en hemlighet som
fortfarande är en platshållare).

**Om första starten misslyckades.** PostgreSQL skapar sina roller bara vid första starten av en tom volym, och en
halvt initierad volym hoppar över det steget vid varje senare start. Rätta orsaken och ta sedan bort volymen innan du
försöker igen (det raderar databasen, så bara efter en första start som aldrig fungerade):
`docker compose --env-file selfhost.env down -v`.

**Sträng umask.** En sträng umask (`077`, vanlig på härdade servrar) gör varje fil i en ny utcheckning läsbar bara för
dig. Compose-filen och imagen kopierar det containrarna behöver som root, så databasrollerna och koden fungerar i båda
fallen. Den enda fil en container läser direkt från utcheckningen är `ntfy/server.yml` (egen ntfy, profilen `push`);
`sh ntfy-init.sh` gör den läsbar för alla, eftersom den inte innehåller något hemligt. Kontrollera så här:

```bash
ls -l ntfy/server.yml     # läget måste ha "r" för grupp och andra, till exempel -rw-r--r--
```

Hemlighetsfilerna (`selfhost.env`, `db.env`, `ntfy.env`) förblir med flit i läge 600.
