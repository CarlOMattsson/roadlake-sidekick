# Bygg, installera och para ihop Android

[English](pair-android.md)

<!-- description: Ladda ner den signerade Android-appen eller bygg den ur källkoden, installera den och koppla telefonen till din server med en engångskod. -->

Ladda ner den signerade Android-appen eller bygg den ur källkoden, installera den och koppla telefonen till din server med en engångskod.

## Vad appen gör och inte gör

Appen är en andra yta mot samma Sidekick-server, bredvid Claude. Den pratar med serverns companion-rutter
under `/companion/v1/` och inget annat.

Appen skapar inga uppgifter eller projekt, kör ingen AI och pratar inte med Claude: det gör du i Claude. Den
har ingen QR-läsare och ingen kamerabehörighet: kopplingskoden skrivs, klistras in eller kommer med en kopplingslänk. Den säkerhetskopierar
eller flyttar inte sin inloggningsuppgift (`android:allowBackup="false"`). Den kräver Android 7.0 eller nyare
(`minSdk` 24). Android 13 och nyare frågar en gång om lov att visa aviseringar, efter parkopplingen. Det finns
ingen iOS-app.

## Ladda ner den signerade appen

Varje release på repots GitHub Releases-sida har en signerad `sidekick-X.Y.Z.apk`, byggd och signerad av
releaseflödet med underhållarens nyckel, bredvid `SHA256SUMS` och dess signatur (`SHA256SUMS.sigstore.json`).
Ladda ner APK:n och de två filerna, kontrollera dem enligt
[Verifiera en release](../maintainers/release.sv.md#verifiera-en-release) (`sha256sum -c SHA256SUMS`, sedan
`cosign verify-blob` och `apksigner verify --print-certs`) och gå vidare till [Installera](#installera). Senare
releaser installeras över den, eftersom de signeras med samma nyckel. Du kan också bygga appen själv, som nedan. En
egenbyggd app har en annan nyckel och kan därför inte uppdatera den nedladdade eller tvärtom: avinstallera den gamla
först och para ihop igen.

## Bygg själv

### Krav

| Verktyg | Version | Källa |
| --- | --- | --- |
| JDK | 21 (CI använder Temurin 21; Kotlin-målet är JVM 21) | `.github/workflows/ci.yml`, `frontend/android/app/build.gradle` |
| Android SDK | Plattform 36 (`compileSdk` och `targetSdk` är 36) | `frontend/android/variables.gradle` |
| Node.js | 22 (CI låser 22.23.4) med npm 10 | `.node-version`, `frontend/package.json` |
| Gradle | 8.14.3, hämtas av wrappern (`./gradlew`) | `frontend/android/gradle/wrapper/gradle-wrapper.properties` |

Peka ut SDK:n för Gradle med `ANDROID_HOME`, eller med `sdk.dir=<path>` i en fil som heter `local.properties` i frontendens mapp `android`
(filen ignoreras av git). Första bygget hämtar Gradle och beroendena för Android och Kotlin från Googles och
Maven Centrals arkiv, så det kräver internet.

### Lägsta WebView

Appens vyer är en webbsida som visas i Android System WebView, som uppdateras separat från Android. `minSdk` 24 säger
inte vilken WebView du har, så appen anger ett eget lägsta krav: **Android System WebView (Chromium) 123 eller
senare**. 123 är första versionen med CSS-funktionen `light-dark()`, som vyerna använder inbyggt. Samma nummer är
`target` och `cssTarget` i mobilbygget (`frontend/vite.mobile.config.ts`; appen har ingen browserslist),
`MIN_CHROMIUM_MAJOR` i `WebViewRequirement.kt` och `minWebViewVersion` i `frontend/capacitor.config.ts`;
`WebViewRequirementTest` fallerar om de skiljer sig. Vid start läser appen den installerade WebView-versionen. Är den
äldre visar appen en kort förklaring (svenska eller engelska, efter appens språkinställning) i stället för en vit
skärm. Åtgärd: uppdatera Android System WebView och Google Chrome i appbutiken. Går versionen inte att läsa startar
appen som vanligt.

### Bygg

Kör från repots rot. Webbdelen (mobilpaketet) byggs först. Sedan kopierar Capacitor in den i Android-projektet
och genererar pluginmodulen, och till sist bygger Gradle appen.

```bash
cd frontend
npm ci
npm run build:mobile          # skriver paketet till dist-mobile
npx cap sync android          # kopierar dist-mobile till Android-projektet
cd android
./gradlew assembleDebug
```

Debug-APK:n är `app/build/outputs/apk/debug/app-debug.apk` inne i `frontend/android`.

Bygget slutar i `frontend/android`. Gå tillbaka till repots rot (`cd ../..`) före serverkommandona nedan som använder
`uv --project backend`.

Kör `npm run build:mobile` och `npx cap sync android` igen efter varje ändring i webbkoden; Gradle bygger inte
om den på egen hand. `./gradlew test` kör de JVM-enhetstester som CI kör.

Debug- och releasebyggen har olika applikations-id (`com.roadlake.sidekick.debug` och `com.roadlake.sidekick`). De är alltså
skilda installationer, och var och en måste paras ihop för sig. Debugbygget signeras med Androids vanliga
debugnyckel. Det godtar också okrypterad `http` till `10.0.2.2`, `localhost` och `127.0.0.1`, så att en
emulator når en server på samma dator. Alla andra adresser måste vara `https`, och releasebygget godtar inget
annat.

**Release.** Repot innehåller ingen signeringskonfiguration och ingen nyckel. `./gradlew assembleRelease` ger
en osignerad APK; signera den med din egen nyckel och förvara nyckeln utanför repot. Publicering i en
appbutik tas inte upp här.

## Installera

- **adb**: slå på utvecklaralternativ och USB-felsökning på telefonen, anslut den och kör sedan
  `adb install -r sidekick-X.Y.Z.apk` för den nedladdade appen, eller `adb install -r app/build/outputs/apk/debug/app-debug.apk` (från `frontend/android`) för ditt eget debugbygge.
- **Sidladdning**: kopiera APK:n till telefonen och öppna den. Android ber dig tillåta installation från den
  app som öppnade filen ("installera okända appar"), och Play Protect kan varna för en okänd utvecklare.

För påminnelser installerar du också en UnifiedPush-distributör. Appen är byggd och testad med Android-appen
**ntfy**. Öppna den en gång efter installationen. På nyare Android-versioner: ställ in dess batterianvändning
på obegränsad, annars kan väckningarna bli fördröjda.

## Server: det som måste vara påslaget

Companion-rutterna är avstängda som förval och finns inte ens på den publika ytan förrän du slår på dem
(`backend/src/sidekick/shared/config/`, `companion_enabled`; `backend/src/sidekick/api/public_surface.py`).

Rutterna, deras parametrar, förfrågningskroppar, den enhetsbehörighet varje rutt kontrollerar och den slutna listan över
avslag publiceras som ett OpenAPI 3.1-dokument,
[`contracts/companion-api.generated.json`](../../contracts/companion-api.generated.json), genererat från de registrerade
rutterna (`python -m sidekick.api.export_companion_contract`); CI fäller bygget när det är föråldrat. Ett lyckat svar är
det strukturerade innehållet från MCP-verktyget med samma namn
([`contracts/mcp-tools.generated.json`](../../contracts/mcp-tools.generated.json)).

| Variabel | Behövs för | Förval |
| --- | --- | --- |
| `SIDEKICK_COMPANION_ENABLED=true` | Parkoppling och hela appen. Starta om API:et efter ändringen. | `false` |
| `SIDEKICK_PUSH_ENABLED=true` | Att köa och skicka påminnelser. Sätt den på API:et **och** push-workern. | `false` |
| `SIDEKICK_PUSH_ALLOWED_HOSTS` | Värdar som en telefon får registrera som sin push-ändpunkt. Lägg till din egen ntfy-värd här. | den publika ntfy-servern |
| `SIDEKICK_PUSH_AUTH_HOST` och `SIDEKICK_PUSH_AUTH_TOKEN` | Bara för en egen ntfy-server som kräver en token för att publicera. Värden måste också stå i listan över tillåtna värdar. | inte satta |
| `SIDEKICK_OWNER_TIMEZONE` | Tidszonen för "idag", sammanfattningens tid och de tysta timmarna. | det inbyggda förvalet |
| `SIDEKICK_PUSH_SUMMARY_TIME`, `SIDEKICK_PUSH_DUE_LEAD_MINUTES`, `SIDEKICK_PUSH_QUIET_START`, `SIDEKICK_PUSH_QUIET_END` | När påminnelserna skickas. | 08:00, 15 minuter, 21:00, 07:00 |
| `SIDEKICK_ENABLED_ROOMS` | Vilka rum servern (och därmed appen) visar. | alla rum |

Telefonen måste nå servern över **HTTPS** på en publik adress, samma slags adress som Claude använder för
anslutningen (se självhostingguiden nedan). Exemplet på Caddyfile i `deploy/selfhost/` skickar redan vidare exakt de companion-sökvägar som behövs, och API:et svarar
med en vanlig 404 på dem tills flaggan är på.

För en självhostad installation sätter du dem i `selfhost.env`; se
[Första starten på en server](../start/self-hosted-server.sv.md). Jobbpaketet för jobbdatorn håller med avsikt
companion och push avstängda och har ingen väg för telefoner.


## På en självhostad server

På en självhostad server är serversteget, i ordning:

1. Sätt `SIDEKICK_COMPANION_ENABLED=true` i `selfhost.env` och skapa sedan om API:et:
   `docker compose --env-file selfhost.env up -d --force-recreate api`.
2. Skriv ut en parningskod (den fungerar en gång, i 10 minuter; rättigheterna den skriver ut är dem telefonen får):

   ```bash
   docker compose --env-file selfhost.env exec -T api python -m sidekick.companion.cli pair --label "My phone" --preset app
   ```

3. Ange i appen din servers adress (`https://<your-domain>`, inget efter värdnamnet) och koden `rspair_...` från JSON-
   svaret på standard ut.

För påminnelser på telefonen behövs också push: se "Push-påminnelser" i
[Push-påminnelser](push-reminders.sv.md) (`--profile push`, och `sh ntfy-init.sh` för den egna
ntfy-servern).

## Para ihop en telefon

Parkopplingen är ett engångssteg som den som driver servern gör. Kommandot skriver ut en kod som telefonen
byter mot en egen inloggningsuppgift; den uppgiften ser du aldrig.

Från en utcheckning (utveckling eller en värd som har backendmiljön), kört från repots rot:

```bash
uv run --project backend python -m sidekick.companion.cli pair --label "My phone" --preset app \
  --server-url https://sidekick.example.com
```

`--server-url` är adressen telefonen når servern på (schema och värd, inget efter; bara `https`, och `http` bara för
`localhost`, `127.0.0.1` och `10.0.2.2` vid utveckling). Den är valfri: med den skriver kommandot också ut en
kopplingslänk (se nedan).

För en självhostad installation kör du samma modul inne i den körande API-containern, från
`<repot>/deploy/selfhost` (där `selfhost.env` finns). `-T` håller standard ut ren, så att JSON-svaret inte blandas med
terminalutdata:

```bash
docker compose --env-file selfhost.env exec -T api \
  python -m sidekick.companion.cli pair --label "My phone" --preset app --server-url https://<din-domän>
```

Det här får du:

- På stderr: rättigheterna telefonen får (på språket i `SIDEKICK_MCP_APP_LOCALE`), tiden då koden slutar
  gälla och hur länge inloggningsuppgiften gäller.
- På stdout: ett JSON-dokument. `pairing_secret` är koden (den börjar med `rspair_`); den visas bara nu.
  Med `--server-url` finns också `pairing_link`: `sidekick://pair?server=<url-kodad adress>&code=<kod>`.

Att tänka på:

- `--scope` eller `--preset app` är obligatoriskt; kommandot vägrar gissa. `--preset app` ger uppgifter (läsa
  och klarmarkera), aviseringar, Inköp (läsa och skriva), Dagbok (läsa och skriva) och licensraden. Du kan i
  stället ange `--scope companion:…`-värden (kan upprepas) för en telefon med snävare rättigheter.
- Koden gäller **en gång** och i **10 minuter** (`PAIRING_TTL` i `backend/src/sidekick/companion/service.py`).
- Utan `--user-id <uuid>` använder kommandot installationens enda aktiva ägare, och det vägrar om det inte
  finns exakt en.
- `--device-days N` (1 till 90, förval 30) anger hur länge telefonens inloggningsuppgift gäller.
- Koden är vanlig text. Det finns ingen QR-kod: klistra in eller skriv den i appen, eller använd kopplingslänken.
- Kopplingslänken innehåller koden, så behandla den som koden: skicka den bara till din egen telefon (en anteckning
  eller ett meddelande till dig själv) och dela den inte. Den slutar gälla efter en användning eller 10 minuter.

**Enklast: kopplingslänken.** Öppna `pairing_link` på telefonen (tryck på den i ett meddelande eller en anteckning).
Sidekick öppnas, visar "Koppla till <din server>?" och kopplar först när du trycker på **Koppla**; **Avbryt** släpper
länken. Länken ensam kopplar ingenting, eftersom vilken app eller sida som helst kan öppna en sådan länk: koppla bara
om du själv skapade koden.

**Varför länken inte är en verifierad Android App Link.** En App Link (`https`, `android:autoVerify="true"`) visar för Android att
appen hör till domänen i länken, genom en `assetlinks.json` på den domänen som anger appens paketnamn och
signeringscertifikatets fingeravtryck. Det går inte här: domänen är din egen servers, och du (eller operatören) bygger och
signerar appen själv, så ingen kan i förväg publicera den filen åt dig. En fast
`roadlake.com`-väg skulle inte heller hjälpa, eftersom ett bygge som signerats med din egen nyckel inte stämmer med ett fingeravtryck som
publicerats där. Appen använder därför ett eget schema, `sidekick://pair`, och skyddet ligger i koden och i appen:

- Koden gäller en gång och i 10 minuter, och servern begränsar misslyckade försök per adress. En app som fångade länken
  efter att du kopplat (eller efter 10 minuter) får ingenting.
- Länken kopplar aldrig av sig själv. Appen visar serverns värd, "Koppla till <värd>?", och väntar på att du trycker på
  **Koppla**; en länk som anger en server du inte väntade dig avvisar du med **Avbryt**.
- Länken tolkas strikt: exakt en `server` och en `code`, ett `https`-ursprung utan sökväg, en kod av rätt form,
  högst 1024 tecken. Allt annat ignoreras.
- En länk som når en telefon som redan är kopplad släpps, och appen säger det en gång.
- Manifestet har ett enda filter, för `sidekick://pair`, och inget `https`-filter; `WidgetResourcesTest` fallerar om ett till läggs till.
- Vill du inte förlita dig på länken, använd kopplingsskärmen för hand: koden går då aldrig genom någon annan app.

Det schemat inte kan hindra är en annan installerad app som också registrerar `sidekick://pair` och som Androids
appväljare väljer (eller är den enda), så att den läser länken före Sidekick. Skicka länken bara till dig själv, kontrollera vilken app som
öppnas och skriv koden för hand om du tvivlar på telefonen. Koden är värdelös efter första användningen.

**För hand.** Öppna Sidekick på telefonen. Kopplingsskärmen talar appens språk (svenska som förval; se [Språk](../reference/languages.sv.md#android-appen)) och har en hjälprad "Var hittar jag koden?". Den frågar efter:

1. **Serveradress**: ursprunget för din Sidekick-server, till exempel `https://sidekick.example.com`. Inget
   efter värden: ingen sökväg (inte `/mcp`), ingen frågesträng, ingen inloggning. Utelämnar du `https://`
   lägger appen till det.
2. **Kopplingskod**: strängen `rspair_…`. Tryck på "Visa koden" för att kontrollera det du klistrade in.

Tryck på Koppla (eller tangentbordets Gå-tangent i kodfältet). Varje fält visar sitt eget fel: ett tomt fält, en
adress som inte är ett `https`-ursprung, en kod som är för kort eller har tecken som en kod aldrig har. Appen frågar
sedan om lov att visa aviseringar (Android 13 och nyare).

Idag-widgeten är som förval 4x2 rutor stor (du kan ändra storleken). Före kopplingen visar den meddelandet "Koppla
Sidekick" med en knapp **Koppla** som öppnar appen på kopplingsskärmen.

### Lista, utöka och spärra telefoner

```bash
uv run --project backend python -m sidekick.companion.cli list
uv run --project backend python -m sidekick.companion.cli revoke --device-id <id>
uv run --project backend python -m sidekick.companion.cli grant --device-id <id> --preset app
```

(Självhostat: från `deploy/selfhost`, använd formen `docker compose --env-file selfhost.env exec -T api python -m sidekick.companion.cli …`.) `list` skriver ut
varje enhets `id`, etikett, rättigheter, utgångstid, `revoked_at` och `last_used_at`; det skriver aldrig ut en
hemlighet. `revoke` stänger ute telefonen och tar bort dess push-registrering; appen går tillbaka till kopplingsskärmen nästa gång den kontaktar servern. `grant`
lägger bara till rättigheter på en redan parkopplad telefon (till exempel när du har slagit på ett rum); det
tar aldrig bort några. På telefonen gör Inställningar, "Koppla från den här telefonen" samma sak för just den
telefonen och tömmer den. Använd `revoke` för en borttappad telefon.

### Hur länge en inloggningsuppgift gäller

En telefons inloggningsuppgift gäller i 30 dagar som förval (`--device-days`, högst 90). Under de sista 7
dagarna förnyar den sig själv, utan att ägaren gör något: appen försöker när den kommer i förgrunden och i
widgetens återkommande bakgrundsjobb, via `POST /companion/v1/device/renew`. Varje förnyelse ger en ny
inloggningsuppgift med full giltighetstid igen. Den gamla fungerar i 10 minuter till, så att ett svar som gick
förlorat kan hämtas på nytt, och högst 5 förnyelser lyckas per 24 timmar. En telefon som inte används förrän
efter utgångstiden måste paras ihop igen med en ny kod.

## Felsökning

| Det du ser (svensk text) | Trolig orsak och åtgärd |
| --- | --- |
| "Adressen måste börja med https:// och bara innehålla servern." | Adressen har en sökväg, frågesträng eller inloggning, eller använder `http`. Använd bara ursprunget. `http` fungerar bara i debugbygget, och bara för `10.0.2.2`, `localhost` och `127.0.0.1`. |
| "Koden ser inte rätt ut." | Den inklistrade koden är avklippt eller har extra tecken. Klistra in hela strängen `rspair_…`. |
| "Koden gäller inte längre eller är redan använd. Skapa en ny." | Servern svarade 401 `pairing_invalid`: koden är äldre än 10 minuter, har redan använts en gång eller är fel. Kör `pair` igen. |
| "Servern kunde inte nås…" eller "Servern svarade inte." | Felskriven adress, problem med DNS, TLS-certifikat eller tunnel, eller inget internet på telefonen. Öppna serverns adress i telefonens webbläsare för att testa att den går att nå och att certifikatet är giltigt. |
| "Kopplingen misslyckades. Försök igen." | Servern svarade något annat, oftast 404 för att `SIDEKICK_COMPANION_ENABLED` inte är `true` (eller för att API:et inte startades om). |
| "För många försök. Vänta en minut och försök igen." | Ändpunkten för parkoppling tillåter 10 misslyckade försök per minut och adress (30 för alla adresser tillsammans, vilket bara gäller adresser som nyligen har misslyckats), plus en liten reserv på 3 försök i minuten för en giltig kod. Bakom en tunnel eller proxy delar alla besökare samma adress. Vänta en minut. |
| "Kopplingen har upphört. Koppla igen." | Servern nekade telefonens inloggningsuppgift (401): telefonen har spärrats, uppgiften har löpt ut eller ägaren har inaktiverats. Para ihop igen med en ny kod. |
| Inställningar: "Installera appen ntfy för att få aviseringar." | Ingen UnifiedPush-distributör är installerad. Installera ntfy och öppna Sidekick igen. |
| Inställningar: "Aviseringar är avstängda för Sidekick." | Tillåt aviseringar för Sidekick i telefonens systeminställningar. |
| Test: "Aviseringar är avstängda på servern." | `SIDEKICK_PUSH_ENABLED` är inte `true` på API:et. |
| Test: "Aviseringar är inte kopplade än." | Servern har ingen push-registrering för den här telefonen: appen ntfy saknas, behörigheten är nekad eller ändpunktens värd står inte i `SIDEKICK_PUSH_ALLOWED_HOSTS` (servern svarar 422 `endpoint_not_allowed`). |
| Testet köades men inget kommer fram | Push-workern är inte igång, batterioptimering är på för ntfy eller så har den publika ntfy-servern nått sin dygnskvot (workern backar och försöker igen). |
| `pair`: "pass --user-id: there is not exactly one active owner" | Installationen har ingen eller flera aktiva användare. Ange `--user-id <uuid>`. |
| `pair`: "requires an explicit --scope … or --preset app" | Välj rättigheterna uttryckligen. |
