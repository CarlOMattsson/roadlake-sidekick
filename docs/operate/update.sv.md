# Uppdatera

[English](update.md)

<!-- description: Uppdatera en självhostad server, antingen från källkoden eller till en signerad avbild. Ta en backup först i båda fallen. -->

Uppdatera en självhostad server, antingen från källkoden eller till en signerad avbild. Ta en backup först i båda fallen.

Det finns två vägar. Ta en backup först, vilken du än väljer ([Backup och återställning](backup-and-restore.sv.md)).

**Från källkod (det som första starten använde).** `git pull --ff-only`, sätt de två byggvariablerna som i
steg 2 under [Första start](../start/self-hosted-server.sv.md#första-start) och kör `docker compose --env-file selfhost.env build`. Stoppa sedan
skrivarna, kör migreraren medan inget skriver och starta allt igen med de profiler du använder (raden med `stop`
nämner varje profil så att alla workers hittas; tjänster som inte körs lämnas orörda):

```bash
C="docker compose --env-file selfhost.env"
$C --profile backup --profile push --profile memory stop api automation-worker backup push memory-worker
$C run --rm -T --no-deps migrate     # om den här misslyckas: starta inte den nya koden
$C --profile vps up -d               # med de profiler du använder, som i Första start
```

Den här vägen har ingen signatur att kontrollera; det du litar på är utcheckningen.

**Till en signerad, digest-låst image.** `update.sh` verifierar signaturen, tar en krypterad ägarbackup och en
krypterad ögonblicksbild av databasen, kör migreraren och väntar tills API:et är redo (det når databasen och schemat har den nya imagens revision) och varje arbetare den startat körs och är frisk; annars rullar den tillbaka. Som förval skriver den
ut planen och ändrar ingenting förrän du anger `--apply`.

```bash
./update.sh                                   # torrkörning
./update.sh --check --cert-identity <signer identity>   # nuvarande digest, signatur och schemats huvud
./update.sh --apply --image ghcr.io/<owner>/roadlake-sidekick@sha256:<digest> --cert-identity <signer identity>
```

Utan signerarens identitet (`--cert-identity` eller `SIDEKICK_RELEASE_CERT_IDENTITY`) rapporterar `--check` signaturen
som NOT CHECKED. De tre värdena kommer från den som publicerar imagen. Release-arbetsflödet
(`.github/workflows/release-image.yml`, startas för hand) publicerar `ghcr.io/<owner>/roadlake-sidekick`, där
`<owner>` är GitHub-kontot eller organisationen som kör det, och skriver ut digesten och signerarens identitet
i körningens jobbsammanfattning: raden `Digest:`, raden `Signer identity:` (på formen
`https://github.com/<owner>/<repo>/.github/workflows/release-image.yml@<ref>`) och kommandot `cosign verify`
med båda. Använd de två värdena exakt. Ange dessutom `--cert-issuer` bara om imagen inte signerades av GitHub
Actions (förvalet är `https://token.actions.githubusercontent.com`). `update.sh` kräver `cosign` och vägrar
fortsätta utan det.

När `--apply` har körts står den låsta imagen i `release.env`. Skicka med den som en andra `--env-file` till
varje senare compose-kommando: `docker compose --env-file selfhost.env --env-file release.env up -d`. Huvudet
i `update.sh` beskriver hela ordningen och reglerna för återgång.

**Vilka versioner som får uppdatera till vilka.** Varje release anger den äldsta version den kan uppdateras från
(image-etiketten `io.sidekick.min-upgrade-from`, som sätts från `deploy/selfhost/min-upgrade-from.txt` när releasen
byggs). Innan något stoppas läser `update.sh` versionen på den image som faktiskt körs
(`org.opencontainers.image.version`) och vägrar ett hopp som hoppar över ett mellansteg: uppdatera först till en
mellanliggande release och sedan till den nyare. Den vägrar också uppdatera när den installerade eller den nya versionen
inte går att avgöra (ett lokalt bygge, eller en image från före etiketterna fanns) och att gå bakåt i version. Bara
det okända fallet går att åsidosätta, med `--allow-unknown-version`, och bara om du vet att installationen är på eller
över den nya imagens miniminivå. Backupen och ögonblicksbilden kommer efter den här kontrollen, så en vägran ändrar
ingenting.

**Avbrutna uppdateringar.** Ctrl-C, ett terminalfönster som stängs, `kill` eller ett oväntat fel under `--apply` kör
samma återhämtning som ett misslyckat steg (fallen nedan): låset släpps, en halvskriven ögonblicksbild tas bort och den
föregående imagen och workers startas igen om migreringen inte hade börjat. Om processen dödas hårt (`kill -9`,
strömavbrott) släpper operativsystemet låset (ett `flock` på `update-state/update.lock`, som hålls under hela körningen,
så att två `--apply` aldrig kan överlappa); nästa `--apply` läser journalen först och, om den slutar på `STARTED`,
`STOPPING_WRITERS` eller `RESUMING`, återupptar: den startar de workers som den dödade körningen hade stoppat, också
när den återupptagna körningen själv misslyckas i en förkontroll (till exempel signaturen) eller avbryts innan den
stoppar något igen. En journal som slutar i ett senare tillstånd (`MIGRATING`, `ROLLING_BACK`, `NEEDS_*`) kräver
fortfarande det manuella beslutet nedan.

**Vad release-arbetsflödet kontrollerar.** När imagen har pushats och innan dess digest signeras skannar Trivy den, och
körningen misslyckas vid varje HIGH- eller CRITICAL-sårbarhet som har en rättning (orättade ignoreras); en image som
inte klarar skanningen signeras aldrig, så `update.sh` vägrar den. BuildKit bifogar en SBOM och ett SLSA-ursprungsintyg
till imagen. Basimagerna i bygget och i compose-filerna är låsta med digest (`tools/pin-image-digests.sh --write`
låser om dem; ett test misslyckas vid en ny olåst image). Läs SBOM:en med:

```bash
docker buildx imagetools inspect ghcr.io/<owner>/roadlake-sidekick@sha256:<digest> --format '{{ json .SBOM }}'
```

**Om en uppdatering misslyckas.** Innan `update.sh` migrerar stoppar den API:et och varje worker som körde eller startade om
(automation, backup, push, minne) och startar dem igen efteråt, alla med samma image. De sista raderna den skriver, och det
sista ordet i `update-state/journal.log`, visar vilket fall du är i:

- `ABORTED`: signaturen, hämtningen, backupen eller ögonblicksbilden misslyckades, eller så gick det inte att avgöra
  en workers tillstånd, eller så körde eller startade om en skrivare fortfarande efter stoppet. API:et och workers är stoppade under backupen och ögonblicksbilden (så att ingen bekräftad
  skrivning missas), och vid detta utfall har de startats igen med den föregående imagen; installationen kör som förut.
- `ROLLED_BACK`: den nya imagen blev inte redo, och den föregående imagen fungerar mot det nya schemat (utgåvan
  anger det med sin migreringsklass). API:et och workers kör den föregående imagen igen. Inget att göra.
- `NEEDS_MANUAL_RESTORE`: databasen kan ligga på ett nyare schema än den föregående imagen klarar. API:et och
  workers förblir stoppade med flit, och nästa `--apply` vägras. Rätta antingen framåt: kör
  `echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) ABORTED manual" >> update-state/journal.log` och kör `update.sh --apply`
  igen med en rättad image. Eller återställ ögonblicksbilden med den **föregående** imagen, enligt
  [Backup och återställning](backup-and-restore.sv.md).
- `NEEDS_RESTART`: uppdateringen avbröts före migreringen (schemat är oförändrat), men den föregående imagen blev inte
  redo igen efter stoppet. Inget migrerades och inget återställs. Starta installationen för hand
  (`docker compose --env-file selfhost.env up -d`, med `--env-file release.env` om den filen finns), kontrollera att
  API:et svarar och kör sedan
  `echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) ABORTED manual" >> update-state/journal.log`. Tills den raden finns i
  journalen vägras nästa `--apply`.

**Docker-nätverksfel vid `up` eller `update.sh`.** Caddy och API:et pratar över ett litet internt Docker-nätverk
(`proxy`) med det fasta adressblocket `198.51.100.0/29` (reserverat för dokumentation, så det routas aldrig på
internet). API:et litar på klientadress och schema från vidarebefordrade huvuden bara från Caddys adress där. Svarar
Docker `Pool overlaps with other one on this address space` krockar blocket med ett befintligt Docker-nätverk eller en
VPN-route på värden: hitta det med `docker network ls` och `docker network inspect`, ta bort eller flytta det nätverket
och kör uppdateringen igen. `update.sh` återskapar en körande Caddy tillsammans med API:et så att den går med i
nätverket.
