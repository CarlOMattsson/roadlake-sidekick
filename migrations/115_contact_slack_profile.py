"""Let a Contact carry the link to its Slack profile.

`contacts.slack` is the normalized profile link of the Contact's Slack member
(`https://<workspace>.slack.com/team/<member id>`); the application checks it before it is stored.
NULL is a Contact with no Slack profile. Like the e-mail address and the phone number it is the
owner's contact detail: it is shown in the Contact app and never read into memory.

Expand only: one nullable column, no default and no index; existing rows read as Contacts with no
Slack profile. The rollback drops the column, which loses only the links entered since.
"""

# migration-class: expand

from yoyo import step

__depends__ = {"114_ai_erased_run_costs"}

steps = [
    step(
        """
        SET LOCAL ROLE sidekick_owner;
        ALTER TABLE sidekick.contacts ADD COLUMN slack character varying(160);
        """,
        """
        SET LOCAL ROLE sidekick_owner;
        ALTER TABLE sidekick.contacts DROP COLUMN IF EXISTS slack;
        """,
    )
]
