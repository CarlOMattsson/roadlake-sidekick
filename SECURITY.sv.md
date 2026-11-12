# Säkerhetspolicy

[English](SECURITY.md)

## Rapportera en sårbarhet

Rapportera sårbarheter **privat via repots funktion för säkerhetsmeddelanden** (fliken "Security" och sedan
"Report a vulnerability"). Öppna inget publikt ärende, ingen pull request och ingen diskussion om en misstänkt
sårbarhet. Publicera inte heller exploit-detaljer, token, loggar med användarinnehåll eller riktig data
någonstans där andra kan se dem.

Om funktionen inte finns i repot: öppna ett ärende som bara säger att du har en säkerhetsrapport och vill ha
en privat kanal, utan detaljer, så ordnar förvaltaren en.

Beskriv vad du hittade, version eller commit, stegen för att återskapa det och vilken påverkan du väntar dig.
Använd bara testdata. Roadlake Sidekick förvaltas av en person, så ingen svarstid garanteras. Du får en bekräftelse, och
rättningar samordnas med dig innan detaljer publiceras.

## Versioner som stöds

Bara den **senaste utgåvan** (och den aktuella grenen `main`) får säkerhetsrättningar. Kontrollera att
problemet finns kvar där innan du rapporterar det.

## Hotmodell

Vad Sidekick skyddar, mot vem och vilka kontroller som håller gränserna sammanfattas i
[hotmodellen](docs/explanation/threat-model.md) (på engelska).

## Omfattas

- Autentisering och behörighet: token, scopes, ägarfiltrering, MCP- och companion-ändpunkterna samt flödena
  för OAuth och parkoppling.
- Läckor av användarinnehåll eller inloggningsuppgifter via loggar, spårning, telemetri, felmeddelanden eller
  svar.
- Injektion och osäker hantering av indata i backend, i MCP-apparnas rum och i Android-appen.
- Svagheter i självhostingpaketet under `deploy/selfhost/` (standardkonfiguration, uppdaterings- och
  backupskript, exponerade portar).
- Brister i hur licensnycklar verifieras som gör att en nyckel som aldrig utfärdats godtas. Licensgivarens publika verifieringsnyckel ligger i repot (`backend/src/sidekick/license/public_key.py`); en publik nyckel är ingen hemlighet, och en instans kan åsidosätta den med `SIDEKICK_LICENSE_PUBLIC_KEY`.

## Omfattas inte

- Fynd som kräver en redan komprometterad värd, en stulen upplåst enhet eller en läckt hemlighet som du själv
  har konfigurerat.
- Överbelastning genom ren volym, och utebliven härdning av infrastruktur som du själv driver (din omvända
  proxy, DNS, brandvägg).
- Rapporter om tredjepartstjänster som du ansluter, till exempel Claude, en modelleverantör eller en
  pushserver: rapportera dem till respektive leverantör.
- Social manipulation, och utdata från automatiska skannrar utan påvisad påverkan.
- Licensnotisen i sig: obetald-notisen är en dokumenterad funktion, inte en sårbarhet.

Checka aldrig in ifyllda `.env`-filer eller inloggningsuppgifter. Hittar du en hemlighet i repots historik,
rapportera den privat enligt ovan.
