# Att utveckla Sidekick med AI-agenter

[English](ai-native-development.md)

<!-- description: Så utvecklas Sidekick: en person styr produkten, arkitekturen och kvalitetskraven, AI-kodagenter skriver koden, och kontroller och daglig användning prövar den. -->

Sidekick utvecklas och underhålls av en person, Carl O Mattsson, och applikationskoden skrivs av AI-kodagenter. Den här sidan förklarar hur det går till, vilka kontroller som står bakom en ändring och var arbetssättet fortfarande är svårt.

Sidan handlar om agenterna som bygger Sidekick. Den AI du använder i Sidekick är något annat: Claude, som du pratar med genom ditt eget abonnemang, och de valfria funktioner som anropar en modell med din egen nyckel ([AI-kostnader](ai-costs.sv.md)).

## Utvecklingsmodellen

Carl skriver inte Sidekicks applikationskod. Arbetet görs i Claude Code. En huvudsession planerar arbetet och lämnar det till kodagenter, med modell efter uppgiftens svårighet: snabba modeller söker i koden, kör tester och uppdaterar dokumentation, och starkare modeller skriver kod, gör designarbete och tar hand om det som rör säkerhet. En separat agent granskar ändringar som ligger nära säkerheten, och testsviterna körs samlat på den integrerade grenen innan något pushas.

Att inte skriva kod för hand är inte detsamma som att slippa det tekniska arbetet. Någon måste veta hur systemet hänger ihop, välja mellan avvägningar och avgöra om beteendet är rätt. Den delen ligger kvar hos underhållaren.

Carl uppger att den privata utvecklingshistoriken rymmer fler än 10 000 commits och att det publika repot är en exporterad delmängd av den. Siffran är hans egen, och den säger ingenting om kvaliteten.

## Riktning och genomförande

Underhållaren bestämmer vad Sidekick ska göra och hur det ska bete sig, på den nivå där en användare märker skillnaden. Två exempel: en AI-plan godkänns av ägaren i appen, aldrig av modellen, och säkra förslag godkänns högst tre åt gången och går att ångra. Hur ett sådant krav blir komponenter, stilregler och databasfrågor får agenterna avgöra.

Att delegera så här är något annat än att ta emot vad som än kommer tillbaka. Ett krav kommer med begränsningar, resultatet provas i verklig användning, och håller det inte går det tillbaka med tydligare besked. Beslut om produkten, priset, publiceringen och licensen fattar underhållaren, och agenterna tar fram underlaget. Vilka förmågor som ska finnas och hur de ska fungera ihop är inte agenternas sak.

## Arkitektur och skrivna regler

En agent börjar varje uppgift utan minne av den förra. Det som följer med är det som står skrivet i repot, och därför finns reglerna där.

- **[AGENTS.md](../../AGENTS.md)** innehåller arkitekturreglerna för alla som ändrar koden, människa eller agent. Den viktigaste är att MCP-verktygen som Claude anropar och vägarna som Android-appen anropar använder samma användningsfall, så att en regel om ägarskap eller behörigheter skrivs en gång ([Så hänger delarna ihop](overview.sv.md)).
- **[Beslutsloggen](../decisions/log.md)** numrerar de produktbeslut som gäller i dag, och koden hänvisar till dem med nummer. Större tekniska beslut finns som arkitekturbeslut, till exempel [ADR-011](../decisions/adr/ADR-011-ai-delegated-steps.md).
- **Backendens lager** är beskrivna och testade ([Backend layering](architecture/backend.md), på engelska). Tester läser importerna och slår larm när till exempel en gränssnittsmodul går rakt på databaslagret.
- **Frontendens lintregler** hindrar ett rums mapp från att importera ett annat rums filer, håller en källfil under 500 rader och kräver att text som användaren ser hämtas ur etikettfilerna.

Där äldre kod bryter mot en regel står filen uppräknad som undantag, och listorna får bara krympa.

## Verifiering

**Konfigurerat.** I repot finns strikt typkontroll för Python och TypeScript, lint och formatering, tester för backend, frontend och Android-appen samt webbläsartester av rummen i en simulerad värd. Policytester täcker arkitekturen och migrationerna, ögonblicksbilder av MCP-verktygens kontrakt måste stämma med koden, och historiken genomsöks efter hemligheter ([utvecklingsguiden](../contribute/development.sv.md)).

