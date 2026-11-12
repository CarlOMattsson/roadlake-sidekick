# Releasing Roadlake Sidekick (maintainer checklist)

This is the exact path from a green `main` to a published, verifiable release. The workflow does everything up to
the bundle; creating the tag, the GitHub release and any store listing is a deliberate step by the maintainer. The
workflow never creates a tag or a release. Svenska: [release.sv.md](release.sv.md).

Releases are made at all three levels: major (`X.0.0`), minor (`X.Y.0`) and patch (`X.Y.Z`). Changes are tested
locally before they are pushed, so CI does not run on every push: the full CI (with the dependency audit) and the
update/backup/restore drill run as gates of every real release, a patch included. A patch may only declare the
migration class `expand` (a fix never ships a one-way schema step).

**Nothing is built, signed or published without the owner's approval.** Every real run pauses once, at the
start, in the GitHub environment `release` until a required reviewer approves it (see [one-time setup](#one-time-setup-steps-only-the-repository-owner-can-take)),
and everything that is published is signed and verifiable: see [Verifying a release](#verifying-a-release).

One release is one version (`MAJOR.MINOR.PATCH`) for the server image, the web bundle and the Android app. It is
defined by `version` in `backend/pyproject.toml`; `tools/check-version-sync.py` (also a unit test) fails when
`backend/src/sidekick/__init__.py`, `frontend/package.json`, `frontend/package-lock.json`, the Android
`versionName`/`versionCode` or `CHANGELOG.md` disagree. See [Versions](#versions).

## Preview status and what is verified

Version 0.1.0 is a preview: there is no tag, no published container image and no published APK yet. You build both
from the repository (the first server start builds the image from your checkout; see the [Quickstart](../../QUICKSTART.md)
and [android.md](../operate/pair-android.md)).

- **Drilled on Linux containers:** install, update, backup and restore of the self-hosted stack and of the work-laptop
  package (`tools/drill.sh`, also a release gate).
- **Followed from a fresh clone:** the self-hosting first start (build, owner, identity line,
  `up -d`, health and discovery checks) under the default and under a strict `umask`, and the Quickstart (dependencies,
  database, migrations, backend, user and token, an MCP call, the stdio server, the MCP App build, static checks), each
  in its own compose project with generated throw-away secrets. The steps work as written; the backend suite on the
  test database was not part of it.
- **Not tried against real services:** the self-hosted HTTPS profile, a real GitHub sign-in, real Claude connections,
  macOS, and the Android app on a real phone with a real server and push delivery.

Expect rough edges and breaking changes until a release is published.

## What a release produces

| Output | Where | Signed with |
| --- | --- | --- |
| Container image, `linux/amd64` and `linux/arm64`, with SBOM and SLSA provenance | `ghcr.io/<owner>/roadlake-sidekick:vX.Y.Z` | cosign keyless (GitHub OIDC), on the index digest; GitHub build provenance attestation |
| Android APK `sidekick-X.Y.Z.apk` | workflow artifact `release-bundle-X.Y.Z` | your Android signing key (`apksigner`); GitHub build provenance attestation |
| `SHA256SUMS` and its signature bundle | same bundle | cosign keyless (`sign-blob`); GitHub build provenance attestation |
| the image SBOM (SPDX JSON) and the release notes (taken from the changelog) | same bundle | covered by `SHA256SUMS`; GitHub build provenance attestation |
| R8 mapping for crash reports | artifact `android-r8-mapping` (90 days) | none (a debugging aid, not part of the release) |

The git tag `vX.Y.Z` is signed by the maintainer (`git tag -s`), so every link from the source tag to the files is
verifiable.

## One-time setup (steps only the repository owner can take)

1. **Android signing key.** Create it on your own machine and keep it outside the repository. Losing it means
   installed apps can no longer be updated (a new key is a new app for the phone).

   ```sh
   keytool -genkeypair -v -keystore sidekick-release.jks -alias sidekick \
     -keyalg RSA -keysize 4096 -validity 10000
   ```

   Back up the `.jks` file and both passwords somewhere safe and separate from GitHub.
2. **The environment `release` (the approval gate, one approval per release).** Settings, Environments, New environment,
   name it exactly `release`, then configure it:

   - **Required reviewers:** tick it and add yourself (up to six people or teams may be added; one approval is enough).
     Only the job `signing-check` uses this environment, and every other real-run job needs that job, so a real run
     pauses once, at the start, until a reviewer approves it. A dry run never reaches the environment and needs no
     approval.
   - **Prevent self-review:** leave it unticked while you are the only reviewer; otherwise you could not approve a
     run that you started. Tick it once a second reviewer exists.
   - **Allow administrators to bypass configured protection rules:** untick it, so the approval cannot be skipped.
   - **Deployment branches and tags:** "Selected branches and tags", add `main`.
   - **Wait timer:** none. A run that nobody approves expires after 30 days.
   - It holds no secret.

   The "Review pending deployments" dialog shows the environment and the run; check the version in the run title
   before you approve.
3. **The environment `release-signing` (the signing secrets).** A second environment, named exactly `release-signing`,
   with **no** required reviewers (the approval was given at `release`). **You MUST set Deployment branches and tags to
   "Selected branches and tags" with `main`:** without reviewers this restriction is the only thing that keeps a
   workflow edited on another branch from reading the signing secrets, so never leave it on "No restriction". The jobs
   `secrets-check`, `sign-apk`, `release` and `sign-bundle` use it; each of them needs `signing-check` (directly or
   through `gates`), so none of them can run before the owner has approved. Add the signing secrets here
   (Settings, Environments, `release-signing`, Environment secrets; not repository secrets). A real run stops
   before building anything if one is missing:

   | Secret | Value |
   | --- | --- |
   | `ANDROID_KEYSTORE_BASE64` | `base64 -w0 sidekick-release.jks` |
   | `ANDROID_KEYSTORE_PASSWORD` | the keystore password |
   | `ANDROID_KEY_ALIAS` | `sidekick` (the alias above) |
   | `ANDROID_KEY_PASSWORD` | the key password |

   ```sh
   base64 -w0 sidekick-release.jks | gh secret set ANDROID_KEYSTORE_BASE64 --env release-signing
   ```

   Delete any repository secret with the same name (`gh secret delete NAME`): a secret that is not in the environment is
   readable by every workflow, and the release workflow does not need it. The cosign signature and the attestations
   need no secret: they use the short-lived GitHub OIDC token of the job.
4. **Pinned certificate (required for a real run).** Repository variable `ANDROID_CERT_SHA256` = the SHA-256 of your signing
   certificate (`keytool -list -v -keystore sidekick-release.jks`, line "SHA256", lower case, without colons).
   The workflow refuses an APK signed with any other key and always refuses a debug certificate. The APK is built
   unsigned in one job (npm and Gradle run there, with no secret) and signed in a separate job with no checkout,
   using the Android build-tools of the runner image at the version pinned in the workflow
   (`ANDROID_BUILD_TOOLS_VERSION`). The signing job publishes the APK's sha256, and the last job refuses to sign
   the checksums unless the APK, the image digest and the SBOM in the bundle match what the trusted jobs reported.
5. **The licensor's license public key.** `DEFAULT_LICENSE_PUBLIC_KEY` in `backend/src/sidekick/license/public_key.py`
   must be the real key, not the placeholder; a real run refuses the placeholder
   (`tools/check-license-public-key.py`). Setting it is the licensor's step, with the licensor's private key kept
   off GitHub.
6. **Repository settings.** Protect `v*` tags with a tag ruleset (Settings, Rules, Rulesets, New tag ruleset, target
   `v*`; restrict updates and deletions and, with yourself on the bypass list, creations): the migration-class check
   trusts the previous tag, and a moved tag would also move what customers think a version is. Allow GitHub Actions
   to write packages. Artifact attestations need a public repository (or a GitHub plan that supports them for private
   ones). After the first push, set the GHCR package visibility (public or private) in the package settings.
7. **Signing the tag.** Configure a signing key for git once (`git config gpg.format ssh` with `user.signingkey` for an
   SSH key, or a GPG key) and add the public key to GitHub as a signing key, so GitHub shows the tag as verified.
8. **Not covered here:** a Google Play account and listing, App Bundle (`.aab`) upload and Play App Signing. Play
   needs its own decision on who holds the upload key; this workflow produces a directly installable APK only.

## Release steps

The steps are the same for every level; what differs is what the version may contain.

| Level | Version | Contains | `migration_class` |
| --- | --- | --- | --- |
| Major | `X.0.0` | breaking changes, a new companion API version | `expand` or `breaking` |
| Minor | `X.Y.0` | new features | `expand` (or `breaking` below 1.0, see [Versions](#versions)) |
| Patch | `X.Y.Z` | fixes only, no behaviour or schema break | `expand` only; the workflow refuses `breaking` |

A patch passes exactly the same gates as the others (the full CI, the drill, version sync, the migration check, the
license key). The migration check compares the declared class with the migrations added since the previous release,
so a patch that adds a contract migration cannot declare `expand` either.

1. **Version.** On a branch set the version in `backend/pyproject.toml` and its mirrors
   (`npm --prefix frontend version X.Y.Z --no-git-tag-version`, edit `__version__` in
   `backend/src/sidekick/__init__.py`, `uv lock --project backend`). In `CHANGELOG.md` rename `## [Unreleased]`
   to `## [X.Y.Z] - YYYY-MM-DD` and start a new empty `## [Unreleased]` above it.
2. **Check locally.**

   ```sh
   python3 tools/check-version-sync.py --release --tag vX.Y.Z
   ```

   Run the checks locally and merge to `main`; the release run itself runs the full CI.
3. **Dry run first.** Actions, "release-image", Run workflow: `version` = `vX.Y.Z`, `migration_class` (see below),
   `previous_release` (`none` for the very first release, otherwise empty), **`dry_run` ticked**. It builds both
   image platforms and the APK unsigned, pushes and signs nothing, needs no secrets, and uploads
   `release-bundle-X.Y.Z-dry-run`. Fix whatever it reports; the `linux/arm64` build runs under emulation and can
   take 20 minutes or more.
4. **Real run.** The same form with `dry_run` unticked. The run first checks that the commit is on `main`, then waits for
   your approval in the environment `release` (approve only a run you started); that is the only approval of the
   release. After it the checks run (the signing secrets and the pinned certificate, the full CI and the drill on
   exactly this commit, version sync, a version higher than every existing release tag, migration class, license key),
   then the APK (built unsigned, then signed), then the image (pushed, Trivy-scanned, signed, attested), then the
   bundle (signed and attested). `migration_class` is `expand` when the previous image still
   works against the new schema and `breaking` for a one-way step; the check compares the declared class with the
   migrations added since the previous release.
5. **Verify** the result as described below, from a machine that is not the build machine.
6. **Tag and release.** Only after step 5:

   ```sh
   git tag -s vX.Y.Z -m "vX.Y.Z" <released-commit> && git tag -v vX.Y.Z && git push origin vX.Y.Z
   gh run download <run-id> -n release-bundle-X.Y.Z -D bundle
   gh release create vX.Y.Z --verify-tag --title "vX.Y.Z" --notes-file bundle/release-notes.md \
     bundle/sidekick-X.Y.Z.apk bundle/SHA256SUMS bundle/SHA256SUMS.sigstore.json bundle/sbom-image-X.Y.Z.spdx.json
   ```

   The tag should be signed (`git tag -s`); an annotated tag (`git tag -a`) is the minimum, because the next release
   finds its comparison point from it and the migration check refuses a lightweight tag. The workflow never creates
   the tag or the release; both are deliberate, signed steps of the maintainer.

## Verifying a release

Every file and the image can be verified by anyone, with `cosign` v3, the GitHub CLI (`gh`) and `apksigner`. Replace
`<owner>/<repo>` with the repository. The release notes of every release repeat these commands with the real values.

```sh
# Image signature: identity and digest are printed in the run summary ("Signer identity", "Digest").
cosign verify ghcr.io/<owner>/roadlake-sidekick@sha256:<digest> \
  --certificate-identity "https://github.com/<owner>/<repo>/.github/workflows/release-image.yml@refs/heads/main" \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com

# Image build provenance (GitHub artifact attestation, signed through Sigstore).
gh attestation verify oci://ghcr.io/<owner>/roadlake-sidekick@sha256:<digest> --repo <owner>/<repo> \
  --signer-workflow <owner>/<repo>/.github/workflows/release-image.yml

# Image metadata: version label, schema head, platforms, SBOM and provenance attestations.
docker buildx imagetools inspect ghcr.io/<owner>/roadlake-sidekick@sha256:<digest>
docker buildx imagetools inspect ghcr.io/<owner>/roadlake-sidekick@sha256:<digest> --format '{{ json .SBOM }}'

# Files: checksums, then the signature of the checksum file.
cd bundle && sha256sum -c SHA256SUMS
cosign verify-blob SHA256SUMS --bundle SHA256SUMS.sigstore.json \
  --certificate-identity "https://github.com/<owner>/<repo>/.github/workflows/release-image.yml@refs/heads/main" \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com

# Build provenance of each file: the APK, the SBOM, the checksums and the release notes.
for file in sidekick-X.Y.Z.apk sbom-image-X.Y.Z.spdx.json SHA256SUMS release-notes.md; do
  gh attestation verify "$file" --repo <owner>/<repo> \
    --signer-workflow <owner>/<repo>/.github/workflows/release-image.yml
done

# APK: the signature must verify and the certificate must be yours (compare with ANDROID_CERT_SHA256).
apksigner verify --verbose --print-certs sidekick-X.Y.Z.apk

# The tag: signed by the maintainer, pointing at the released commit.
git fetch --tags && git tag -v vX.Y.Z
```

`apksigner` is in the Android SDK build-tools (`$ANDROID_HOME/build-tools/<version>/`). Expect `Verifies`, scheme
v2 (or newer) `true`, and exactly one signer whose SHA-256 digest equals the pinned value. A debug certificate
(`CN=Android Debug`) or an unsigned APK means the release must not be published.

What each check proves: `cosign verify` and `cosign verify-blob` prove that the image or the checksum file was signed
by this workflow file in this repository (no key to steal; the certificate lives for minutes and is logged publicly in
Sigstore). `gh attestation verify` proves that a file with exactly that digest was produced by that workflow run of
that repository. `sha256sum -c` ties the files you downloaded to the signed checksum list, and `apksigner` ties the
APK to the owner's own signing key, which the phone also checks on every update.

The `<ref>` in the identity is the ref the workflow ran from (`refs/heads/main` when you start it from `main`). A
release is signed by the workflow file, so renaming `release-image.yml` would change the identity every customer has
pinned in `update.sh`. Running through the environments `release` and `release-signing` does not change the identity.

## Proving an update across a schema change

The first release has no predecessor, so there is nothing to update from; the baseline is described in
[the migration baseline](../explanation/schema-baseline.md). From the second release on, before announcing:

1. Take the previous release image digest (`FROM`) and the new one (`TO`), and the signer identity from above.
2. Run the drill against the released images. It installs `FROM`, writes marker data, updates to `TO` with the real
   `update.sh` and the real cosign check, checks that the schema version moved and the marker survived, then
   backs up, deletes every volume and restores (needs Docker Compose v2.24.4 or newer and `cosign`):

   ```sh
   bash tools/drill.sh selfhost \
     --from-image ghcr.io/<owner>/roadlake-sidekick@sha256:<FROM> \
     --to-image ghcr.io/<owner>/roadlake-sidekick@sha256:<TO> \
     --cert-identity "https://github.com/<owner>/<repo>/.github/workflows/release-image.yml@refs/heads/main"
   ```

   Setting the repository variables `DRILL_FROM_IMAGE`, `DRILL_TO_IMAGE` and `DRILL_CERT_IDENTITY` makes the drill (a release
   gate, or started by hand) do the same on a clean runner.
3. A `breaking` release is one-way: also read the notes in [the self-hosting guide](../operate/update.md)
   about rollback, and release it as a minor (below 1.0) or major version. The release also declares the oldest
   version it can be updated from in `deploy/selfhost/min-upgrade-from.txt`; keep it truthful, because `update.sh`
   refuses a jump that skips it.
4. Install the APK on a phone that has the previous app, pair it with the updated server and check that Today,
   Work and Journal load. The companion API (`/companion/v1/`) is additive within a major line, so an older app must
   keep working against a newer server.

## If something fails

- A gate, the CI or the drill fails: nothing was built or pushed; fix it and start again (the version tag is not used up).
- The approval was refused or expired: nothing was built or signed past that point; start a new run.
- The image was pushed but a later step failed (the vulnerability scan, signing, or the bundle): the tag `vX.Y.Z`
  exists in GHCR and is never moved, and the workflow refuses to push the same version again. The fix is the next patch
  version (`X.Y.(Z+1)`), or the next minor or a major if the change warrants it, with its own changelog section,
  version bump and checks as above. The failed `vX.Y.Z` stays unused: do not push the git tag for it, do not publish
  its image or bundle, and never delete or retag the image to reuse the number.
- The signing key leaked or was lost: delete the environment secrets, tell the owner of the installations, and treat the
  next APK as a new app lineage.

## Tags and the first release

The release workflow (`.github/workflows/release-image.yml`, started by hand) only runs from a commit on `main`, builds
major, minor and patch versions after the owner's approval, and runs the full CI and the drill itself as gates (CI does not run on pushes; changes are tested locally first). It also checks the declared migration class against the migrations added since the previous release (a patch may only declare `expand`).
It never creates git tags. After a release, push the signed tag at the released commit yourself; the next release finds its
comparison point from that tag:

```sh
git tag -s vX.Y.Z -m "vX.Y.Z" <released-commit> && git tag -v vX.Y.Z && git push origin vX.Y.Z
```

The tag should be signed (`-s`); at least it must be annotated (`-a`), because the migration check refuses a lightweight tag. Protect `v*`
tags with a tag protection rule (or a ruleset) in the GitHub repository settings. The protection is a precondition
of the migration check: it trusts the tag, and a force-moved tag could make the comparison empty. The workflow
cannot set this up and prints a warning about it on every run.

For the very first release there is no tag, so start the workflow with `previous_release` set to `none`. `none` is refused once any `v*` tag exists, and for a first release every
migration is checked against the declared class, not just new ones.

## Versions

Sidekick has one release version, `MAJOR.MINOR.PATCH` ([Semantic Versioning](https://semver.org/)). Its source
is `version` in `backend/pyproject.toml`. `backend/src/sidekick/__init__.py`, `frontend/package.json` and
`frontend/package-lock.json` mirror it, and `backend/tests/policy/test_version_sync.py` fails when they differ. The same
rules run as `tools/check-version-sync.py`, which also checks `CHANGELOG.md` and the Android derivation, and which the
release workflow runs before it builds anything.
The OpenAPI document takes its version from the package.

- **Server and app share the version.** The server image, the MCP App bundle and the Android app are built
  from the same commit and carry the same number. The Android build reads `versionName` from
  `frontend/package.json` and derives `versionCode` as `MAJOR*10000 + MINOR*100 + PATCH` (0.1.0 is 100), so
  every bump raises it. `MINOR` and `PATCH` therefore stay below 100; the build refuses anything else.
- **Compatibility goes through the companion API, not the release number.** The app talks to the server only
  under `/companion/v1/`, and companion responses carry `api_version` (`companion.v1`, set by
  `API_VERSION` in `backend/src/sidekick/api/companion.py`). Within `v1` a change is additive only: new
  routes, new optional fields, no removed or renamed fields. A breaking change gets a new prefix and
  `api_version` (`/companion/v2/`, `companion.v2`), and the server keeps serving `v1` alongside it, because a
  phone may run an older app than the server. That is a major or minor release, never a patch.
- **What the number means.** A patch fixes without changing behaviour or schema in a breaking way. A minor
  release adds features and may add `expand` migrations. A `breaking` migration class or a new companion API
  version needs at least a minor release while the version is below 1.0, and a major release after that.
