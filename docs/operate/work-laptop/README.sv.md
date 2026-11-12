# Drift av jobbpaketet

[English](README.md)

<!-- description: Jobbpaketet körs lokalt mot Claude Desktop och har ett stängt nätverk, så det har egna driftguider. -->

Jobbpaketet körs lokalt mot Claude Desktop och har ett stängt nätverk, så det har egna driftguider.

- [Så är nätet stängt](network.sv.md): containrarna har ingen väg ut, och hur du tillåter fler adresser.
- [Start vid inloggning](start-at-login.sv.md): låt Sidekick starta när du loggar in.
- [Säkerhetskopia och uppdatering](backup-and-update.sv.md): krypterade säkerhetskopior, uppdatering och att gå tillbaka.
- [macOS](macos.sv.md): vad som skiljer sig från Linux.
- [Modellservern](model-server.sv.md): vad servern måste klara och hur du ställer in den.
- [Stoppa och avinstallera](uninstall.sv.md): stoppa Sidekick eller ta bort allt.

## Rum

Bara de rum du behöver kan vara på. Guiden frågar vilka rum du vill ha och föreslår alla utom inköp:
`SIDEKICK_ENABLED_ROOMS=work,journal,contacts,control` i `deploy/work/work.env`. Tryck Enter för förslaget, eller svara `-` för att slå på alla rum. Listan måste innehålla `work` (Sidekick startar inte utan det);
övriga rum är `journal`, `shopping`, `contacts` och `control`. Värdet läggs i api-containerns miljö, så både HTTP-ytan och
stdio-processen som Claude Desktop startar (den körs i samma container) visar samma rum. Ändra raden och kör
`bash tools/work.sh start` igen.

| Rumsvärde | Vad det innehåller |
| --- | --- |
| `work` | Arbete: agenda, statustavla, områden, rutiner/processer, projekt, uppgifter och steg. Krävs. |
| `journal` | Dagbok: daterade anteckningar, källor och granskning av utkast. |
| `shopping` | Inköp: listor, varor och avbockning av köp. |
| `contacts` | Kontakter: personer, kontaktuppgifter och kopplingar till arbetsposter. |
| `control` | Kontroll: papperskorg och återställning, senaste ändringar och reglage för härlett minne. |

Till exempel slår `SIDEKICK_ENABLED_ROOMS=work,contacts,control` på tre rum. Att stänga av ett rum döljer dess
navigering och MCP-verktyg och utesluter dess poster från läsningar över rumsgränser, som sök; befintliga data behålls.
En tom eller borttagen inställning slår på alla rum. Genvägen `-` gäller i `setup`, inte som inställningsvärde.

## Telefon

En lokal MCP-server nås inte från Claude på telefonen, eftersom telefonappen kräver en connector med publik adress.
Någon mobilväg finns inte i den här versionen.
