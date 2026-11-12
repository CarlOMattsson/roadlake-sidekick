# Stoppa och avinstallera

[English](uninstall.md)

<!-- description: Stoppa Sidekick på jobbdatorn, eller ta bort allt: containrar, data, backuper och hemligheter. -->

Stoppa Sidekick på jobbdatorn, eller ta bort allt: containrar, data, backuper och hemligheter.

- `bash tools/work.sh stop` stoppar Sidekick; data och hemligheter ligger kvar.
- `bash tools/work.sh stop --purge` raderar containrar, databas- och minnesvolymer, säkerhetskopior, hemligheter (även säkerhetskopians nyckel) och autostart (frågar först). Din kopia av nyckeln utanför datorn rörs inte.
- Ta sedan bort `sidekick-work`-posten i `claude_desktop_config.json`, kör `docker image rm roadlake-sidekick:work` och radera repot.
