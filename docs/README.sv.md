# Roadlake Sidekicks dokumentation

[English](README.md) · [Tillbaka till README](../README.sv.md)

Det här är kartan över dokumentationen som följer med Roadlake Sidekick. De flesta användarguider finns på svenska och
engelska; referensen, arkitekturposterna, besluten och guiden för kodagenter finns bara på engelska.

Ny här? Börja med en av de här:

- [Första starten på en server](start/self-hosted-server.sv.md): kör Sidekick på en server du själv styr.
- [Sidekick på jobbdatorn](start/work-laptop.sv.md): jobbpaketet, använt från Claude Desktop.
- [Samtalet och rummen](guide/README.sv.md): hur du arbetar med Sidekick när den är igång.

## Kom igång

| Dokument | Innehåll |
| --- | --- |
| [Välj din väg](start/README.sv.md) | Fyra sätt att börja: en egen server, en jobbdator, din första dag eller utveckling. |
| [Första starten på en server](start/self-hosted-server.sv.md) | Från en ren klon till en server som svarar: krav, hemligheter, bygge, ägare och kontroll. |
| [Sidekick på jobbdatorn](start/work-laptop.sv.md) | Jobbpaketet: Sidekick och ett privat minne i Docker på en bärbar dator, använt från Claude Desktop med stängd utgående nätverkstrafik. |
| [Din första dag med Sidekick](start/first-day.sv.md) | Ett samtal som tar dig genom alla fyra rummen. |
| [Kör Sidekick lokalt som utvecklare](start/first-contribution.sv.md) | Uppsättning från en klon, backend, en token med scopes och en första titt på rummen. |

## Användarguide

| Dokument | Innehåll |
| --- | --- |
| [Samtalet och rummen](guide/README.sv.md) | Hur du arbetar med Sidekick genom Claude, och vad varje rum är till för. |
| [Vanliga frågor](faq.sv.md) | Korta svar om kostnad, integritet, nycklar och anslutningar. |

## Driva en server

| Dokument | Innehåll |
| --- | --- |
| [Drift](operate/README.sv.md) | En karta över vad du gör när du driver en Sidekick-server. |
| [Anslut Claude](operate/connect-claude.sv.md) | Lägg till din server som anpassad connector och logga in med GitHub. |
| [Bygg, installera och para ihop Android](operate/pair-android.sv.md) | Installera den signerade APK:n från en release eller bygg appen ur källkoden, och koppla telefonen med en engångskod. |
| [Uppdatera](operate/update.sv.md) | Uppdatera från källkoden eller till en signerad image. |
| [Backup och återställning](operate/backup-and-restore.sv.md) | Krypterade backuper och att läsa tillbaka dem. |
| [Drift av jobbpaketet](operate/work-laptop/README.sv.md) | Nätverket, start vid inloggning, backup och uppdatering, modellservern och avinstallation. |

## Referens

| Dokument | Innehåll |
| --- | --- |
| [MCP-verktygsreferens](reference/mcp/index.md) (engelska) | Varje MCP-verktyg per område, med scopes och parametrar. Genererad ur kontraktet. |
| [Konfigurationsreferens](reference/configuration.md) (engelska) | Varje miljövariabel som backend läser. Genererad ur `Settings`. |
| [Kommandoradsreferens](reference/cli.md) (engelska) | Varje operatörskommando med sina argument. Genererad ur argumentparsrarna. |
| [Scopereferens](reference/scopes.md) (engelska) | MCP-scopes och companion-rättigheter, och vad som använder varje. |
| [Compose-profiler och filer](reference/selfhost-profiles.sv.md) | Vilka tjänster varje profil startar, och vad filerna i paketet är till för. |
| [Språk i rummen, appen och servern](reference/languages.sv.md) | Var varje språkinställning finns. |
| [Designsystem för MCP-appen](reference/design-system.md) (engelska) | De visuella reglerna och interaktionsreglerna för rummen och inbäddade kort. |

## Förklaring

| Dokument | Innehåll |
| --- | --- |
| [Så hänger delarna ihop](explanation/overview.sv.md) | Claude och Android-appen, en server med en uppsättning regler, och PostgreSQL som källan till sanningen. |
| [Säkerhet och integritet](explanation/security-and-privacy.sv.md) | Vem som ser vad, på vanlig svenska. |
| [Hotmodell](explanation/threat-model.md) (engelska) | Vad Sidekick skyddar, mot vem, och vilka kontroller som finns. |
| [Licens, licensnyckel och pris](explanation/licensing.sv.md) | Licensen på vanlig svenska, vad den frivilliga nyckeln gör och de planerade priserna. |
| [Schemabaslinjen 0.1.0](explanation/schema-baseline.sv.md) | Vad den enda baslinjemigreringen är och varför äldre installationer inte uppgraderas på plats. |
| [Backendens lager](explanation/architecture/backend.md) (engelska) | Hur backend är delad i lager, och vilka importer testerna förbjuder. |
| [MCP-appar som Sidekicks produktgränssnitt](explanation/architecture/mcp-apps.md) (engelska) | Hur rummen körs i Claude och på Android, och vad en vy får be värden om. |

## För bidragsgivare och underhållare

### Beslut

| Dokument | Innehåll |
| --- | --- |
| [Beslut och ADR:er](decisions/README.md) (engelska) | Så läser du beslutsloggen och arkitekturbesluten, med ADR-index. |
| [Beslutslogg](decisions/log.md) (engelska) | Produkt- och arkitekturbesluten som kod och dokument hänvisar till som `D-0xx`. |

### Bidra och underhålla

| Dokument | Innehåll |
| --- | --- |
| [Utvecklingsguide](contribute/development.sv.md) | Kontrollerna en ändring måste klara, hela testsviten, genererade filer och kodstil. |
| [Underhåll av Sidekick](maintainers/README.sv.md) | Att släppa en version, releaseövningen och protokollet över vad som har verifierats. |

### På andra ställen i repot

| Dokument | Innehåll |
| --- | --- |
| [Bidra](../CONTRIBUTING.sv.md) | Hur du rapporterar fel och förslag, och hur pull requests och CLA fungerar. |
| [Snabbstart för utvecklare](../QUICKSTART.sv.md) | En kort hänvisning till utvecklarsidorna. |
| [Säkerhetspolicy](../SECURITY.sv.md) | Hur du rapporterar en sårbarhet privat och vad som omfattas. |
| [Ändringslogg](../CHANGELOG.md) (engelska) | Märkbara ändringar per release. |
| [Licens](../LICENSE.md) (engelska) | Den bindande licenstexten: Sustainable Use License 1.0 med Roadlake Sidekicks tilläggsvillkor (källkoden är tillgänglig, men det är inte öppen källkod). |
| [Guide för kodagenter](../AGENTS.md) (engelska) | Repots konventioner, gränser och kontroller, skrivna för mänskliga och AI-bidragsgivare. |
| [Testdatabaspool](../tools/test-db-pool.md) (engelska) | Köra databastester parallellt utan att körningarna raderar varandras data. |
