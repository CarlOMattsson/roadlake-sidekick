# The release drill

[Svenska](release-drill.sv.md)

<!-- description: The release drill installs, updates, backs up and restores in throw-away containers. It runs before every version. -->

The release drill installs, updates, backs up and restores in throw-away containers. It runs before every version.

A backup nobody has restored is a hope, not a backup. The workflow `.github/workflows/release-drill.yml` runs
`tools/drill.sh` on a clean runner as a gate of every release (and on demand, not on a schedule): it installs the previous release, writes a marker row (and a marker file
in the Hindsight volume), updates to the newest release with the real `update.sh`, checks that the marker survived and
that the schema version moved, takes an encrypted backup, deletes every volume, restores from the backup and checks the
marker again. A wrong or missing key must make the restore fail closed. The stack runs with the `memory` profile (the real
Hindsight container with a model address that goes nowhere), and its volume is archived and restored the way
[Backup and restore](../operate/backup-and-restore.md) describes. The same drill covers the work package (`tools/work.sh`: encrypted
database and Hindsight backups with their own key). The workflow has one job per package; inside the drill every stage is
a named step (`install`, `update`, `backup`, `destroy-volumes`, `key-fails-closed`, `restore`, ...), so a failure says
which one broke (an error annotation, and a table of step durations in the job summary). The log is attached to the run
as the artifact `drill-log-<package>`.

Set the repository variables `DRILL_FROM_IMAGE`, `DRILL_TO_IMAGE` and `DRILL_CERT_IDENTITY` (the same three values
`update.sh` needs, see [Update](../operate/update.md)) to drill with released images and the real cosign signature check. Without
them the workflow builds the api image twice from the checkout (`--local-images`), serves both from a throw-away
registry on the runner to get real digests, and drills with those; the signature is then **not** verified (cosign is a
stand-in) and both images carry the same schema, so the check that the schema moved is waived.

To run it yourself, from the repository root (needs Docker Compose v2.24.4 or newer and `cosign`):

```bash
bash tools/drill.sh selfhost --from-image ghcr.io/<owner>/roadlake-sidekick@sha256:<digest> --to-image ghcr.io/<owner>/roadlake-sidekick@sha256:<digest> --cert-identity <signer identity>
bash tools/drill.sh all --local-images   # no release needed; builds the image from this checkout, about 15 minutes
bash tools/drill.sh all --dry-run
```

A local run creates only compose projects named `sk-drill-*`, with their own temporary directory, random ports on
`127.0.0.1` and generated secrets. It never touches your installation, and it removes everything it created when it
ends, also on Ctrl-C (`--local-images` also removes the images it built). `--dry-run` uses a fake `docker` and starts
nothing. A full run on a laptop with `--local-images` and both packages takes about 15 minutes; the longest steps are the
work package's `update` and `backup` (about 2.5 minutes each, Hindsight is stopped for the copy) and its `restore`.
