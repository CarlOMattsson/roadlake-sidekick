# Schemabaslinjen 0.1.0

[English](schema-baseline.md)

<!-- description: Sidekick 0.1.0 skapar databasen från en enda baslinje. Här står vad det betyder för nya installationer och varför äldre installationer inte uppgraderas på plats. -->

Sidekick 0.1.0 skapar databasen från en enda baslinje. Här står vad det betyder för nya installationer och varför äldre installationer inte uppgraderas på plats.

## Vad baslinjen är

Katalogen `migrations/` börjar med `100_baseline_0_1_0.py`. Den skapar hela schemat i en tom databas: tabeller,
villkor, index, behörigheter och standardbehörigheter, med Sidekicks namn på schema, roller och databas (`sidekick`,
`sidekick_owner`, `sidekick_migrator`, `sidekick_app`). Nya migreringar fortsätter från `101_`; den första, `101_tasks_project_and_due_indexes.py`, lägger bara till två index på `tasks`.

- Den skapar bara. I en databas som redan har schemat misslyckas den vid första satsen och ändrar ingenting.
- Den kan inte rullas tillbaka: det skulle ta bort varje ägartabell. Vägen tillbaka är en säkerhetskopia.
- Kedjan den ersätter levereras inte.
- Tabellerna för funktioner som togs bort före 0.1.0 (den tidigare inbyggda chatten, livesamtal med röst,
  agentkörningen, assistentens autonomiinställning och inställningarna för den avvecklade skrivbordsappen) skapas inte
  (besluten D-082 och D-084).
- Två rester av den borttagna webbinloggningen är undantaget: baslinjen skapar fortfarande tabellen `sessions` och
  kolumnen `users.password_hash`. Migrationen `105_drop_sessions_and_password_hash.py` tar bort båda, eftersom
  installationer kan ha tillämpat baslinjen redan och den därför aldrig ändras i efterhand.

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
(baslinjen `100_baseline_0_1_0.py` och de numrerade migreringarna efter den, i ordning), skapa ägaren och importera. Inget behöver markeras eller lagas för hand.
