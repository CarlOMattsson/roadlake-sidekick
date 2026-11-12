# Underhåll av Sidekick

[English](README.md)

<!-- description: För dem som underhåller Sidekick: hur du släpper en version, releaseövningen och protokollet över vad som har verifierats. -->

För dem som underhåller Sidekick: hur du släpper en version, releaseövningen och protokollet över vad som har verifierats.

- [Släpp en version](release.sv.md): checklistan, signeringshemligheterna och hur du verifierar en release.
- [Releaseövningen](release-drill.sv.md): installera, uppdatera, säkerhetskopiera och återställa i engångscontainrar.
- [Verifieringsloggar](verification.sv.md): vad som kontrollerades i varje guide, och hur.
- [Publicera webbplatsen](website-domain.sv.md): DNS, domänverifiering och HTTPS för roadlake.com.

## Vad som har verifierats

| Guide | Senast kontrollerad | Hur | Inte verifierat |
| --- | --- | --- | --- |
| [Snabbstart](../start/first-contribution.sv.md) | 2026-11-11 | läst mot koden; körd utan sidoeffekter; följd från en ny klon | `pyright`, webbläsarkontroller, testsviter |
| [Android-appen](../operate/pair-android.sv.md) | 2026-11-10 | läst mot koden; `--help` för companion-CLI:n | Gradle-bygge i den här kontrollen (appen är verifierad på en riktig telefon av underhållaren, 2026-11-12) |
| [Självhostning](../start/self-hosted-server.sv.md) | 2026-11-11 | läst, körd, övad på containrar, följd från en ren export under standard- och `umask 077` | `vps`-profilen, uppdatering över en riktig schemaändring, cosign-kontroll mot en släppt avbildning (den riktiga Claude-anslutningen och Linux-driften är verifierade av underhållaren, 2026-11-12) |
| [Arbetspaketet](../start/work-laptop.sv.md) | 2026-11-11 (uppföljning), 2026-11-10 | läst, `bash -n`, tester med ersättnings-`docker`, övad på containrar | umask 077 på en riktig Ubuntu-installation, macOS |
