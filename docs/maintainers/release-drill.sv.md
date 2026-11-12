# Releaseövningen

[English](release-drill.md)

<!-- description: Releaseövningen installerar, uppdaterar, tar backup och återställer i tillfälliga containrar. Den körs inför varje version. -->

Releaseövningen installerar, uppdaterar, tar backup och återställer i tillfälliga containrar. Den körs inför varje version.

En säkerhetskopia som ingen har återställt är ett hopp, inte en säkerhetskopia. Arbetsflödet
`.github/workflows/release-drill.yml` kör `tools/drill.sh` på en ren runner som grind inför varje release (och vid behov, inte enligt schema): det installerar den
föregående releasen, skriver en markörrad (och en markörfil i Hindsight-volymen), uppdaterar till den senaste releasen
med den riktiga `update.sh`, kontrollerar att markören finns kvar och att schemaversionen har flyttats, tar en
krypterad säkerhetskopia, raderar alla volymer, återställer från säkerhetskopian och kontrollerar markören igen. En
felaktig eller saknad nyckel ska göra att återställningen stoppas. Stacken körs med profilen `memory` (den riktiga
Hindsight-containern med en modelladress som inte leder någonstans), och dess volym arkiveras och återställs som
[Backup och återställning](../operate/backup-and-restore.sv.md) beskriver. Samma övning täcker jobbpaketet
(`tools/work.sh`: krypterade databas- och Hindsight-kopior med egen nyckel). Arbetsflödet har ett jobb per paket; i
övningen är varje moment ett eget namngivet steg (`install`, `update`, `backup`, `destroy-volumes`, `key-fails-closed`,
`restore`, ...), så ett fel visar vilket som gick sönder (en felannotering och en tabell med stegens tider i
jobbsammanfattningen). Loggen bifogas körningen som artefakten `drill-log-<paket>`.

Sätt repositoryvariablerna `DRILL_FROM_IMAGE`, `DRILL_TO_IMAGE` och `DRILL_CERT_IDENTITY` (samma tre värden som
`update.sh` behöver, se [Uppdatera](../operate/update.sv.md)) för att öva med släppta avbildningar och den riktiga cosign-kontrollen av
signaturen. Utan dem bygger arbetsflödet api-avbildningen två gånger från utcheckningen (`--local-images`), serverar
båda från ett tillfälligt register på runnern för att få riktiga digests och övar med dem; signaturen kontrolleras då
**inte** (cosign är en ersättning) och båda avbildningarna har samma schema, så kontrollen att schemat flyttats hoppas
över.

För att köra den själv, från repositoryts rot (kräver Docker Compose v2.24.4 eller nyare och `cosign`):

```bash
bash tools/drill.sh selfhost --from-image ghcr.io/<owner>/roadlake-sidekick@sha256:<digest> --to-image ghcr.io/<owner>/roadlake-sidekick@sha256:<digest> --cert-identity <signer identity>
bash tools/drill.sh all --local-images   # ingen release behövs; bygger avbildningen från utcheckningen, cirka 15 minuter
bash tools/drill.sh all --dry-run
```

En lokal körning skapar bara compose-projekt som heter `sk-drill-*`, med egen temporär katalog, slumpade portar på
`127.0.0.1` och genererade hemligheter. Den rör aldrig din installation och tar bort allt den skapade när den slutar,
också vid Ctrl-C (`--local-images` tar också bort avbildningarna den byggde). `--dry-run` använder en låtsas-`docker` och
startar ingenting. En hel körning på en bärbar dator med `--local-images` och båda paketen tar cirka 15 minuter; de
längsta stegen är jobbpaketets `update` och `backup` (cirka 2,5 minuter vardera, Hindsight stoppas under kopieringen)
och dess `restore`.
