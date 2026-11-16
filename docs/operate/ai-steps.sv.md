# Kör AI-steg

[English](ai-steps.md)

<!-- description: Låt din egen Claude Code, eller din server med din egen Anthropic-nyckel, köra AI-stegen i en godkänd uppgift och granska det den skriver. -->

Vissa steg i en uppgift kan göras av AI: ett första utkast, research, en sammanfattning, en checklista. Du godkänner planen, din egen Claude Code eller din egen server kör AI-stegen, och varje resultat väntar på att du granskar det. Ett AI-steg gör bara text inne i Sidekick. Att skicka, köpa, radera eller publicera är alltid ett steg som du gör själv.

## Flödet

1. **Markera uppgiften som möjlig med AI.** Öppna ⋯-menyn på uppgiften i rummet Arbete, eller be Claude. Markeringen kostar inget.
2. **Be Claude planera uppgiften.** Varje steg markeras "Du" eller "AI". Varje AI-steg har en kort instruktion: målet, när det är klart, resultatformatet, vilka verktyg det får använda, en budget och när det ska stoppa och fråga dig.
3. **Godkänn planen i rummet Arbete** med ett klick. Godkännandet gäller exakt den här planen. Ändras planen efteråt körs ingenting förrän du godkänner den igen.
4. **Kör AI-stegen** med Claude Code, eller på din server, så som det beskrivs nedan.
5. **Granska varje resultat** i rummet, eller be Claude. Du kan godkänna det, be om ett nytt försök med en kommentar, avvisa det, eller svara på en fråga som steget ställde. Bara du gör ett steg klart.

## Ge Claude Code en egen token

Claude Code behöver en personlig token med behörigheten `ai:run`. Den behörigheten är valfri: ingen vanlig token har den. Skapa en token med bara det körningen behöver:

```bash
uv run --project backend sidekick-admin create-token --user-id <USER_UUID> --label "Claude Code" --scope ai:run --scope tasks:read
```

- `<USER_UUID>` är ditt användar-id, så som `create-user` skrev ut det.
- Utan `tasks:write` kan den här klienten inte godkänna planer, godkänna resultat eller flytta något till papperskorgen. Lägg till `projects:read` om svaren ska nämna projekt, och `contacts:read` om ett steg behöver kontakter. [Behörighetsreferensen](../reference/scopes.md) listar vad varje behörighet tillåter.
- Token visas en gång. Behandla den som ett lösenord.

> **Varning: ge aldrig modellen en token med både `ai:run` och `tasks:write`.** Tillsammans låter de en och samma klient köra ett steg, rapportera sitt eget resultat och sedan godkänna det, och godkänna eller ändra planen den kör. Då försvinner granskningen som låter dig styra. Den lokala stdio-anslutningen har alla behörigheter, så en modell som nås via stdio har båda: använd bara stdio för klienter du litar på med hela kontot, och använd den här begränsade token för klienten som kör stegen.

En personlig token fungerar bara i utvecklingsläget `pat`. På en server som loggar in via GitHub nekar `/mcp` den, som [Anslut Claude](connect-claude.sv.md) förklarar, så den vägen finns inte där.

## Koppla Claude Code

Lägg servern i en fil i mappen där du kör Claude Code, till exempel sidekick.mcp.json. Token ligger i en miljövariabel och kommer aldrig in i filen:

```json
{
  "mcpServers": {
    "sidekick": {
      "type": "http",
      "url": "https://<your-domain>/mcp",
      "headers": {
        "Authorization": "Bearer ${SIDEKICK_AI_TOKEN}"
      }
    }
  }
}
```

Servernamnet `sidekick` ger prefixet `mcp__sidekick__` till verktygen och snedstreckskommandot. `url` är adressen till `/mcp` på din server, som i [Anslut Claude](connect-claude.sv.md).

## Kör stegen

Interaktivt startar du Claude Code med `claude --mcp-config sidekick.mcp.json` och skriver snedstreckskommandot med uppgiftens id. Argumentet är valfritt:

```
/mcp__sidekick__ai_steps <task-id>
```

Utan gränssnitt, från ett skript eller en terminal, finns två varianter. Claude Code kör AI-stegen i planens ordning; ett steg är redo först när stegen före det är klara.

Planinloggning (din Claude-prenumeration):

```bash
claude -p "/mcp__sidekick__ai_steps <task-id>" --mcp-config sidekick.mcp.json --allowedTools "mcp__sidekick__start_ai_step,mcp__sidekick__report_ai_step_result,WebSearch,WebFetch" --permission-mode dontAsk --output-format json
```

API-nyckel, satt i miljön och inte på kommandoraden:

```bash
export ANTHROPIC_API_KEY=<your-api-key>
claude -p "/mcp__sidekick__ai_steps <task-id>" --bare --mcp-config sidekick.mcp.json --allowedTools "mcp__sidekick__start_ai_step,mcp__sidekick__report_ai_step_result,WebSearch,WebFetch" --permission-mode dontAsk --output-format json
```

