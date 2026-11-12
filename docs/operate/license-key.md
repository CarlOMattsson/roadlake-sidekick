# Enter a license key

[Svenska](license-key.sv.md)

<!-- description: Enter a license key in a room, in the Android app or from the command line on the server. Only the owner of the instance can do it. -->

Enter a license key in a room, in the Android app or from the command line on the server. Only the owner of the instance can do it.

Only the owner of the instance can enter a key. Use one of these.

- **In an MCP app.** Tap the mark in the top bar, or open the license row at the bottom of Control. Choose "Enter license key", paste the key and choose "Save".
  If the key is accepted the row says so and shows the licensee. If not, nothing is changed.
- **In the Android app.** Open Settings, go to the license row at the bottom, choose "Enter license key", paste the key and save.
  The app sends it to your server over the paired connection (`PUT /companion/v1/license`).
- **On the server.** The instance's operator can store the key from the command line. The key is read from standard input, and the example below reads it with a silent prompt so that it is never typed
  into a command line that the shell would keep in its history. The other commands are `show`, `clear` and `reset-clock`.

```bash
cd deploy/selfhost                      # in the repository, where selfhost.env is
read -rs LICENSE_KEY                    # Bash: paste the key, it is not echoed; press Enter
printf '%s' "$LICENSE_KEY" | docker compose --env-file selfhost.env run --rm -T api python -m sidekick.license.cli set
unset LICENSE_KEY
```
