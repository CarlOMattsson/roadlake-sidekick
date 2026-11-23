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
  agentkörningen, assistentens autonomiinställning och inställningarna för den avvecklade skrivbordsappen) skapas inte.
- Resterna av den borttagna webbinloggningen (tabellen `sessions` och kolumnen `users.password_hash`) skapas inte
  heller.

## Den invikta utvecklingskedjan

Före första releasen byggdes schemat av `100_baseline_0_1_0` följd av fem migreringar: `101` (två index på `tasks`),
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

## Migrering 107: taggar på kontakter och dagboksposter

`107_contact_and_journal_entry_tags.py` är en additiv (expand) migrering. Den skapar länktabellerna `contact_tags` och
`journal_entry_tags`, formade som `task_tags`: en rad per tagg och post, där taggen och posten har samma ägare
(sammansatta främmande nycklar) och försvinner med någon av dem. Taggordlistan `work_tags` delas av alla sorters poster.
En återrullning tar bara bort de två länktabellerna. Ägarexporten bär dem som två nya samlingar (format 6); en export i
format 5 har inga och återställs utan taggar.

## Migrering 108: glömda fakta

`108_memory_forgotten_facts.py` är en additiv (expand) migrering för att glömma ett enskilt minnesfaktum. Den skapar
`memory_forgotten_facts` (en rad per påstående som ägaren bett Sidekick sluta använda, med bara en saltad kontrollsumma av
det normaliserade påståendet och aldrig dess text) och `memory_forgotten_units` (de faktaid hos minnestjänsten som bär ett
sådant påstående, och hur långt döljandet har kommit: avstämningspassets kö). En enhet kan bara höra till en ägares
påstående och källrad (sammansatta främmande nycklar, vilket krävde en unik nyckel på `memory_sources (id, owner_id)`).
Den lägger också till den nullbara `memory_settings.forget_salt`, ägarens salt för kontrollsumman. Återställning tar bort
de två tabellerna, kolumnen och nyckeln, vilket kastar alla glömda påståenden som gjorts sedan dess; ingen post eller
inställning rörs. Ägarexporten tar ännu inte med de nya tabellerna eller saltet.

## Migrering 109: när en uppgift senast gicks igenom

`109_task_last_reviewed_at.py` är en additiv (expand) migrering. Den lägger till den nullbara `tasks.last_reviewed_at`,
tidpunkten då ett beslut i en genomgång senast rörde uppgiften; befintliga uppgifter räknas som aldrig genomgångna. En
återrullning tar bara bort den kolumnen. Ägarexporten bär den på varje uppgiftsrad (format 7); en export i format 6 har
ingen sådan kolumn, och dess uppgifter återställs som aldrig genomgångna.

## Migrering 110: en uppgift som ambition

`110_task_ambition.py` är en additiv (expand) migrering. Den lägger till den nullbara `tasks.ambition_since`,
tidpunkten då ägaren valde att ha uppgiften som en ambition: synlig, men aldrig daterad, genomgången eller påmind om.
Befintliga uppgifter räknas som vanliga uppgifter. En återrullning tar bara bort den kolumnen, så varje ambition blir
en vanlig odaterad uppgift. Ägarexporten bär den på varje uppgiftsrad (format 7, som släpps första gången med den
kolumnen); en export i format 6 har ingen sådan kolumn, och dess uppgifter återställs som vanliga uppgifter.

## Migrering 112: AI-steg

`112_ai_steps.py` är en additiv (expand) migrering för steg som Claude Code får köra. Den lägger till
`tasks.ai_possible_since` (markeringen), `tasks.ai_plan_digest` och `tasks.ai_plan_approved_at` (den godkända planen, båda
satta eller båda NULL) och `tasks.ai_task_cap_microusd` (utgiftstaket, NULL för instansens förval). Den lägger till
`steps.performer`, som är `owner` för alla befintliga steg, och `steps.ai_spec`, som bara ett AI-steg bär. Den nya tabellen
`ai_step_runs` håller en rad per försök. Applikationsrollen får läsa, lägga till och uppdatera den men inte radera: migreringen
återkallar DELETE, eftersom standardbehörigheterna annars skulle ge den. En rad försvinner bara tillsammans med sitt steg
eller sin uppgift när de raderas för gott. En återrullning tar bort kolumnerna och tabellen, vilket bara förlorar AI-datan.
Ägarexporten bär dessa kolumner och samlingen `ai_step_runs` (format 8); en export i format 7 har ingen av dem och
återställer sina steg som ägarens egna.

## Migrering 113: serverköns index

`113_ai_server_queue.py` är en rent additiv (expand) migrering. Den lägger till ett partiellt index,
`ix_ai_step_runs_server_queue`, på `ai_step_runs (lease_until)` för serverkörningar, så att AI-workern snabbt hittar köade och
avstannade körningar. Inga data flyttas och inga behörigheter ändras. En återrullning släpper indexet.

## Migrering 114: kostnader för raderade körningar

