# Resursgränser och hemligheter per container

[English](limits-and-secrets.md)

<!-- description: Vilka minnes- och processgränser varje självhostad container har, hur du ändrar dem och vilka inställningar varje container får. -->

Vilka minnes- och processgränser varje självhostad container har, hur du ändrar dem och vilka inställningar varje container får.

## Resursgränser

Varje container i bastacken och i profilerna `memory`, `backup` och `push` har ett minnestak och en processgräns (`mem_limit` och `pids_limit` i `compose.yaml`). De hindrar en skenande process från att dra ner hela värden. Minnesvärdet är ett tak, inte en reservation. En container som går över det dödas och startas om av Docker; `docker inspect <container>` visar då `OOMKilled`.

| Tjänst | Minne | Processer | Variabelprefix |
| --- | --- | --- | --- |
| `postgres` | 1g | 256 | `SELFHOST_POSTGRES_` |
| `migrate` | 512m | 64 | `SELFHOST_MIGRATE_` |
| `api` | 3g | 256 | `SELFHOST_API_` |
| `automation-worker` | 512m | 64 | `SELFHOST_AUTOMATION_` |
| `backup` | 3g | 64 | `SELFHOST_BACKUP_` |
| `push` | 512m | 64 | `SELFHOST_PUSH_` |
| `memory-worker` | 512m | 64 | `SELFHOST_MEMORY_` |
| `hindsight` | 4g | 512 | `SELFHOST_HINDSIGHT_` |

Den egna `ntfy`-servern behåller sina fasta gränser (128m, 64 processer).

För att ändra en lägger du `SELFHOST_<TJÄNST>_MEM_LIMIT` eller `SELFHOST_<TJÄNST>_PIDS_LIMIT` i `selfhost.env` (de bortkommenterade raderna i `selfhost.env.example` listar alla), till exempel `SELFHOST_HINDSIGHT_MEM_LIMIT=6g`, och startar tjänsten igen med `docker compose --env-file selfhost.env up -d`. Namnen börjar inte på `SIDEKICK_`, så API:et godtar dem i samma fil.

Varför `backup` och `api` har 3g: en backup håller en hel ägarexport i minnet, högst 512 MiB klartext, och krypteringen har flera kopior av den levande samtidigt (texten, byten, det utfyllda blocket och token, som är ungefär en tredjedel större i base64). `update.sh` och `restore.sh` kör ögonblicksbildskrypteringen och backupimporten som engångscontainrar av tjänsten `api`, så `api` behöver samma utrymme. En vanlig installation använder en liten del. Sänk de två värdena bara på en liten värd med en liten databas, och höj dem om en backup eller en uppdatering slutar med `Killed` eller felkod 137.

Värdet för `hindsight` är en uppskattning, inte en mätning: de lokala inbäddnings- och omrankningsmodellerna körs i den.

## Vilka inställningar varje container får

:::caution[Ange alltid `--env-file selfhost.env`]
Varje `docker compose`-kommando behöver `--env-file selfhost.env`: `up`, `restart`, `run`, och kommandona i egna systemd-enheter eller skript också. Workers läser inte längre `selfhost.env` själva. Utan flaggan startar de utan databas-URL och kraschar i en omstartsloop medan `api` fortsätter köra, så felet är lätt att missa. Kontrollera med `docker compose --env-file selfhost.env ps`.
:::

`selfhost.env` innehåller alla inställningar, men en container får bara de som dess process läser.

- `api` läser hela `selfhost.env`. Det är den enda processen som behöver GitHub-inloggningens inställningar, rummen och begäransgränserna. Den får aldrig `db.env`.
- `automation-worker`, `backup`, `push` och `memory-worker` får en namngiven lista med inställningar, hämtade ur `--env-file selfhost.env` i kommandot. De har ingen `env_file`. Varje worker får databas-URL:en, de två signeringshemligheterna, tidsbudgetarna och tidszonen, eftersom produktionsläget vägrar starta utan dem.
- Bara `backup` får `SIDEKICK_BACKUP_ENCRYPTION_KEY` och retentionsinställningarna. Bara `push` får `SIDEKICK_PUSH_AUTH_TOKEN`. Minnestoken och nyckeln som härleder minnes-id går till `memory-worker` och till `automation-worker`, eftersom den senare bygger samma container som API:et.
- Ingen worker får GitHub-klienthemligheten, OAuth-signeringsnyckeln, de tillåtna identiteterna eller scopes.
- `postgres` och `migrate` läser `db.env`. `hindsight` läser `hindsight.env`. `ntfy` läser `ntfy.env`. Ingen annan tjänst läser de filerna. `migrate` får fortfarande hela `db.env`, med PostgreSQL-superanvändarens lösenord, fast den bara behöver migreringsadressen. Det är en engångscontainer utan väg ut på internet.

Praktiska följder:

