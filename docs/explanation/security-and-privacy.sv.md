# Säkerhet och integritet i klartext

[English](security-and-privacy.md)

<!-- description: Vem som ser vad när du använder Sidekick – du, Claude, modellleverantören för minnet, GitHub, ntfy-servern och webbplatsens värd. -->

Den här sidan säger rakt vem som ser dina data och när. Den lovar inte mer än det som går att visa i koden. Den tekniska genomgången finns i [hotmodellen](threat-model.md), som är på engelska.

:::caution[Självhostning håller inte innehållet borta från Claude]
Att självhosta betyder att du kör Sidekick på en server du själv styr. Dina poster lagras där. Men det Claude får läsa för att kunna hjälpa dig lämnar servern och delas med Claude.
:::

## Vem ser vad

| Vem | Vad | När |
| --- | --- | --- |
| Du | Allt. Du har servern, databasen och nycklarna. | Alltid |
| Claude | Det som connectorns scopes tillåter, också dagbokstext om `journal:read` är med. Dessutom det du skriver och ser i samtalet. | När Claude anropar ett verktyg eller visar ett rum |
| Modellleverantören för minnet | Text ur de källor du har slagit på: dagbok, kontakter, projekt och uppgifter. Aldrig kontakters e-post, telefon, adress eller Slack-länk. | Bara om du har slagit på minnet |
| GitHub | Att du loggar in på din server. Sidekick ber inte GitHub om något utöver vem du är. | När du loggar in connectorn |
| Anthropic, för AI-steg på din server | Briefen för varje steg du kör: uppgiftens titel och beskrivning, stegets instruktion, åtgärdernas titlar, projektets titel samt kontaktnamn eller referenstitlar om steget tillåter det. Aldrig e-post, telefon, adress, Slack-länk, dagbokstext eller minne. | Bara om du har slagit på profilen `ai` och trycker på Kör |
| ntfy-servern | Att en telefon väcktes, när det hände och telefonens IP-adress. Inget innehåll. | Bara om du har slagit på påminnelser |
| Webbplatsens värd (GitHub) | Det en webbserver ser, till exempel din IP-adress, enligt GitHubs egen policy. | När du besöker den här webbplatsen |

## Var dina data ligger

Dina poster ligger i PostgreSQL på din server: uppgifter, projekt, dagbok, kontakter och inköpslistor. Sidekick har ingen central tjänst som tar emot dem. En instans är till för en ägare. Det finns ingen öppen registrering.

## Vad Claude ser

En scope är en behörighet som servern kontrollerar vid varje anrop. Du anger vilka scopes connectorn får, och Claude kan inte gå utanför dem. Exempelkonfigurationen ger bara läsrätt till projekt, uppgifter, kontakter och inköp, och ingen tillgång till dagboken.

Det Claude läser inom sina scopes lämnar din server. Det omfattas då av Anthropics villkor, inte av något Sidekick styr över. Ge därför de snävaste scopes som räcker för det du vill göra.

En sak till är bra att veta. En text som Claude läser, till exempel en inklistrad webbsida, kan försöka styra Claude. Claude kan då fortfarande bara använda de scopes du har gett.

## Minnet

Minnet är valfritt och avstängt tills du slår på det. När det är på skickar tjänsten Hindsight text till den modellleverantör du själv har ställt in. Du kan pausa minnet, stänga av en källa och hålla en enskild post utanför. [Läs om Kontroll och minnet](../guide/control-and-memory.sv.md).

På jobbdatorn når containrarna (minnets anrop inräknade) bara företagets egen modellserver. Claude Desktop är ändå en extern tjänst: det som visas eller skrivs i samtalet, och namn, argument och resultat för de Sidekick-verktyg Claude anropar (uppgiftstitlar, kontaktnamn, datum), delas med Claude.

## Ingen telemetri

Sidekick skickar ingen telemetri och ingen statistik. Servern kontaktar bara de tjänster du själv ställer in: GitHub för inloggningen, en ntfy-server för påminnelser, en modellleverantör för minnet och, om du har slagit på det, Anthropic för AI-steg du kör på servern. Sidekick anropar ingen språkmodell på egen hand: ett anrop görs bara när du trycker på Kör på ett godkänt steg.

## AI-steg på din server

Det här avsnittet gäller bara om du har slagit på profilen `ai`. Då kan ett godkänt AI-steg köras på din server: du trycker på Kör i appen, och containern `ai-worker` gör ett anrop till Anthropics API. [Kör AI-steg](../operate/ai-steps.sv.md) förklarar hur du ställer in det.

