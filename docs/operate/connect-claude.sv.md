# Anslut Claude

[English](connect-claude.md)

<!-- description: Lägg till din server som en anpassad connector i Claude och logga in med GitHub. Här bestämmer du också vilka scopes sessionen får, och hur du tar bort åtkomst. -->

Lägg till din server som en anpassad connector i Claude och logga in med GitHub. Här bestämmer du också vilka scopes sessionen får, och hur du tar bort åtkomst.

Claude loggar in på din server via GitHub, men det är Sidekick som avgör vem som släpps in: bara de
GitHub-konton som står i `SIDEKICK_MCP_OAUTH_ALLOWED_IDENTITIES`.

**Registrera en OAuth-app hos GitHub** (GitHub, Settings, Developer settings, OAuth Apps, New OAuth App):

- Homepage URL: `https://<your-domain>`
- Authorization callback URL: `https://<your-domain>/mcp/auth/callback`
- Generera en klienthemlighet. Lägg Client ID och hemligheten i `SIDEKICK_MCP_OAUTH_GITHUB_CLIENT_ID` och
  `SIDEKICK_MCP_OAUTH_GITHUB_CLIENT_SECRET`. Sidekick ber inte GitHub om några andra rättigheter än att få veta
  vem du är.

**Lägg till anslutningen i Claude.** Serveradressen är `https://<your-domain>/mcp` (utan avslutande
snedstreck, samma värd som i `SIDEKICK_MCP_PUBLIC_BASE_URL`). Öppna Settings och sedan Connectors i Claude och
välj att lägga till en anpassad anslutning (custom connector). Menynamnen varierar med Claude-version och
abonnemang; i Team- och Enterprise-abonnemang lägger en organisationsägare till den först; se
[Anthropics guide till anpassade anslutningar](https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp).
Ge den ett namn, till exempel "Sidekick", och klistra in adressen. Ange inget OAuth-klient-id och ingen
hemlighet under Advanced settings: Claude registrerar sig själv hos servern. Som förval godtas bara Claudes
egen callback (`https://claude.ai/api/mcp/auth_callback`) som omdirigering.

**Första inloggningen.** Välj Connect. Claude öppnar din servers samtyckessida, som ber dig godkänna
anslutningen. Godkänn den och logga sedan in med det GitHub-konto vars id du angav. Du hamnar i Claude igen,
med anslutningen på plats. Ett GitHub-konto som inte står i listan nekas efter inloggningen. Kontrollera
genom att be Claude om något som Sidekick har, till exempel "Vilka uppgifter har jag öppna?".

**Vad sessionen får göra.** Exakt de scopes som står i `SIDEKICK_MCP_OAUTH_SCOPES`, oavsett vad klienten ber
om och vad GitHub säger. Exemplet levereras bara med läs-scopes för projekt, uppgifter, kontakter och inköp: Claude kan
läsa det, kan inte ändra något och har ingen åtkomst till Dagboken. Lägg till `journal:read` för Dagboken. Ett
`:write`-scope (anges bredvid sitt `:read`, till exempel `projects:write,projects:read`) låter Claude ändra den datan,
`license:write` låter appen ange instansens licensnyckel (lägg bara till det om du anger nyckeln i appen), och
`automation:read` / `automation:write` gäller automationsrummet. Utöka listan med eftertanke och skapa sedan om API:et
(`docker compose --env-file selfhost.env up -d --force-recreate api`). Om Claude inte märker ändringen: ta
bort anslutningen och lägg till den igen.

**Långsamma klienter.** API:et ger en publik begäran en enda tidsgräns för att hela kroppen ska hinna fram, så en klient
som droppar byte för byte får `408 Request Timeout` i stället för att binda en arbetare:
`SIDEKICK_BODY_READ_TIMEOUT_SECONDS` (förval 30) för begäranden i allmänhet och den kortare
`SIDEKICK_OAUTH_BODY_READ_TIMEOUT_SECONDS` (förval 10) för OAuth-formulären. Båda anges i sekunder, över 0 och högst 300,
och är utkommenterade i `selfhost.env.example`. Höj en av dem bara om en legitim klient på en mycket långsam
uppkoppling nekas, och skapa sedan om API:et.

