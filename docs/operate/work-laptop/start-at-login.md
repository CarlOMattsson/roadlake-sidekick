# Start at login

[Svenska](start-at-login.sv.md)

<!-- description: Let Sidekick start when you log in to your work laptop, and turn that off again. -->

Let Sidekick start when you log in to your work laptop, and turn that off again.

`bash tools/work.sh autostart on` installs a systemd user unit on Linux (`~/.config/systemd/user/sidekick-work.service`;
add `sudo loginctl enable-linger $USER` to start without logging in) or a launchd agent on macOS
(`~/Library/LaunchAgents/local.sidekick.work.plist`; Docker Desktop itself must also start at login). `autostart off`
removes it. The containers also restart on their own after a reboot unless you stopped them with `stop`.
