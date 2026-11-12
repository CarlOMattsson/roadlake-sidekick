# Verifieringsloggar

[English](verification.md)

<!-- description: Vad som har kontrollerats i varje guide, hur det gjordes och vad som inte är verifierat. -->

Vad som har kontrollerats i varje guide, hur det gjordes och vad som inte är verifierat.

För underhållare. Posterna anger vilka delar av användarguiderna som lästs mot koden, vilka kommandon som körts, vad som
följts från en ren klon och vad som inte verifierats. De ligger utanför guiderna med avsikt: guiderna är instruktioner, och
detta är ett testprotokoll.

Tabellen över de senaste kontrollerna finns på [underhållssidan](README.sv.md).

## Snabbstart

Kontrollerad 2026-11-11.

- **Kontrollerat mot koden (läst, inte kört):** portarna i `deploy/compose.dev.yaml` (55440) och
  `deploy/compose.test.yaml` (55433), deras tjänstnamn `db`, rollerna i `deploy/postgres-init.test-only.sql`,
  inställningsnamnen och minimilängden 32 tecken i `backend/src/sidekick/shared/config/` och `.env.example`,
  vägarna `/mcp/`, `/health/*` och `/companion/v1/`, fälten i startposten, npm-skriptens namn i
  `frontend/package.json`, var `build:mcp-app` skriver sitt resultat och testsvitens flagga `--full`.
- **Kört, utan sidoeffekter:** `uv run --project backend python -c 'import sidekick'`; `--help` för
  `sidekick-admin` (`create-user`, `create-token`), `python -m sidekick.mcp.stdio`, `sidekick.api.export_openapi`,
  `sidekick.mcp.export_contract`, `tools.seed` och `yoyo apply`; `docker compose -f deploy/compose.dev.yaml config -q`
  och detsamma för `deploy/compose.test.yaml`.
- **Följt från en ny klon, 2026-11-11** (eget compose-projekt, databasen på en annan port enligt
  steg 2, genererade engångshemligheter): steg 1 till 4 och bygget i steg 6 som de står (steg 5, seedningen och exempelfrågan, kontrollerades bara mot koden). `uv sync`, `npm ci`, databasen och `yoyo apply`,
  backend med `/health/live` och `/health/ready`, `create-user` och `create-token`, ett MCP-`initialize` med token,
  stdio-servern som svarar på `initialize`, och `build:mcp-app` (den incheckade filen kom tillbaka byte för byte lika).
  `ruff format --check` och `ruff check` gick igenom. Testdatabasen på port 55433 och backendsviten kördes inte.
- **Inte verifierat i den här kontrollen:** själva stdio-anslutningen från Claude Desktop (bara serversidan), `pyright`,
  webbläsarkontrollerna och testsviterna. CI kör byggena och testerna som grind vid varje release, inte för pull requests.

## Android-appen

Kontrollerad 2026-11-10.

- **Kontrollerat mot koden (läst, inte kört):** SDK-nivåerna i `frontend/android/variables.gradle`, JVM-målet och
  applikations-id:na i `frontend/android/app/build.gradle`, Gradle-versionen i wrappern, värdarna som bara debugbygget når över okrypterad
  `http`, `allowBackup`, CI:s byggsteg (`build:mobile`, `cap sync android`, `./gradlew test` på Temurin 21),
  Caddyfilens companion-vägar, serverinställningarna och deras förval i `backend/src/sidekick/shared/config/`, och
  gränserna för parkoppling, förnyelse och testnotiser i `backend/src/sidekick/companion/`.
- **Kört, utan sidoeffekter:** `--help` för `python -m sidekick.companion.cli` och för dess kommandon `pair` och
  `grant` (flaggor, scopes och förvalet `app` stämmer med guiden).
- **Inte verifierat i den här kontrollen:** ett Gradle-bygge, installation på en telefon eller emulator,
  parkoppling mot en körande server och push-leverans via ntfy. CI bygger webbpaketet, kör JVM-enhetstesterna och lint,
  bygger den osignerade release-APK:n och kör ett instrumenterat rökprov av parkoppling och Capacitor-bryggan på en
  emulator. CI installerar aldrig appen på en riktig telefon, parkopplar den inte mot en riktig server och levererar
  ingen push.

