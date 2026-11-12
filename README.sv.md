<p align="center"><img src="assets/brand/sidekick-favicon.svg" width="112" height="112" alt="Appikonen för Roadlake Sidekick: en väg som svänger runt en sjö."></p>

# Roadlake Sidekick

<p align="center">
<!-- release badges are added with the first release (v0.1.0) -->
<a href="LICENSE.md"><img src="https://img.shields.io/badge/license-Source%20Available-blue" alt="Licens: Source Available"></a>
<a href="https://roadlake.com"><img src="https://img.shields.io/badge/web-roadlake.com-informational" alt="Webbplats: roadlake.com"></a>
</p>

Roadlake Sidekick är en personlig assistent som du kör på din egen server: du frågar Claude om dina uppgifter, din dagbok, dina kontakter och dina inköp, och din data stannar i din egen databas.

[English](README.md) · [Dokumentation](docs/README.sv.md) · [Snabbstart](QUICKSTART.sv.md) · [Licens](LICENSE.md) · [Bidra](CONTRIBUTING.sv.md) · [Säkerhet](SECURITY.sv.md) · [Beslut](docs/decisions/log.md)

> **Status: första versionen, ännu inte släppt.** Version 0.1.0 har ingen tagg än, så tills vidare bygger du containerimagen
> och APK:n från det här repot. Från och med första releasen har varje release en signerad image och en signerad APK. Den används dagligen med Claude, med Android-appen på en riktig
> telefon och på Linux; macOS är ännu inte provat.
> Detaljer: [docs/maintainers/release.md](docs/maintainers/release.md) (på engelska) och [docs/maintainers/release.sv.md](docs/maintainers/release.sv.md).

Roadlake Sidekick är ett självhostat, MCP-först personligt operativsystem för arbete och uppgifter, dagbok, inköp och
kontakter. Du pratar med det via Claude, och interaktiva MCP-appar (rum) öppnas i samtalet när du vill arbeta
med resultatet. En Android-app använder samma poster på din server.

Sidekick är **AI-först**: många ändringar görs genom att be Claude i stället för i ett formulär för varje fält.
Rummen ger direkta kontroller för de arbetsflöden som stöds, och allt lagras som varaktiga poster i din egen
PostgreSQL-databas.

## Vad du får

| Område | Funktioner |
| --- | --- |
| **Arbete** | Agenda, statustavla, domäner, processer, projekt, uppgifter och steg; datum, prioritet, taggar, uppskattning, väntar-på och återkommande arbete. |
| **Dagbok** | Flera anteckningar per dag, egen skrivning och redigering, anteckningar och sammanfattningar skrivna av Claude, länkad kontext. |
| **Kontakter** | Personer, organisationer, roller, kontaktvägar och relationsanteckningar, länkade till uppgifter, projekt och dagboksanteckningar. |
| **Inköp** | Listor, mängder, butiksgrupper, avprickning och ångra. |
| **Kontroll** | Papperskorg och återställning, senaste ändringar och kontroller för Sidekicks minne. Permanent radering är inget publikt verktyg. |
| **Minne** | Valfritt Hindsight-minne härlett från dina poster, med omkopplare per källa, paus och undantag per post. |
| **Android** | Parkoppling, en Idag-widget, rummen Arbete, Dagbok och Inköp, påminnelser via UnifiedPush (ntfy). |

