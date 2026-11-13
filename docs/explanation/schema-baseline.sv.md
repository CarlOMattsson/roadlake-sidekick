# Schemabaslinjen 0.1.0

[English](schema-baseline.md)

<!-- description: Sidekick 0.1.0 skapar databasen från en enda baslinje. Vad det betyder för nya installationer och varför äldre inte uppgraderas på plats. -->

Sidekick 0.1.0 skapar databasen från en enda baslinje. Här står vad det betyder för nya installationer och varför äldre installationer inte uppgraderas på plats.

## Vad baslinjen är

Katalogen `migrations/` börjar med `100_schema_baseline_0_1_0.py`. Den skapar hela schemat i en tom databas: tabeller,
villkor, index, behörigheter och standardbehörigheter, med Sidekicks namn på schema, roller och databas (`sidekick`,
`sidekick_owner`, `sidekick_migrator`, `sidekick_app`). Nya migreringar numreras från `106_`, eftersom `101` till `105` är upptagna av den invikta kedjan i äldre databasers migreringslogg.

- Den skapar schemat i en tom databas. I en databas som redan har ett `sidekick`-schema skapar den ingenting: den
  känner antingen igen eller uppgraderar databasen (se nästa avsnitt) eller vägrar med ett meddelande och ändrar ingenting.
- Den kan inte rullas tillbaka: det skulle ta bort varje ägartabell. Vägen tillbaka är en säkerhetskopia.
- Kedjan den ersätter levereras inte.
- Tabellerna för funktioner som togs bort före 0.1.0 (den tidigare inbyggda chatten, livesamtal med röst,
  agentkörningen, assistentens autonomiinställning och inställningarna för den avvecklade skrivbordsappen) skapas inte
  (besluten D-082 och D-084).
- Resterna av den borttagna webbinloggningen (tabellen `sessions` och kolumnen `users.password_hash`) skapas inte
  heller.

## Den invikta utvecklingskedjan

Före första releasen byggdes schemat av `100_baseline_0_1_0.py` följd av fem migreringar: `101` (två index på `tasks`),
`102` (händelseloggen och aktivitetsprojektionen blev append-only för appens roll), `103` (raderingsrätt på `domains`
och `processes`), `104` (`audit_events.source`) och `105_drop_sessions_and_password_hash` (inloggningsresterna). De
viktes in i den här baslinjen, som alltså bygger det schema de slutade i; ett test binder det till det incheckade
fingeravtrycket. De gamla filerna levereras inte, men en installation, ägarens, hade tillämpat dem.

Baslinjen avgör utifrån databasens egen bokföring (`public._yoyo_migration`):

| Databas | Vad baslinjen gör |
| --- | --- |
| Inget `sidekick`-schema | Skapar schemat. |
| `sidekick`-schema och `105_drop_sessions_and_password_hash` tillämpad | Ingenting: schemat är redan detta. yoyo bokför baslinjen som tillämpad; ingen tabell, rad eller behörighet rörs. |
| `sidekick`-schema och ett prefix av kedjan tillämpat (`100_baseline_0_1_0`, eller den och `101` till `104`, i ordning) | Kör exakt de saknade stegens satser, ordagrant från de invikta migreringarna, i samma transaktion, och därefter samma kontroller som ovan; vid fel rullas allt tillbaka. Bara baslinjen bokförs; de id:n som redan finns står kvar. |
| Allt annat: ett hål i kedjan, ett okänt id eller inget id alls | Vägrar med de tillämpade id:na och vad som ska göras, ändrar ingenting och bokför ingenting. |

En databas som stod på `102` när kedjan viktes in får satserna från `103`, `104` och `105` (raderingsrätter,
`audit_events.source`, borttagning av `sessions` och `users.password_hash`, vilket tar bort eventuella kvarvarande
sessioner och lösenordshashar) och behåller all övrig data. En databas som vägras byggs om från en tom databas med
en återställning via `sidekick-backup import`. Exporter och säkerhetskopior stämplade med något av de gamla id:na
godtas fortfarande av importen.

## Migrering 106: de avvecklade automationstabellerna

`106_drop_retired_automation_tables.py` tar bort `assistant_automation_policies`, `assistant_automation_control`,
`assistant_automation_runs` och `assistant_task_review_findings`, som baslinjen fortfarande skapar (installationer har
redan kört den, så den ändras inte). Inget skriver eller läser dem längre, så de är tomma. Migreringen vägrar, med
tabellen utpekad och utan ändringar, om någon av dem innehåller en rad, och den kan inte rullas tillbaka. Kolumnen
`domain_events.automation_run_id` och huvudbokens typ `automation_run` finns kvar. Ägarexporten tappade också de fyra
samlingarna (format 5); en export i format 4 läses fortfarande, och vägras om någon av de samlingarna inte är tom.

## Ändra schemat: det incheckade fingeravtrycket

`backend/tests/fixtures/baseline-catalogue.json` är schemats fingeravtryck: efter `yoyo apply` på en tom databas de
sorterade raderna ur `pg_catalog` för tabeller, kolumner (typ, nullbarhet, standardvärde), villkor, index, funktioner,
triggers, policyer, ägare, behörigheter och standardbehörigheter, utan OID:er. Testet
`test_a_fresh_install_matches_the_checked_in_schema_fingerprint` (`backend/tests/integration/test_migration_baseline.py`)
misslyckas med en diff över de rader som skiljer när en migrering ändrar schemat utan fingeravtrycket. En migrering
som ändrar schemat checkar därför in den omgenererade filen i samma commit:

```
eval "$(bash tools/test-db-pool.sh env N)"
SIDEKICK_UPDATE_BASELINE_SNAPSHOT=1 backend/.venv/bin/python -m pytest backend/tests/integration/test_migration_baseline.py \
  -k checked_in_schema_fingerprint --full
git diff backend/tests/fixtures/baseline-catalogue.json   # granska: exakt den avsedda ändringen
```

Allt som MCP-apparna och Android-appen använder finns i baslinjen: uppgifter, projekt, domäner, steg, dagboken,
kontakter, inköpslistor, minnesbokföring, aktivitetsloggen och automation, push, licensen och token.

## Andra driftsättningar

En driftsättning med egna skript gör likadant: börja från en tom databas, kör `yoyo apply` med migrerarrollen
(baslinjen `100_schema_baseline_0_1_0.py` och de numrerade migreringarna efter den, i ordning), skapa ägaren och importera. Inget behöver markeras eller lagas för hand.
