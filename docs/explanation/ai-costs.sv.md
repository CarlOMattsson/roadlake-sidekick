# AI-kostnader

[English](ai-costs.md)

<!-- description: Vad Sidekick kan kosta utöver licensen: inget extra i Claude med abonnemang, och betalning per anrop för funktioner som din server kör med en API-nyckel. -->

Sidekick i sig är gratis. AI:n runt det är inte alltid gratis. Den här sidan säger var kostnaden kommer ifrån, vad Sidekick begränsar och vad du själv bestämmer, så att du vet vad du ger dig in på innan du slår på något.

## Kort version

- **Använd Sidekick i Claude med ett Claude-abonnemang. Vi rekommenderar det.** När du arbetar via connectorn gör Claude AI-arbetet och det ingår i ditt abonnemang. Sidekick lägger ingen AI-kostnad ovanpå.
- **Ett abonnemang täcker inte allt.** Det som din egen server kör själv kräver en API-nyckel, och en API-nyckel debiteras per anrop av leverantören. Det gäller AI-steg som körs på servern, minnet (Hindsight) när det använder en modell via nyckel och, senare, automationer och deras kontrollmodell.
- **Inget av detta är på som förval.** Du slår på varje del själv, och varje del kräver en nyckel som du själv anger.
- **Du kan använda Sidekick utan något av det.** Uppgifter, dagbok, kontakter och inköpslistor anropar ingen modell.

## Vad som kostar och vad som inte gör det

| Funktion | Körs | Betalas | Förval |
| --- | --- | --- | --- |
| Använda Sidekick i Claude via connectorn | Claude | Ditt Claude-abonnemang, inget extra | Alltid tillgängligt |
| AI-steg som körs av din egen Claude Code | Din dator | Din Claude-plan, eller en API-nyckel om du använder en | Du startar dem |
| AI-steg som körs på din server (Kör) | Din server | Per anrop med din Anthropic API-nyckel | Av |
| Minne (Hindsight) | Din server | Per anrop med nyckeln till den modellleverantör du väljer; inbäddningarna körs lokalt | Av |
| Automationer och kontrollmodell (kommande, inte byggda än) | Din server | Per anrop med din nyckel | Finns inte än; av som förval när de kommer |

## De två sorternas nyckel

- **Anthropic API.** Debiteras av Anthropic per token, på den nyckel du skapar i Anthropic Console. Sätt en utgiftsgräns där också.
- **OpenRouter.** En nyckel som når många modeller hos många leverantörer. Du betalar OpenRouter, och priset beror på vilken modell och leverantör du väljer. Du kan också peka Sidekick mot en modell på ditt eget nätverk (till exempel Ollama eller LM Studio), vilket inte kostar något per anrop.

Ingen av nycklarna behövs för att använda Sidekick i Claude. De är bara till för funktioner som din server kör.

## Gränser som Sidekick sätter

De gäller AI-steg som körs på din server. Värdena är förvalen och kan ändras i serverns inställningar.

| Gräns | Förval |
| --- | --- |
| Kostnad per kalendermånad för AI-steg som debiteras per anrop | 50 USD |
| Kostnad per uppgift | 2 USD |
| Försök på ett steg i en uppgift | 3 |
| AI-steg som startas per dag på servern | 50 |
| AI-steg som din egen Claude Code startar per dag | 50 |

Servern räknar ut det mesta ett anrop kan kosta innan anropet görs, och vägrar det om det skulle passera en gräns. Körningar på en lokal modell kostar inget och kan hållas utanför pengagränserna med `SIDEKICK_AI_LOCAL_MODELS_EXEMPT_FROM_CAP`. Sidekicks siffra är en uppskattning, avrundad uppåt. Leverantörens faktura är det som gäller, så sätt också en gräns hos leverantören.

Minnet har egna dagsgränser för hur mycket som skickas till modellleverantören: som förval 40 poster från liveändringar, 150 från bakgrundsinläsningen och 400 000 tecken totalt per ägare och dag.

## Kommande: automationer

*Inte byggt än. Det här är planen, inte en funktion du kan använda.* Automationer blir avstängda som förval och körs på din server med en API-nyckel, tillsammans med en kontrollmodell som granskar vad de föreslår. Planerade gränser: ett eget tak för automationer, 15 USD per månad som förval inom månadstaket på 50 USD och justerbart; högst 1 USD per körning; högst 20 körningar per dag. Kontrollmodellens anrop räknas mot samma tak. Med en Anthropic-nyckel är Sonnet planerad förvald modell. Med OpenRouter rekommenderar vi en billig modell hos en betrodd värd.

## Att välja med OpenRouter

Med OpenRouter väljer du själv leverantör och modell, så kostnaden och integriteten är dina att välja klokt.

- **Välj leverantörer du litar på.** Föredra en leverantör som kör modellen utanför Kina och som uppger att den inte sparar dina prompter och inte tränar på dem. Kontrollera det i OpenRouters leverantörsinställningar och i leverantörens egna villkor. En inställning där du kan kräva "ingen datainsamling" är det säkrare valet.
- **Var modellen körs spelar större roll än var den är gjord.** Öppna modeller som utvecklats i Kina, till exempel DeepSeek, är i sin ordning när en betrodd värd utanför Kina kör dem, till exempel Google, Azure eller AWS eller liknande. Det som räknas är var modellen körs och om den leverantören sparar eller tränar på dina data.
- **Använd billiga modeller till enkla uppgifter.** En kort sammanfattning eller en checklista behöver inte den största modellen. Börja med en liten, billig modell och gå upp först om resultatet inte räcker.
- **Följ priserna.** De ändras, så den här sidan anger inga. Se [Anthropics priser](https://www.anthropic.com/pricing) och [OpenRouters modeller och priser](https://openrouter.ai/models).

## Vad en siffra betyder

Kostnaden beror på hur mycket text som går in och ut, och på modellen. Ett stegs underlag och svar är text på högst några sidor, men samma steg kostar flera gånger mer på en stor modell än på en liten. Eftersom priserna ändras ger Sidekick dig taken ovan i stället för ett pris per uppgift. Med förvalen kan AI-steg på din server inte kosta mer än 50 USD under en kalendermånad.

## Läs mer

- [Kör AI-steg](../operate/ai-steps.sv.md): att slå på körningen och gränserna i detalj.
- [Slå på minnet](../operate/memory.sv.md).
- [Resursgränser och hemligheter](../operate/limits-and-secrets.sv.md): var nycklarna ligger.
- [Licens, licensnyckel och pris](licensing.sv.md): licensen är skild från de här kostnaderna.
