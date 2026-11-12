# Start vid inloggning

[English](start-at-login.md)

<!-- description: Låt Sidekick starta när du loggar in på jobbdatorn, och stäng av det igen. -->

Låt Sidekick starta när du loggar in på jobbdatorn, och stäng av det igen.

`bash tools/work.sh autostart on` lägger en systemd-användarenhet på Linux (`~/.config/systemd/user/sidekick-work.service`;
lägg till `sudo loginctl enable-linger $USER` för start utan inloggning) eller en launchd-agent på macOS
(`~/Library/LaunchAgents/local.sidekick.work.plist`; Docker Desktop måste också starta vid inloggning). `autostart off`
tar bort den. Containrarna startar också om av sig själva efter en omstart av datorn, om du inte stoppat dem med `stop`.
