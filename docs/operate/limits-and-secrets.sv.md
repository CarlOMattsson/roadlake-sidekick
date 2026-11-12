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
