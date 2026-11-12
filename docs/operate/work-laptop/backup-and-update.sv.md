# Säkerhetskopia och uppdatering

[English](backup-and-update.md)

<!-- description: Ta krypterade backuper av databasen och minnet på jobbdatorn, uppdatera, och gå tillbaka om en uppdatering misslyckas. -->

Ta krypterade backuper av databasen och minnet på jobbdatorn, uppdatera, och gå tillbaka om en uppdatering misslyckas.

Med minnet på (`SIDEKICK_WORK_MEMORY=on` i `work.env`) sparar `bash tools/work.sh backup` i `deploy/work/backups/` två filer med samma tidsstämpel: databasdumpen
(`sidekick-<tid>.sql.enc`) och Hindsights minne (`hindsight-<tid>.tar.gz.enc`). Med minnet av (`SIDEKICK_WORK_MEMORY=off`, förvalet, se [När minnet är av](#när-minnet-är-av)) sparas bara den första filen. **Båda är krypterade** (se
[Säkerhetskopians nyckel](#säkerhetskopians-nyckel)); ingen klartextdump eller klartextarkiv skrivs någonsin till disk. Hindsight lagrar minnet i en inbyggd Postgres i
volymen `hindsight_pg0`. För att de två kopiorna ska hänga ihop med varandra pausas först `api`, `memory-worker` och `automation-worker`, och de
startas igen när båda kopiorna är klara (även om säkerhetskopian misslyckas eller avbryts). En kopia av levande databasfiler hänger inte ihop, så Hindsight stoppas några sekunder medan
volymen arkiveras (med `tar` från den fastnålade Hindsight-avbildningen, utan nät, med skrivskyddad montering) och
startas sedan igen. De sju senaste av varje slag sparas (`SIDEKICK_WORK_KEEP_BACKUPS` ändrar antalet; minst 1); filerna är dessutom läsbara bara för dig (600).
Innan något pausas kontrollerar `backup` (och `update` och `restore --apply`, som tar en) att `deploy/work/backups/` har
plats för en ny uppsättning: den senaste uppsättningens storlek gånger `SIDEKICK_BACKUP_SPACE_MARGIN_PCT` (förval 150, minst 100) och minst
`SIDEKICK_BACKUP_SPACE_FLOOR_MB` (förval 64 MiB). Är det för lite plats, eller går det lediga utrymmet inte att läsa, vägrar kommandot med ett
tydligt fel och ändrar inget. Gallringen körs först efter att den nya uppsättningen lästs tillbaka, tar aldrig bort den
uppsättningen eller den senaste färdiga, och rör bara filer som heter exakt `sidekick-<tid>.sql.enc` och `hindsight-<tid>.tar.gz.enc`. En säkerhetskopia räknas först när
den har **lästs tillbaka**: `backup` avkrypterar varje fil igen, kontrollerar att dumpen slutar med pg_dumps
slutmarkering och att arkivet går att lista och inte är tomt, och rapporterar den först därefter. En fil som inte klarar
kontrollen tas bort och kommandot misslyckas (skrivarna och Hindsight startas igen).

## När minnet är av

`SIDEKICK_WORK_MEMORY=off` är förvalet. Då körs varken Hindsight eller minnesarbetaren och det finns ingen Hindsight-volym att säkerhetskopiera:
`backup` skriver "Minnet är av; bara databasen säkerhetskopieras." och sparar bara `sidekick-<tid>.sql.enc`, och under tiden pausas bara `api`
och `automation-worker`. `restore` behöver då bara den filen: det letar inte efter eller rör något minnesarkiv och planen markerar minnet
som av (en säkerhetskopia som också har en minnesfil återställs utan den). Slår du på minnet senare
(`bash tools/work.sh setup`, eller `SIDEKICK_WORK_MEMORY=on` plus modellserverns inställningar i `work.env`, sedan `start`) **börjar det tomt**:
inget byggs upp i efterhand från tiden det var av, och en databaskopia från den tiden innehåller inget minne. En `work.env` från före
inställningen saknar raden och behåller minnet på.

## Säkerhetskopians nyckel

Säkerhetskopiorna krypteras med Fernet (autentiserad kryptering) av samma mekanism som de krypterade databas-ögonblicksbilderna i
en egen installation (`deploy/selfhost/update.sh`), körd i en engångscontainer av Sidekick-avbildningen
(`deploy/selfhost/snapshot_crypto.py`). Nyckeln är **en egen**: inte `SIDEKICK_BACKUP_ENCRYPTION_KEY` i en egen
installation och inte en hemlighet i den körande stacken.

- **Var den ligger.** Första `backup` skapar `deploy/work/secrets/backup.key` (läge 600, katalogen 700) och skriver ut
  sökvägen. Innehållet skrivs aldrig ut eller loggas, och det når containern via miljön, inte via en kommandorad. Nyckeln
  ligger med avsikt utanför `deploy/work/backups/`; kommandot vägrar en nyckelfil inne i säkerhetskopiornas katalog.
  `SIDEKICK_WORK_BACKUP_KEY_FILE=/sökväg/till/nyckel` lägger den någon annanstans, till exempel på ett monterat
  nyckellager.
- **Kopiera den bort från datorn, skild från säkerhetskopiorna.** Kopiera nyckeln direkt efter första säkerhetskopian till
  en plats som varken är den här datorn eller ligger bredvid kopiorna: en lösenordshanterare eller ett USB-minne som
  förvaras separat. En säkerhetskopia på samma plats som sin nyckel skyddar inget, och en nyckel som bara finns på den här
  datorn försvinner med datorn.
- **Förlorad nyckel betyder förlorade säkerhetskopior.** Utan nyckeln går de inte att återskapa: filerna är autentiserad
  chiffertext. `stop --purge` raderar `deploy/work/secrets/` och alltså nyckeln tillsammans med säkerhetskopiorna.
- **Stänger säkert.** `backup` och `restore` avbryter innan något ändras om nyckelfilen saknas eller inte innehåller en
  giltig nyckel. Finns krypterade säkerhetskopior men nyckeln är borta skapar `backup` **ingen** ny nyckel (de gamla
  kopiorna skulle då bli oläsliga): lägg tillbaka nyckeln från din kopia. Bara när ingen krypterad säkerhetskopia finns
  skapas en ny nyckel.
- **Nyckelbyte.** Ta först en säkerhetskopia, flytta sedan `deploy/work/secrets/backup.key` och de gamla filerna åt sidan
  (behåll dem tills de nya är kontrollerade), kör `backup` för en ny nyckel och nya filer och kopiera den nya nyckeln bort
  från datorn. Gamla kopior går bara att återställa med den gamla nyckeln: behåll den gamla nyckeln och de gamla filerna
  tillsammans, eller radera båda. Byt nyckel när någon annan kan ha sett den.
- **Kopior från före krypteringen** (`sidekick-<tid>.sql`, `hindsight-<tid>.tar.gz`) är klartextfiler, listas och
  återställs inte av `restore` och innehåller fortfarande all din data i klartext: radera dem när en kontrollerad krypterad
  säkerhetskopia finns.
- **Minne.** Krypteringen håller hela filen i minnet medan den arbetar, samma gräns som för ögonblicksbilderna i en egen
  installation; det går bra för en bärbars databas och minne, men inte för flera gigabyte.

Om `docker compose ps` inte kan avgöra vilka skrivare som körs, eller om någon av dem fortfarande körs efter stoppet,
avbryter säkerhetskopian innan något kopieras. Kommandona som ändrar stacken (`setup`, `init`, `start`, `stop`,
`backup`, `update` och `restore --apply`) delar ett lås (`deploy/work/.work.lock`, eller katalogen
`deploy/work/.work.lock.d` där `flock` saknas, som på macOS): medan ett av dem kör nekas ett andra med "pågår redan"
och ändrar ingenting. `status` och provkörningen av `restore` tar inget lås. Ett lås som lämnats kvar av ett kommando
som inte längre kör tas över automatiskt.

`bash tools/work.sh update` kräver att repot är **klonat med git** (`git clone`), inte nedladdat som zip: koden hämtas med `git pull --ff-only`. Ordningen är byggd så att skrivarna står stoppade så kort tid som möjligt:

1. Först sparas avbildningen som körs nu under taggen `roadlake-sidekick:previous`, koden hämtas och migreringarna den förde med sig kontrolleras, som `deploy/selfhost/update.sh` gör med klassetiketten på sin avbildning: `tools/check-release-migration-class.py` jämför dem med den commit du stod på, och en ny migrering som den gamla koden inte kan köras mot (`DROP`, `RENAME`, typbyte på kolumn, `SET NOT NULL`, `REVOKE` eller markören `migration-class: contract`) gör att `update` vägrar, lägger tillbaka koden på din commit och inte ändrar något annat (inget stoppas och ingen säkerhetskopia tas). `bash tools/work.sh update --allow-breaking-migration` godtar en sådan migrering; att gå tillbaka efteråt betyder då att återställa den säkerhetskopia som kommandot tar (nedan).
2. Därefter hämtas fastnålade avbildningar och Sidekick byggs. Inget av det rör data, och den körande stacken fortsätter köra under tiden.
3. Först nu stoppas `api`, `memory-worker` och `automation-worker` och samma `backup` tas med dem stoppade, så att ingen skrivning hamnar mellan säkerhetskopian och migreringen; misslyckas någon av kopiorna migreras inget och de stoppade tjänsterna startar igen från den föregående avbildningen.
4. Skrivarna förblir stoppade medan migreringen körs med den nya avbildningen, `api` startas ensamt och kommandot väntar tills det är redo (databasen svarar och schemat ligger på den nya avbildningens revision, inte bara att containern är uppe); först då startar arbetarna, och kontrollen görs igen.
5. Sist skrivs Claude Desktop-inställningen om och tid och commit skrivs till `deploy/work/generated/build-info.json`.

Filen skapas redan av `init` och `start`, visas av `status`, monteras skrivskyddat i api-containern som `/etc/sidekick/build-info.json` och pekas ut av `SIDEKICK_BUILD_INFO_FILE`, så att gränssnittets påminnelse om uppdatering räknar från första dagen (`SIDEKICK_UPDATE_REMINDER_DAYS`, 14 som förval).

Vad som händer vid fel beror på om migreringen har påbörjats. **Före den** (hämtningen, migreringskontrollen, bygget eller säkerhetskopian misslyckas, eller du avbryter) läggs koden tillbaka på din commit, den föregående avbildningen läggs tillbaka under sitt namn och, om säkerhetskopian hade stoppat dem, startar tjänsterna igen från den; databasen rördes inte. Ett fel före stoppet ändrar inget i den körande stacken. **Från migreringen och framåt** lämnas skrivarna stoppade och inget återställs automatiskt, eftersom databasens tillstånd är osäkert; meddelandet anger säkerhetskopian och kommandot för att titta på den (`bash tools/work.sh restore <tid>`, först utan `--apply`).

## Gå tillbaka efter en misslyckad uppdatering

Om migreringen, omstarten eller beredskapskontrollen misslyckas lämnar `update` skrivarna stoppade och rullar inget tillbaka. Den skriver vilken commit du stod på
(`<före>`) och vilken den gick till (`<efter>`), kommandot för att gå tillbaka och var säkerhetskopiorna ligger; de togs
innan något ändrades. Att gå tillbaka är två skilda frågor, koden och databasen.

1. **Kom uppdateringen med migreringar?** `git diff --stat <före> <efter> -- migrations`.
   - Ingen utskrift: schemat ändrades inte. `git checkout <före> && bash tools/work.sh start --build` räcker
     (`git checkout <din gren>` senare, för att följa uppdateringar igen).
   - Filer listas: den nya koden migrerade databasen när stacken kom upp, och den gamla koden kanske inte fungerar mot
     det migrerade schemat (paketet märker inte migreringar som säkra att gå tillbaka över). Checka ut `<före>` och kör
     `bash tools/work.sh start --build` så att den gamla avbildningen byggs (stacken blir kanske inte frisk mot det
     migrerade schemat; det är väntat här), och återställ sedan säkerhetskopian som den här uppdateringen tog (nedan),
     så att kod och data hör ihop. `restore` kör den gamla avbildningens migrering på den återställda datan.
2. Om `start --build` av den gamla koden går och `bash tools/work.sh status` är frisk är du klar. Inget behöver
   återställas när databasen inte migrerats eller skadats.

## Återställa från en säkerhetskopia

`backup` skriver `sidekick-<tid>.sql.enc` (vanlig SQL gjord med `pg_dump --no-owner`, sedan krypterad) och
`hindsight-<tid>.tar.gz.enc` (volymen som `tar.gz`, sedan krypterad), en **säkerhetskopia** per tidsstämpel. `restore`
behöver samma nyckel (`deploy/work/secrets/backup.key`) och avkrypterar på vägen in i Postgres och i volymen: ingen
klartextfil skrivs. En säkerhetskopia återställs bara hel, eftersom Sidekicks databas bokför vilka källor
som skickats till Hindsight och Hindsight håller själva minnena. Säkerhetskopiorna innehåller inga lösenord och
hemligheterna i `deploy/work/secrets/` ingår inte: rollerna och deras lösenord hör till Postgres-volymen, så en
återställning fungerar med de hemligheter som den körande stacken har. Ägaren `jobb` ingår i dumpen.

```bash
bash tools/work.sh restore                          # listar de kompletta säkerhetskopiorna i deploy/work/backups/
bash tools/work.sh restore 20261110-142500          # provkörning: kontrollerar kopian och visar planen, ändrar inget
bash tools/work.sh restore 20261110-142500 --apply  # återställer; ber dig skriva projektets namn (sidekick-work)
```

I stället för en tidsstämpel kan du ange sökvägen till någon av kopians två filer, till exempel en kopia som flyttats
från en annan dator. Utan `--apply` läser kommandot bara: det kontrollerar att båda filerna finns, att nyckeln finns, att båda filerna går
att avkryptera med den, att dumpen är hel (den slutar med pg_dumps slutmarkering), att arkivet går att läsa och inte är
tomt och att minnesvolymen finns, och visar planen. Med `--apply` gör det ingenting förrän du skrivit projektets namn, och sedan:

1. tar det en färsk säkerhetskopia av det som finns nu till `deploy/work/backups/` (vägen tillbaka; inget rensas bort),
2. pausar `api`, `memory-worker` och `automation-worker` (det avslutar också Claude Desktops session),
3. döper om databasen `sidekick` till `sidekick_before_restore_<tid>` (den behålls och raderas inte), skapar en ny
   `sidekick` med de behörigheter paketets rollbootstrap ger, läser in dumpen i en enda transaktion och ger varje objekt
   tillbaka sin ägare (`deploy/selfhost/restore-ownership.sql`; utan det kunde migreringsrollen inte ändra tabellerna vid
   en senare uppdatering),
4. stoppar Hindsight, tömmer dess volym och packar upp arkivet i den (utan nät, med den fastnålade Hindsight-avbildningen),
5. kör migreringen, så att en kopia från äldre kod lyfts till schemat för avbildningen du kör,
6. startar Hindsight och skrivarna, väntar tills api:t är redo (databasen svarar och schemat ligger på avbildningens
   revision), pekar Claude Desktop-inställningen på den återställda `jobb`-användaren och skriver om den.

**När något går fel.**

- Kopian saknar en fil, nyckeln saknas eller är fel, en fil är skadad eller ändrad (krypteringen är autentiserad, så
  en enda ändrad bit vägras), dumpen är avklippt, arkivet är trasigt eller tomt, minnesvolymen finns inte (kör `start`
  först) eller du skriver inte projektets namn: kommandot avbryter och inget ändras.
- Ett annat ändrande kommando (till exempel `start`, `backup` eller `update`) kör: `restore` nekas och inget ändras.
  Kör det igen när det andra är klart.
- Den färska säkerhetskopian i steg 1 misslyckas, `docker compose ps` kan inte avgöra vilka skrivare som körs, eller
  en skrivare körs fortfarande efter stoppet: det avbryter innan något ändrats, och skrivarna det stoppade startas igen.
- Steg 3, 4 eller 5 misslyckas, eller kommandot avbryts (Ctrl-C, en stängd terminal) under dem: minnet packas upp igen
  från den färska säkerhetskopian i steg 1, den nya databasen släpps och `sidekick_before_restore_<tid>` får tillbaka sitt
  gamla namn, och sedan startar Hindsight och skrivarna. Meddelandet säger "Det som fanns före är tillbaka". Det gäller
  också när avbrottet kommer direkt efter omdöpningen: tillbakaläggningen frågar Postgres vilka av de två namnen som
  finns, så den blir rätt oavsett om omdöpningen hann köras, och att köra den två gånger ändrar ingenting.
- Även tillbakaläggningen misslyckas: inget startas (memory-worker skulle annars starta Hindsight på en volym i okänt
  skick). Meddelandet anger loggen (`deploy/work/work.log`), den förra databasens namn och den färska säkerhetskopian.
  Läs loggen och återställ sedan den färska kopian med `restore <dess tid> --apply`; om databasen inte döpts tillbaka,
  gör det först:
  `docker exec sidekick-work-postgres-1 psql -U postgres -d postgres -c "DROP DATABASE IF EXISTS sidekick" -c "ALTER DATABASE sidekick_before_restore_<tid> RENAME TO sidekick"`.
- Tjänsterna startar inte eller api:t blir inte redo efter steg 6: inget rullas tillbaka, eftersom tjänsterna redan har
  kört mot den återställda datan. Den förra databasen och den färska säkerhetskopian behålls och nämns i meddelandet;
  läs loggen och återställ den färska kopian om du vill gå tillbaka.

När allt gick bra: be i Claude Desktop om något du vet finns i det återställda. När du är säker frigör du utrymmet med
kommandot som återställningen skriver ut:
`docker exec sidekick-work-postgres-1 psql -U postgres -d postgres -c "DROP DATABASE sidekick_before_restore_<tid>"`.

På en ny dator: kör först `setup` eller `init` och `start` (de skapar rollerna, en ny `jobb`-användare och
minnesvolymen), kopiera dit säkerhetskopian **och säkerhetskopians nyckel** (lägg nyckeln i `deploy/work/secrets/backup.key`) och kör
`restore <sökväg till kopians .sql.enc-fil> --apply`. Claude
Desktop-inställningen skrivs om för den återställda `jobb`-användaren; lägg in den igen som i steg 4 under [Steg](../../start/work-laptop.sv.md#steg).