**Körs.** Före en push kör `tools/check-all.sh` de här stegen lokalt. I det publika repot körs CI vid varje push till `main`, med trösklar för testtäckning, och CodeQL analyserar varje push. En release lägger till en granskning av beroendena, en sårbarhetsskanning av containerimagen och en övning som installerar, uppdaterar, säkerhetskopierar och återställer en installation i engångscontainrar. Därefter signeras imagen och Android-appens APK, och vem som helst kan kontrollera signaturerna ([Verifiera en release](../maintainers/release.sv.md#verifiera-en-release)).

**Verifierat.** Sidekick används dagligen med Claude, med Android-appen på en riktig telefon och på Linux. macOS är inte provat.

Inget av detta gör AI-skriven kod säker eller korrekt i sig. Kontrollerna fångar vissa sorters fel, som en typ som inte passar, en korsad gräns eller en läckt hemlighet. De kan inte säga om en funktion gör det en människa behöver, och varje rad läses inte av en människa.

## En ändring från början till slut

En typisk ändring börjar med ett problem som underhållaren har märkt eller en förmåga han vill ha, beskrivet med sina begränsningar. Agenter läser in sig på den befintliga koden och genomför ändringen inom arkitekturen. Kontrollerna körs, resultatet provas i verklig användning och underhållaren ger nya besked tills det duger. Sedan dokumenteras ändringen och kommer med i en release.

[Issue #53](https://github.com/CarlOMattsson/roadlake-sidekick/issues/53) visar det i ett verkligt fall. Det gäller AI-steg ([issue #26](https://github.com/CarlOMattsson/roadlake-sidekick/issues/26)), där Claude utformar en plan och ägaren godkänner den i appen.

1. **En rapport ur verklig användning.** Carl tryckte på Godkänn plan i appvyn i en av Claudes skrivbordsklienter och fick ett behörighetsfel.
2. **En första rättning.** En misstänkt orsak togs bort, och statusnoteringen sade att rättningen inte var verifierad i en riktig värd.
3. **Ett prov i en riktig värd.** Felet fanns kvar. Serverloggarna visade varför: värden tappade den märkning som appen sätter på sina anrop, och servern förlitade sig på märkningen för att skilja appen från modellen.
4. **En ny design.** En nyckel som skickas som ett vanligt argument skulle inte räcka, eftersom också modellen kunde hämta den. Servern ger nu appen ett signerat beslutsbevis för engångsbruk, i metadata som modellen inte får se. Samma bevis täcker automationer och grupper av förslag ([issue #40](https://github.com/CarlOMattsson/roadlake-sidekick/issues/40)).
5. **Tillbaka till verklig användning.** Ändringen genomfördes, granskades och slogs ihop. När detta skrevs var issuet fortfarande öppet: designen räknas inte som verifierad förrän den har fungerat i den värd där felet hittades.

Den första rättningen nådde `main`, och felet fanns kvar. Det hittades för att en människa använde funktionen.

## Vad det möjliggör och vad som förblir svårt

En person kan hålla en backend, rummen i Claude, en Android-app och dokumentation på två språk i rörelse samtidigt. En idé kan provas som fungerande programvara kort efter att den har beskrivits, och ett andra angreppssätt när det första inte håller.

Det här är det svåra:

- **Enhetlighet.** Agenter följer de mönster de kan se. En regel som bara finns i någons huvud följs inte.
- **Regressioner och komplexitet.** Sviterna fångar bara det som någon har kommit på att testa. Kod är billig att ta fram och blir därför lätt för mycket, och systemet är större än vad en person hinner läsa om. Storleksgränserna och de krympande undantagslistorna håller emot.
- **Resultat som bara ser rätt ut.** En ändring kan klara varje kontroll och ändå inte fungera för den som använder den. Att upptäcka det tar underhållarens tid.

## Vem som står bakom

Carl O Mattsson har skapat Sidekick och underhåller det. Hans del är produktens riktning, arkitekturen, interaktionsdesignen, kraven och bedömningen av kvaliteten. Det är han som ansvarar för det som släpps.

## Ett pågående experiment

Sidekick är i första hand en produkt. Det är också ett praktiskt prov på hur mycket sammanhängande och användbar programvara en person kan bygga och underhålla när AI-agenter står för genomförandet och en människa för riktningen.

Projektet har tillgänglig källkod (source available) men är inte öppen källkod ([Licens, licensnyckel och pris](licensing.sv.md)), så koden, reglerna, kontrollerna och issuen finns att läsa. Den här sidan påstår inte att arbetssättet passar alla projekt eller ersätter ett team. Den beskriver vad som har fungerat här hittills, och vad som inte har gjort det.
