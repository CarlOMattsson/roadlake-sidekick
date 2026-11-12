# Backup och återställning

[English](backup-and-restore.md)

<!-- description: Ta krypterade backuper av dina data och läs tillbaka dem. Förvara nyckeln och en kopia av backuperna någon annanstans än på servern. -->

Ta krypterade backuper av dina data och läs tillbaka dem. Förvara nyckeln och en kopia av backuperna någon annanstans än på servern.

Det här innehåller varje kopia:

| Kopia | Skapas av | Innehåller | Återställs med |
| --- | --- | --- | --- |
| Krypterad ägarbackup (`.skbackup`) | `--profile backup` och `update.sh --apply` | en eller flera ägares data, som en export | `restore.sh` (`sidekick-backup import`) |
| Krypterad ögonblicksbild av databasen | `update.sh --apply`, i `update-state/snapshots/` | hela databasen | stegen nedan |
| Hindsight-minnet | inget automatiskt | volymen `hindsight_pg0` | stegen nedan |

**Ägarbackuper.** Skapa nyckeln och lägg den i `selfhost.env` som `SIDEKICK_BACKUP_ENCRYPTION_KEY`, och starta
sedan profilen. Spara en kopia av nyckeln någon annanstans än på den här maskinen: utan den går varken
backuperna eller uppdateringarnas ögonblicksbilder att läsa.

```bash
docker compose --env-file selfhost.env run --rm --no-deps api sidekick-backup keygen
docker compose --env-file selfhost.env --profile backup up -d
```

Filerna hamnar i `/var/lib/sidekick/backups` i volymen `state` och sparas så länge som `selfhost.env` anger.
Kopiera dem från maskinen:

```bash
mkdir -p backups && docker compose --env-file selfhost.env --profile backup cp backup:/var/lib/sidekick/backups/. ./backups/
```

**Ledigt utrymme och gallring.** En ny ägarbackup, och ögonblicksbilden i `update.sh --apply`, skrivs bara när
katalogen har plats: minst den senaste färdiga filens storlek gånger `SIDEKICK_BACKUP_SPACE_MARGIN_PCT` (förval 150,
minst 100) och minst 64 MiB. För ögonblicksbilden läser `update.sh` golvet från sin egen miljö som
`SIDEKICK_BACKUP_SPACE_FLOOR_MB` (förval 64). Den första har inget att jämföra med, så då gäller
bara golvet. Annars vägrar kommandot med ett tydligt fel; `update.sh` kontrollerar detta **innan** något stoppas
(journal `ABORTED`, inget rört), och ett ledigt utrymme som inte går att läsa räknas som en vägran. Ägarbackuperna
behåller minst de `SIDEKICK_BACKUP_MIN_KEEP` (förval 5) senaste färdiga filerna, hur gamla de än är, utöver antals- och
åldersgränserna. `update.sh` gallrar ögonblicksbilder först efter en **lyckad** uppdatering, behåller de
`SIDEKICK_SNAPSHOT_KEEP` (förval 5, läses ur skriptets egen miljö) senaste och aldrig den som nyss togs. Gallringen rör
bara filer vars hela namn har den färdiga formen (`sidekick-pre-<UTC-tid>.dump.enc`,
`sidekick-backup-<UTC-tid>-<id>.skbackup`), aldrig en `.partial`, en dold fil, en symbolisk länk eller något annat du
lagt där.

**Storlekstak.** En ägarbackup rymmer högst 512 MiB klartext: en större nekas när den skapas (en säker loggrad,
ingenting skrivs), och `sidekick-backup import` nekar en större backup eller export innan den läses. En backup över
512 MiB klartext som skrevs innan taket fanns går inte att importera, och det finns avsiktligt ingen inställning för
att höja taket. Taket tillämpas medan exporten läses, så en för stor backup nekas efter ungefär så mycket data och inte först när hela
databasen har lästs in. Krypteringen är inte strömmande (backupen är en enda Fernet-token), så en backup strax under
taket hålls fortfarande i minnet, och i några kopior, medan den krypteras och läses tillbaka.