- Enligt Claude Codes dokumentation läser `--bare` inte inloggningen i en plan. Därför behöver den andra varianten en API-nyckel.
- `--allowedTools` anger vad körningen får använda utöver Sidekicks egna verktyg. De två webbverktygen står med här; ta bort dem om stegen inte ska söka på webben.
- `--max-budget-usd` kan läggas till för att prova ett tak på en körning. Det är inte verifierat här att flaggan fungerar med planinloggning, så kontrollera utdata och sätt en gräns hos din leverantör också.

## Gränser och kostnader

| Inställning | Förval | Vad den begränsar |
| --- | --- | --- |
| `SIDEKICK_AI_DEFAULT_TASK_CAP_USD` | 2 | Utgifter per uppgift, i US-dollar |
| `SIDEKICK_AI_MONTHLY_CAP_USD` | 50 | Utgifter per kalendermånad |
| `SIDEKICK_AI_MAX_ATTEMPTS_PER_STEP` | 3 | Försök på ett AI-steg i en cykel av dess uppgift; en återkommande uppgift får dem tillbaka varje gång den görs klar |
| `SIDEKICK_AI_CLAUDE_CODE_STARTS_PER_DAY` | 50 | AI-steg som din Claude Code får starta per dag |

De sätts som övriga inställningar; se [Konfigurationsreferensen](../reference/configuration.md). `SIDEKICK_AI_LOCAL_MODELS_EXEMPT_FROM_CAP` tar körningar på en lokal modell, som inte kostar något, utanför pengataken.

Kostnaden som Claude Code rapporterar är en uppskattning. Sidekick sparar den med varje körning men räknar den inte mot pengataken, eftersom en planinloggning inte faktureras per anrop. Skyddet där är antalet försök och starter. Pengataken gäller för körningar på din server, som avsnittet nedan beskriver.

## Kör AI-steg på din server

I stället för Claude Code kan din egen server köra ett godkänt AI-steg. Du trycker på **Kör** i rummet Arbete, och en separat container, `ai-worker`, skickar steget till Anthropics API med din egen API-nyckel och skriver tillbaka svaret som ett resultat som du granskar. Det är avstängt tills du slår på det.

**Slå på det.**

1. Lägg din Anthropic-nyckel i en fil och starta profilen `ai`, som sidan om [Compose-profiler](../reference/selfhost-profiles.sv.md) och `deploy/selfhost/README.md` beskriver. Skriv nyckeln direkt till `secrets/ai_anthropic_api_key`, eller låt `secrets-to-files.sh` flytta den dit.
2. Sätt `SIDEKICK_AI_RUNNER_ENABLED=true` i `selfhost.env` och starta profilen med `docker compose --env-file selfhost.env --profile ai up -d`.

Nyckeln når bara `ai-worker`. Den får inte ligga kvar i `selfhost.env`: i produktion vägrar API:t starta när det hittar nyckeln där. `ai-worker` är också den enda containern på nätet `ai`, den enda utgående vägen ut på internet. Se [Gränser och hemligheter](limits-and-secrets.sv.md).

**Modell.** Förvalet är `claude-opus-5-5`; byt med `SIDEKICK_AI_MODEL`. Sidekick har inbyggda priser för `claude-opus-5-5` och `claude-sonnet-5-5`. En modell som inte finns i den tabellen kräver alla fyra priserna (`SIDEKICK_AI_PRICE_INPUT_USD_PER_MTOK`, `SIDEKICK_AI_PRICE_OUTPUT_USD_PER_MTOK`, `SIDEKICK_AI_PRICE_CACHE_WRITE_USD_PER_MTOK` och `SIDEKICK_AI_PRICE_CACHE_READ_USD_PER_MTOK`), eftersom en kostnad som inte kan räknas inte kan begränsas. Ge alla fyra eller ingen.

**Så fungerar Kör.**

- Kör finns bara i appen (rummet Arbete). Claude kan inte trycka på den åt dig, och den kräver behörigheten att ändra uppgifter.
- Du trycker på Kör på en godkänd plan. Nästa AI-steg ställs i kö. `ai-worker` tar det inom några sekunder (`SIDEKICK_AI_POLL_SECONDS`) och gör ett modellanrop.
- Svaret är alltid något du ska granska: ett resultat, en fråga eller ett misslyckande. Inget går till minnet, och inget skickas, köps, raderas eller publiceras.
- Ett steg körs i taget, i planens ordning. Du trycker på Kör igen för nästa steg. Du kan avbryta en körning som ligger i kö eller pågår; ett anrop som redan är på väg faktureras ändå.
- Ett steg som är markerat för att bara köras med Claude Code kan inte köras här.

**Pengataken.** Servern räknar ut vad ett anrop högst kan kosta innan anropet görs.