- **Nyckeln.** Din Anthropic-nyckel når bara `ai-worker`, som en fil. Den lagras aldrig i databasen, skrivs aldrig i en logg eller ett spår och returneras aldrig av något verktyg. I produktion vägrar API:t och de andra workers starta om de hittar nyckeln i sin miljö.
- **Vägen ut.** `ai-worker` är den enda containern på ett eget nät, `ai`, som är den enda utgående vägen ut på internet. Den delar inget nät med Hindsight eller ntfy. API-adressen och nyckeln är fasta i koden, så ingen miljövariabel kan skicka nyckeln någon annanstans.
- **Vad som skickas.** Stegets brief går till Anthropic enligt Anthropics API-villkor: uppgiftens titel och beskrivning, stegets instruktion, åtgärdernas titlar, projektets titel och, om steget tillåter det, kontakters namn och referensers titlar. Aldrig e-post, telefon, adress, Slack-länk, dagbokstext eller minne.
- **Promptinjektion.** En text i en uppgift kan försöka styra modellen. Fyra saker begränsar vad det kan leda till. Den godkända planen är den enda källan till instruktioner, och servern skriver den. Ägarens text hägnas in som data och rensas från styrtecken. Modellen har inga verktyg: den kan inte läsa, skriva, surfa eller skicka något. Svaret måste vara strikt JSON som servern kontrollerar, och servern lagrar det bara som text som du granskar. Sidekick försöker inte upptäcka injektioner med filter.
- **Pengar.** Workern reserverar det mesta ett anrop kan kosta innan anropet görs, under ett lås per ägare, och avräknar den verkliga kostnaden efteråt. Taken gäller per steg, per uppgift och per månad. Ett anrop med okänt utfall bokas till sin reserverade kostnad. [Kör AI-steg](../operate/ai-steps.sv.md) har detaljerna.
- **Telemetri.** Anthropics SDK kan skicka OpenTelemetry-spår och spårhuvuden. Sidekick stänger av det i koden och i containern, så inget spårhuvud och inget innehåll lämnar processen. Loggar och telemetri från workern innehåller id, tillstånd och antal, aldrig text.

## Loggar

Loggarna innehåller inget användarinnehåll och inga inloggningsuppgifter. Titlar, text och nycklar skrivs aldrig dit. Fel som skickas till en klient är allmänt hållna och har ett id som går att söka på i loggen.

## Licensnyckeln

Licensnyckeln kontrolleras offline mot en publik nyckel. Sidekick kontaktar ingen server för att kontrollera den. Nyckeln innehåller namnet på den som fått den, och namnet visas i appen. Dela inte din nyckel.

## Telefonen

Android-appen paras ihop med en kod som fungerar en gång och i tio minuter. Telefonen får då en egen behörighet som lagras krypterat på telefonen och inte följer med i telefonens säkerhetskopior. Du kan återkalla den från servern när som helst.

Påminnelser skickas som väckningar utan innehåll. Telefonen hämtar själv innehållet från din server. På den publika ntfy-servern är ämnets namn den enda hemligheten, så använd en egen ntfy-server för mer än ett prov.

## Backuper

Backuper krypteras när du har slagit på backup-profilen och skapat en nyckel. Utan nyckeln går de inte att läsa. Förvara nyckeln någon annanstans än på servern, och ha en kopia av backuperna utanför servern. Den som har en backup och dess nyckel kan läsa alla dina poster.

## Det här skyddar Sidekick inte mot

- En server, en databas eller ett nyckelförråd som någon har tagit sig in i.
- Vad Claude, modellleverantören eller ntfy-servern sparar. Sidekick begränsar vad som skickas men styr inte vad de behåller.
- Någon som har en giltig behörighet. Återkalla telefoner och åtkomster som du inte längre använder.

Sidekick 0.1.0 är den första versionen. Den används dagligen med Claude, med Android-appen på en riktig telefon och på Linux. macOS är ännu inte provat.

## Rapportera en sårbarhet

Rapportera sårbarheter privat, inte i ett öppet ärende. [Läs hur du rapporterar en sårbarhet](../../SECURITY.sv.md).

## Den här webbplatsen

Webbplatsen har inga kakor, ingen spårning och inga skript från tredje part. Sökningen körs i din webbläsare mot ett index som följer med sidan. Ditt val av ljust eller mörkt tema sparas i webbläsaren och ingen annanstans. GitHub driftar webbplatsen och kan logga IP-adresser enligt sin egen policy.