## Självhostning

Guiden kontrolleras som ADR-004 kräver av varje guide; vad som lästs och vad som körts anges nedan.

- **Kontrollerat mot koden (läst, inte kört):** tjänstnamn, profiler, nät, volymer, env-filer och portar i
  `compose.yaml` (även `automation-worker`, som startar utan profil), filerna guiden kopierar (`*.example`,
  `postgres-init.sh`, `ntfy-init.sh`), inställningsnamnen mot `backend/src/sidekick/shared/config/` och
  `selfhost.env.example`, flaggorna i `update.sh` och `restore.sh` och listan över workers som `update.sh` stoppar,
  kommandona `sidekick-admin` och `sidekick-backup`, och rättigheterna som databasåterställningen upprepar.
- **Kört, utan sidoeffekter:** `docker compose config -q` med en påhittad `--env-file`, för basstacken och med alla
  fyra profiler (`vps`, `memory`, `backup`, `push`), vilket också listade tjänsterna och imagerna;
  `bash -n` på `update.sh` och `restore.sh`, och `sh -n ntfy-init.sh`; `--help` för `sidekick-admin`.
- **Övat på riktiga containrar, 2026-11-11** (`tools/drill.sh all --local-images`, Docker 29 på Linux): installation,
  en uppdatering med `update.sh --apply` (ersättning för signaturkontrollen, samma schema: se
  [Releaseövning](release-drill.sv.md)), den krypterade ögonblicksbilden och dess dekryptering, en krypterad databas- och
  Hindsight-kopia, radering av alla volymer, återställningen (`pg_restore`, uppackning av Hindsight-volymen) och
  vägran vid fel eller tom nyckel.
- **Följt från en ren kopia av källträdet, 2026-11-11** (eget compose-projekt, genererade
  engångshemligheter, hemmaprofilen, ingen tunnel): bygge, `create-user`, identitetsraden, `up -d` (friskt, schemat
  tillämpat), OAuth-upptäcktsdokumenten, dynamisk klientregistrering, authorize och samtycke (omdirigerar till GitHub),
  tokenslutpunktens avslag på en okänd kod, 401-utmaningen på `/mcp`, att vidga behörigheterna och återskapa API:t,
  `sidekick-backup keygen` och backupprofilen, att kopiera ut en backup, `restore.sh` plan och `--apply` till en andra
  ägare, uppdateringen från källkod, torrkörning och `--check` av `update.sh` samt parningskoden för appen.
  Inloggningen efter GitHub, tokenutbytet, MCP-anropen `initialize` och verktygslistningen, `create_task` och `list_tasks` kördes i den
  riktiga avbildningen mot den riktiga databasen med GitHub ersatt av en stand-in (ett riktigt GitHub-konto går inte
  att använda i ett test).
- **Ny klon under `umask 077`, 2026-11-11:** en ren kopia av källträdet klonades och den här guiden följdes på
  Docker 29 (Compose 2.40) med en sträng umask. Det avslöjade två fel som en tidigare körning under standardumask inte
  hade visat: PostgreSQL kunde inte läsa den monterade `postgres-init.sh`, och imagen innehöll kod som den
  oprivilegierade användaren inte kunde läsa. Körningen gick igenom efter att de kringgåtts för hand: bygge,
  `create-user`, identitetsraden, `up -d` (friskt), upptäcktsdokumenten, `401` på `/mcp`. Rättelserna som nu ligger i
  repot ersätter de manuella stegen (tester täcker dem). Körningen upprepades sedan med dem, från en ny klon under
  `umask 077`: bygge, `create-user` medan GitHub-klient-id, hemlighet och identitetsrad ännu hade sina platshållare,
  identitetsraden, `up -d` (friskt), upptäcktsdokumentet, `readiness` som skrev `ok`, `401` på `/mcp/`. Inget manuellt
  steg behövdes.