- Före varje anrop reserverar workern det mesta anropet kan kosta. Det sker under ett lås per ägare, så två workers kan aldrig reservera förbi samma tak. Efter anropet ersätts reservationen av den kostnad som tokenräkningen ger.
- Ett anrop vägras när det skulle passera stegets egen budget, uppgiftens tak (`SIDEKICK_AI_DEFAULT_TASK_CAP_USD`, räknat per cykel för en återkommande uppgift) eller månadens tak (`SIDEKICK_AI_MONTHLY_CAP_USD`).
- Kostnader avrundas uppåt. Sidekicks siffra kan vara högre än vad du betalar: Anthropics faktura är facit.
- Ett anrop vars utfall är okänt (en timeout, en bruten förbindelse), eller en worker som dör under ett anrop, bokar reservationen som kostnad. Taken räknar därför aldrig mindre än vad som spenderats.
- En körning räknas fortfarande efter att du raderat dess steg eller uppgift permanent. Sidekick behåller bara körningens kostnad, körsätt och tid (siffror, ingen text) så länge ditt konto finns.
- Sätt en utgiftsgräns för nyckeln i Anthropic Console som yttre skydd. Sidekicks tak är det inre.

**Vad som lämnar din maskin.** Stegets brief går till Anthropic enligt Anthropics API-villkor. Den innehåller uppgiftens titel och beskrivning, stegets instruktion, åtgärdernas titlar, projektets titel och, om steget tillåter det, kontakters namn och referensers titlar. Kontakters e-post, telefon och adress, dagbokstext och minne skickas aldrig. Nyckeln och briefen skrivs inte till loggarna och sparas inte i databasen; resultatet, frågan eller misslyckandet sparas som körningens resultat.

**Stöds inte ännu.** Webbsökning och webbhämtning är avstängda, och lokala modeller likaså. Ett steg som kräver webben eller är markerat `local_only` vägras med `ai_runner_off`.

**Inställningar.**

| Inställning | Förval | Vad den gör |
| --- | --- | --- |
| `SIDEKICK_AI_RUNNER_ENABLED` | `false` | Slår på serverkörningen |
| `SIDEKICK_AI_MODEL` | `claude-opus-5-5` | Modellen som kör stegen |
| `SIDEKICK_AI_SERVER_STARTS_PER_DAY` | 50 | Hur många steg du får köra på servern per dag |
| `SIDEKICK_AI_MAX_OUTPUT_TOKENS` | 16000 | Det mesta ett anrop får skapa |
| `SIDEKICK_AI_REQUEST_TIMEOUT_SECONDS` | 300 | Hur länge ett anrop får ta |
| `SIDEKICK_AI_POLL_SECONDS` | 5 | Hur ofta workern letar efter en körning i kö |
| `SIDEKICK_AI_PRICE_*` | inte satt | De fyra priserna för en modell som inte finns i den inbyggda tabellen |

Nyckeln själv är `SIDEKICK_AI_ANTHROPIC_API_KEY`, given som filen `ai_anthropic_api_key`. Alla inställningar finns i [Konfigurationsreferensen](../reference/configuration.md).

**Om Kör inte fungerar.**

| Du ser | Gör så här |
| --- | --- |
| `ai_runner_off` | Körningen är av, eller steget kräver webben eller en lokal modell. Kontrollera `SIDEKICK_AI_RUNNER_ENABLED` på `api` och att profilen `ai` körs. |
| `ai_budget_reached` | Det första anropet skulle passera stegets budget, uppgiftens tak eller månadens tak. Höj taket, eller vänta till nästa cykel eller månad. |
| `ai_limit_reached` | Försöken på steget i cykeln är slut, eller du har kört dagens antal steg. |
| Körningen blir kvar i "I kö" | `ai-worker` körs inte, eller Anthropic avvisade nyckeln. En körning som ingen tar förfaller efter 30 minuter och förbrukar inget försök. Starta workern eller rätta nyckeln och tryck på Kör igen. |
| En körning som togs och sedan tystnade | Den förfaller efter 15 minuter, och dess reservation bokas som kostnad. |
| Workern tar inga fler körningar | Anthropic avvisade nyckeln, och workern slutar ta körningar tills den startas om. Lägg en ny nyckel i filen och starta om `ai-worker`. |

## Det du bör veta innan du kör

- Sidekick startar aldrig Claude Code och tar aldrig emot din Claude-inloggning. Du kör din egen klient.
- På din server går stegets text till Anthropic med din egen nyckel, som avsnittet ovan säger.
- Uppgiftens text når din Claude Code som data, aldrig som instruktioner.
- Kontaktuppgifter (e-post, telefon, adress) skickas aldrig. Bara ett namn skickas, och bara när ett stegs instruktion ber om det.
- Din egen Claude Code-konfiguration (hooks, andra MCP-servrar, tillåtna verktyg) ligger utanför Sidekicks kontroll. Gå igenom den innan du kör steg.
- Sätt en utgiftsgräns hos din leverantör som yttre skydd. Sidekicks siffror är uppskattningar.

## Om det inte fungerar

| Du ser | Gör så här |
| --- | --- |
| Planen har ändrats | Godkänn planen igen i rummet Arbete. |
| Steget är inte redo | Ett tidigare steg är fortfarande öppet, en körning pågår eller väntar på dig, eller försöken är slut. |
| En körning som stannade utan rapport | Den kan ersättas efter 30 minuter. Starta steget igen. |
