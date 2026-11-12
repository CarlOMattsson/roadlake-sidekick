"""Drop the four tables of the retired automation engine.

`assistant_automation_policies`, `assistant_automation_control`, `assistant_automation_runs` and
`assistant_task_review_findings` belonged to the retired in-app assistant's autonomy posture and task
health review. Nothing writes them any more and nothing reads them, so they are empty on every
installation. The tables are not created by anything but the 0.1.0 baseline, which stays as it is
because installations have already applied it.

Safety: a table that holds a row stops the migration with an error that names the table, and the
transaction rolls back, so no data is thrown away without notice. The tables are dropped in one
statement without CASCADE, so a live object that still depends on one of them (a foreign key from a
kept table, a view) also makes the migration fail instead of being removed with it. Every check and
statement tolerates a missing table, so a database that never had them is left unchanged.

Not touched: `domain_events.automation_run_id` and the ledger aggregate type `automation_run`,
which are history of the ledger and stay readable.

One-way: the rollback refuses, because the tables hold nothing to restore and no code uses them.
"""

# migration-class: contract

from yoyo import step

__depends__ = {"100_schema_baseline_0_1_0"}

steps = [
    step(
        """
        SET LOCAL ROLE sidekick_owner;
        DO $guard$
        DECLARE
          retired text;
          has_rows boolean;
        BEGIN
          FOREACH retired IN ARRAY ARRAY[
            'assistant_task_review_findings',
            'assistant_automation_runs',
            'assistant_automation_policies',
            'assistant_automation_control'
          ]
          LOOP
            IF to_regclass(format('sidekick.%I', retired)) IS NOT NULL THEN
              EXECUTE format('SELECT EXISTS (SELECT 1 FROM sidekick.%I)', retired) INTO has_rows;
              IF has_rows THEN
                RAISE EXCEPTION 'sidekick.% holds rows, so the retired automation tables are not '
                  'dropped. Nothing was changed. Back up the database and remove the rows by hand '
                  'if they are really unwanted, then run the update again.', retired;
              END IF;
            END IF;
          END LOOP;
        END
        $guard$;
        DROP TABLE IF EXISTS
          sidekick.assistant_task_review_findings,
          sidekick.assistant_automation_runs,
          sidekick.assistant_automation_policies,
          sidekick.assistant_automation_control;
        """,
        """
        DO $refuse$
        BEGIN
          RAISE EXCEPTION 'migration 106 dropped the retired automation tables; it cannot be '
            'rolled back. Restore the backup taken before the update instead.';
        END
        $refuse$;
        """,
    )
]
