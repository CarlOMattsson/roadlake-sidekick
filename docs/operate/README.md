# Operate

[Svenska](README.sv.md)

<!-- description: A map of what you do when you run a Sidekick server – connect Claude, update, back up, turn on memory and pair Android. -->

These are the guides for you who run a Sidekick server. Each guide does one thing. If you have not started the server yet, begin with [First start on a server](../start/self-hosted-server.md).

:::note[Preview]
Install, update, backup and restore are drilled on Linux containers. The HTTPS profile, a real GitHub sign-in and real Claude connections have not been tried. Take a backup before you change anything.
:::

## Connect

- [Connect Claude](connect-claude.md): register the sign-in, add the connector and decide what the session may do.
- [Build, install and pair Android](pair-android.md): build the app from source and connect the phone with a one-time code.
- [Reminders through ntfy](push-reminders.md): turn on reminders to the phone, through the public ntfy server or your own.

## Maintain

- [Update](update.md): fetch new code and run the migrations, from source or to a signed image.
- [Backup and restore](backup-and-restore.md): take encrypted backups, keep the key somewhere else and read them back.
- [Resource limits and secrets per container](limits-and-secrets.md): change the memory and process limits and see which settings each container receives.
- [Empty the trash](empty-trash.md): delete what is in the trash for good, with one command.
- [Move data between installations](move-data.md): bring your records to a new server or an empty database.

## Add

- [Turn on memory](memory.md): start Hindsight and choose which model provider receives the text.
- [Enter a license key](license-key.md): store a key in a room, in the Android app or from the command line.

## Work laptop

The work package has its own guides, because it runs locally against Claude Desktop and has a closed network.

- [Operating the work package](work-laptop/README.md): the network, start at login, backup and update, the model server and uninstalling.

## Look up

- [Compose profiles and files](../reference/selfhost-profiles.md)
- [Security and privacy in plain words](../explanation/security-and-privacy.md)