**Överbelastning och gissade nycklar.** Två begränsningar i minnet skyddar API:et mot klienter som kostar det mer än de
kostar avsändaren. Begärandekroppar hålls i minnet tills de är kompletta; högst `SIDEKICK_MAX_BUFFERED_REQUESTS` (förval
32, 1 till 1024, upp till 1 MiB vardera) får vara på väg in samtidigt, och en begäran som möter fullt får `503` med
`Retry-After: 1`. En plats frigörs när kroppen är komplett, inte när begäran besvarats, eftersom ett MCP-svar kan stå
öppet länge. En fjärdedel av platserna hålls tillbaka för bärartokens som API:et har verifierat den senaste timmen, så att
anonyma klienter som öppnar många långsamma kroppar inte kan svälta dina anslutna klienter. Att kontrollera en bärartoken kostar en databasfråga, så misslyckade försök (svar 401) räknas i en glidande
minut: efter `SIDEKICK_FAILED_AUTH_PER_CLIENT_PER_MINUTE` (förval 10) från en klientadress, eller
`SIDEKICK_FAILED_AUTH_GLOBAL_PER_MINUTE` (förval 60) från alla klienter tillsammans, får ytterligare begäranden med en
okänd token `429` med `Retry-After` innan databasen berörs. En token som API:et verifierat den senaste timmen stryps
aldrig (timmen förnyas vid varje användning), så dina anslutna klienter fortsätter fungera under en attack.
`SIDEKICK_FAILED_AUTH_RESERVE_PER_MINUTE` (förval 5, 0 stänger av) släpper igenom så många begäranden per minut med okänd
token oavsett, så ditt första giltiga anrop efter en omstart av API:et, eller efter en timmes tystnad, når API:et inom
sekunder även under en pågående attack (en angripare kan förbruka reserven, så en klient kan behöva några försök).
Bakom en tunnel som Tailscale Funnel delar alla besökare adress och ingen vidarebefordrad rubrik litas på, så
per-klientgränsen blir lika med den globala och det är den globala gränsen och reserven som skyddar dig. Eftersom en
slut budget ger `429` för okända token men `401` eller lyckat svar för kända kan en klient skilja en nyligen använd token
från en gissning; det är ofarligt för de slumpmässiga 256-bitarstoken som Sidekick utfärdar. Alla fyra inställningarna
är utkommenterade i `selfhost.env.example`; sänk dem bara om du vill ha ett snävare skydd, och höj dem om många
legitima klienter skriver fel token samtidigt.

**Ta bort åtkomst.**

- En person: ta bort personens post ur `SIDEKICK_MCP_OAUTH_ALLOWED_IDENTITIES` och skapa om API:et enligt ovan.
  Personens sessioner slutar fungera då, inte först när de löper ut. API:et minns en lyckad GitHub-kontroll i
  `SIDEKICK_MCP_OAUTH_UPSTREAM_CACHE_SECONDS` (förval 300, fem minuter; högst 3600; `0` frågar GitHub vid varje anrop), och
  när containern skapas om rensas det minnet.
- Stäng ute en person direkt och för gott: `docker compose --env-file selfhost.env run --rm -T api sidekick-admin disable-user --user-id <UUID>`.
  Till skillnad från stegen ovan kontrolleras det vid varje anrop. Att bara skapa om API:et räcker inte för att stänga
  ute någon: en person som fortfarande står i listan och vars GitHub-inloggning fortfarande är giltig släpps in igen.
  För att en återkallad GitHub-auktorisering ska gälla direkt: återkalla den hos GitHub (nedan) och skapa om API:et, så
  töms minnet av tidigare GitHub-kontroller:

  ```bash
  docker compose --env-file selfhost.env up -d --force-recreate api
  ```

- Alla sessioner på en gång: byt `SIDEKICK_MCP_OAUTH_SIGNING_KEY` och skapa om API:et. Varje klient måste logga in igen.
- Ta också bort anslutningen i Claude, och återkalla OAuth-appen hos GitHub under Settings, Applications,
  Authorized OAuth Apps.
- Personliga åtkomsttoken gäller inte för den här stacken. Guiden kör `SIDEKICK_MCP_AUTH_MODE=github_oauth`, och i det
  läget accepterar `/mcp` bara GitHub-inloggningen som beskrivs ovan: en token från `sidekick-admin create-token` nekas
  med `401 invalid_token`, utan reservväg. Token fungerar bara i `SIDEKICK_MCP_AUTH_MODE=pat`, det lokala
  utvecklarläget ([QUICKSTART.md](../../QUICKSTART.md)), där ingen GitHub-inloggning finns. Vilket läge som
  gäller avgörs av den enda inställningen; det andra lägets inloggningsuppgifter fungerar aldrig.
  `sidekick-admin list-tokens --user-id <UUID>` och `revoke-token --token-id <ID>` (körs som kommandona ovan) hanterar
  token i utvecklarläget.
