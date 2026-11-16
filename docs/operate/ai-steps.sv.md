# Kör AI-steg med Claude Code

[English](ai-steps.md)

<!-- description: Låt din egen Claude Code köra AI-stegen i en godkänd uppgift och granska det den skriver. Sidekick ser aldrig din Claude-inloggning. -->

Vissa steg i en uppgift kan göras av AI: ett första utkast, research, en sammanfattning, en checklista. Du godkänner planen, din egen Claude Code kör AI-stegen, och varje resultat väntar på att du granskar det. Ett AI-steg gör bara text inne i Sidekick. Att skicka, köpa, radera eller publicera är alltid ett steg som du gör själv.

## Flödet

1. **Markera uppgiften som möjlig med AI.** Öppna ⋯-menyn på uppgiften i rummet Arbete, eller be Claude. Markeringen kostar inget.
2. **Be Claude planera uppgiften.** Varje steg markeras "Du" eller "AI". Varje AI-steg har en kort instruktion: målet, när det är klart, resultatformatet, vilka verktyg det får använda, en budget och när det ska stoppa och fråga dig.
3. **Godkänn planen i rummet Arbete** med ett klick. Godkännandet gäller exakt den här planen. Ändras planen efteråt körs ingenting förrän du godkänner den igen.
4. **Kör AI-stegen** med Claude Code, så som det beskrivs nedan.
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
| `SIDEKICK_AI_MAX_ATTEMPTS_PER_STEP` | 3 | Försök på ett AI-steg |
| `SIDEKICK_AI_CLAUDE_CODE_STARTS_PER_DAY` | 50 | AI-steg som din Claude Code får starta per dag |

De sätts som övriga inställningar; se [Konfigurationsreferensen](../reference/configuration.md). `SIDEKICK_AI_LOCAL_MODELS_EXEMPT_FROM_CAP` tar körningar på en lokal modell, som inte kostar något, utanför pengataken.

Kostnaden som Claude Code rapporterar är en uppskattning. Sidekick sparar den med varje körning men räknar den inte mot pengataken, eftersom en planinloggning inte faktureras per anrop. Skyddet där är antalet försök och starter. Pengataken gäller när en server-runner finns. Den runnern är planerad men ännu inte byggd.

## Det du bör veta innan du kör

- Sidekick startar aldrig Claude Code och tar aldrig emot din Claude-inloggning. Du kör din egen klient.
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