- Kör alltid `docker compose` med `--env-file selfhost.env`, som alla guider gör. Utan den startar en worker utan databas-URL och stannar med ett fel i stället för att köra på förval.
- En inställning som bara API:et läser (till exempel `SIDEKICK_MCP_OAUTH_SCOPES`) gäller efter att du startat om `api`; workers behöver den inte.
- En ny `SIDEKICK_`-inställning som en worker ska läsa måste läggas till i listan i `compose.yaml`. Testet `backend/tests/selfhost/test_selfhost_secret_scope.py` kontrollerar att varje listat namn är en deklarerad inställning.
- Arbetspaketet (`tools/work.sh`) påverkas inte: det ersätter listorna med sina egna hemlighetsfiler.

## Hemligheter som filer

En hemlighet i `selfhost.env` är en miljövariabel i containern: varje process i den kan läsa den, och `docker inspect` skriver ut den. Som fil monteras den skrivskyddad på `/run/secrets/<namn>`, bara i de tjänster som läser den (samma listor som ovan), och `docker inspect` visar sökvägen men inte värdet. De nio hemliga inställningarna kan flyttas på det sättet:

`SIDEKICK_DATABASE_URL`, `SIDEKICK_CURSOR_SIGNING_SECRET`, `SIDEKICK_TOKEN_PEPPER`, `SIDEKICK_MCP_OAUTH_GITHUB_CLIENT_SECRET`, `SIDEKICK_MCP_OAUTH_SIGNING_KEY`, `SIDEKICK_MEMORY_HINDSIGHT_API_TOKEN`, `SIDEKICK_MEMORY_ID_DERIVATION_KEY`, `SIDEKICK_BACKUP_ENCRYPTION_KEY` och `SIDEKICK_PUSH_AUTH_TOKEN`.

Befintliga installationer fungerar oförändrat: en vanlig variabel läses fortfarande. Flytta värdena när det passar:

```sh
cd deploy/selfhost
sh secrets-to-files.sh --dry-run   # visar vad som skulle flyttas, ändrar ingenting
sh secrets-to-files.sh             # flyttar
docker compose --env-file selfhost.env up -d
```

För varje hemlighet som har ett riktigt värde i `selfhost.env` skriver skriptet det till `secrets/<namn>`, läser tillbaka filen och jämför, och först därefter tar det bort raden `SIDEKICK_<NAMN>=` och lägger till `SELFHOST_<NAMN>_FILE=./secrets/<namn>`. Det skriver aldrig ut ett värde och skickar aldrig ett på en kommandorad. Det lämnar en hemlighet kvar, med en notering, när flytten kan ändra dess betydelse: värdet är fortfarande en platshållare, är satt två gånger eller har ett tecken som Compose behandlar speciellt (citationstecken, mellanslag, `$`, `#`, omvänt snedstreck). Flytta de för hand: skriv exakt värde och en radbrytning till filen, ta bort raden `SIDEKICK_<NAMN>=` och lägg till raden `SELFHOST_<NAMN>_FILE=`. Kör skriptet igen efteråt; det som redan är flyttat rörs inte. `update.sh` godtar en backupnyckel som ligger i en fil.

Så fungerar det:

- `compose.yaml` monterar varje fil som en Docker-secret och sätter `SIDEKICK_<NAMN>_FILE=/run/secrets/<namn>` i de tjänster som läser den, men bara medan `SELFHOST_<NAMN>_FILE` är satt. Utan den är hemligheten en tom `/dev/null`-montering och backend ignorerar den tomma variabeln.
- Backend läser filen som `SIDEKICK_<NAMN>_FILE` pekar på för var och en av de nio inställningarna (de som är markerade som hemliga i [konfigurationsreferensen](../reference/configuration.md)), tar bort den avslutande radbrytningen och validerar värdet som vilket annat. En saknad, oläsbar, tom, icke-UTF-8-fil eller en för stor fil stoppar starten med ett fel som nämner variabeln, aldrig innehållet.
- Om både `SIDEKICK_<NAMN>` och `SIDEKICK_<NAMN>_FILE` är satta stoppas starten med ett fel. Ett tomt `SIDEKICK_<NAMN>` räknas inte som satt. `SIDEKICK_<NAMN>_FILE` läses bara ur processmiljön, inte ur en `.env`-fil.
- Katalogen `secrets/` har läge 700 och filerna läge 644, inte 600. Compose bind-monterar en filhemlighet som den är på värden och ignorerar `uid`, `gid` och `mode`, och containerns användare är inte du, så en fil med läge 600 går inte att läsa i containern. Katalogen är det som håller andra användare på värden ute. Den är gitignorerad.
- Ta backup på `secrets/` tillsammans med `selfhost.env` och håll båda privata. Förlorar du backupnyckeln går backuperna fortfarande inte att läsa.

`db.env` (PostgreSQL-lösenorden och migreringsadressen), `hindsight.env` och `ntfy.env` är separata filer som andra tjänster läser; de förblir som de är.