MCP-appernas texter är på svenska som standard (`SIDEKICK_MCP_APP_LOCALE=sv`); sätt `SIDEKICK_MCP_APP_LOCALE=en` på
servern för engelska. Android-appen har en egen språkinställning; se [Språk](docs/reference/languages.sv.md#android-appen).

## Prata igenom dagen med Claude

Det effektivaste sättet att använda Sidekick är att prata med Claude i röstläget medan du går, cyklar eller kör bil. Du behöver inte diktera kommandon: låt Claude fråga om dagen och berätta fritt om det du har i huvudet. Ett samtal på tio minuter brukar ge en hel del uppgifter, dagboksanteckningar och kopplingar, och tankarna som snurrar får komma ur huvudet.

- Börja till exempel med: "Fråga mig hur dagen har varit och hjälp mig få ordning på allt jag behöver göra."
- Claude ställer följdfrågor om vem det gäller, när något ska vara klart och vad som hänger ihop. Sedan skapar Claude uppgifter, dagboksanteckningar och kontakter i Sidekick och kopplar ihop dem.
- Med andra connectors i Claude kan Claude dessutom gå igenom Slack, e-post och kalender för att lägga till uppgifter du missat och boka möten.
- Prata bara när det är säkert, till exempel handsfree i bilen.

## Vad Claude kan göra

Claude arbetar genom en kurerad uppsättning MCP-verktyg, så du frågar på vanlig svenska och Claude väljer verktyget. Kärnverktygen per rum (alla finns i [MCP-verktygsreferensen](docs/reference/mcp/index.md), på engelska):

- **Överblick:** `get_today_brief` för det som är viktigt idag, `search` över dina poster, `list_recent_changes` för vad som ändrats.
- **Arbete:** `get_work_agenda` och `get_work_board`, `list_tasks`, `create_task` och `update_task`, samt steg, projekt och processer.
- **Dagbok:** `write_journal_entry`, `get_journal_day` och `list_journal_entries`, och `set_daily_journal_summary` för dagens sammanfattning.
- **Kontakter:** `list_contacts`, `create_contact` och `get_contact_context`, med länkar till uppgifter och projekt.
- **Inköp:** `get_shopping_list`, `add_shopping_items` och `set_shopping_items_purchased`.
- **Kontroll och minne:** `move_to_trash` och `restore_from_trash`, och `recall_memory` när det valfria minnet är på.

## Så ser det ut

Rummen på svenska, som är standardspråket, med påhittade exempeldata i en simulerad värd:

<table>
  <tr>
    <td align="center" valign="top"><img src="docs/images/rooms/work-status-board-dark.png" width="200" alt="Rummet Arbete, statustavlan i mörkt läge, med gruppen Att göra och påhittade uppgifter."><br><strong>Arbete</strong><br>Statustavlan i mörkt läge</td>
    <td align="center" valign="top"><img src="docs/images/rooms/journal-day.png" width="200" alt="Rummet Dagbok med en dag, veckonavigering, en dagssammanfattning och en anteckning."><br><strong>Dagbok</strong><br>En dag med sammanfattning</td>
    <td align="center" valign="top"><img src="docs/images/rooms/contact.png" width="200" alt="Rummet Kontakter med en påhittad leverantör, roll, organisation och anteckningar."><br><strong>Kontakter</strong><br>En person i sitt sammanhang</td>
    <td align="center" valign="top"><img src="docs/images/rooms/shopping-list.png" width="200" alt="Rummet Inköp med en lista grupperad per butik, avprickningsförlopp och mängder."><br><strong>Inköp</strong><br>En lista per butik</td>
  </tr>
</table>

## Så hänger det ihop

Claude och Android-appen pratar med en och samma Sidekick-server. Servern tillämpar samma regler för varje anrop och lagrar dina poster i PostgreSQL, med valfritt minne och påminnelser runt omkring. [Så hänger delarna ihop](docs/explanation/overview.sv.md) förklarar varje del, med ett diagram.

## Kör Sidekick

Det finns två sätt. Välj efter var Claude ska köra.

**1. Lokalt på din dator (enklast).** Sidekick och databasen körs i Docker på din egen dator, och du använder det från Claude Desktop via en lokal MCP-server. Allt Sidekick lagrar och kör stannar på din dator.

- Du behöver ingen publik adress, domän, TLS-certifikat eller GitHub-konto, och den här vägen har ingen telefonåtkomst.
- Du behöver Linux eller macOS med Docker (otestat på macOS, se [anteckningarna om macOS](docs/operate/work-laptop/macos.sv.md)) och Claude Desktop.
- Bara för det valfria privata Hindsight-minnet behöver du också adressen till en OpenAI-kompatibel modellserver. Uppsättningen frågar först om du vill slå på minnet; förvalet är nej, och då behövs ingen modellserver.
- Rummen väljer du själv. Det du gör i Claude Desktop delas fortfarande med Claude.
- Guide: [Sidekick på jobbdatorn](docs/start/work-laptop.sv.md) (engelska: [Sidekick on a work laptop](docs/start/work-laptop.md)), startas med `bash tools/work.sh setup`.

**2. Egen server som Claude når på webben och i mobilen.** Du kör Sidekick på en Linux x86_64-dator med Docker Compose, en VPS eller en hemdator som alltid är på. Den här vägen kräver en Claude-plan som stöder egna connectors, en publik HTTPS-adress till servern (en domän eller en tunnel dit) och ett GitHub-konto (används för inloggning). Det är också vägen för Android-appen. Guide: [Första start på en server](docs/start/self-hosted-server.sv.md#första-start).

Sidekick skickar ingen telemetri eller analys; det kontaktar bara de tjänster du själv konfigurerar (GitHub-inloggning, push och modelltjänsten för det valfria Hindsight-minnet).

### Mer om den självhostade servern

- **Självhostad server:** [deploy/selfhost/](deploy/selfhost/) börjar med
  `git clone https://github.com/CarlOMattsson/roadlake-sidekick.git`, kopierar sedan `*.example`-filerna,
  genererar dina hemligheter, skapar ägaren och registrerar GitHub-inloggningen före första `up`. Profiler: `vps` (Caddy
  terminerar TLS på din domän) eller ingen (hemma: ordna en egen publik HTTPS-tunnel till `127.0.0.1:8000`).

  Claudes fjärranslutning kräver ett **publikt HTTPS-ursprung**; enbart åtkomst i lokalnätet räcker inte.
  Valfria profiler: `memory` (privat Hindsight), `backup` (krypterade ägarexporter) och `push` (påminnelser via
  en härdad egen ntfy). `update.sh` kör som standard en torrkörning och verifierar en signerad, digest-låst
  image innan något tillämpas. Backuper omfattar ägarens produktdata, inte en hel serverimage; ta en kopia
  utanför servern. Hur du kopplar Claude till den körande servern står i
  [Anslut Claude](docs/operate/connect-claude.sv.md). Hur du parar Android-appen står i
  [Android-app](docs/operate/pair-android.sv.md).
- **Utvecklare:** Sidekick kan också köras som en lokal stdio-MCP-server för Claude Desktop från en källkodskopia; se steg 4 i [Kör Sidekick lokalt som utvecklare](docs/start/first-contribution.sv.md).
- **Android-appen:** från och med första releasen installerar du den signerade APK:n som ligger i GitHub-releasen, eller
  bygger appen från det här repot (JDK 21, Android SDK 36, Node.js 22), och parar ihop den med din server; se [Bygg, installera och para ihop Android](docs/operate/pair-android.sv.md).

## Utveckla

Du behöver Python 3.13 med `uv`, Node.js 22 / npm 10 och Docker (för PostgreSQL).
Alla steg finns i [Kör Sidekick lokalt som utvecklare](docs/start/first-contribution.sv.md):

```bash
git clone https://github.com/CarlOMattsson/roadlake-sidekick.git
cd roadlake-sidekick
[ -f .env ] || cp .env.example .env
uv sync --project backend --all-groups
npm --prefix frontend ci
docker compose -f deploy/compose.dev.yaml up -d db
uv run --project backend yoyo apply --batch \
  --database postgresql+psycopg://sidekick_migrator:sidekick_migrator@127.0.0.1:55440/sidekick migrations
uv run --project backend uvicorn sidekick.api.app:create_app --factory --reload --no-access-log   # från repo-roten
npm --prefix frontend run build:mcp-app   # bygger om den incheckade MCP-appresursen
```

Sidekick är en modulär Python-monolit. De kurerade FastMCP-verktygen och companion-routerna för Android-appen
anropar samma applikationsfall; PostgreSQL äger poster, identitet och varaktiga händelser. Konventionerna för
bidragsgivare och kodagenter finns i [AGENTS.md](AGENTS.md), och hur du rapporterar en bugg eller ett förslag står i
[CONTRIBUTING.sv.md](CONTRIBUTING.sv.md) (pull requests är välkomna, med CLA, men hanteras i begränsad omfattning); kontrollerna finns i [utvecklingsguiden](docs/contribute/development.sv.md). Besluten som koden kallar `D-0xx` finns i
[docs/decisions/log.md](docs/decisions/log.md).

## Säkerhet

Identiteten fastställs av servern, med ägarfiltrering och uttryckliga scopes på varje anrop. Loggar och
spårning innehåller varken användartext eller inloggningsuppgifter. Claude kan läsa det innehåll som
anslutningens scopes tillåter, även dagbokstext; självhosting håller inte innehållet borta från Claude eller
en minnes-/modelleverantör du själv konfigurerar. Checka aldrig in ifyllda `.env`-filer eller hemligheter.
Sårbarheter rapporteras privat, enligt [SECURITY.sv.md](SECURITY.sv.md).

## Licens

Sidekick är **source available**, inte öppen källkod. Det licensieras under **Roadlake Sidekick Source Available License**, som är
Sustainable Use License 1.0 med Roadlake Sidekick Additional Terms; det bindande licensvillkoret (på engelska) står i [LICENSE.md](LICENSE.md). I korthet:
du får använda och ändra det för din egen interna verksamhet eller för icke-kommersiellt och personligt bruk,
och sprida det kostnadsfritt för icke-kommersiella ändamål. Du får betala en konsult eller byrå för att
installera, anpassa och sköta det på din egen installation, men ingen får sälja det eller erbjuda det som
hostad tjänst. En licensnyckel verifieras offline; den behövs
aldrig för att utöva en rättighet enligt licensen, men utan giltig nyckel visar programvaran en
obetald-notis, och en giltig nyckel tar bort den; notisen får inte tas bort eller döljas, och
nyckelkontrollen får inte kringgås. Sammanfattningen är inte licensen: texten i `LICENSE.md`
gäller. Licensen på vanlig svenska, hur du anger en nyckel och de planerade priserna finns i [Licens, licensnyckel och pris](docs/explanation/licensing.sv.md).
Tredjepartskomponenter behåller sina egna licenser; de förtecknas i [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) (på engelska).

### Licensnycklar

En licensnyckel är valfri och kontrolleras offline; utan nyckel visar programvaran en obetald-notis, och inget annat ändras. Operatörer sparar en nyckel med `python -m sidekick.license.cli set` och kontrollerar den med `python -m sidekick.license.cli show`. Hur nycklar verifieras, vilken publik nyckel instansen använder och hur du kontrollerar uppsättningen står i [Ange en licensnyckel](docs/operate/license-key.sv.md#så-kontrolleras-nyckeln); sammanfattningen på vanlig svenska och priserna finns i [Licens, licensnyckel och pris](docs/explanation/licensing.sv.md).
