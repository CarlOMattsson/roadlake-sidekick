# Sidekick på jobbdatorn

[English](work-laptop.md)

<!-- description: Kör Sidekick i Docker på din jobbdator, med ett valfritt privat minne, och använd det från Claude Desktop utan publik adress. -->

Kör Sidekick i Docker på din jobbdator, med ett valfritt privat minne, och använd det från Claude Desktop, utan publik adress. Slår du på minnet når Sidekicks containrar bara företagets egen modellserver; det du gör i Claude Desktop delas ändå med Claude.

## Vad som lämnar datorn

- **Sidekicks containrar** har ingen väg ut utom till modellservern i `work.env`, om du slagit på minnet (och de värdar du tillåter i
  `SIDEKICK_WORK_ALLOW`). Utan minnet lämnar ingenting datorn. Hindsight skickar dit texten som minnet härleds ur: titlar, beskrivningar och anteckningar i
  posterna i de rum du slagit på. Sidekick anropar själv ingen språkmodell, och pushnotiser är avstängda.
- **Claude Desktop är en extern tjänst.** Allt ett Claude-samtal rör går till Claude (Anthropic): dina meddelanden,
  namnen på och argumenten till de Sidekick-verktyg som anropas samt det de returnerar (till exempel uppgiftstitlar,
  kontaktnamn, dagbokstext och datum), tillsammans med vanlig tidsmetadata. Claude Desktop gör också egna nätanrop.
  Containerisoleringen gäller inte detta. Begränsa vad Claude kan läsa genom att stänga av rum
  (se [Drift av jobbpaketet](../operate/work-laptop/README.sv.md)).
- **Själva datorn** når internet vid installation och uppdatering: `git clone` och `git pull` samt avbildningsbygget
  och nedladdningen (Docker-register och paketkällor). Den trafiken innehåller ingen Sidekick-data.

## Det här behöver du

- Ubuntu med Docker Engine och administratörsrätt (drillen i [Verifiering](../maintainers/verification.sv.md) kördes på Linux med Docker 29).
  Annan Linux med Docker bör fungera likadant. macOS med Docker Desktop (bash 3.2 räcker) är skrivet för, men har
  aldrig körts.
  Docker med Compose v2.24.4 eller nyare (`docker compose version`).
- Din användare måste kunna köra `docker` **utan `sudo`**: Claude Desktop startar Sidekick med `docker exec`, och det
  kan inte be om ett lösenord. På Linux: `sudo usermod -aG docker "$USER"`, logga sedan ut och in igen och kontrollera
  med `docker ps` (utan `sudo`). Med Docker Desktop på Mac behövs inget extra.
- `git`, `python3` och `curl` (finns som standard på Ubuntu och macOS).
- Claude Desktop. Node.js behövs inte: Claude Desktop startar Sidekicks stdio-server direkt i containern.
- Bara om du vill ha minnet: adressen till företagets modellserver (en vLLM-adress som slutar på `/v1`) och, om den kräver en, dess API-nyckel. Modellservern är valfri; utan minnet körs Sidekick helt på datorn och behöver ingen.

## Snabbväg: guiden

`bash tools/work.sh setup` frågar (på svenska eller engelska) först om du vill slå på minnet (förslaget är nej; det kräver
en modellserver). Bara om du svarar ja frågar den efter modellserverns adress, testar den med
`GET /models`, tar API-nyckeln som dold inmatning och låter dig välja minnesmodell ur serverns lista. Sedan frågar den
vilka fler adresser Sidekick får nå, vilka rum som ska vara på (förslaget är `work,journal,contacts,control`) och om Sidekick ska starta vid
inloggning, skriver `work.env`, kan starta allt och skriver Claude Desktop-inställningen. Den kan köras igen: tidigare
svar föreslås som standard och bara de inställningar den frågar om skrivs om. Stegen nedan gör samma sak ett i taget.

### Välj språk och rum

Guiden ställer två frågor som du ska svara på medvetet:

