# Maintaining Sidekick

[Svenska](README.sv.md)

<!-- description: For the people who maintain Sidekick: how to release a version, the release drill, and the record of what has been verified. -->

For the people who maintain Sidekick: how to release a version, the release drill, and the record of what has been verified.

- [Release a version](release.md): the checklist, the signing secrets and how to verify a release.
- [The release drill](release-drill.md): install, update, back up and restore in throw-away containers.
- [Verification logs](verification.md): what was checked in each guide, and how.
- [Publish the website](website-domain.md): DNS, domain verification and HTTPS for roadlake.com.

## What has been verified

| Guide | Last checked | How | Not verified |
| --- | --- | --- | --- |
| [Quickstart](../start/first-contribution.md) | 2026-11-11 | read against the code; run without side effects; followed from a fresh clone | the Claude Desktop stdio connection, `pyright`, browser checks, test suites |
| [Android app](../operate/pair-android.md) | 2026-11-10 | read against the code; `--help` of the companion CLI | Gradle build, install on a phone, pairing against a running server, push delivery |
| [Self-hosting](../start/self-hosted-server.md) | 2026-11-11 | read, run, drilled on containers, followed from a clean export under the default and `umask 077` | real GitHub sign-in, real Claude connection, `vps` profile, update across a real schema change, cosign check against a released image |
| [Work package](../start/work-laptop.md) | 2026-11-11 (follow-up), 2026-11-10 | read, `bash -n`, tests with a stand-in `docker`, drilled on containers | umask 077 on a real Ubuntu install, a real Claude Desktop session, macOS |
