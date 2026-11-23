"""Let a photo carry what the app read from the file before it was shrunk, beside the clean image.

The file stored for a photo holds no metadata (the server refuses a file that does). What the
owner may want to know about a photo is kept here as fields instead: where it was taken
(`location_lat`, `location_lon` and an optional place name), the camera, and the file's
orientation (1 to 8, as the camera wrote it; the pixels are already upright). The time it was taken
is the existing `taken_at`. The client sends every one of these. Location is the owner's to keep,
change or remove, so every field is nullable and a photo without them reads as before. None of them
is ever read into memory.

Expand only: five nullable columns and the CHECK constraints that bound them (valid degrees, both
coordinates or neither, a place name only with coordinates, a real orientation, no blank text). The
rollback drops the columns, which loses only the details entered since.
"""

# migration-class: expand

from yoyo import step

__depends__ = {"117_journal_attachments"}

steps = [
    step(
        """
        SET LOCAL ROLE sidekick_owner;
        ALTER TABLE sidekick.journal_attachments
            ADD COLUMN location_lat double precision,
            ADD COLUMN location_lon double precision,
            ADD COLUMN location_name character varying(120),
            ADD COLUMN camera character varying(80),
            ADD COLUMN orientation smallint,
            ADD CONSTRAINT ck_journal_attachments_location CHECK (
                (location_lat IS NULL) = (location_lon IS NULL)
                AND (location_lat IS NULL OR location_lat BETWEEN -90 AND 90)
                AND (location_lon IS NULL OR location_lon BETWEEN -180 AND 180)
            ),
            ADD CONSTRAINT ck_journal_attachments_location_name CHECK (
                location_name IS NULL
                OR (location_lat IS NOT NULL AND length(btrim(location_name)) > 0)
            ),
            ADD CONSTRAINT ck_journal_attachments_camera
                CHECK (camera IS NULL OR length(btrim(camera)) > 0),
            ADD CONSTRAINT ck_journal_attachments_orientation
                CHECK (orientation IS NULL OR orientation BETWEEN 1 AND 8);
        """,
        """
        SET LOCAL ROLE sidekick_owner;
        ALTER TABLE sidekick.journal_attachments
            DROP CONSTRAINT IF EXISTS ck_journal_attachments_orientation,
            DROP CONSTRAINT IF EXISTS ck_journal_attachments_camera,
            DROP CONSTRAINT IF EXISTS ck_journal_attachments_location_name,
            DROP CONSTRAINT IF EXISTS ck_journal_attachments_location,
            DROP COLUMN IF EXISTS orientation,
            DROP COLUMN IF EXISTS camera,
            DROP COLUMN IF EXISTS location_name,
            DROP COLUMN IF EXISTS location_lon,
            DROP COLUMN IF EXISTS location_lat;
        """,
    )
]
