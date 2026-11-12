# Flytta data mellan installationer

[English](move-data.md)

<!-- description: Flytta dina poster från en installation av 0.1.0 till en annan, till exempel till en ny server. Data från installationer före 0.1.0 går inte att importera. -->

Flytta dina poster från en installation av 0.1.0 till en annan, till exempel till en ny server. Data från installationer före 0.1.0 går inte att importera.

## Flytta din data mellan 0.1.0-installationer

Använd detta för att flytta till en ny server eller en ny databas. Källan måste vara en 0.1.0-installation som har en
ägarbackup (`sidekick-backup create`, eller backupprofilen) eller kan göra en ägarexport. Importen läser bara det
nuvarande formatet (format 5), som bara 0.1.0 skriver, och formatet före det (format 4, skrivet vid baslinjens huvud). Det finns inget stött sätt att
importera data från en installation före 0.1.0: backuper, exporter, ögonblicksbilder och SQL-dumpar från före 0.1.0
läses inte, och `sidekick-backup import` kan inte importera dem. Behåll dem som arkiv.

1. **Gör en sista backup i den gamla 0.1.0-installationen** och håll nyckelfilen privat.
2. **Starta den nya installationen** från en tom databas ([självhostad uppsättning](../start/self-hosted-server.sv.md)).
   Migreraren skapar baslinjen.
3. **Skapa ägaren** i den nya installationen: `sidekick-admin create-user --login LOGIN --display-name NAME`. Använd samma GitHub-id som förut om du loggar
   in via GitHub.
4. **Importera.** Ange nyckeln som backupen krypterades med, som `SIDEKICK_BACKUP_ENCRYPTION_KEY` i miljön eller med `--key-file FILE` (läge 600). En nyckel som skapats för den nya installationen kan inte dekryptera den gamla backupen. Först planen, som inte skriver något, sedan samma plan tillämpad med sin kontrollsumma (`deploy/selfhost/restore.sh --backup FILE --target-owner UUID [--source-owner UUID]`, sedan med `--apply`). En okrypterad `.json`-ägarexport behöver ingen nyckel. Antal per samling kontrolleras efter skrivningen.
   Utan omslaget, i utvecklingsstacken: `uv run --project backend sidekick-backup import FILE --target-owner UUID` skriver ut planen med dess `plan_checksum`; kör sedan samma kommando med `--apply --plan-checksum SHA` och den checksumman.
5. **Kontrollera resultatet**: öppna rummen Arbete och Dagbok i Claude och jämför med de antal som importen skrev ut.

Det som inte finns i en ägarbackup och därför måste göras om: personliga åtkomsttoken, OAuth-registreringar och token,
parade telefoner, push-registreringar, licensraden, driftlås och härledd minnesmetadata. Post-id mappas om till nya id,
så id som klistrats in i gamla konversationer pekar inte längre på något. Minnet byggs om av minnesarbetaren utifrån de
importerade posterna.

## Storleksgräns för de krypterade databassnapshotarna

De krypterade databassnapshots som `update.sh` tar (och arbetspaketets backuper, som använder samma
`deploy/selfhost/snapshot_crypto.py`) krypteras med Fernet, som inte är ett strömmande format: hela dumpen hålls i
minnet. Taket är **512 MiB klartext** (dumpen som pg_dump skriver den, före kryptering). En större dump nekas med
`backup encrypt refused: input is over the 512 MiB ceiling`, ingenting skrivs, och uppdateringen eller backupen stoppar
innan den ändrat något. Avkrypteringen har motsvarande tak för den krypterade filen. Ligger din dump nära gränsen:
rensa först i databasen, eller ta din backup med ett verktyg som strömmar, utanför Sidekick.
