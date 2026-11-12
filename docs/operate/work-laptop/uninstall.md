# Stop and uninstall

[Svenska](uninstall.sv.md)

<!-- description: Stop Sidekick on your work laptop, or remove everything: containers, data, backups and secrets. -->

Stop Sidekick on your work laptop, or remove everything: containers, data, backups and secrets.

- `bash tools/work.sh stop` stops Sidekick; data and secrets stay.
- `bash tools/work.sh stop --purge` deletes the containers, the database and memory volumes, the backups, the secrets (including the backup key) and the autostart entry (asks first). Your copy of the key outside this machine is not touched.
- Then remove the `sidekick-work` entry from `claude_desktop_config.json`, `docker image rm roadlake-sidekick:work`, and delete the checkout.