**Återställ en ägare** från en `.skbackup`-fil (eller en okrypterad ägarexport, `.json`) till en befintlig, tom ägare
(skapa den först med `sidekick-admin create-user`, steg 3 under [Första start](../start/self-hosted-server.sv.md#första-start)). `restore.sh` är ett tunt
omslag kring `sidekick-backup import` i en engångscontainer av `api`. Det visar planen och skriver ingenting utan
`--apply`; med `--apply` skriver det exakt den plan det just visade (matchad med checksumman) och kontrollerar
radantalen. En målägare som redan har data nekas, och det gör också fel nyckel eller en ändrad plan. Bara backuper och
exporter i det nuvarande formatet läses; äldre backuper och ägarexporter läses inte. Utan omslaget används `sidekick-backup import`:

```bash
./restore.sh --backup FILE.skbackup --target-owner UUID [--source-owner UUID]           # bara planen
./restore.sh --backup FILE.skbackup --target-owner UUID [--source-owner UUID] --apply
```

För en backup från en tidigare installation måste nyckeln vara den som den installationen krypterade den med, inte den nya nyckeln från `keygen` ovan, som inte kan dekryptera den. Nyckeln läses från `SIDEKICK_BACKUP_ENCRYPTION_KEY` i `selfhost.env` (eller från `--key-file` nedan); en okrypterad `.json`-export behöver ingen nyckel. Utan omslaget kör du kommandot själv och tillämpar i ett andra steg med den checksumma planen skrev ut
(`FILE` som `-` läser standard in; `--key-file PATH` läser nyckeln från en fil med läge 600 i stället för från
miljön):

```bash
sidekick-backup import FILE --target-owner UUID [--source-owner UUID]
sidekick-backup import FILE --target-owner UUID [--source-owner UUID] --apply --plan-checksum SHA256
```

**Återställ hela databasen** från en ögonblicksbild som en uppdatering tog (till exempel efter en dålig
migrering). Ögonblicksbilden är en `pg_dump -Fc`-fil där ägarna ingår, så ingen reparation behövs efteråt.
Den gamla databasen byter namn och raderas inte:

```bash
(umask 077; ./update.sh --decrypt-snapshot update-state/snapshots/<file>.dump.enc > snapshot.dump)
# Ögonblicksbilden är från före uppdateringen, så starta imagen som kördes då, inte den nya i release.env.
# update.sh skriver den i journalen när uppdateringen startar; release.env är inte tillförlitlig här, för efter en
# misslyckad migrering har den inte skrivits om än och kan peka på imagen före den föregående.
PREV="$(grep ' STARTED ' update-state/journal.log | tail -n 1 | sed -n 's/.* previous=\([^ ]*\).*/\1/p')"
export SIDEKICK_API_IMAGE="${PREV:-roadlake-sidekick:selfhost}"
C="docker compose --env-file selfhost.env"        # ingen release.env här
$C --profile backup --profile push --profile memory stop api automation-worker backup push memory-worker
PG="$C exec -T postgres psql -U postgres -v ON_ERROR_STOP=1 -q"
$PG -d postgres -c "ALTER DATABASE sidekick RENAME TO sidekick_before_restore"
$PG -d postgres <<'SQL'
CREATE DATABASE sidekick;
GRANT CONNECT ON DATABASE sidekick TO sidekick_migrator, sidekick_app;
GRANT CREATE ON DATABASE sidekick TO sidekick_owner;
SQL
$PG -d sidekick -c "GRANT CREATE, USAGE ON SCHEMA public TO sidekick_migrator"
$C exec -T postgres pg_restore -U postgres -d sidekick --exit-on-error --single-transaction < snapshot.dump
$C --profile vps up -d                                            # med de profiler du använder
```

När den återställda installationen svarar: låt filerna stämma med den. `release.env` går tillbaka till den
föregående imagen (filen tas bort om det var ett lokalt bygge), och journalen antecknar återställningen så att
nästa uppdatering tillåts:

```bash
case "$PREV" in *@sha256:*) printf 'SIDEKICK_API_IMAGE=%s\n' "$PREV" > release.env ;; *) rm -f release.env ;; esac
echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) ROLLED_BACK manual-restore" >> update-state/journal.log
```

Om ett steg misslyckas: släpp den nya databasen och ge `sidekick_before_restore` tillbaka sitt namn. När den
återställda installationen fungerar frigör `$PG -d postgres -c "DROP DATABASE sidekick_before_restore"`
utrymmet. Den dekrypterade `snapshot.dump` innehåller all din data i klartext. Den skrevs så att bara du kan
läsa den, så radera den (eller lägg den på krypterad lagring) när du är klar. Återställningskommandona har
körts mot en tillfällig PostgreSQL som sattes upp med `postgres-init.sh`; resultatet hade samma ägare och
rättigheter som originalet. En ögonblicksbild är en dump av ett enda ögonblick: volymen `state` (lagringen av
OAuth-klienter) ingår inte, och inloggade klienter kan behöva logga in igen.

**Hindsight-minnet** ingår inte i någon av kopiorna ovan. Arkivera det för hand genom att stoppa Hindsight en stund och
packa volymen med tar från den låsta imagen själv. Arkivet är inte krypterat: det innehåller hela minnet i klartext och
skrivs därför läsbart bara för dig (`umask 077`); förvara det på krypterad lagring. `tools/work.sh backup` (jobbpaketet)
gör samma kopia men krypterar den med egen nyckel, som `hindsight-<tid>.tar.gz.enc`, så använd den om du kör jobbpaketet:

```bash
C="docker compose --env-file selfhost.env --profile memory"
$C stop hindsight
(umask 077; docker run --rm --network none -v sidekick_hindsight_pg0:/src:ro \
  --entrypoint tar "$($C config --images | grep vectorize-io/hindsight)" -C /src -czf - . > hindsight-$(date +%Y%m%d).tar.gz)
$C up -d hindsight
```

För att återställa arkivet: stoppa allt som använder minnet, töm volymen och packa upp arkivet i den med samma låsta
image, och starta sedan igen. Kontrollera att `docker volume ls` visar `sidekick_hindsight_pg0` och att imagen som det
första kommandot skriver ut är den Hindsight-image du kör; steget som tömmer och packar upp raderar det som ligger i
volymen:

```bash
C="docker compose --env-file selfhost.env --profile memory"
$C stop api memory-worker hindsight
$C config --images | grep vectorize-io/hindsight
docker run --rm -i --network none -v sidekick_hindsight_pg0:/dst --entrypoint sh \
  "$($C config --images | grep vectorize-io/hindsight)" \
  -c 'find /dst -mindepth 1 -delete && tar -C /dst -xzf -' < hindsight-YYYYMMDD.tar.gz
$C up -d hindsight memory-worker api               # med --profile vps om du använder den
```

Kontrollera att Hindsight blir frisk (`docker compose --env-file selfhost.env --profile memory ps`) och att minnet svarar
i Claude. Den [releaseövningen](../maintainers/release-drill.sv.md) kör båda riktningarna mot en riktig Hindsight-volym (en markörfil i den, inte en minnesbank som läses tillbaka genom Hindsight).