`114_ai_erased_run_costs.py` är en additiv (expand) migrering. En körning lämnar `ai_step_runs` tillsammans med sitt steg
eller sin uppgift när de raderas permanent, så månadstaket och dagsgränsen för starter skulle glömma vad den kostade. Den
nya tabellen `ai_erased_run_costs` behåller per raderad körning bara identifierare och siffror: körningen, dess ägare och
uppgift, körsätt, kostnadskälla, kostnaden (plus en reservation som ännu hölls) och skapandetid. En `BEFORE DELETE`-trigger
på `ai_step_runs` skriver raden genom en funktion som körs med schemaägarens rättigheter, så applikationsrollen får bara
läsa tabellen. När ägarens konto självt raderas skriver triggern ingenting, och främmande nyckeln tar bort de rader som
redan sparats. En återrullning släpper triggern, funktionen och tabellen, vilket bara förlorar de kostnaderna. Ägarexporten
innehåller inte tabellen.

## Migrering 115: en kontakts Slack-profil

`115_contact_slack_profile.py` är en additiv (expand) migrering. Den lägger till den nullbara `contacts.slack`, den
normaliserade länken till kontaktens Slack-profil (`https://<arbetsyta>.slack.com/team/<medlems-id>`), som programmet
kontrollerar innan den lagras. Befintliga kontakter läses som utan Slack-profil. Ägarexporten bär den i varje kontaktrad
(format 8, som ännu inte hade getts ut); en export i format 7 saknar kolumnen och dess kontakter återställs utan
Slack-profil. En återrullning släpper kolumnen, vilket bara förlorar de länkar som lagts in sedan dess.

## Migrering 116: automationer

`116_automations.py` är en additiv (expand) migrering. Den lägger till sex tabeller för automationer: `automations`
(ägarens register: instruktion, tillåtna effekter, schema, godkännande, en utgiftsgräns på en US-dollar per körning som
förval och `model_tier`, `standard` eller `strong`), `automation_runs` (en rad per försök vid ett tillfälle, också
serverkörarens kö; ett försök per tillfälle är aktivt åt gången), `automation_datapoints` (fakta som en körning läste,
aldrig åtgärder), `automation_suggestions` (beslutskort), `automation_checks` (en rad per oberoende kontroll, koder ur
en sluten mängd och ingen fri text) och `automation_report_cursors`. Definitionens digest (`spec_digest`, som omfattar
`model_tier`) räknas av applikationen. Applikationsrollen får läsa, lägga till och ändra raderna men inte radera
något, och `automation_checks` är bara-tillägg; en rad försvinner först med ägarens konto, genom främmande nycklar. Ingen
data flyttas. En återställning släpper de sex tabellerna och förlorar bara automationsdata. Ägarexporten bär ännu inte
tabellerna.

## Migrering 117: fotometadata

`117_journal_attachments.py` är en additiv (expand) migrering. Den lägger till `journal_attachments`, en rad per foto på
en dagboksanteckning eller en dagboksdag: typen (JPEG eller WebP), storleken i byte (högst 4 MiB), måtten (högst 4096
px), SHA-256-avtrycken för den lagrade filen och dess miniatyr, valfri alternativtext med vem som skrev den (`you` eller
`claude`), tidpunkten då fotot togs när klienten skickade den, och positionen. Ett foto hör till exakt en av en
anteckning (`entry_id`) eller en dag (`journal_date`); CHECK-villkor håller alla gränser, så databasen vägrar en rad som
programmet aldrig borde skriva. Själva bytena ligger inte i PostgreSQL. Till skillnad från `journal_entries` har
programrollen `DELETE` på tabellen, eftersom ett foto kan raderas ur papperskorgen; den har inga DDL-rättigheter och
inget `TRUNCATE`. En rad försvinner med sin ägare eller anteckning via främmande nycklar. Fotots papperskorgsslag är
`journal_attachment`; foton går aldrig till minnet. Ägarexporten bär ännu inte tabellen. En återrullning släpper
tabellen, vilket bara förlorar fotometadatan.

## Migrering 124: fotodetaljer

`124_journal_attachment_details.py` är en additiv (expand) migrering. Den lägger till fem nullbara kolumner i
`journal_attachments`: platsen där fotot togs (`location_lat`, `location_lon` och ett valfritt `location_name`),
`camera` och filens `orientation` (1 till 8). Klienten läser dem ur filen innan den krymper den och skickar dem som fält,
eftersom den lagrade filen inte bär någon metadata; tidpunkten är den befintliga `taken_at`. CHECK-villkor håller
gränserna: giltiga grader, båda koordinaterna eller ingen, ortnamn bara med koordinater, ingen tom text och en riktig
orientering. Ägaren kan ändra eller ta bort varje fält, och inget av dem går till minnet. Ett foto som lagrades före
migreringen behåller alla värden och läses som ett foto utan plats, kamera eller orientering. En återrullning släpper de
fem kolumnerna, vilket bara förlorar de detaljer som angetts sedan dess.

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