- **Inte verifierat i den här kontrollen:** en riktig GitHub-inloggning och en riktig Claude-anslutning, `vps`-profilen
  (Caddy, TLS), en uppdatering över en riktig schemaändring och den riktiga cosign-kontrollen mot en släppt avbildning.

## Arbetspaketet

KNOWN (uppföljning 2026-11-11): umask-hanteringen, cacheflaggan, diagnosen av misslyckad initiering och den
frivilliga Claude-sammanslagningen kontrolleras med stubbad Docker, tillfälliga filer och en lokal modellserverfixtur.
OPEN: ändringarna har inte provats i en riktig Ubuntu-installation med umask 077 eller i en riktig Claude
Desktop-session; inga containrar startades under denna uppföljning.

Kontrollerat 2026-11-10. Verifierat:

- `tools/work.sh` går att tolka (`bash -n`) och kontrolleras av shellcheck i CI (`--severity=warning`);
  `backend/tests/selfhost/work_package/` kör kommandona `setup`, `init`, `start`, `stop`, `backup`, `update`,
  `restore` och `autostart` (inte `status`) på Linux mot en ersättnings-`docker` som bokför anropen och misslyckas på
  beställning. För `restore` täcker det provkörningen, att en saknad eller ofullständig kopia vägras, den skrivna
  bekräftelsen, stegens ordning med `--apply`, att båda läggs tillbaka när ett steg misslyckas eller avbryts (även direkt efter omdöpningen) och att
  allt lämnas stoppat när tillbakaläggningen misslyckas; för själva säkerhetskopiorna att filerna är krypterade (ingen
  klartextdump eller klartextarkiv på disk), att nyckeln skapas privat och hålls utanför kopiornas katalog, att en
  säkerhetskopia som inte går att läsa tillbaka inte sparas, att en saknad, fel eller ändrad nyckelfil eller
  säkerhetskopia stoppar `backup` och `restore` innan något ändras, och att en säkerhetskopia följd av en återställning
  ger Postgres och volymen exakt det som kopierades (ersättnings-`docker` kör den riktiga krypteringskoden); för alla ändrande kommandon det delade låset (flock och
  mkdir-reserven) och att inget ändras när pausen av skrivarna misslyckas eller inte kan bekräftas.
- När Docker finns installerat låter samma tester Docker Compose själv slå ihop `deploy/selfhost/compose.yaml` och
  `deploy/work/compose.yaml` och kontrollerar resultatet (fastnålade avbildningar, den enda publicerade porten på
  loopback, den enda vägen ut genom grindvakten).
- Databassatserna som `restore` kör (namnbyte, skapande med behörigheter, inläsning, ägarlagning) kördes för hand mot
  en tillfällig Postgres uppsatt med paketets rollbootstrap; resultatet hade samma ägare och behörigheter som
  originalet och migreringsrollen kunde fortfarande ändra dess tabeller.
- Övningen (`bash tools/drill.sh work --local-images`, se releaseövningen i
  [releaseövningen](release-drill.sv.md)) körde paketet på riktiga
  containrar på Linux (Docker 29): `init`, `start`, `backup` (databas och Hindsight, krypterade och
  inlästa igen), en uppdatering som byter api-avbildning och skapar stacken på nytt, radering av alla volymer,
  `restore --apply` (databas, ägare och Hindsight-volymen) och vägran vid fel eller saknad nyckel.

Inte verifierat:

- Den övningens gränser: Hindsight-kontrollen är en markörfil i volymen, inte en minnesbank som läses tillbaka genom
  Hindsight; `update` övades som ett avbildningsbyte, inte vägen med `git pull` och bygge; båda avbildningarna har samma
  schema; modellservern är en påhittad adress, så ingen modell anropas. Öva en säkerhetskopia och en återställning en
  gång på din egen dator innan du förlitar dig på dem.
- macOS (Docker Desktop, launchd, nyckelring) har aldrig körts. Andra Linux-distributioner än Ubuntu har inte provats.
