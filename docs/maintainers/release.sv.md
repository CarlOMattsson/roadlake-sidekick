# Release av Roadlake Sidekick (underhållarens checklista)

Detta är den exakta vägen från en grön `main` till en publicerad, verifierbar release. Arbetsflödet gör allt fram till
paketet; att skapa taggen, GitHub-releasen och eventuell butiksnotering är ett medvetet steg som underhållaren tar. Arbetsflödet
skapar aldrig en tagg eller en release. English: [release.md](release.md).

Releaser görs på alla tre nivåer: major (`X.0.0`), minor (`X.Y.0`) och patch (`X.Y.Z`). Ändringar testas lokalt innan
de pushas, så CI körs aldrig vid push eller enligt schema (det körs för hand och som releasegrind): hela CI (med beroendegranskningen) och drillen för uppdatering, backup och
återställning körs som grindar vid varje riktig release, också en patch. En patch får bara deklarera migrationsklassen
`expand` (en rättning levererar aldrig ett enkelriktat schemasteg).

**Inget byggs, signeras eller publiceras utan ägarens godkännande.** Varje riktig körning pausar en gång, i
början, i GitHub-miljön `release` tills en obligatorisk granskare godkänner den (se [engångsuppsättningen](#engångsuppsättning-steg-som-bara-repots-ägare-kan-ta)),
och allt som publiceras är signerat och verifierbart: se [Verifiera en release](#verifiera-en-release).

En release är en version (`MAJOR.MINOR.PATCH`) för serverimagen, webbpaketet och Android-appen. Den bestäms av `version`
i `backend/pyproject.toml`; `tools/check-version-sync.py` (också ett enhetstest) misslyckas när
`backend/src/sidekick/__init__.py`, `frontend/package.json`, `frontend/package-lock.json`, Androids
`versionName`/`versionCode` eller `CHANGELOG.md` inte stämmer överens. Se [Versioner](#versioner).

## Första versionen och vad som är verifierat

Version 0.1.0 är den första versionen. Tills den är publicerad finns ingen tagg, containerimage eller APK att ladda ner,
så du bygger båda från repot (första serverstarten bygger imagen från din kopia; se
[Snabbstart](../../QUICKSTART.md) och [android.sv.md](../operate/pair-android.sv.md)). Från första releasen bär varje
GitHub-release den signerade APK:n `sidekick-X.Y.Z.apk`, och imagen publiceras på `ghcr.io` (se
[Vad en release ger](#vad-en-release-ger)); att bygga dem själv fungerar fortfarande.

- **Drillat på Linux-containrar:** installation, uppdatering, backup och återställning av den självhostade stacken och
  av arbetsdatorpaketet (`tools/drill.sh`, också en releasegrind).
- **Följt från en ny klon:** självhostningens första start (bygge, ägare, identitetsrad,
  `up -d`, hälso- och upptäcktskontroller) under standard- och under sträng `umask`, samt snabbstarten (beroenden,
  databas, migreringar, backend, användare och token, ett MCP-anrop, stdio-servern, bygget av MCP-appen,
  statiska kontroller), var och en i ett eget compose-projekt med genererade engångshemligheter. Stegen fungerar som
  de står; backendsviten mot testdatabasen ingick inte.
- **I daglig användning, verifierat av underhållaren 2026-11-12:** anslutningen till riktiga Claude, Android-appen på en
  riktig telefon och servern på Linux.
- **Ännu inte provat:** macOS.

Räkna med skavanker och brytande ändringar tills en release är publicerad.

## Vad en release ger

| Resultat | Var | Signerat med |
| --- | --- | --- |
| Containerimage, `linux/amd64` och `linux/arm64`, med SBOM och SLSA-proveniens | `ghcr.io/<owner>/roadlake-sidekick:vX.Y.Z` | cosign keyless (GitHub OIDC), på indexets digest; GitHubs byggproveniensattestering |
| Android-APK `sidekick-X.Y.Z.apk` | arbetsflödets artefakt `release-bundle-X.Y.Z` | din Android-signeringsnyckel (`apksigner`); GitHubs byggproveniensattestering |
| `SHA256SUMS` och dess signaturpaket | samma paket | cosign keyless (`sign-blob`); GitHubs byggproveniensattestering |
| imagens SBOM (SPDX JSON) och releaseanteckningarna (tagna ur ändringsloggen) | samma paket | täcks av `SHA256SUMS`; GitHubs byggproveniensattestering |
| R8-mappning för kraschrapporter | artefakten `android-r8-mapping` (90 dagar) | ingen (ett felsökningshjälpmedel, inte en del av releasen) |

Git-taggen `vX.Y.Z` signeras av underhållaren (`git tag -s`), så varje länk från källtaggen till filerna går att
verifiera.

## Engångsuppsättning (steg som bara repots ägare kan ta)

1. **Android-signeringsnyckel.** Skapa den på din egen dator och förvara den utanför repot. Förlorar du den kan
   installerade appar inte längre uppdateras (en ny nyckel är en ny app för telefonen).

   ```sh
   keytool -genkeypair -v -keystore sidekick-release.jks -alias sidekick \
     -keyalg RSA -keysize 4096 -validity 10000
   ```

   Säkerhetskopiera `.jks`-filen och båda lösenorden på ett säkert ställe, skilt från GitHub.
2. **Miljön `release` (godkännandegrinden, ett godkännande per release).** Settings, Environments, New environment, döp
   den exakt till `release` och ställ in den:

   - **Required reviewers:** kryssa i och lägg till dig själv (upp till sex personer eller team; ett godkännande räcker).
     Bara jobbet `signing-check` använder den här miljön, och varje annat jobb i en riktig körning behöver det jobbet,
     så en riktig körning pausar en gång, i början, tills en granskare godkänner den. En torrkörning når aldrig
     miljön och behöver inget godkännande.
   - **Prevent self-review:** låt den vara urkryssad så länge du är enda granskare; annars kan du inte godkänna en körning
     som du själv startat. Kryssa i den när en andra granskare finns.
   - **Allow administrators to bypass configured protection rules:** kryssa ur den, så att godkännandet inte kan hoppas över.
   - **Deployment branches and tags:** "Selected branches and tags", lägg till `main`.
   - **Wait timer:** ingen. En körning som ingen godkänner går ut efter 30 dagar.
   - Den innehåller ingen hemlighet.

   Dialogen "Review pending deployments" visar miljön och körningen; kontrollera versionen i körningens titel innan du
   godkänner.
3. **Miljön `release-signing` (signeringshemligheterna).** En andra miljö, döpt exakt `release-signing`, **utan**
   obligatoriska granskare (godkännandet gavs i `release`). **Du MÅSTE sätta Deployment branches and tags till "Selected
   branches and tags" med `main`:** utan granskare är den begränsningen det enda som hindrar ett arbetsflöde som ändrats
   på en annan gren från att läsa signeringshemligheterna, så lämna den aldrig på "No restriction". Jobben `secrets-check`, `sign-apk`, `release` och `sign-bundle` använder den; vart och ett behöver `signing-check`
   (direkt eller via `gates`), så inget av dem kan köras före ägarens godkännande. Lägg signeringshemligheterna här
   (Settings, Environments, `release-signing`, Environment secrets; inte repositoryhemligheter). En riktig körning
   stoppar innan något byggs om en saknas:

   | Hemlighet | Värde |
   | --- | --- |
   | `ANDROID_KEYSTORE_BASE64` | `base64 -w0 sidekick-release.jks` |
   | `ANDROID_KEYSTORE_PASSWORD` | lösenordet till nyckelarkivet |
   | `ANDROID_KEY_ALIAS` | `sidekick` (aliaset ovan) |
   | `ANDROID_KEY_PASSWORD` | nyckelns lösenord |

   ```sh
   base64 -w0 sidekick-release.jks | gh secret set ANDROID_KEYSTORE_BASE64 --env release-signing
   ```

   Radera varje repositoryhemlighet med samma namn (`gh secret delete NAME`): en hemlighet som inte ligger i miljön kan
   läsas av varje arbetsflöde, och release-arbetsflödet behöver den inte. Cosign-signaturen och attesteringarna behöver
   ingen hemlighet: de använder det kortlivade GitHub OIDC-tokenet i jobbet.
4. **Fastnålat certifikat (krävs för en riktig körning).** Repositoryvariabeln `ANDROID_CERT_SHA256` = SHA-256 för ditt
   signeringscertifikat (`keytool -list -v -keystore sidekick-release.jks`, raden "SHA256", gemener, utan kolon).
   Arbetsflödet vägrar en APK som signerats med någon annan nyckel och vägrar alltid ett debugcertifikat. APK:n byggs
   osignerad i ett jobb (npm och Gradle körs där, utan hemlighet) och signeras i ett separat jobb utan utcheckning, med
   runnerimagens Android build-tools i den version som är låst i arbetsflödet (`ANDROID_BUILD_TOOLS_VERSION`).
   Signeringsjobbet publicerar APK:ns sha256, och sista jobbet vägrar signera kontrollsummorna om inte APK:n,
   imagens digest och SBOM i paketet stämmer med det de betrodda jobben rapporterade.
5. **Licensgivarens publika licensnyckel.** `DEFAULT_LICENSE_PUBLIC_KEY` i `backend/src/sidekick/license/public_key.py`
   måste vara den riktiga nyckeln, inte platshållaren; en riktig körning vägrar platshållaren
   (`tools/check-license-public-key.py`). Att sätta den är licensgivarens steg, med licensgivarens privata nyckel
   förvarad utanför GitHub.
6. **Repositoryinställningar.** Skydda `v*`-taggar med en tagg-ruleset (Settings, Rules, Rulesets, New tag ruleset, mål
   `v*`; begränsa uppdateringar och radering och, med dig själv på bypass-listan, skapande): kontrollen av migrationsklass
   litar på föregående tagg, och en flyttad tagg skulle också flytta vad kunderna tror att en version är. Tillåt GitHub
   Actions att skriva paket. Artefaktattesteringar kräver ett publikt repo (eller en GitHub-plan som stöder dem för privata).
   Efter första pushen, sätt GHCR-paketets synlighet (publik eller privat) i paketinställningarna.
7. **Signera taggen.** Ställ in en signeringsnyckel för git en gång (`git config gpg.format ssh` med `user.signingkey` för
   en SSH-nyckel, eller en GPG-nyckel) och lägg till den publika nyckeln hos GitHub som signeringsnyckel, så att GitHub
   visar taggen som verifierad.
8. **Ingår inte här:** ett Google Play-konto och en notering där, uppladdning av App Bundle (`.aab`) och Play App
   Signing. Play kräver ett eget beslut om vem som håller uppladdningsnyckeln; detta arbetsflöde ger bara en direkt
   installerbar APK.

## Releasesteg

Stegen är desamma för varje nivå; det som skiljer är vad versionen får innehålla.

| Nivå | Version | Innehåller | `migration_class` |
| --- | --- | --- | --- |
| Major | `X.0.0` | brytande ändringar, en ny companion-API-version | `expand` eller `breaking` |
| Minor | `X.Y.0` | nya funktioner | `expand` (eller `breaking` under 1.0, se [Versioner](#versioner)) |
| Patch | `X.Y.Z` | bara rättningar, inget brott i beteende eller schema | bara `expand`; arbetsflödet vägrar `breaking` |

En patch passerar exakt samma grindar som de andra (hela CI, drillen, versionssynk, migrationskontrollen,
licensnyckeln). Migrationskontrollen jämför den deklarerade klassen med migreringarna som tillkommit sedan föregående
release, så en patch som lägger till en contract-migrering kan inte heller deklarera `expand`.

1. **Version.** Sätt versionen i `backend/pyproject.toml` och dess speglar på en gren
   (`npm --prefix frontend version X.Y.Z --no-git-tag-version`, ändra `__version__` i
   `backend/src/sidekick/__init__.py`, `uv lock --project backend`). Döp om `## [Unreleased]` i `CHANGELOG.md`
   till `## [X.Y.Z] - YYYY-MM-DD` och starta en ny tom `## [Unreleased]` ovanför.
2. **Kontrollera lokalt.**

   ```sh
   python3 tools/check-version-sync.py --release --tag vX.Y.Z
   ```

   Kör sedan hela releasegrinden på den commit du ska släppa:

   ```sh
   bash tools/check-all.sh --slot K --release
   ```

   `--release` lägger till, efter de vanliga stegen och i samma ordning som `.github/workflows/ci.yml`, de kontroller
   som release-CI kör utöver dem: kontraktsdiffen (`sidekick.export_reference --check`,
   `sidekick.mcp.export_tool_reference --check`, `generate:tool-types --check`, och ögonblicksbilderna under
   `contracts/` som exporteras på nytt och jämförs), frontendens täckningströskel, Playwrights mobilgranskning,
   beroendegranskningen i `audit.yml` (pip-audit, `npm audit` för frontend och webbplatsen, OSV-Scanner på
   Gradle-låsfilerna) och drillen (`tools/drill.sh selfhost --local-images`, cirka 3 minuter, på slumpade portar och i
   ett eget Compose-projekt, så den rör aldrig en körande instans). Frontend-steget omfattar redan MCP-appens vyer på
   Preact. Grinden kör testerna som CI gör: backend- och frontendtester i UTC (frontendtesterna även i
   `America/Los_Angeles`), Playwright-testerna, shellcheck och gitleaks i de avbilder som är fastnålade i
   `tools/ci-images.sh` (samma som CI använder, så webbläsarbygge, typsnitt och verktygsversioner stämmer), och
   steget `published-tree` bygger den publika exporten och kontrollerar den som den publicerade CI kommer att göra
   (lint, prettier, tsc, vitest, policytester, shellcheck, gitleaks, Playwright-testerna). Docker krävs för dem;
   beroendegranskningen kräver nätverk. En del vars verktyg eller värd inte finns skriver en `SKIPPED: ...`-rad och
   steget rapporteras som `SKIPPED`, aldrig som `ok`; lägg till `--strict` för att göra det till ett fel, och kör
   grinden på en maskin med Docker och nätverk innan du släpper. Täcks inte lokalt: emulatortestet, avbildsbygget och
   Compose-röktestet; releasekörningen gör dem.
   Slå ihop med `main` när det är grönt. Starta sedan arbetsflödet `CI` för hand i det publika repot (Actions, "CI",
   Run workflow) på den commit du ska släppa; själva releasekörningen kör hela CI igen.
3. **Torrkör först.** Actions, "release-image", Run workflow: `version` = `vX.Y.Z`, `migration_class` (se nedan),
   `previous_release` (`none` för den allra första releasen, annars tomt), **`dry_run` ikryssad**. Den bygger båda
   imageplattformarna och APK:n osignerad, pushar och signerar ingenting, behöver inga hemligheter och laddar upp
   `release-bundle-X.Y.Z-dry-run`. Rätta det den rapporterar; `linux/arm64`-bygget körs under emulering och kan ta
   20 minuter eller mer.
4. **Riktig körning.** Samma formulär med `dry_run` urkryssad. Körningen kontrollerar först att commiten ligger på `main` och
   väntar sedan på ditt godkännande i miljön `release` (godkänn bara en körning du själv startat); det är releasens enda
   godkännande. Efter det körs kontrollerna (signeringshemligheterna och det fastnålade certifikatet, hela CI och drillen
   på exakt denna commit, versionssynk, en version högre än varje befintlig releasetagg, migrationsklass, licensnyckel),
   sedan APK:n (byggd osignerad, sedan signerad), sedan imagen (pushad, Trivy-skannad, signerad, attesterad) och till sist
   paketet (signerat och attesterat). `migration_class` är `expand` när föregående
   image fortfarande fungerar mot det nya schemat och `breaking` för ett enkelriktat steg; kontrollen jämför den
   deklarerade klassen med de migreringar som tillkommit sedan föregående release.
5. **Verifiera** resultatet enligt nedan, från en dator som inte är byggdatorn.
6. **Tagga och släpp.** Först efter steg 5:

   ```sh
   git tag -s vX.Y.Z -m "vX.Y.Z" <released-commit> && git tag -v vX.Y.Z && git push origin vX.Y.Z
   gh run download <run-id> -n release-bundle-X.Y.Z -D bundle
   gh release create vX.Y.Z --verify-tag --title "vX.Y.Z" --notes-file bundle/release-notes.md \
     bundle/sidekick-X.Y.Z.apk bundle/SHA256SUMS bundle/SHA256SUMS.sigstore.json bundle/sbom-image-X.Y.Z.spdx.json
   ```

   Taggen ska vara signerad (`git tag -s`); en annoterad tagg (`git tag -a`) är minimum, eftersom nästa release hittar
   sin jämförelsepunkt från den och migrationskontrollen vägrar en lättviktig tagg. Arbetsflödet skapar aldrig taggen
   eller releasen; båda är medvetna, signerade steg som underhållaren tar.

7. **Scorecard.** När releasen är publicerad startar du arbetsflödet `scorecard` för hand från `main` (Actions,
   "scorecard", Run workflow). Det analyserar det publika repot med den officiella OpenSSF Scorecard-actionen och
   publicerar resultatet som Scorecard-badgen i README visar; kontrollera i körloggen att resultatet publicerades.
   Det har medvetet ingen release-trigger: actionen analyserar bara standardgrenen, och en `release`-händelse körs på
   taggen, så actionen skulle vägra. Repot måste vara publikt. Kör det också en gång så snart repot är publikt, och
   starta arbetsflödet `ci` för hand på `main` en gång: Scorecard- och CI-badgarna i README förblir avstängda (steg 8) tills vart och ett av dem har körts, så att ingen visar
   en trasig bild eller "no status".
8. **README.** Slå på de utkommenterade badgarna i `README.md` och `README.sv.md` (i underhållsrepot ligger de i
   `tools/export/overlay/`; ta bort kommentarsraden som börjar med `<!-- release badges, off until the first release`
   och den avslutande `-->`-raden under de sex badgarna; gör det först efter de första körningarna av `ci` och
   `scorecard`, och när releasen finns) och byt statusnotisen ("ännu inte släppt") mot texten mellan markörerna `START` och `END` i kommentaren
   under den; ta sedan bort kommentaren. Kontrollera i båda språken att badgarna renderas och att länkarna fungerar.
   Varje badge stämmer bara för att arbetsflödet har körts på riktigt: CI, Scorecard, senaste GitHub-releasen, senaste körningen
   av `release-image`, cosign-signaturen med build provenance och Trivy-skanningen av imagen.

## Verifiera en release

Varje fil och imagen kan verifieras av vem som helst, med `cosign` v3, GitHub CLI (`gh`) och `apksigner`. Byt
`<owner>/<repo>` mot repot. Releaseanteckningarna för varje release upprepar kommandona med de riktiga värdena.

```sh
# Image signature: identity and digest are printed in the run summary ("Signer identity", "Digest").
cosign verify ghcr.io/<owner>/roadlake-sidekick@sha256:<digest> \
  --certificate-identity "https://github.com/<owner>/<repo>/.github/workflows/release-image.yml@refs/heads/main" \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com

# Image build provenance (GitHub artifact attestation, signed through Sigstore).
gh attestation verify oci://ghcr.io/<owner>/roadlake-sidekick@sha256:<digest> --repo <owner>/<repo> \
  --signer-workflow <owner>/<repo>/.github/workflows/release-image.yml

# Image metadata: version label, schema head, platforms, SBOM and provenance attestations.
docker buildx imagetools inspect ghcr.io/<owner>/roadlake-sidekick@sha256:<digest>
docker buildx imagetools inspect ghcr.io/<owner>/roadlake-sidekick@sha256:<digest> --format '{{ json .SBOM }}'

# Files: checksums, then the signature of the checksum file.
cd bundle && sha256sum -c SHA256SUMS
cosign verify-blob SHA256SUMS --bundle SHA256SUMS.sigstore.json \
  --certificate-identity "https://github.com/<owner>/<repo>/.github/workflows/release-image.yml@refs/heads/main" \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com

# Build provenance of each file: the APK, the SBOM, the checksums and the release notes.
for file in sidekick-X.Y.Z.apk sbom-image-X.Y.Z.spdx.json SHA256SUMS release-notes.md; do
  gh attestation verify "$file" --repo <owner>/<repo> \
    --signer-workflow <owner>/<repo>/.github/workflows/release-image.yml
done

# APK: the signature must verify and the certificate must be yours (compare with ANDROID_CERT_SHA256).
apksigner verify --verbose --print-certs sidekick-X.Y.Z.apk

# The tag: signed by the maintainer, pointing at the released commit.
git fetch --tags && git tag -v vX.Y.Z
```

`apksigner` finns i Android SDK:s build-tools (`$ANDROID_HOME/build-tools/<version>/`). Förvänta dig `Verifies`,
schema v2 (eller nyare) `true` och exakt en signerare vars SHA-256-digest är lika med det fastnålade värdet. Ett
debugcertifikat (`CN=Android Debug`) eller en osignerad APK betyder att releasen inte får publiceras.

Vad varje kontroll bevisar: `cosign verify` och `cosign verify-blob` bevisar att imagen eller kontrollsummefilen
signerats av denna arbetsflödesfil i detta repo (ingen nyckel att stjäla; certifikatet lever i minuter och loggas
offentligt i Sigstore). `gh attestation verify` bevisar att en fil med exakt den digesten tillverkades av den
arbetsflödeskörningen i det repot. `sha256sum -c` binder filerna du laddat ner till den signerade kontrollsummelistan,
och `apksigner` binder APK:n till ägarens egen signeringsnyckel, som telefonen också kontrollerar vid varje uppdatering.

`<ref>` i identiteten är den ref arbetsflödet kördes från (`refs/heads/main` när du startar det från `main`). En release
signeras av arbetsflödesfilen, så om `release-image.yml` döptes om skulle den identitet ändras som varje kund har
fastnålat i `update.sh`. Att köra genom miljöerna `release` och `release-signing` ändrar inte identiteten.

## Bevisa en uppdatering över en schemaändring

Den första releasen har ingen föregångare, så det finns inget att uppdatera från; baslinjen beskrivs i
[migrationsbaslinjen](../explanation/schema-baseline.sv.md). Från den andra releasen och framåt, före
tillkännagivandet:

1. Ta föregående releaseimages digest (`FROM`) och den nya (`TO`), samt signerarens identitet från ovan.
2. Kör drillen mot de släppta imagerna. Den installerar `FROM`, skriver markördata, uppdaterar till `TO` med den
   riktiga `update.sh` och den riktiga cosign-kontrollen, kontrollerar att schemaversionen flyttats och markören
   överlevt, och tar sedan backup, raderar varje volym och återställer (kräver Docker Compose v2.24.4 eller nyare och
   `cosign`):

   ```sh
   bash tools/drill.sh selfhost \
     --from-image ghcr.io/<owner>/roadlake-sidekick@sha256:<FROM> \
     --to-image ghcr.io/<owner>/roadlake-sidekick@sha256:<TO> \
     --cert-identity "https://github.com/<owner>/<repo>/.github/workflows/release-image.yml@refs/heads/main"
   ```

   Om repositoryvariablerna `DRILL_FROM_IMAGE`, `DRILL_TO_IMAGE` och `DRILL_CERT_IDENTITY` sätts gör drillen (en
   releasegrind, eller startad för hand) detsamma på en ren runner.
3. En `breaking`-release är enkelriktad: läs också anteckningarna i [självhostningsguiden](../operate/update.sv.md)
   om återgång, och släpp den som en minor-version (under 1.0) eller major-version. Releasen deklarerar också den äldsta
   version den kan uppdateras från i `deploy/selfhost/min-upgrade-from.txt`; håll den sann, för `update.sh` vägrar ett
   hopp som hoppar över den.
4. Installera APK:n på en telefon som har den förra appen, para den med den uppdaterade servern och kontrollera att
   Idag, Arbete och Dagbok laddas. Companion-API:t (`/companion/v1/`) är additivt inom en major-linje, så en äldre app
   måste fortsätta fungera mot en nyare server.

## Om något misslyckas

- En grind, CI eller drillen misslyckas: inget byggdes eller pushades; rätta och börja om (versionstaggen är inte
  förbrukad).
- Godkännandet nekades eller gick ut: inget har byggts eller signerats efter den punkten; starta en ny körning.
- Imagen pushades men ett senare steg misslyckades (sårbarhetsskanningen, signeringen eller paketet): taggen `vX.Y.Z`
  finns i GHCR och flyttas aldrig, och arbetsflödet vägrar pusha samma version igen. Rättningen är nästa patchversion
  (`X.Y.(Z+1)`), eller nästa minor eller en major om ändringen motiverar det, med eget ändringsloggsavsnitt,
  versionshöjning och kontroller som ovan. Den misslyckade `vX.Y.Z` förblir oanvänd: pusha inte git-taggen för den,
  publicera inte dess image eller paket, och radera eller tagga aldrig om imagen för att återanvända numret.
- Signeringsnyckeln läckte eller förlorades: radera miljöhemligheterna, berätta för ägaren av installationerna och
  behandla nästa APK som en ny applinje.

## Taggar och den första releasen

Release-arbetsflödet (`.github/workflows/release-image.yml`, startas för hand) körs bara från en incheckning på
`main`, bygger major-, minor- och patchversioner efter ägarens godkännande och kör hela CI och drillen själv som grindar (CI körs aldrig vid push eller enligt schema, bara för hand och som den här grinden, aldrig för pull requests; ändringar testas lokalt först). Det kontrollerar också den angivna migrationsklassen mot migrationerna som lagts till sedan föregående
release (en patch får bara deklarera `expand`). Det skapar aldrig git-taggar. Pusha den signerade taggen på den släppta incheckningen själv efter en release; nästa
release hittar sin jämförelsepunkt från den taggen:

```sh
git tag -s vX.Y.Z -m "vX.Y.Z" <released-commit> && git tag -v vX.Y.Z && git push origin vX.Y.Z
```

Taggen ska vara signerad (`-s`); minst måste den vara annoterad (`-a`), eftersom migrationskontrollen vägrar en lättviktig tagg. Skydda
`v*`-taggar med en tag protection rule (eller en ruleset) i GitHub-repots inställningar. Skyddet är en förutsättning
för migrationskontrollen: den litar på taggen, och en tvångsflyttad tagg kan ge en tom jämförelse. Arbetsflödet kan
inte sätta upp det och skriver ut en varning om det vid varje körning.

Den allra första releasen saknar tagg, så starta arbetsflödet med `previous_release` satt till `none`. `none` vägras så snart någon `v*`-tagg finns, och vid en första release kontrolleras alla
migrationer mot den angivna klassen, inte bara nya.

## Versioner

Sidekick har en enda releaseversion, `MAJOR.MINOR.PATCH` ([semantisk versionering](https://semver.org/)). Källan
är `version` i `backend/pyproject.toml`. `backend/src/sidekick/__init__.py`, `frontend/package.json` och
`frontend/package-lock.json` speglar den, och `backend/tests/policy/test_version_sync.py` fallerar när de skiljer
sig. Samma regler körs som `tools/check-version-sync.py`, som också kontrollerar `CHANGELOG.md` och Androids
härledning, och som release-arbetsflödet kör innan något byggs. OpenAPI-dokumentet tar sin version från paketet.

- **Servern och appen delar version.** Serverns image, MCP App-paketet och Android-appen byggs från samma
  incheckning och har samma nummer. Android-bygget läser `versionName` från `frontend/package.json` och räknar
  fram `versionCode` som `MAJOR*10000 + MINOR*100 + PATCH` (0.1.0 blir 100), så varje höjning ökar den.
  `MINOR` och `PATCH` hålls därför under 100; bygget vägrar annat.
- **Kompatibiliteten går via companion-API:t, inte via releasenumret.** Appen pratar bara med servern under
  `/companion/v1/`, och companion-svaren har `api_version` (`companion.v1`, satt av `API_VERSION` i
  `backend/src/sidekick/api/companion.py`). Inom `v1` är en ändring bara tillägg: nya rutter, nya valfria fält,
  inga borttagna eller omdöpta fält. En brytande ändring får ett nytt prefix och en ny `api_version`
  (`/companion/v2/`, `companion.v2`), och servern fortsätter att svara på `v1` vid sidan av, eftersom en
  telefon kan köra en äldre app än servern. Det är en major- eller minor-release, aldrig en patch.
- **Vad numret betyder.** En patch rättar fel utan att bryta beteende eller schema. En minor-release lägger till
  funktioner och får ha `expand`-migreringar. Migrationsklassen `breaking` eller en ny version av
  companion-API:t kräver minst en minor-release så länge versionen är under 1.0, och en major-release därefter.

## Kvartalsvis genomgång av beroenden

`fastmcp` är fastlåst till en exakt version och undantaget från automatiska uppdateringsförslag, eftersom det bär
verktygs- och schemakontraktet som rummen och klienterna litar på. En fastlåst version får inga rättningar av sig
själv, så en gång per kvartal (och tidigare om en säkerhetsnotis nämner den) läser man versionsanteckningar och
säkerhetsnotiser för `fastmcp`, `mcp`, `httpx`, `httpx2` och de andra fastlåsta körtidsbiblioteken och avgör för var
och en om den ska uppgraderas eller varför inte. En uppgradering av `fastmcp` går först genom kontrakttesterna
(den genererade verktygslistan, `backend/tests/contract/test_tool_context_budget.py` och autentiseringstesterna),
aldrig bara på en grön enhetstestkörning. Resonemanget finns i
[hotmodellen](../explanation/threat-model.md#reviewing-the-frozen-mcp-library-and-other-dependencies) (på engelska).
