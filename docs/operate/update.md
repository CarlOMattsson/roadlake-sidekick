# Update

[Svenska](update.sv.md)

<!-- description: Update a self-hosted server, either from source or to a signed image. Take a backup first in both cases. -->

Update a self-hosted server, either from source or to a signed image. Take a backup first in both cases.

There are two routes. Take a backup first in both ([Backup and restore](backup-and-restore.md)).

**From source (what the first start used).** `git pull --ff-only`, set the two build variables as in
[First start](../start/self-hosted-server.md#first-start) step 2 and run `docker compose --env-file selfhost.env build`. Then stop the writers, run
the migrator while nothing writes, and start everything again with the profiles you use (the `stop` line names every
profile so that every worker is found; services that are not running are left alone):

```bash
C="docker compose --env-file selfhost.env"
$C --profile backup --profile push --profile memory stop api automation-worker backup push memory-worker
$C run --rm -T --no-deps migrate     # if this fails, do not start the new code
$C --profile vps up -d               # with the profiles you use, as in First start
```

There is no signature to check on this route; the checkout is what you trust.

**To a signed, digest-pinned image.** `update.sh` verifies the signature, takes an encrypted owner backup and an
encrypted database snapshot, runs the migrator and waits until the API is ready (it answers the database and the
schema is at the revision of the new image) and every worker it started is running and healthy; otherwise it goes back to the previous image when the schema allows it (see "If an update fails"); it never rolls back the database. It prints the plan by default and changes
nothing until `--apply`.

```bash
./update.sh                                   # dry run
./update.sh --check --cert-identity <signer identity>   # current digest, signature and schema head
./update.sh --apply --image ghcr.io/<owner>/roadlake-sidekick@sha256:<digest> --cert-identity <signer identity>
```

Without a signer identity (`--cert-identity` or `SIDEKICK_RELEASE_CERT_IDENTITY`) `--check` reports the signature as NOT
CHECKED. The three values come from whoever publishes the image. The release workflow (`.github/workflows/release-image.yml`,
started by hand) pushes `ghcr.io/<owner>/roadlake-sidekick`, where `<owner>` is the GitHub account or organisation that runs
it, and prints the digest and the signer identity in the job summary of the run: the line `Digest:`, the line
`Signer identity:` (of the form `https://github.com/<owner>/<repo>/.github/workflows/release-image.yml@<ref>`) and the
`cosign verify` command with both. Use those two values exactly. Also give `--cert-issuer` only if the image was not
signed by GitHub Actions (the default is `https://token.actions.githubusercontent.com`). `update.sh` needs `cosign`
and refuses to go on without it. It also needs `python3` (3.9 or newer, nothing installed on top) and the
`update_policy.py` that ships next to it, because the update decisions live there; `--apply` refuses without both.

Once `--apply` has run, the pinned image is recorded in `release.env`; pass it as a second `--env-file` to every later
compose command: `docker compose --env-file selfhost.env --env-file release.env up -d`. See the header of `update.sh`
for the full order and the rollback rules.

**Which versions may update to which.** Each release declares the oldest version it can be updated from (the image
label `io.sidekick.min-upgrade-from`, set from `deploy/selfhost/min-upgrade-from.txt` when the release is built).
Before anything is stopped, `update.sh` reads the version of the image that is actually running
(`org.opencontainers.image.version`) and refuses a jump that skips a stepping-stone: update to an intermediate release
first, then to the newer one. It also refuses to update when the installed or the new version cannot be determined
(a local build, or an image from before the labels existed) and to downgrade. Only the unknown case can be overridden,
with `--allow-unknown-version`, and only if you know the installation is at or above the new image's minimum. The
backup and the snapshot come after this check, so a refusal changes nothing.

**Interrupted updates.** Ctrl-C, a terminal that closes, `kill` or an unexpected error during `--apply` runs the same
recovery as a failed step (the cases below): the lock is released, a half-written snapshot is removed, and the
previous image and the workers are started again if the migration had not begun. If the process is killed hard
(`kill -9`, power loss) the operating system drops the lock (an `flock` on `update-state/update.lock`, held for the
whole run, so two `--apply` runs can never overlap); the next `--apply` reads the journal first and, if it ends in
`STARTED`, `STOPPING_WRITERS` or `RESUMING`, resumes: it starts the workers the killed run had stopped, also when the
resumed run itself fails a pre-check (for example the signature) or is interrupted before it stops anything again.
A journal that ends in a later state (`MIGRATING`, `ROLLING_BACK`, `NEEDS_*`) still needs the manual decision below.

**What the release workflow checks.** After the image is pushed and before its digest is signed, Trivy scans it and
the run fails on any HIGH or CRITICAL vulnerability that has a fix (unfixed ones are ignored); an image that fails is
never signed, so `update.sh` refuses it. BuildKit attaches an SBOM and a SLSA provenance attestation to the image. The
base images used by the build and by the compose files are pinned by digest (`tools/pin-image-digests.sh --write`
re-pins them; a test fails on a new unpinned image). Read the SBOM with:

```bash
docker buildx imagetools inspect ghcr.io/<owner>/roadlake-sidekick@sha256:<digest> --format '{{ json .SBOM }}'
```

**If an update fails.** Before it migrates, `update.sh` stops the API and every worker that was running or restarting
(automation, backup, push, memory), and starts them again afterwards, all with the same image. The last lines it prints, and the last word in
`update-state/journal.log`, tell you which case you are in:

- `ABORTED`: the signature, the pull, the backup or the snapshot failed, or the state of a worker could not be
  determined, or a writer was still running or restarting after the stop. The API and the workers are stopped for the backup and the snapshot (so that no confirmed write is
  missed), and on this outcome they have been started again with the previous image; the installation runs as before.
- `ROLLED_BACK`: the new image did not become ready, and the previous image works against the new schema (the release
  says so with its migration class). The API and the workers are running the previous image again. Nothing to do.
- `NEEDS_MANUAL_RESTORE`: the database may be on a newer schema than the previous image supports. The API and the
  workers stay stopped on purpose, and the next `--apply` is refused. Either fix forward: run
  `echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) ABORTED manual" >> update-state/journal.log` and run `update.sh --apply` again
  with a corrected image. Or restore the snapshot with the **previous** image, as described under
  [Backup and restore](backup-and-restore.md).
- `NEEDS_RESTART`: the update stopped before the migration (the schema is unchanged), but the previous image did not
  become ready again after the stop. Nothing was migrated and nothing is restored. Start the installation by hand
  (`docker compose --env-file selfhost.env up -d`, with `--env-file release.env` if that file exists), check that the
  API answers, and then run
  `echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) ABORTED manual" >> update-state/journal.log`. Until that line is in the
  journal, the next `--apply` is refused.

**Docker network error on `up` or `update.sh`.** Caddy and the API talk over a small internal Docker network
(`proxy`) that uses the fixed address block `198.51.100.0/29` (reserved for documentation, so it is never routed on
the internet). The API trusts the forwarded client address and scheme only from Caddy's address there. If Docker
answers `Pool overlaps with other one on this address space`, the block collides with an existing Docker network or
a VPN route on the host: find it with `docker network ls` and `docker network inspect`, remove or move that network,
and run the update again. `update.sh` recreates a running Caddy together with the API so that it joins this network.