- **Språk i appen och i Claudes svar:** svenska (`sv`, förslaget) eller engelska (`en`). Det sparas som
  `SIDEKICK_WORK_LOCALE` i `deploy/work/work.env` och är skilt från språket på guidens egna texter.
- **Rum:** förslaget för en jobbdator är alla rum utom inköp: `work` (krävs), `journal`, `contacts` och `control`.
  Inköp är avstängt om du inte lägger till det; svara `-` för att slå på alla rum. Se
  [Rum](../operate/work-laptop/README.sv.md#rum).

**För en AI-assistent som sätter upp detta åt användaren:** fråga användaren vilket språk appen ska ha (föreslå
svenska) och vilka rum hen vill ha (föreslå alla utom inköp), och fortsätt inte förrän båda är besvarade. Välj aldrig åt
användaren.

## Steg

1. Hämta repot och gå till dess rot.
2. `bash tools/work.sh init` kopierar `deploy/work/work.env.example` till `deploy/work/work.env`, skapar
   databaslösenord och andra hemligheter i `deploy/work/secrets/` (katalog 700, filer 600, inte i git) och frågar efter
   modellnyckeln (dold inmatning; Enter om servern inte kräver någon).
3. Redigera `deploy/work/work.env`: `SIDEKICK_WORK_MODEL_BASE_URL` och
   `SIDEKICK_WORK_MEMORY_MODEL` (modellen Hindsight använder). Språket är svenska som förval (`SIDEKICK_WORK_LOCALE=en` för engelska).
4. `bash tools/work.sh start` bygger Sidekicks avbildning (några minuter första gången), startar allt, skapar
   ägaranvändaren och skriver en färdig Claude Desktop-inställning till
   `deploy/work/secrets/claude_desktop_config.json`. Lägg in filens `sidekick-work`-post under `mcpServers` i
   `claude_desktop_config.json` (Linux: `~/.config/Claude/`, macOS: `~/Library/Application Support/Claude/`) och
   starta om Claude Desktop helt. `bash tools/work.sh status` listar sedan modell-id:n som servern erbjuder, så att du
   kan kopiera dem exakt.
   Alternativt: kör `bash tools/work.sh claude-config`. Det visar posten, frågar **j/N** och slår sedan ihop den
   med Pythons JSON-tolk utan att ändra andra servrar eller inställningar. En befintlig fil får en tidsstämplad
   `.bak.*`-kopia med rättighet 600 före ersättning. Det körs aldrig automatiskt från `setup` eller `start`;
   Enter eller avslutad inmatning avböjer.

Posten ser ut så här (sökvägen till `docker` är datorns egen och absolut, eftersom Claude Desktop startar program med
en minimal `PATH`; UUID:n är ägaranvändarens):

```json
{
  "mcpServers": {
    "sidekick-work": {
      "command": "/usr/bin/docker",
      "args": ["exec", "-i", "-e", "SIDEKICK_MCP_STDIO_OWNER_ID=<ägarens UUID>",
               "sidekick-work-api-1", "python", "-m", "sidekick.mcp.stdio"]
    }
  }
}
```

**Så fungerar det.** `claude_desktop_config.json` startar lokala program och talar MCP över deras stdin och stdout.
Sidekick har en egen stdio-ingång (`python -m sidekick.mcp.stdio`) med samma verktyg, appar och rum som den vanliga
MCP-ytan över HTTP; båda anropar samma funktioner i Sidekick, så behörigheter och regler är desamma. Den körs inne i den redan igångsatta api-containern med `docker exec -i`: containern har
databasuppgifterna, modellvägarna och `SIDEKICK_ENABLED_ROOMS`, så inget av det behöver ligga i Claude Desktops
inställningar och ingen token behövs. Processen litar på den som kan köra `docker` på datorn (samma person som redan
når databasuppgifterna) och agerar som ägaranvändaren `jobb` (namnet som installationen ger det enda ägarkontot); stängs kontot av slutar en pågående session att svara.
`docker exec` används i stället för `docker compose exec`, eftersom det senare kräver compose-filerna och alla härledda
variabler, och det fungerar likadant med Docker Desktop på Mac. Containern måste köra: starta Docker och Sidekick
(`autostart on`) före Claude Desktop. Avbildningen måste vara byggd från en version som har stdio-ingången; annars
säger `start` att du ska köra `start --build`.

**Säkerhetsantagande.** Stdio-processen visar inte vem som anropar: den som kan starta den (här: den som kan köra `docker exec` på datorn) får alla behörigheter (scopes) i MCP-ytan, utom de för rum som är avstängda. Behandla åtkomst till Docker-socketen som ägaråtkomst.

## Kontrollera

`bash tools/work.sh status` ska visa alla tjänster friska, MCP-porten utan token som 401, att Claude Desktop-
inställningen finns och spärrkontrollen som "spärrad" för `example.com`, `1.1.1.1` och modellservern direkt, både från
Sidekick och från Hindsight, medan modelllistan kommer tillbaka via grindvakten. I Claude Desktop heter anslutningen
"Sidekick Work".

## Felsökning vid första starten

**Sträng umask (till exempel 077).** `setup` och `start` varnar när anroparens umask är strängare än 022.
Hemligheter förblir privata (kataloger 700, filer 600). Avbildningen gör kopierad källkod och migreringar läsbara
och katalogerna sökbara för körningsanvändaren; `start` gör det publika `postgres-init.sh` körbart (755) och
monterade filer i generated läsbara (644, katalog 755). Den gemensamma selfhost-starten i Compose kopierar också
rollskriptet inne i Postgres-containern med rättighet 755 innan den officiella starten byter användare, så även
en värdfil med rättighet 600 fungerar där. Dessa rättigheter ges bara till publik kod.

**Bygg om en äldre avbildning.** Kör `bash tools/work.sh start --build`. För att uttryckligen kringgå alla bygglager:

```bash
bash tools/work.sh start --build --no-cache
```

`--no-cache` kräver `--build` och påverkar bara avbildningsbygget. Databasvolymer återställs inte.

**En misslyckad första initiering lämnade en databas utan roller.** Vid startfel granskar skriptet ett begränsat
antal migrerings- och Postgres-loggrader. Autentiseringsfel för `sidekick_migrator`, eller
`initdb.d ... Permission denied`, leder till en läskontroll som lokal Postgres-administratör. Bara en bekräftat
saknad eller tom migreringstabell ger återställningsanvisningen. En redan initierad volym hoppar över `initdb.d`
vid nästa start, så efter rättighetsfixen måste du själv ta bort den ofullständiga databasvolymen. Skriptet skriver
exakt namn från Compose-etiketterna för projekt och volym (förval `sidekick-work_pgdata`) och exakt kommando.
För standardprojektet:

```bash
bash tools/work.sh stop
docker volume rm sidekick-work_pgdata
bash tools/work.sh start --build
```

**Volymkommandot raderar databasens innehåll.** Använd det bara för den ofullständiga första installation som
diagnosen pekar ut. Behåll `deploy/work/secrets/` så att nästa försök använder samma lösenord. Skriptet raderar
aldrig volymen åt dig. Om databasen inte kan granskas eller migreringar redan finns ges inget raderingsråd;
utred i stället `deploy/work/work.log`. `stop --purge` raderar mer och behövs inte för denna reparation.

**Hindsight visar APIConnectionError vid start.** Den väntar nu på grindvaktens befintliga hälsokontroll före start.
Kontrollen bekräftar grindvaktens lyssnare, inte att företagets modellserver går att nå. Om felet kvarstår:
kontrollera modelladressen, VPN och `bash tools/work.sh status`.

**Sidekick-posten saknas i Claude Desktop.** Kör `bash tools/work.sh claude-config` efter en lyckad `start`, granska
förhandsvisningen och svara j. Starta om Claude Desktop helt. Ogiltig JSON nekas utan att filen ersätts; rätta den
först eller lägg in den genererade posten för hand. Kommandot visar bara den nya Sidekick-posten, aldrig andra
anslutningars inloggningsuppgifter. Ångra en sammanslagning genom att lägga tillbaka den tidsstämplade säkerhetskopian
bredvid inställningsfilen.
