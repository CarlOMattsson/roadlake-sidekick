# Enter a license key

[Svenska](license-key.sv.md)

<!-- description: Enter a license key in a room, in the Android app or from the command line on the server. Only the owner of the instance can do it. -->

Enter a license key in a room, in the Android app or from the command line on the server. Only the owner of the instance can do it.

Only the owner of the instance can enter a key. Use one of these.

- **In an MCP app.** Open the license row at the bottom of Control; while the instance has no valid key, the coin at the bottom of each room leads there too (with Control switched off, the row is in the room's ⋯ panel). Choose "Enter license key", paste the key and choose "Save".
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

## How the key is checked

Keys are verified offline against a **public** key (base64 raw Ed25519) held by the licensor. The instance reads it from `SIDEKICK_LICENSE_PUBLIC_KEY`, which takes precedence, and otherwise from the default in `backend/src/sidekick/license/public_key.py`. That default is the licensor's public key, so a build from this repository with the setting unset accepts keys issued by the licensor.

Only if the effective public key is the placeholder or is not a valid key does startup log `license_public_key_unusable` (reason `placeholder` or `invalid`); every key is then treated as unlicensed and the unpaid notice is shown. Valid keys are issued only by the licensor (see [LICENSE.md](../../LICENSE.md)); do not look for, generate or share one.

The release workflow refuses to build an image while that default is still the placeholder (`tools/check-license-public-key.py`). Leave `SIDEKICK_LICENSE_PUBLIC_KEY` unset unless you deliberately use a different public key, for example one you published yourself for your own fork; it is a public value, not a secret.

To verify, start the instance and check that the log has no `license_public_key_unusable` record, then run `python -m sidekick.license.cli show`.
