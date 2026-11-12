#!/usr/bin/env bash
# "Sidekick Work": Sidekick isolated on a work laptop, used from Claude Desktop through a local MCP server, with every
# model call going to the company's own OpenAI-compatible server (vLLM) and nowhere else.
# Platforms: written for Ubuntu (Linux with Docker Engine) and for macOS (Docker Desktop). Linux has been drilled on
# real containers (see docs/maintainers/verification.md); macOS has never been run.
# Compose overlay: deploy/work/compose.yaml on top of deploy/selfhost/compose.yaml, project sidekick-work.
# Docs: docs/start/work-laptop.sv.md and docs/start/work-laptop.md. Touches only the compose project sidekick-work.
# Portable bash: runs on bash 3.2 (macOS) and on Ubuntu; no associative arrays, no mapfile, no GNU-only flags.
#
#   bash tools/work.sh setup               interactive guide: language, model server, models, allowed addresses,
#                                          rooms, autostart; writes work.env; safe to run again
#   bash tools/work.sh init [--model-key]  copy work.env, generate secrets into deploy/work/secrets/ (700/600);
#                                          --model-key asks for the model server's API key again
#   bash tools/work.sh start [--build [--no-cache]]
#                                          build the image if missing (or with --build), start the stack, create the
#                                          owner user and write the Claude Desktop configuration (stdio, no token)
#   bash tools/work.sh claude-config       preview and confirm merging the entry into Claude Desktop; backs up first
#   bash tools/work.sh stop [--purge]      stop and remove containers; --purge also deletes data and secrets (asks)
#   bash tools/work.sh status              health, proof that the egress is closed, the model ids the server offers
#   bash tools/work.sh backup              dump the database and copy Hindsight's memory into deploy/work/backups/, both
#                                          encrypted with a key kept apart (deploy/work/secrets/backup.key); a backup counts
#                                          only after it was decrypted and checked again
#   bash tools/work.sh autostart on|off    start at login: systemd user unit (Linux) or launchd agent (macOS)
#   bash tools/work.sh update [--allow-breaking-migration]
#                                          backup (database and memory), git pull --ff-only, check the migration class,
#                                          build/pull, migrate, restart
#   bash tools/work.sh restore [SET] [--apply]
#                                          put the database and Hindsight's memory back from one backup set (a time
#                                          stamp or a path to either file; needs the same key); without --apply it only checks the set
#                                          and shows the plan; --apply asks for the project name, backs up first and
#                                          puts the previous data back if a step fails
#
# Texts are in Swedish or English: SIDEKICK_WORK_LANG, else SIDEKICK_WORK_LOCALE in work.env, else the system LANG.
# Compose output goes to deploy/work/work.log (a file, never a pipe); the last lines are shown on failure.
# No command prints a secret. The database passwords and the model key live only in files with mode 600.
# The whole script is one function call, so `update` can replace this very file without breaking the running copy.
set -euo pipefail
CALLER_UMASK="$(umask)"
umask 077

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEPLOY="$REPO/deploy"
SELFHOST="$DEPLOY/selfhost"
WORK="$DEPLOY/work"
WORK_ENV="$WORK/work.env"
SECRETS="$WORK/secrets"
GEN="$WORK/generated"
BACKUPS="$WORK/backups"
LOG="$WORK/work.log"
PROJECT="${SIDEKICK_WORK_PROJECT:-sidekick-work}"
GATEWAY_NAME=model.work.internal
# Free-space check and safe pruning, shared with deploy/selfhost/update.sh.
# shellcheck source=../deploy/selfhost/backup_space.sh
. "$SELFHOST/backup_space.sh"
KEEP_BACKUPS="${SIDEKICK_WORK_KEEP_BACKUPS:-7}"
ALLOW_PARSED=""
L=sv
DEFAULT_ROOMS="work,journal,contacts,control"

now() { date +%Y-%m-%dT%H:%M:%S; }
now_utc() { date -u +%Y-%m-%dT%H:%M:%SZ; }

compose() {
  local args
  args=(-p "$PROJECT" --project-directory "$SELFHOST" -f "$SELFHOST/compose.yaml" -f "$WORK/compose.yaml")
  if [ -f "$GEN/allow.compose.yaml" ]; then args+=(-f "$GEN/allow.compose.yaml"); fi
  # The self-hosted file demands a domain for its Caddy service (profile vps, never used here), even to parse.
  SELFHOST_DOMAIN=work.invalid docker compose "${args[@]}" --env-file "$WORK_ENV" --profile memory "$@"
}

# ---------------------------------------------------------------------------------------------------------
# Texts, one table. Language in $L (sv or en). Add a language by adding cases. %s are filled by sayf/errf.
msg() {
  case "$L:$1" in
    sv:lang_q|en:lang_q) printf '%s' 'Språk för den här guiden / Language of this guide (sv/en)' ;;
    sv:applang_q) printf '%s' 'Vilket språk ska appen och Claudes svar ha? (sv = svenska, en = engelska; Enter = förslaget)' ;;
    en:applang_q) printf '%s' 'Which language should the app and the answers use? (sv = Swedish, en = English; Enter = the proposal)' ;;
    sv:applang_bad|en:applang_bad) printf '%s' 'Svara sv eller en / Answer sv or en.' ;;
    sv:summary) printf '%s' 'Appens språk: %s. Rum: %s.' ;;
    en:summary) printf '%s' 'App language: %s. Rooms: %s.' ;;
    # --- guide (setup)
    sv:title) printf '%s' 'Sidekick Work: installationsguide' ;;
    en:title) printf '%s' 'Sidekick Work: setup guide' ;;
    sv:intro) printf '%s' 'Guiden ställer några frågor och skriver deploy/work/work.env. Du kan köra den igen när som helst; svaren du redan gett föreslås som standard.' ;;
    en:intro) printf '%s' 'The guide asks a few questions and writes deploy/work/work.env. You can run it again at any time; earlier answers are offered as defaults.' ;;
    sv:need) printf '%s' 'Saknas: %s. Installera det och kör guiden igen.' ;;
    en:need) printf '%s' 'Missing: %s. Install it and run the guide again.' ;;
    sv:compose_old) printf '%s' 'Docker Compose v2.24.4 eller nyare behövs (docker compose version).' ;;
    en:compose_old) printf '%s' 'Docker Compose v2.24.4 or newer is required (docker compose version).' ;;
    sv:url_q) printf '%s' 'Modellserverns adress (bas-URL, till exempel http://vllm.foretag.lan:8000/v1)' ;;
    en:url_q) printf '%s' 'Model server address (base URL, for example http://vllm.company.lan:8000/v1)' ;;
    sv:url_bad) printf '%s' 'Adressen går inte att använda: %s' ;;
    en:url_bad) printf '%s' 'That address cannot be used: %s' ;;
    sv:key_q) printf '%s' 'API-nyckel (dold inmatning; Enter behåller nuvarande, - tar bort)' ;;
    en:key_q) printf '%s' 'API key (hidden input; Enter keeps the current one, - removes it)' ;;
    sv:testing) printf '%s' 'Testar %s/models ...' ;;
    en:testing) printf '%s' 'Testing %s/models ...' ;;
    sv:test_ok) printf '%s' 'Servern svarar. %s modeller hittades.' ;;
    en:test_ok) printf '%s' 'The server answers. %s models found.' ;;
    sv:test_fail) printf '%s' 'Servern svarade inte som väntat (kontrollera adress, nyckel, nätverk/VPN).' ;;
    en:test_fail) printf '%s' 'The server did not answer as expected (check address, key, network/VPN).' ;;
    sv:retry_q) printf '%s' 'Försöka igen med en annan adress eller nyckel? (j/N)' ;;
    en:retry_q) printf '%s' 'Try again with another address or key? (y/N)' ;;
    sv:models_head) printf '%s' 'Modeller på servern:' ;;
    en:models_head) printf '%s' 'Models on the server:' ;;
    sv:mem_q) printf '%s' 'Modell för minnet (Hindsight, nummer eller id; en snabb modell räcker)' ;;
    en:mem_q) printf '%s' 'Model for memory (Hindsight, number or id; a fast model is enough)' ;;
    sv:allow_q) printf '%s' 'Fler adresser Sidekick får nå utöver modellservern (värdnamn:port, kommaseparerat; tomt = inga)' ;;
    en:allow_q) printf '%s' 'More addresses Sidekick may reach besides the model server (host:port, comma separated; empty = none)' ;;
    sv:allow_note) printf '%s' 'Allt annat är spärrat. Varje adress får en egen port på grindvakten och måste vara ett värdnamn.' ;;
    en:allow_note) printf '%s' 'Everything else is blocked. Each address needs its own port on the gateway and must be a host name.' ;;
    sv:allow_bad) printf '%s' 'Ogiltig lista: %s' ;;
    en:allow_bad) printf '%s' 'Invalid list: %s' ;;
    sv:rooms_q) printf '%s' 'Vilka rum vill du ha? (kommaseparerat: work, journal, shopping, contacts, control; - = alla; Enter = förslaget)' ;;
    en:rooms_q) printf '%s' 'Which rooms do you want? (comma separated: work, journal, shopping, contacts, control; - = all; Enter = the proposal)' ;;
    sv:rooms_note) printf '%s' 'work = Arbete (agenda, projekt, uppgifter, rutiner; krävs). journal = Dagbok (anteckningar och granskning). shopping = Inköp (listor och varor). contacts = Kontakter (personer och kopplingar). control = Kontroll (papperskorg, senaste ändringar och minnesreglage). Förslag för en jobbdator: alla rum utom inköp (work,journal,contacts,control); inköp är avstängt som förslag. Avstängda rum döljer verktyg och navigering; data behålls.' ;;
    en:rooms_note) printf '%s' 'work = Work (agenda, projects, tasks, routines; required). journal = Journal (entries and review). shopping = Shopping (lists and items). contacts = Contacts (people and links). control = Control (trash, recent changes and memory controls). Proposal for a work machine: every room except shopping (work,journal,contacts,control); shopping is off as a proposal. Disabled rooms hide tools and navigation; data is kept.' ;;
    sv:auto_q) printf '%s' 'Starta Sidekick automatiskt när du loggar in? (j/N)' ;;
    en:auto_q) printf '%s' 'Start Sidekick automatically when you log in? (y/N)' ;;
    sv:wrote) printf '%s' 'Skrev deploy/work/work.env. Hemligheter ligger i deploy/work/secrets/ (visas aldrig).' ;;
    en:wrote) printf '%s' 'Wrote deploy/work/work.env. Secrets are in deploy/work/secrets/ (never shown).' ;;
    sv:start_q) printf '%s' 'Starta Sidekick nu? (J/n)' ;;
    en:start_q) printf '%s' 'Start Sidekick now? (Y/n)' ;;
    sv:done) printf '%s' 'Klart. Kontroll: bash tools/work.sh status. Uppdatera senare: bash tools/work.sh update.' ;;
    en:done) printf '%s' 'Done. Check: bash tools/work.sh status. Update later: bash tools/work.sh update.' ;;
    sv:mobile) printf '%s' 'Obs: en lokal MCP nås inte från Claude på telefonen (kräver en connector); någon mobilväg finns inte i den här versionen.' ;;
    en:mobile) printf '%s' 'Note: a local MCP server cannot be reached from Claude on a phone (it needs a connector); there is no mobile route in this version.' ;;
    # --- address checks (python helpers use their own copies, same wording)
    sv:url_unset) printf '%s' 'SIDEKICK_WORK_MODEL_BASE_URL i deploy/work/work.env saknas eller är en platshållare.' ;;
    en:url_unset) printf '%s' 'SIDEKICK_WORK_MODEL_BASE_URL in deploy/work/work.env is missing or a placeholder.' ;;
    sv:mem_unset) printf '%s' 'SIDEKICK_WORK_MEMORY_MODEL i deploy/work/work.env saknas eller är en platshållare (Hindsights modell).' ;;
    en:mem_unset) printf '%s' "SIDEKICK_WORK_MEMORY_MODEL in deploy/work/work.env is missing or a placeholder (Hindsight's model)." ;;
    sv:url_unset_hint) printf '%s' 'Sätt den till modellserverns adress, till exempel http://vllm.foretag.lan:8000/v1 (eller kör: bash tools/work.sh setup)' ;;
    en:url_unset_hint) printf '%s' 'Set it to the model server address, for example http://vllm.company.lan:8000/v1 (or run: bash tools/work.sh setup)' ;;
    sv:port_clash) printf '%s' 'Modellserverns port (8765) krockar med grindvaktens interna MCP-port. Använd en annan port på modellservern.' ;;
    en:port_clash) printf '%s' "The model server's port (8765) clashes with the gateway's internal MCP port. Use another port on the model server." ;;
    # --- common
    sv:no_docker) printf '%s' 'docker saknas' ;;
    en:no_docker) printf '%s' 'docker is missing' ;;
    sv:no_tool) printf '%s' '%s saknas' ;;
    en:no_tool) printf '%s' '%s is missing' ;;
    sv:env_created) printf '%s' 'Skapade deploy/work/work.env. Redigera den (modellserverns adress och modell-id) och kör sedan om kommandot.' ;;
    en:env_created) printf '%s' 'Created deploy/work/work.env. Edit it (model server address and model ids), then run the command again.' ;;
    sv:no_secrets) printf '%s' 'Hemligheter saknas. Kör först: bash tools/work.sh init' ;;
    en:no_secrets) printf '%s' 'Secrets are missing. Run first: bash tools/work.sh init' ;;
    sv:no_work_env) printf '%s' 'deploy/work/work.env saknas. Kör: bash tools/work.sh setup' ;;
    en:no_work_env) printf '%s' 'deploy/work/work.env is missing. Run: bash tools/work.sh setup' ;;
    sv:model_key_ask) printf '%s' 'API-nyckel till modellservern (Enter om servern inte kräver någon): ' ;;
    en:model_key_ask) printf '%s' "API key for the model server (Enter if the server needs none): " ;;
    sv:model_key_saved) printf '%s' 'Modellnyckeln är sparad i %s (visas inte).' ;;
    en:model_key_saved) printf '%s' 'The model key is saved in %s (not shown).' ;;
    sv:model_key_none) printf '%s' 'Ingen modellnyckel sparad (servern antas inte kräva någon).' ;;
    en:model_key_none) printf '%s' 'No model key saved (the server is assumed to need none).' ;;
    # --- init
    sv:init_created) printf '%s' 'Hemligheter skapade i %s (katalog 700, filer 600). Inget av innehållet visas.' ;;
    en:init_created) printf '%s' 'Secrets created in %s (directory 700, files 600). None of the content is shown.' ;;
    sv:init_kept) printf '%s' 'Hemligheterna finns redan i %s och lämnas orörda (databaslösenord kan inte bytas på en befintlig databas).' ;;
    en:init_kept) printf '%s' 'The secrets already exist in %s and are left alone (database passwords cannot be changed on an existing database).' ;;
    sv:init_existing) printf '%s' 'En befintlig eller ofullständig installation hittades i %s (någon av sidekick.env, db.env, hindsight.env eller en hemlighetsfil från en äldre version finns). init skriver aldrig över hemligheter. Inget ändrat. Äldre installation: se importanvisningen (flytten går via kommandot sidekick-backup import; kör sidekick-backup import --help) och installera i en ny katalog. Annars: ta bort filerna för hand först om du är säker på att de inte behövs.' ;;
    en:init_existing) printf '%s' 'An existing or incomplete installation was found in %s (one of sidekick.env, db.env, hindsight.env or a secrets file from an older version exists). init never overwrites secrets. Nothing changed. Older installation: see the import instructions (the move goes through the command sidekick-backup import; run sidekick-backup import --help) and install in a new directory. Otherwise remove the files by hand first, if you are sure they are not needed.' ;;
    sv:init_key_hint) printf '%s' 'Byt bara modellnyckeln med: bash tools/work.sh init --model-key' ;;
    en:init_key_hint) printf '%s' 'Change only the model key with: bash tools/work.sh init --model-key' ;;
    sv:init_next) printf '%s' 'Nästa steg: redigera deploy/work/work.env (eller kör bash tools/work.sh setup), sedan: bash tools/work.sh start' ;;
    en:init_next) printf '%s' 'Next: edit deploy/work/work.env (or run bash tools/work.sh setup), then: bash tools/work.sh start' ;;
    # --- start
    sv:strict_umask) printf '%s' 'VARNING: umask %s är strängare än 022. Källkod och monterade startfiler behöver läs- och katalogrättigheter för containeranvändarna. Sidekick säkrar dessa rättigheter; hemlighetsfiler förblir 600. Bygg om en äldre avbildning med: bash tools/work.sh start --build' ;;
    en:strict_umask) printf '%s' 'WARNING: umask %s is stricter than 022. Source code and mounted startup files need read and directory permissions for container users. Sidekick ensures those permissions; secret files stay 600. Rebuild an older image with: bash tools/work.sh start --build' ;;
    sv:first_start_volume) printf '%s' 'Första databasstarten misslyckades: rollinitieringen kunde inte köras eller sidekick_migrator kan inte autentiseras, och inga migreringar har tillämpats. Volymen %s måste tas bort för att initieringen ska köras igen. Detta raderar databasvolymens innehåll; använd bara för denna ofullständiga installation. Inget raderas automatiskt. Behåll deploy/work/secrets/. Kör först:\n  %s\nSedan exakt:\n  %s\nStarta därefter med: bash tools/work.sh start --build' ;;
    en:first_start_volume) printf '%s' 'The first database start failed: role initialization could not run or sidekick_migrator cannot authenticate, and no migrations have been applied. Volume %s must be removed to rerun initialization. This deletes the database volume contents; use only for this incomplete installation. Nothing is deleted automatically. Keep deploy/work/secrets/. First run:\n  %s\nThen exactly:\n  %s\nThen start with: bash tools/work.sh start --build' ;;
    sv:docker_wait) printf '%s' 'Docker svarar inte.' ;;
    en:docker_wait) printf '%s' 'Docker does not answer.' ;;
    sv:building) printf '%s' 'Bygger Sidekick-avbildningen %s (några minuter första gången, hämtar beroenden).' ;;
    en:building) printf '%s' 'Building the Sidekick image %s (a few minutes the first time, fetches dependencies).' ;;
    sv:build_fail) printf '%s' 'bygget misslyckades; se %s' ;;
    en:build_fail) printf '%s' 'the build failed; see %s' ;;
    sv:up_fail) printf '%s' 'compose up misslyckades; se %s' ;;
    en:up_fail) printf '%s' 'compose up failed; see %s' ;;
    sv:gw_fail) printf '%s' 'grindvakten startade inte om; se %s' ;;
    en:gw_fail) printf '%s' 'the gateway did not restart; see %s' ;;
    sv:started) printf '%s' 'Startad.' ;;
    en:started) printf '%s' 'Started.' ;;
    sv:old_image) printf '%s' 'Avbildningen saknar stdio-ingången (den är byggd före den fanns). Kör: bash tools/work.sh start --build' ;;
    en:old_image) printf '%s' 'The image has no stdio entry point (it was built before it existed). Run: bash tools/work.sh start --build' ;;
    sv:owner_stale) printf '%s' 'secrets/user-id pekar på en användare som inte finns i den här databasen (ny eller tom databas?). Använder användaren jobb i databasen, eller skapar den.' ;;
    en:owner_stale) printf '%s' 'secrets/user-id points to a user that does not exist in this database (a new or empty database?). Using the user jobb of the database, or creating it.' ;;
    sv:user_fail) printf '%s' 'kunde inte skapa ägaranvändaren; se %s' ;;
    en:user_fail) printf '%s' 'could not create the owner user; see %s' ;;
    sv:desktop_written) printf '%s' 'Claude Desktop-inställning (ingen token, startar Sidekick via docker exec): %s' ;;
    en:desktop_written) printf '%s' 'Claude Desktop configuration (no token, starts Sidekick through docker exec): %s' ;;
    sv:desktop_hint) printf '%s' 'Lägg innehållet under "mcpServers" i claude_desktop_config.json (Linux: ~/.config/Claude/, macOS: ~/Library/Application Support/Claude/), eller kör bash tools/work.sh claude-config för förhandsvisning och bekräftelse. Starta sedan om Claude Desktop helt.' ;;
    en:desktop_hint) printf '%s' 'Merge it under "mcpServers" in claude_desktop_config.json (Linux: ~/.config/Claude/, macOS: ~/Library/Application Support/Claude/), or run bash tools/work.sh claude-config for preview and confirmation. Then restart Claude Desktop completely.' ;;
    sv:desktop_nodocker) printf '%s' 'Hittar inte docker med absolut sökväg; Claude Desktop behöver den.' ;;
    en:desktop_nodocker) printf '%s' 'Cannot find docker by absolute path; Claude Desktop needs it.' ;;
    # --- stop
    sv:purge_q) printf '%s' "Detta raderar Sidekick Works databas, minne, säkerhetskopior och hemligheter. Skriv 'ja' för att fortsätta: " ;;
    en:purge_q) printf '%s' "This deletes Sidekick Work's database, memory, backups and secrets. Type 'yes' to continue: " ;;
    sv:purge_yes) printf '%s' 'ja' ;;
    en:purge_yes) printf '%s' 'yes' ;;
    sv:aborted) printf '%s' 'Avbrutet, inget raderat.' ;;
    en:aborted) printf '%s' 'Aborted, nothing deleted.' ;;
    sv:down_fail) printf '%s' 'compose down misslyckades; se %s' ;;
    en:down_fail) printf '%s' 'compose down failed; see %s' ;;
    sv:purged) printf '%s' 'Raderat: containrar, volymer, säkerhetskopior, hemligheter och autostart. work.env finns kvar.' ;;
    en:purged) printf '%s' 'Deleted: containers, volumes, backups, secrets and autostart. work.env remains.' ;;
    sv:stopped) printf '%s' 'Stoppad. Data och hemligheter ligger kvar (radera med: bash tools/work.sh stop --purge).' ;;
    en:stopped) printf '%s' 'Stopped. Data and secrets remain (delete with: bash tools/work.sh stop --purge).' ;;
    # --- status
    sv:st_not_running) printf '%s' '%s: kör inte' ;;
    en:st_not_running) printf '%s' '%s: not running' ;;
    sv:st_unknown) printf '%s' 'okänd' ;;
    en:st_unknown) printf '%s' 'unknown' ;;
    sv:st_version) printf '%s' 'version: commit %s (%s), byggd %s, senast uppdaterad %s' ;;
    en:st_version) printf '%s' 'version: commit %s (%s), built %s, last updated %s' ;;
    sv:st_noauth) printf '%s' 'MCP-porten utan token (ska vara 401): %s' ;;
    en:st_noauth) printf '%s' 'The MCP port without a token (should be 401): %s' ;;
    sv:st_api_down) printf '%s' 'Sidekick kör inte, hoppar över spärrkontrollen.' ;;
    en:st_api_down) printf '%s' 'Sidekick is not running, skipping the egress check.' ;;
    sv:st_probe_api) printf '%s' 'Spärrkontroll från api-containern (alla fyra ska vara spärrade):' ;;
    en:st_probe_api) printf '%s' 'Egress check from the api container (all four should be blocked):' ;;
    sv:st_probe_hs) printf '%s' 'Spärrkontroll från hindsight-containern:' ;;
    en:st_probe_hs) printf '%s' 'Egress check from the hindsight container:' ;;
    sv:st_probe_fail) printf '%s' 'kunde inte köra kontrollen' ;;
    en:st_probe_fail) printf '%s' 'could not run the check' ;;
    sv:st_direct) printf '%s' 'modellservern direkt' ;;
    en:st_direct) printf '%s' 'the model server directly' ;;
    sv:st_reached) printf '%s' 'NÅDDE' ;;
    en:st_reached) printf '%s' 'REACHED' ;;
    sv:st_blocked) printf '%s' 'spärrad' ;;
    en:st_blocked) printf '%s' 'blocked' ;;
    sv:st_via) printf '%s' 'Via grindvakten till modellservern:' ;;
    en:st_via) printf '%s' 'Through the gateway to the model server:' ;;
    sv:st_models) printf '%s' 'modeller %s' ;;
    en:st_models) printf '%s' 'models %s' ;;
    sv:st_models_err) printf '%s' 'modeller FEL %s' ;;
    en:st_models_err) printf '%s' 'models ERROR %s' ;;
    sv:st_outside) printf '%s' 'utanför bassökvägen %s' ;;
    en:st_outside) printf '%s' 'outside the base path %s' ;;
    sv:st_outside_reached) printf '%s' 'utanför bassökvägen NÅDDE' ;;
    en:st_outside_reached) printf '%s' 'outside the base path REACHED' ;;
    sv:st_outside_err) printf '%s' 'utanför bassökvägen FEL %s' ;;
    en:st_outside_err) printf '%s' 'outside the base path ERROR %s' ;;
    sv:st_model_ok) printf '%s' 'modell-id finns hos servern: %s' ;;
    en:st_model_ok) printf '%s' 'model id exists on the server: %s' ;;
    sv:st_model_missing) printf '%s' "VARNING: modell-id '%s' finns inte i serverns lista; rätta work.env" ;;
    en:st_model_missing) printf '%s' "WARNING: model id '%s' is not in the server's list; correct work.env" ;;
    sv:st_desktop_ok) printf '%s' 'Claude Desktop-inställning finns: %s' ;;
    en:st_desktop_ok) printf '%s' 'Claude Desktop configuration exists: %s' ;;
    sv:st_desktop_missing) printf '%s' 'Claude Desktop-inställning saknas; kör: bash tools/work.sh start' ;;
    en:st_desktop_missing) printf '%s' 'Claude Desktop configuration is missing; run: bash tools/work.sh start' ;;
    # --- autostart
    sv:as_launchd) printf '%s' 'Autostart på (launchd): %s. Docker Desktop måste också starta vid inloggning (dess egen inställning).' ;;
    en:as_launchd) printf '%s' 'Autostart on (launchd): %s. Docker Desktop must also start at login (its own setting).' ;;
    sv:as_systemd) printf '%s' 'Autostart på (systemd --user): %s. För start även utan inloggning: sudo loginctl enable-linger %s' ;;
    en:as_systemd) printf '%s' 'Autostart on (systemd --user): %s. To start without logging in: sudo loginctl enable-linger %s' ;;
    sv:as_off) printf '%s' 'Autostart av.' ;;
    en:as_off) printf '%s' 'Autostart off.' ;;
    sv:as_state_on) printf '%s' 'på: %s' ;;
    en:as_state_on) printf '%s' 'on: %s' ;;
    sv:as_state_off) printf '%s' 'av' ;;
    en:as_state_off) printf '%s' 'off' ;;
    sv:as_usage) printf '%s' 'användning: bash tools/work.sh autostart on|off|status' ;;
    en:as_usage) printf '%s' 'usage: bash tools/work.sh autostart on|off|status' ;;
    # --- backup and update
    sv:bk_db_start) printf '%s' 'databasen startade inte; se %s. Inget ändrat.' ;;
    en:bk_db_start) printf '%s' 'the database did not start; see %s. Nothing changed.' ;;
    sv:bk_fail) printf '%s' 'Säkerhetskopian misslyckades. Avbryter innan något ändrats; se %s.' ;;
    en:bk_fail) printf '%s' 'The backup failed. Stopping before anything is changed; see %s.' ;;
    sv:bk_db_ok) printf '%s' 'Krypterad säkerhetskopia av databasen: %s (avkrypterad och kontrollerad)' ;;
    en:bk_db_ok) printf '%s' 'Encrypted database backup: %s (decrypted and checked again)' ;;
    sv:bk_key_new) printf '%s' 'En ny nyckel för säkerhetskopiorna skapades: %s
Kopiera den nu till en plats utanför den här datorn, skild från säkerhetskopiorna (till exempel en lösenordshanterare eller ett USB-minne som förvaras separat). Utan nyckeln går säkerhetskopiorna inte att läsa. Innehållet visas aldrig.' ;;
    en:bk_key_new) printf '%s' 'A new key for the backups was created: %s
Copy it now to a place outside this computer, apart from the backups (for example a password manager or a USB stick kept separately). Without the key the backups cannot be read. The content is never shown.' ;;
    sv:bk_key_missing) printf '%s' 'Nyckeln för säkerhetskopiorna saknas: %s. Krypterade säkerhetskopior finns i %s och går bara att läsa med den nyckeln. Lägg tillbaka nyckelfilen från din kopia utanför datorn (en ny nyckel skapas inte åt dig, för då skulle de gamla kopiorna bli oläsliga). Inget ändrat.' ;;
    en:bk_key_missing) printf '%s' 'The key for the backups is missing: %s. Encrypted backups are in %s and can only be read with that key. Put the key file back from your copy outside this computer (a new key is not created for you, because the old backups would become unreadable). Nothing changed.' ;;
    sv:bk_key_bad) printf '%s' 'Nyckelfilen %s innehåller ingen giltig nyckel (44 tecken, URL-säker base64). Inget ändrat.' ;;
    en:bk_key_bad) printf '%s' 'The key file %s does not hold a valid key (44 characters, URL-safe base64). Nothing changed.' ;;
    sv:bk_key_inside) printf '%s' 'Nyckelfilen %s ligger i säkerhetskopiornas katalog %s. Nyckeln ska förvaras skilt från kopiorna. Inget ändrat.' ;;
    en:bk_key_inside) printf '%s' 'The key file %s is inside the backup directory %s. The key must be kept apart from the backups. Nothing changed.' ;;
    sv:bk_verify_fail) printf '%s' 'Säkerhetskopian %s gick inte att läsa tillbaka (avkryptering och kontroll misslyckades) och räknas därför inte. Den har tagits bort; se %s.' ;;
    en:bk_verify_fail) printf '%s' 'The backup %s could not be read back (decryption and check failed), so it does not count. It has been removed; see %s.' ;;
    sv:bk_writers_pause) printf '%s' 'Pausar %s medan kopiorna tas, så att databasen och minnet hänger ihop ...' ;;
    en:bk_writers_pause) printf '%s' 'Pausing %s while the copies are made, so that the database and the memory match ...' ;;
    sv:bk_writers_fail) printf '%s' 'Säkerhetskopiorna är klara men %s startade inte igen; se %s.' ;;
    en:bk_writers_fail) printf '%s' 'The backup files are done but %s did not start again; see %s.' ;;
    sv:bk_mem_pause) printf '%s' 'Stoppar Hindsight en stund för en konsekvent kopia av minnet ...' ;;
    en:bk_mem_pause) printf '%s' "Stopping Hindsight for a moment for a consistent copy of the memory ..." ;;
    sv:bk_mem_ok) printf '%s' 'Krypterad säkerhetskopia av Hindsights minne: %s (avkrypterad och kontrollerad)' ;;
    en:bk_mem_ok) printf '%s' "Encrypted backup of Hindsight's memory: %s (decrypted and checked again)" ;;
    sv:bk_mem_none) printf '%s' 'Hindsights minnesvolym finns inte än; inget minne att kopiera.' ;;
    en:bk_mem_none) printf '%s' "Hindsight's memory volume does not exist yet; no memory to copy." ;;
    sv:bk_space) printf '%s' 'För lite ledigt utrymme för en ny säkerhetskopia i %s: %s byte ledigt, %s behövs (den senaste kopian gånger marginalen, minst golvet). Inget ändrat och inget stoppat. Frigör utrymme eller flytta gamla kopior; marginalen styrs av SIDEKICK_BACKUP_SPACE_MARGIN_PCT och golvet av SIDEKICK_BACKUP_SPACE_FLOOR_MB.' ;;
    en:bk_space) printf '%s' 'Not enough free space for a new backup in %s: %s bytes free, %s needed (the latest backup times the margin, at least the floor). Nothing changed and nothing stopped. Free up space or move old backups away; the margin is set by SIDEKICK_BACKUP_SPACE_MARGIN_PCT and the floor by SIDEKICK_BACKUP_SPACE_FLOOR_MB.' ;;
    sv:bk_space_unknown) printf '%s' 'Kunde inte avgöra om det finns utrymme för en ny säkerhetskopia i %s (df gav inget svar, eller SIDEKICK_BACKUP_SPACE_MARGIN_PCT / SIDEKICK_BACKUP_SPACE_FLOOR_MB är inte giltiga tal; marginalen är minst 100). Inget ändrat och inget stoppat.' ;;
    en:bk_space_unknown) printf '%s' 'Could not tell whether there is room for a new backup in %s (df gave no answer, or SIDEKICK_BACKUP_SPACE_MARGIN_PCT / SIDEKICK_BACKUP_SPACE_FLOOR_MB is not a valid number; the margin is at least 100). Nothing changed and nothing stopped.' ;;
    sv:bk_keep_bad) printf '%s' 'SIDEKICK_WORK_KEEP_BACKUPS=%s är inte ett heltal på minst 1. Inget ändrat.' ;;
    en:bk_keep_bad) printf '%s' 'SIDEKICK_WORK_KEEP_BACKUPS=%s is not a whole number of at least 1. Nothing changed.' ;;
    sv:bk_keep) printf '%s' 'De %s senaste av varje slag sparas i %s.' ;;
    en:bk_keep) printf '%s' 'The last %s of each kind are kept in %s.' ;;
    sv:up_pull_fail) printf '%s' 'git pull --ff-only misslyckades (lokala ändringar eller en annan historik). Inget ändrat; se %s.' ;;
    en:up_pull_fail) printf '%s' 'git pull --ff-only failed (local changes or a different history). Nothing changed; see %s.' ;;
    sv:up_no_git) printf '%s' 'update kräver att repot är klonat med git (git clone), inte nedladdat som zip. Inget ändrat.' ;;
    en:up_no_git) printf '%s' 'update needs the repository to be cloned with git (git clone), not downloaded as a zip. Nothing changed.' ;;
    sv:up_same) printf '%s' 'Koden var redan senaste (%s).' ;;
    en:up_same) printf '%s' 'The code was already the latest (%s).' ;;
    sv:up_changed) printf '%s' 'Uppdaterad: %s -> %s' ;;
    en:up_changed) printf '%s' 'Updated: %s -> %s' ;;
    sv:up_contract) printf '%s' 'uppdateringen innehåller migreringar som den gamla koden inte kan köras mot (DROP, RENAME, typbyte på kolumn, SET NOT NULL, REVOKE eller markören "migration-class: contract"); de står ovan och i %s. Inget har stoppats eller migrerats; koden hämtades och läggs tillbaka på föregående commit. Vill du ta uppdateringen ändå: bash tools/work.sh update --allow-breaking-migration (den tar en säkerhetskopia före migreringen; att gå tillbaka efteråt betyder att återställa den).' ;;
    en:up_contract) printf '%s' 'the update holds migrations that the old code cannot run against (DROP, RENAME, a column type change, SET NOT NULL, REVOKE or the "migration-class: contract" marker); they are listed above and in %s. Nothing was stopped or migrated; the code was fetched and is put back on the previous commit. To take the update anyway: bash tools/work.sh update --allow-breaking-migration (it takes a backup before the migration; going back afterwards means restoring that backup).' ;;
    sv:up_class_fail) printf '%s' 'kunde inte kontrollera migreringsklassen; se %s. Koden läggs tillbaka på föregående commit; inget har stoppats.' ;;
    en:up_class_fail) printf '%s' 'could not check the migration class; see %s. The code is put back on the previous commit; nothing was stopped.' ;;
    sv:up_class_stuck) printf '%s' 'koden kunde inte läggas tillbaka på föregående commit (lokala ändringar i vägen?). Gör det själv: git -C %s reset --keep %s' ;;
    en:up_class_stuck) printf '%s' 'the code could not be put back on the previous commit (local changes in the way?). Do it yourself: git -C %s reset --keep %s' ;;
    sv:up_building) printf '%s' 'Hämtar och bygger avbildningar ...' ;;
    en:up_building) printf '%s' 'Fetching and building images ...' ;;
    sv:up_offline) printf '%s' 'Varning: kunde inte hämta färska avbildningar (offline?); använder de som finns.' ;;
    en:up_offline) printf '%s' 'Warning: could not fetch fresh images (offline?); using the ones present.' ;;
    sv:up_build_fail) printf '%s' 'bygget misslyckades; se %s. Inget har stoppats eller migrerats; föregående version körs vidare.' ;;
    en:up_build_fail) printf '%s' 'the build failed; see %s. Nothing was stopped or migrated; the previous version keeps running.' ;;
    sv:up_restart_fail) printf '%s' 'omstarten misslyckades; se %s. Säkerhetskopiorna ligger i %s.' ;;
    en:up_restart_fail) printf '%s' 'the restart failed; see %s. The backups are in %s.' ;;
    sv:up_rollback) printf '%s' 'Koden är redan uppdaterad (%s -> %s); inget har rullats tillbaka automatiskt. Gå tillbaka till föregående version med:
  git -C %s checkout %s && bash tools/work.sh start --build
Säkerhetskopior (databas och minne) från före uppdateringen: %s. Återställ dem bara om du vet att data skadats
(bash tools/work.sh restore <tid>, först utan --apply).
Vill du senare uppdatera igen: git -C %s checkout %s' ;;
    en:up_rollback) printf '%s' 'The code is already updated (%s -> %s); nothing was rolled back automatically. Go back to the previous version with:
  git -C %s checkout %s && bash tools/work.sh start --build
Backups (database and memory) from before the update: %s. Restore them only if you know data was damaged
(bash tools/work.sh restore <time>, first without --apply).
To update again later: git -C %s checkout %s' ;;
    sv:up_prev_saved) printf '%s' 'Föregående avbildning sparad som %s (för återgång).' ;;
    en:up_prev_saved) printf '%s' 'The previous image is kept as %s (for going back).' ;;
    sv:up_old_running) printf '%s' 'Uppdateringen avbröts före migreringen: föregående version körs igen (avbildning %s) och databasen är orörd.' ;;
    en:up_old_running) printf '%s' 'The update stopped before the migration: the previous version runs again (image %s) and the database is untouched.' ;;
    sv:up_retag_failed) printf '%s' 'VARNING: avbildningsnamnet %s kunde inte sättas tillbaka till föregående avbildning (se %s); det pekar kvar på det nya bygget. Föregående avbildning finns kvar som %s.' ;;
    en:up_retag_failed) printf '%s' 'WARNING: the image name %s could not be put back on the previous image (see %s); it still points at the new build. The previous image is kept as %s.' ;;
    sv:up_old_not_running) printf '%s' 'Uppdateringen avbröts före migreringen och databasen är orörd, men föregående version körs INTE: avbildningsnamnet %s pekar kvar på det nya bygget. Föregående avbildning finns som %s (docker tag %s %s återställer namnet).' ;;
    en:up_old_not_running) printf '%s' 'The update stopped before the migration and the database is untouched, but the previous version is NOT running: the image name %s still points at the new build. The previous image is kept as %s (docker tag %s %s restores the name).' ;;
    sv:up_old_failed) printf '%s' 'Uppdateringen avbröts före migreringen men föregående version kunde inte startas igen; se %s. Skrivarna är stoppade. Databasen är orörd: bash tools/work.sh start startar om.' ;;
    en:up_old_failed) printf '%s' 'The update stopped before the migration but the previous version could not be started again; see %s. The writers are stopped. The database is untouched: bash tools/work.sh start starts it again.' ;;
    sv:up_stay_stopped) printf '%s' 'Skrivarna (%s) lämnas stoppade: migreringen har påbörjats och databasens tillstånd är osäkert. Inget har återställts automatiskt. Säkerhetskopian från före uppdateringen: databas %s och minne %s i %s. Återställ den bara om du vet att data skadats: bash tools/work.sh restore %s (först utan --apply). Föregående avbildning finns kvar som %s.' ;;
    en:up_stay_stopped) printf '%s' 'The writers (%s) are left stopped: the migration has begun and the state of the database is uncertain. Nothing was restored automatically. The backup from before the update: database %s and memory %s in %s. Restore it only if you know data was damaged: bash tools/work.sh restore %s (first without --apply). The previous image is kept as %s.' ;;
    sv:up_migrate_fail) printf '%s' 'migreringen misslyckades; se %s. Skrivarna förblir stoppade. Säkerhetskopiorna ligger i %s. Se avsnittet "Gå tillbaka efter en misslyckad uppdatering" i docs/operate/work-laptop/backup-and-update.sv.md.' ;;
    en:up_migrate_fail) printf '%s' 'the migration failed; see %s. The writers stay stopped. The backups are in %s. See the section "Going back after a failed update" in docs/operate/work-laptop/backup-and-update.md.' ;;
    sv:up_ready_wait) printf '%s' 'Väntar på att databasen och schemat är redo (högst %s s) ...' ;;
    en:up_ready_wait) printf '%s' 'Waiting for the database and the schema to be ready (up to %s s) ...' ;;
    sv:up_ready_fail) printf '%s' 'api:t blev inte redo (databas och schemarevision); se %s. Säkerhetskopiorna ligger i %s.' ;;
    en:up_ready_fail) printf '%s' 'the api did not become ready (database and schema revision); see %s. The backups are in %s.' ;;
    sv:up_done) printf '%s' 'Klart. Version och tidpunkt finns i %s (och i bash tools/work.sh status).' ;;
    en:up_done) printf '%s' 'Done. Version and time are in %s (and in bash tools/work.sh status).' ;;
    # --- restore
    sv:rs_usage) printf '%s' 'användning: bash tools/work.sh restore <tidsstämpel ÅÅÅÅMMDD-TTMMSS | sökväg till sidekick-<tid>.sql.enc eller hindsight-<tid>.tar.gz.enc> [--apply]' ;;
    en:rs_usage) printf '%s' 'usage: bash tools/work.sh restore <time stamp YYYYMMDD-HHMMSS | path to sidekick-<time>.sql.enc or hindsight-<time>.tar.gz.enc> [--apply]' ;;
    sv:rs_sets) printf '%s' 'Kompletta säkerhetskopior i %s:' ;;
    en:rs_sets) printf '%s' 'Complete backup sets in %s:' ;;
    sv:rs_no_sets) printf '%s' 'Inga kompletta säkerhetskopior (databas och minne med samma tid) i %s.' ;;
    en:rs_no_sets) printf '%s' 'No complete backup sets (database and memory with the same time) in %s.' ;;
    sv:rs_bad_name) printf '%s' '%s är varken en tidsstämpel (ÅÅÅÅMMDD-TTMMSS) eller en fil från bash tools/work.sh backup. Inget ändrat.' ;;
    en:rs_bad_name) printf '%s' '%s is neither a time stamp (YYYYMMDD-HHMMSS) nor a file from bash tools/work.sh backup. Nothing changed.' ;;
    sv:rs_missing) printf '%s' 'Säkerhetskopian är ofullständig: %s saknas eller är tom. Databasen och minnet återställs bara tillsammans. Inget ändrat.' ;;
    en:rs_missing) printf '%s' 'The backup set is incomplete: %s is missing or empty. The database and the memory are only restored together. Nothing changed.' ;;
    sv:rs_bad_dump) printf '%s' '%s är ingen komplett databasdump som går att läsa med nyckeln i %s (fel nyckel, skadad fil eller slutmarkeringen saknas). Inget ändrat.' ;;
    en:rs_bad_dump) printf '%s' '%s is not a complete database dump readable with the key in %s (wrong key, damaged file or the end marker is missing). Nothing changed.' ;;
    sv:rs_bad_archive) printf '%s' '%s är inget läsbart minnesarkiv med nyckeln i %s (fel nyckel, skadad fil eller tomt arkiv). Inget ändrat.' ;;
    en:rs_bad_archive) printf '%s' '%s is not a readable memory archive with the key in %s (wrong key, damaged file or empty archive). Nothing changed.' ;;
    sv:rs_no_ownership) printf '%s' '%s saknas; utcheckningen är ofullständig. Inget ändrat.' ;;
    en:rs_no_ownership) printf '%s' '%s is missing; the checkout is incomplete. Nothing changed.' ;;
    sv:rs_no_volume) printf '%s' 'Hindsights minnesvolym finns inte i projektet %s. Kör bash tools/work.sh start först. Inget ändrat.' ;;
    en:rs_no_volume) printf '%s' "Hindsight's memory volume does not exist in the project %s. Run bash tools/work.sh start first. Nothing changed." ;;
    sv:rs_plan) printf '%s' 'Återställning från en säkerhetskopia:
  databas: %s
  minne:   %s
  mål:     projektet %s (databasen sidekick och Hindsights minnesvolym)
Filerna är krypterade och läses utan att någon klartextfil skrivs till disk.
Med --apply: 1) en ny säkerhetskopia av det som finns nu, till %s (vägen tillbaka), 2) api, memory-worker och
automation-worker pausas, 3) databasen sidekick döps om (raderas inte) och dumpen läses in i en ny, 4) Hindsight
stoppas och volymen ersätts med arkivet, 5) migreringen körs, 6) allt startas och api:t ska bli redo.
Misslyckas steg 3-5 läggs den förra databasen och det förra minnet tillbaka automatiskt.' ;;
    en:rs_plan) printf '%s' 'Restore from a backup set:
  database: %s
  memory:   %s
  target:   the project %s (the database sidekick and the memory volume of Hindsight)
The files are encrypted and are read without writing any plain file to disk.
With --apply: 1) a fresh backup of what is there now, to %s (the way back), 2) api, memory-worker and
automation-worker are paused, 3) the database sidekick is renamed (not deleted) and the dump is read into a new one,
4) Hindsight is stopped and its volume is replaced by the archive, 5) the migration runs, 6) everything is started
and the api must become ready. If step 3-5 fails, the previous database and memory are put back automatically.' ;;
    sv:rs_dry) printf '%s' 'Provkörning: inget ändrat. Kör igen med --apply för att återställa.' ;;
    en:rs_dry) printf '%s' 'Dry run: nothing changed. Run again with --apply to restore.' ;;
    sv:rs_confirm_q) printf '%s' 'Detta ersätter databasen och minnet i projektet %s. Skriv projektets namn för att fortsätta: ' ;;
    en:rs_confirm_q) printf '%s' 'This replaces the database and the memory of the project %s. Type the project name to continue: ' ;;
    sv:rs_safety) printf '%s' 'Vägen tillbaka, det som fanns före återställningen: %s och %s' ;;
    en:rs_safety) printf '%s' 'The way back, what was there before the restore: %s and %s' ;;
    sv:rs_db) printf '%s' 'Läser in databasen (den förra behålls som %s) ...' ;;
    en:rs_db) printf '%s' 'Reading the database in (the previous one is kept as %s) ...' ;;
    sv:rs_mem) printf '%s' 'Ersätter Hindsights minne ...' ;;
    en:rs_mem) printf '%s' "Replacing Hindsight's memory ..." ;;
    sv:rs_migrating) printf '%s' 'Kör migreringen mot den återställda databasen ...' ;;
    en:rs_migrating) printf '%s' 'Running the migration against the restored database ...' ;;
    sv:rs_step_db) printf '%s' 'databasen' ;;
    en:rs_step_db) printf '%s' 'the database' ;;
    sv:rs_step_mem) printf '%s' 'minnet' ;;
    en:rs_step_mem) printf '%s' 'the memory' ;;
    sv:rs_step_migrate) printf '%s' 'migreringen' ;;
    en:rs_step_migrate) printf '%s' 'the migration' ;;
    sv:rs_fail) printf '%s' 'Återställningen misslyckades vid %s; se %s.' ;;
    en:rs_fail) printf '%s' 'The restore failed at %s; see %s.' ;;
    sv:rs_rolled_back) printf '%s' 'Det som fanns före är tillbaka: databasen sidekick (från %s) och minnet (från %s). Inget från säkerhetskopian ligger kvar.' ;;
    en:rs_rolled_back) printf '%s' 'What was there before is back: the database sidekick (from %s) and the memory (from %s). Nothing from the backup set remains.' ;;
    sv:rs_rollback_fail) printf '%s' 'Kunde inte lägga tillbaka allt automatiskt; se %s. Hindsight och skrivarna lämnas stoppade. Den förra databasen heter %s om den inte redan döpts tillbaka, och säkerhetskopian av det som fanns före är %s och %s. Se avsnittet "Återställa från en säkerhetskopia" i docs/operate/work-laptop/backup-and-update.sv.md.' ;;
    en:rs_rollback_fail) printf '%s' 'Could not put everything back automatically; see %s. Hindsight and the writers are left stopped. The previous database is %s unless it was already renamed back, and the backup of what was there before is %s and %s. See the section "Restoring from a backup" in docs/operate/work-laptop/backup-and-update.md.' ;;
    sv:rs_start_fail) printf '%s' 'Säkerhetskopian är inläst men tjänsterna startade inte; se %s. Den förra databasen finns kvar som %s; säkerhetskopian av det som fanns före är %s och %s.' ;;
    en:rs_start_fail) printf '%s' 'The backup set is in place but the services did not start; see %s. The previous database is kept as %s; the backup of what was there before is %s and %s.' ;;
    sv:rs_ready_fail) printf '%s' 'Säkerhetskopian är inläst men api:t blev inte redo (databas och schemarevision); se %s. Inget rullas tillbaka nu, eftersom tjänsterna redan kört mot den återställda datan. Den förra databasen finns kvar som %s; säkerhetskopian av det som fanns före är %s och %s.' ;;
    en:rs_ready_fail) printf '%s' 'The backup set is in place but the api did not become ready (database and schema revision); see %s. Nothing is rolled back now, because the services already ran against the restored data. The previous database is kept as %s; the backup of what was there before is %s and %s.' ;;
    sv:rs_owner_none) printf '%s' 'Den återställda databasen har ingen användare jobb; en ny skapas för Claude Desktop.' ;;
    en:rs_owner_none) printf '%s' 'The restored database has no user jobb; a new one is created for Claude Desktop.' ;;
    sv:rs_done) printf '%s' 'Återställt från %s. Den förra databasen finns kvar som %s. Fråga Claude Desktop efter något du vet finns i den återställda datan; när du är säker frigör du platsen med:
  docker exec %s-postgres-1 psql -U postgres -d postgres -c "DROP DATABASE %s"' ;;
    en:rs_done) printf '%s' 'Restored from %s. The previous database is kept as %s. Ask Claude Desktop for something you know is in the restored data; when you are sure, free the space with:
  docker exec %s-postgres-1 psql -U postgres -d postgres -c "DROP DATABASE %s"' ;;
    sv:busy) printf '%s' 'Ett annat ändrande kommando i Sidekick Work pågår redan (%s; låset är %s). Vänta tills det är klart och försök igen; status går att köra under tiden. Inget ändrat.' ;;
    en:busy) printf '%s' 'Another changing Sidekick Work command is already running (%s; the lock is %s). Wait until it has finished and try again; status can be run meanwhile. Nothing changed.' ;;
    sv:writers_unknown) printf '%s' 'Kunde inte avgöra vilka av %s som körs (docker compose ps misslyckades); se %s. Avbryter innan något ändras.' ;;
    en:writers_unknown) printf '%s' 'Could not tell which of %s are running (docker compose ps failed); see %s. Stopping before anything is changed.' ;;
    sv:writers_still) printf '%s' 'Något av %s körs fortfarande efter stoppet. Avbryter innan något ändras.' ;;
    en:writers_still) printf '%s' 'One of %s is still running after the stop. Stopping before anything is changed.' ;;
    sv:usage) printf '%s' 'användning: bash tools/work.sh setup | init [--model-key] | start [--build [--no-cache]] | claude-config | stop [--purge] | status | backup | autostart on|off|status | update [--allow-breaking-migration] | restore [SET] [--apply]' ;;
    en:usage) printf '%s' 'usage: bash tools/work.sh setup | init [--model-key] | start [--build [--no-cache]] | claude-config | stop [--purge] | status | backup | autostart on|off|status | update [--allow-breaking-migration] | restore [SET] [--apply]' ;;
    *) printf '%s' "$1" ;;
  esac
}

say() { printf '%s\n' "$(msg "$1")"; }
# sayf KEY args...: the text as a printf format on stdout; errf: the same on stderr.
sayf() { local f; f="$(msg "$1")"; shift; printf "$f\n" "$@"; }
errf() { local f; f="$(msg "$1")"; shift; printf "$f\n" "$@" >&2; }

# Language of the texts: SIDEKICK_WORK_LANG, else SIDEKICK_WORK_LOCALE in work.env, else the system language.
init_lang() {
  local v="${SIDEKICK_WORK_LANG:-}"
  if [ -z "$v" ]; then v="$(envval SIDEKICK_WORK_LOCALE)"; fi
  if [ -z "$v" ]; then v="${LANG:-}"; fi
  case "$v" in sv*|SV*) L=sv ;; *) L=en ;; esac
}

need_docker() { command -v docker >/dev/null 2>&1 || { errf no_docker; exit 1; }; }
need_tool() { command -v "$1" >/dev/null 2>&1 || { errf no_tool "$1"; exit 1; }; }

warn_strict_umask() {
  if [ "$((8#$CALLER_UMASK & 0755))" -ne 0 ]; then errf strict_umask "$CALLER_UMASK"; fi
}

# One plain value from work.env (last assignment wins, quotes stripped). Never sourced: values hold spaces.
envval() {
  [ -f "$WORK_ENV" ] || return 0
  sed -n "s/^[[:space:]]*$1=//p" "$WORK_ENV" | tail -n 1 | sed -e 's/^"\(.*\)"$/\1/' -e "s/^'\(.*\)'$/\1/"
}

# Replace the first "KEY=..." or "# KEY=..." line of work.env with "KEY=value" (or append). Rewrites only that
# line, so every other setting and comment survives a second run of the guide.
set_env() {
  local key="$1" value="$2" tmp
  tmp="$(mktemp "$WORK/.env.XXXXXX")"
  awk -v k="$key" -v v="$value" '
    BEGIN { done = 0 }
    {
      if ($0 ~ ("^" k "=") || $0 ~ ("^# ?" k "=")) {
        if (!done) { print k "=" v; done = 1 }
        next
      }
      print
    }
    END { if (!done) print k "=" v }' "$WORK_ENV" >"$tmp"
  chmod 600 "$tmp"
  mv "$tmp" "$WORK_ENV"
}

# Turn an active "KEY=..." line into a comment (the setting is then off).
unset_env() {
  local key="$1" tmp
  tmp="$(mktemp "$WORK/.env.XXXXXX")"
  awk -v k="$key" '{ if ($0 ~ ("^" k "=")) print "# " $0; else print }' "$WORK_ENV" >"$tmp"
  chmod 600 "$tmp"
  mv "$tmp" "$WORK_ENV"
}

# Split SIDEKICK_WORK_MODEL_BASE_URL into scheme, host, port, path, is_ip (one per line); exit 2 with a reason.
parse_base_url() {
  python3 - "$1" "$L" <<'PY'
import ipaddress
import sys
from urllib.parse import urlsplit

TEXT = {
    "sv": {
        "parse": "adressen kan inte tolkas: {error}",
        "scheme": "adressen måste börja med http:// eller https:// och ha en värd",
        "credentials": "adressen får inte innehålla inloggning, query eller fragment",
        "path": "adressen måste ha en sökväg, till exempel /v1",
    },
    "en": {
        "parse": "the address cannot be parsed: {error}",
        "scheme": "the address must start with http:// or https:// and have a host",
        "credentials": "the address must not contain credentials, a query or a fragment",
        "path": "the address needs a path, for example /v1",
    },
}[sys.argv[2]]
raw = sys.argv[1].strip()
try:
    parts = urlsplit(raw)
    host = parts.hostname
    port = parts.port
except ValueError as error:
    sys.exit(TEXT["parse"].format(error=error))
if parts.scheme not in ("http", "https") or not host:
    sys.exit(TEXT["scheme"])
if parts.username or parts.password or parts.query or parts.fragment:
    sys.exit(TEXT["credentials"])
path = parts.path.rstrip("/")
if not path:
    sys.exit(TEXT["path"])
try:
    ipaddress.ip_address(host)
    is_ip = "1"
except ValueError:
    is_ip = "0"
print(parts.scheme, host, port or (443 if parts.scheme == "https" else 80), path, is_ip, sep="\n")
PY
}

# Validate the allowlist "host:port,host:port": host names only (they become names on the internal network, so
# the client keeps its own name and certificate check), ports distinct from each other and from the two the
# gateway already uses. Prints the normalized list, one "host port" per line; exit 2 with a reason.
parse_allowlist() {
  python3 - "$1" "$2" "$L" <<'PY'
import re
import sys

TEXT = {
    "sv": {
        "format": "'{entry}': skriv värdnamn:port, till exempel embed.foretag.lan:443",
        "ip": "'{entry}': IP-adresser går inte att tillåta, använd ett värdnamn",
        "used": "'{entry}': porten {port} används redan (modellservern, MCP eller en annan post)",
    },
    "en": {
        "format": "'{entry}': write host:port, for example embed.company.lan:443",
        "ip": "'{entry}': IP addresses cannot be allowed, use a host name",
        "used": "'{entry}': port {port} is already used (the model server, MCP or another entry)",
    },
}[sys.argv[3]]
entries = [e.strip().lower() for e in sys.argv[1].replace(" ", ",").split(",") if e.strip()]
used = {8765, int(sys.argv[2])}
seen = []
for entry in entries:
    match = re.fullmatch(r"([a-z0-9]([a-z0-9.-]*[a-z0-9])?):([0-9]{1,5})", entry)
    if not match or not 0 < int(match.group(3)) < 65536:
        sys.exit(TEXT["format"].format(entry=entry))
    if re.fullmatch(r"[0-9.]+", match.group(1)):
        sys.exit(TEXT["ip"].format(entry=entry))
    port = int(match.group(3))
    if port in used:
        sys.exit(TEXT["used"].format(entry=entry, port=port))
    used.add(port)
    seen.append((match.group(1), port))
for host, port in seen:
    print(host, port)
PY
}

# Derive everything compose needs from work.env and export it. Strict: refuses a placeholder or a bad address.
# With "lenient" (stop) an unusable work.env is not an error, because compose only needs the names to parse.
derive() {
  local lenient="${1:-}" base parsed scheme host port path is_ip resolve addr hosthdr tls allow
  base="$(envval SIDEKICK_WORK_MODEL_BASE_URL)"
  if [ -z "$base" ] || [[ "$base" == *"<"* ]]; then
    if [ "$lenient" = lenient ]; then export_placeholders; return 0; fi
    errf url_unset
    errf url_unset_hint
    exit 1
  fi
  if ! parsed="$(parse_base_url "$base" 2>&1)"; then
    if [ "$lenient" = lenient ]; then export_placeholders; return 0; fi
    echo "SIDEKICK_WORK_MODEL_BASE_URL: $parsed" >&2
    exit 1
  fi
  { read -r scheme; read -r host; read -r port; read -r path; read -r is_ip; } <<<"$parsed"
  if [ "$port" = 8765 ]; then
    errf port_clash
    exit 1
  fi
  allow="$(envval SIDEKICK_WORK_ALLOW)"
  if ! ALLOW_PARSED="$(parse_allowlist "$allow" "$port" 2>&1)"; then
    if [ "$lenient" = lenient ]; then
      ALLOW_PARSED=""
    else
      echo "SIDEKICK_WORK_ALLOW: $ALLOW_PARSED" >&2
      exit 1
    fi
  fi
  resolve="$(envval SIDEKICK_WORK_MODEL_RESOLVE_IP)"
  addr="${resolve:-$host}"
  if [[ "$addr" == *:* ]]; then addr="[$addr]"; fi
  hosthdr="$host"
  if [[ "$hosthdr" == *:* ]]; then hosthdr="[$hosthdr]"; fi
  if [ "$scheme" = http ] && [ "$port" != 80 ]; then hosthdr="$hosthdr:$port"; fi
  if [ "$scheme" = https ] && [ "$port" != 443 ]; then hosthdr="$hosthdr:$port"; fi
  tls=""
  if [ "$scheme" = https ]; then
    tls="ssl verify required ca-file /etc/ssl/work-ca.pem verifyhost $host"
    if [ "$is_ip" = 0 ]; then tls="$tls sni str($host)"; fi
  fi
  export SIDEKICK_WORK_MODEL_PORT="$port" SIDEKICK_WORK_MODEL_PATH="$path"
  export SIDEKICK_WORK_UPSTREAM_ADDR="$addr:$port" SIDEKICK_WORK_UPSTREAM_HOST_HEADER="$hosthdr"
  export SIDEKICK_WORK_UPSTREAM_TLS="$tls"
  # work.env is also compose's --env-file; these exports win over it, which is the point.
  export SIDEKICK_WORK_MEMORY_MODEL="${SIDEKICK_WORK_MEMORY_MODEL:-$(envval SIDEKICK_WORK_MEMORY_MODEL)}"
  if [ "$lenient" != lenient ] && { [ -z "$SIDEKICK_WORK_MEMORY_MODEL" ] || [[ "$SIDEKICK_WORK_MEMORY_MODEL" == *"<"* ]]; }; then
    errf mem_unset
    exit 1
  fi
  derive_ca_bundle
}

export_placeholders() {
  ALLOW_PARSED=""
  export SIDEKICK_WORK_MODEL_PORT=1 SIDEKICK_WORK_MODEL_PATH=/v1 SIDEKICK_WORK_UPSTREAM_ADDR=unset:1
  export SIDEKICK_WORK_UPSTREAM_HOST_HEADER=unset SIDEKICK_WORK_UPSTREAM_TLS="" SIDEKICK_WORK_MEMORY_MODEL=unset
  derive_ca_bundle
}

# The trust store the gateway uses for an https model server. Linux: the system bundle (a company CA installed on
# Ubuntu is in it). macOS has no such file: export the keychain certificates into a bundle in generated/.
derive_ca_bundle() {
  local configured
  configured="$(envval SIDEKICK_WORK_CA_BUNDLE)"
  if [ -n "$configured" ]; then
    export SIDEKICK_WORK_CA_BUNDLE="$configured"
  elif [ -f /etc/ssl/certs/ca-certificates.crt ]; then
    export SIDEKICK_WORK_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt
  else
    mkdir -p "$GEN"
    if [ "$(uname -s)" = Darwin ] && command -v security >/dev/null 2>&1; then
      security find-certificate -a -p /Library/Keychains/System.keychain \
        /System/Library/Keychains/SystemRootCertificates.keychain >"$GEN/ca-bundle.pem" 2>/dev/null || true
    else
      : >"$GEN/ca-bundle.pem"
    fi
    chmod 755 "$GEN"
    chmod 644 "$GEN/ca-bundle.pem"
    export SIDEKICK_WORK_CA_BUNDLE="$GEN/ca-bundle.pem"
  fi
}

# Files compose mounts that depend on settings: the gateway configuration with one passthrough listener per
# allowed address, the matching network aliases, and the build information file (created if missing).
render_generated() {
  # The shared selfhost entrypoint also copies this file with mode 755 before dropping privileges.
  chmod 755 "$SELFHOST/postgres-init.sh"
  # The gateway container runs as an unprivileged user, so what it mounts must be world-readable despite umask 077.
  mkdir -p "$GEN"
  chmod 755 "$GEN"
  python3 - "$WORK/gateway.haproxy.cfg" "$GEN" "$ALLOW_PARSED" <<'PY'
import os
import sys

template, out_dir, allow = sys.argv[1:4]
entries = [line.split() for line in allow.splitlines() if line.strip()]
blocks = []
for index, (host, port) in enumerate(entries, start=1):
    blocks.append(
        f"frontend allow_{index}\n    mode tcp\n    bind :{port}\n    default_backend allow_{index}_server\n\n"
        f"backend allow_{index}_server\n    mode tcp\n"
        f"    server upstream {host}:{port} resolvers docker init-addr libc,none\n"
    )
text = open(template, encoding="utf-8").read().replace("# @ALLOWLIST@\n", "\n".join(blocks))
with open(os.path.join(out_dir, "gateway.haproxy.cfg"), "w", encoding="utf-8") as handle:
    handle.write(text)
override = os.path.join(out_dir, "allow.compose.yaml")
if entries:
    aliases = ", ".join(host for host, _ in entries)
    with open(override, "w", encoding="utf-8") as handle:
        handle.write(
            "# Generated by tools/work.sh from SIDEKICK_WORK_ALLOW: the allowed names resolve to the gateway.\n"
            f"services:\n  gateway:\n    networks:\n      edge:\n        aliases: [{aliases}]\n"
        )
elif os.path.exists(override):
    os.remove(override)
PY
  chmod 644 "$GEN/gateway.haproxy.cfg"
  if [ -f "$GEN/allow.compose.yaml" ]; then chmod 644 "$GEN/allow.compose.yaml"; fi
  ensure_build_info
}

# The build information file must exist before compose mounts it (a missing file would become a directory), and
# from the first day on, so the update reminder has a date to count from.
ensure_build_info() {
  mkdir -p "$GEN"
  chmod 755 "$GEN"
  if [ ! -f "$GEN/build-info.json" ]; then write_build_info; fi
}

# build-info.json: which commit this checkout is on, when the image was built and when it was last updated.
# Mounted read-only into the api at /etc/sidekick/build-info.json (SIDEKICK_BUILD_INFO_FILE) for the interface to read.
write_build_info() {
  local commit date
  commit="$(git -C "$REPO" rev-parse HEAD 2>/dev/null || echo unknown)"
  date="$(git -C "$REPO" log -1 --format=%cI 2>/dev/null || echo unknown)"
  mkdir -p "$GEN"
  python3 - "$GEN/build-info.json" "$commit" "$date" "$(now_utc)" "${1:-}" "${2:-}" <<'PY'
import json
import os
import sys

path, commit, commit_date, now, previous, updated = sys.argv[1:7]
old = {}
if os.path.exists(path):
    try:
        old = json.load(open(path, encoding="utf-8"))
    except ValueError:
        old = {}
info = {
    "commit": commit,
    "commit_date": commit_date,
    "built_at": now,
    "updated_at": now if updated == "updated" else old.get("updated_at", now),
    "previous_commit": previous or old.get("previous_commit", ""),
}
with open(path, "w", encoding="utf-8") as handle:
    json.dump(info, handle, indent=2)
    handle.write("\n")
PY
  chmod 644 "$GEN/build-info.json"
}

ensure_work_env() {
  if [ ! -f "$WORK_ENV" ]; then
    cp "$WORK/work.env.example" "$WORK_ENV"
    chmod 600 "$WORK_ENV"
    say env_created
    return 1
  fi
}

secrets_exist() { [ -f "$SECRETS/sidekick.env" ] && [ -f "$SECRETS/db.env" ] && [ -f "$SECRETS/hindsight.env" ]; }

ensure_secrets() {
  secrets_exist && return 0
  errf no_secrets
  exit 1
}

# Replace or append KEY=value in a secrets file without printing anything.
set_line() {
  local file="$1" key="$2" value="$3" tmp
  tmp="$(mktemp "$SECRETS/.tmp.XXXXXX")"
  { grep -v "^$key=" "$file" || true; printf '%s=%s\n' "$key" "$value"; } >"$tmp"
  chmod 600 "$tmp"
  mv "$tmp" "$file"
}

# Remove KEY=... from a secrets file (no output, mode kept).
drop_line() {
  local file="$1" key="$2" tmp
  tmp="$(mktemp "$SECRETS/.tmp.XXXXXX")"
  { grep -v "^$key=" "$file" || true; } >"$tmp"
  chmod 600 "$tmp"
  mv "$tmp" "$file"
}

# Write the model server's API key into the two 600 files; an empty key means "the server checks nothing".
# The api container only gets it for the status probe, under a name without the SIDEKICK_ prefix (Settings refuses
# unknown SIDEKICK_ names).
apply_model_key() {
  local key="$1"
  if [ -n "$key" ]; then
    set_line "$SECRETS/sidekick.env" WORK_MODEL_API_KEY "$key"
    set_line "$SECRETS/hindsight.env" HINDSIGHT_API_LLM_API_KEY "$key"
  else
    drop_line "$SECRETS/sidekick.env" WORK_MODEL_API_KEY
    # Hindsight insists on a value even when the server does not check it (upstream's own local-LLM example).
    set_line "$SECRETS/hindsight.env" HINDSIGHT_API_LLM_API_KEY not-needed
  fi
}

# The key currently stored (empty when none).
# Only ever held in a variable, never printed.
stored_model_key() {
  [ -f "$SECRETS/sidekick.env" ] || return 0
  sed -n 's/^WORK_MODEL_API_KEY=//p' "$SECRETS/sidekick.env" | tail -n 1
}

# SIDEKICK_WORK_MODEL_API_KEY in the environment, else asked for on a terminal (no echo), else none.
store_model_key() {
  local key="${SIDEKICK_WORK_MODEL_API_KEY:-}"
  if [ -z "$key" ] && [ -t 0 ]; then
    read -rsp "$(msg model_key_ask)" key
    echo
  fi
  apply_model_key "$key"
  if [ -n "$key" ]; then
    sayf model_key_saved "$SECRETS"
  else
    say model_key_none
  fi
}

rand_hex() { openssl rand -hex 32; }
rand_b64() { openssl rand -base64 48 | tr -d '\n'; }

generate_secrets() {
  local app mig pg hs f legacy_env
  legacy_env="char""lie.env"
  # Never overwrite: a secrets file left by an older version (see legacy_env) or an interrupted init would otherwise lose
  # the database passwords of a database that already exists. -e, not -f: a symlink or odd file counts too.
  for f in sidekick.env db.env hindsight.env "$legacy_env"; do
    if [ -e "$SECRETS/$f" ] || [ -L "$SECRETS/$f" ]; then errf init_existing "$SECRETS"; exit 1; fi
  done
  app="$(rand_hex)"; mig="$(rand_hex)"; pg="$(rand_hex)"; hs="$(rand_b64)"
  {
    printf 'POSTGRES_PASSWORD=%s\n' "$pg"
    printf 'SIDEKICK_DB_APP_PASSWORD=%s\n' "$app"
    printf 'SIDEKICK_DB_MIGRATOR_PASSWORD=%s\n' "$mig"
    printf 'SIDEKICK_MIGRATION_DATABASE_URL=postgresql+psycopg://sidekick_migrator:%s@postgres:5432/sidekick\n' "$mig"
  } >"$SECRETS/db.env"
  {
    printf 'SIDEKICK_DATABASE_URL=postgresql+psycopg://sidekick_app:%s@postgres:5432/sidekick\n' "$app"
    printf 'SIDEKICK_CURSOR_SIGNING_SECRET=%s\n' "$(rand_b64)"
    printf 'SIDEKICK_TOKEN_PEPPER=%s\n' "$(rand_b64)"
    printf 'SIDEKICK_MEMORY_HINDSIGHT_API_TOKEN=%s\n' "$hs"
    printf 'SIDEKICK_MEMORY_ID_DERIVATION_KEY=%s\n' "$(rand_b64)"
  } >"$SECRETS/sidekick.env"
  # Hindsight's own settings (retain mission, chunk sizes, local embeddings) are reused from the self-hosted
  # example, so there is one copy of them. Compose overrides provider, URL, model and language per work.env.
  sed -e "s|^HINDSIGHT_API_LLM_PROVIDER=.*|HINDSIGHT_API_LLM_PROVIDER=openai|" \
      -e "s|^HINDSIGHT_API_LLM_BASE_URL=.*|HINDSIGHT_API_LLM_BASE_URL=http://$GATEWAY_NAME/v1|" \
      -e "s|^HINDSIGHT_API_LLM_MODEL=.*|HINDSIGHT_API_LLM_MODEL=set-in-work-env|" \
      -e "s|^HINDSIGHT_API_LLM_API_KEY=.*|HINDSIGHT_API_LLM_API_KEY=not-needed|" \
      -e "s|^HINDSIGHT_API_TENANT_API_KEY=.*|HINDSIGHT_API_TENANT_API_KEY=$hs|" \
      "$SELFHOST/hindsight.env.example" >"$SECRETS/hindsight.env"
  chmod 600 "$SECRETS"/*.env
}

# SIDEKICK_ENABLED_ROOMS goes into the api container environment only when set in work.env, so a release without
# that setting still starts. The stdio process Claude Desktop starts runs inside the api container (docker exec)
# and so sees the same value.
write_rooms_env() {
  local rooms
  rooms="$(envval SIDEKICK_ENABLED_ROOMS)"
  if [ -n "$rooms" ]; then
    printf 'SIDEKICK_ENABLED_ROOMS=%s\n' "$rooms" >"$SECRETS/rooms.env"
    chmod 600 "$SECRETS/rooms.env"
  else
    rm -f "$SECRETS/rooms.env"
  fi
}

container_id() { compose ps -q "$1" 2>/dev/null || true; }

# ask VARNAME KEY [default]: prompt text from the table; the answer (or the default) ends up in $VARNAME.
ask() {
  local __var="$1" __key="$2" __def="${3:-}" __ans=""
  if [ -z "$__def" ]; then __def="${4:-}"; fi
  if [ -n "$__def" ]; then printf '%s [%s]: ' "$(msg "$__key")" "$__def" >&2; else printf '%s: ' "$(msg "$__key")" >&2; fi
  IFS= read -r __ans || __ans=""
  printf -v "$__var" '%s' "${__ans:-$__def}"
}

# yes/no with a default (y or n); j/y/ja/yes are yes.
confirm() {
  local key="$1" default="$2" ans=""
  printf '%s: ' "$(msg "$key")" >&2
  IFS= read -r ans || ans=""
  ans="${ans:-$default}"
  case "$ans" in j|J|y|Y|ja|JA|yes|YES|Yes) return 0 ;; *) return 1 ;; esac
}

# GET <base>/models with the key passed on stdin (never on a command line). Prints the model ids, one per line.
list_models() {
  local base="$1" key="$2" body
  if [ -n "$key" ]; then
    body="$(printf 'header = "Authorization: Bearer %s"\n' "$key" | curl -s -f -m 15 -K - "$base/models" 2>/dev/null)" || return 1
  else
    body="$(curl -s -f -m 15 "$base/models" 2>/dev/null)" || return 1
  fi
  printf '%s' "$body" | python3 -c '
import json, sys
try:
    data = json.load(sys.stdin).get("data", [])
    ids = [m["id"] for m in data if isinstance(m, dict) and "id" in m]
except Exception:
    sys.exit(1)
print("\n".join(ids))
' || return 1
}

# Pick from a numbered list or take a typed id. $1 variable, $2 prompt key, $3 default id, rest: the ids.
pick_model() {
  local var="$1" key="$2" def="$3" ans; shift 3
  ask ans "$key" "$def"
  case "$ans" in
    ''|*[!0-9]*) ;;
    *) if [ "$ans" -ge 1 ] && [ "$ans" -le "$#" ]; then ans="$(eval "printf '%s' \"\${$ans}\"")"; fi ;;
  esac
  printf -v "$var" '%s' "$ans"
}

# ---------------------------------------------------------------------------------------------------------

cmd_init() {
  need_docker; need_tool openssl; need_tool python3
  mkdir -p "$SECRETS"
  chmod 700 "$SECRETS"
  ensure_work_env || true
  if ! secrets_exist; then
    generate_secrets
    sayf init_created "$SECRETS"
    store_model_key
  elif [ "${1:-}" = "--model-key" ]; then
    store_model_key
  else
    sayf init_kept "$SECRETS"
    say init_key_hint
  fi
  ensure_build_info
  say init_next
}

# The stdio entry point is part of the image only from the release that added it: an image built earlier must be rebuilt.
check_stdio_entry() {
  compose exec -T api python -c "import sidekick.mcp.stdio" >>"$LOG" 2>&1 || { errf old_image; exit 1; }
}

is_uuid() { printf '%s' "$1" | grep -Eqi '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'; }

# One value from the database, whitespace removed. Fails (never "empty") when the database cannot be asked.
db_scalar() {
  local out
  out="$(pg_admin -d sidekick -tAc "$1" 2>>"$LOG")" || return 1
  printf '%s' "$out" | tr -d '[:space:]'
}

# The user Claude Desktop acts as. The database is the truth, secrets/user-id only remembers its UUID: the file counts
# only while that user exists in the database. A user-id left from another database (a new, empty data volume) is
# replaced by the user jobb of this database if it has one, else by a new one. Needs the running api (the database is
# migrated by then). create-user asks for no password and prints the UUID.
ensure_owner() {
  local tmp stored="" found id
  if [ -s "$SECRETS/user-id" ]; then stored="$(tr -d '[:space:]' <"$SECRETS/user-id")"; fi
  if is_uuid "$stored"; then
    found="$(db_scalar "select 1 from sidekick.users where id = '$stored'")" || { errf user_fail "$LOG"; exit 1; }
    if [ "$found" = 1 ]; then return 0; fi
    say owner_stale
  fi
  id="$(db_scalar "select id from sidekick.users where username = 'jobb'")" || { errf user_fail "$LOG"; exit 1; }
  tmp="$(mktemp "$SECRETS/.tmp.XXXXXX")"
  if is_uuid "$id"; then
    printf '%s\n' "$id" >"$tmp"
  elif ! compose exec -T api sidekick-admin create-user --login jobb --display-name "Sidekick Work" \
      </dev/null >"$tmp" 2>>"$LOG" \
      || ! is_uuid "$(tr -d '[:space:]' <"$tmp")"; then
    rm -f "$tmp"
    errf user_fail "$LOG"
    exit 1
  fi
  chmod 600 "$tmp"
  mv "$tmp" "$SECRETS/user-id"
}

# Claude Desktop starts local programs only, with a minimal PATH. The entry runs Sidekick's stdio server inside the
# running api container: `docker exec -i` (not `docker compose exec`, which would need the compose files and every
# derived variable), the docker binary and the container by absolute path/name. The owner is passed with -e; the
# rest of the settings (rooms, database, model routes) are the container's own. No token: the process is trusted
# because the OS user that can run docker already holds the database credentials. The file holds no secret
# but is written 600 like the others.
write_desktop_config() {
  local docker_bin cid name owner out
  docker_bin="$(command -v docker)"
  case "$docker_bin" in /*) ;; *) errf desktop_nodocker; exit 1 ;; esac
  cid="$(container_id api)"
  name="$(docker inspect --format '{{.Name}}' "$cid")"
  name="${name#/}"
  owner="$(tr -d '[:space:]' <"$SECRETS/user-id")"
  out="$SECRETS/claude_desktop_config.json"
  python3 - "$out" "$docker_bin" "$name" "$owner" <<'PY'
import json
import os
import sys

out_file, docker_bin, container, owner = sys.argv[1:5]
config = {
    "mcpServers": {
        "sidekick-work": {
            "command": docker_bin,
            "args": [
                "exec", "-i", "-e", f"SIDEKICK_MCP_STDIO_OWNER_ID={owner}",
                container, "python", "-m", "sidekick.mcp.stdio",
            ],
        }
    }
}
fd = os.open(out_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
with os.fdopen(fd, "w", encoding="utf-8") as handle:
    json.dump(config, handle, indent=2)
    handle.write("\n")
os.chmod(out_file, 0o600)
PY
  sayf desktop_written "$out"
  say desktop_hint
}

desktop_setup() {
  check_stdio_entry
  ensure_owner
  write_desktop_config
}

# This is deliberately separate from setup/start: Claude's settings are changed only after an explicit answer.
# fd 3 preserves the caller's stdin while Python reads its program from the heredoc.
cmd_claude_config() {
  [ "$#" = 0 ] || { errf usage; exit 2; }
  need_tool python3
  local target="${SIDEKICK_WORK_CLAUDE_CONFIG:-}"
  if [ -n "$target" ]; then
    :  # Explicit path, also used by tests so that the real Claude configuration is never touched.
  elif [ "$(uname -s)" = Darwin ]; then
    target="$HOME/Library/Application Support/Claude/claude_desktop_config.json"
  else
    target="$HOME/.config/Claude/claude_desktop_config.json"
  fi
  python3 - "$SECRETS/claude_desktop_config.json" "$target" "$L" 3<&0 <<'PY'
import datetime
import json
import os
from pathlib import Path
import sys
import tempfile

source, target = (Path(p) for p in sys.argv[1:3])
texts = {
    "sv": {
        "missing": "Sidekick-posten saknas. Kör först: bash tools/work.sh start",
        "invalid": "Inställningsfilen kunde inte läsas som ett JSON-objekt med mcpServers. Inget ändrat.",
        "preview": "Ändring i {path}: {action} mcpServers.sidekick-work med följande post (andra poster behålls):",
        "add": "lägg till", "replace": "ersätt",
        "ask": "Spara ändringen? (j/N): ",
        "abort": "Avbrutet, inget ändrat.",
        "same": "Sidekick-posten är redan aktuell. Inget ändrat.",
        "changed": "Inställningsfilen ändrades efter förhandsvisningen. Kör kommandot igen. Inget ändrat.",
        "backup": "Säkerhetskopia: {path}",
        "saved": "Sparat: {path}. Starta om Claude Desktop helt.",
        "failed": "Kunde inte spara inställningen. Originalet behålls; eventuell säkerhetskopia ligger bredvid filen.",
    },
    "en": {
        "missing": "The Sidekick entry is missing. First run: bash tools/work.sh start",
        "invalid": "Could not read the configuration as a JSON object with mcpServers. Nothing changed.",
        "preview": "Change in {path}: {action} mcpServers.sidekick-work with the following entry (other entries are kept):",
        "add": "add", "replace": "replace",
        "ask": "Save the change? (y/N): ",
        "abort": "Aborted, nothing changed.",
        "same": "The Sidekick entry is already current. Nothing changed.",
        "changed": "The configuration changed after the preview. Run the command again. Nothing changed.",
        "backup": "Backup: {path}",
        "saved": "Saved: {path}. Restart Claude Desktop completely.",
        "failed": "Could not save the configuration. The original is kept; any backup is next to the file.",
    },
}[sys.argv[3]]
if not source.is_file():
    sys.exit(texts["missing"])
try:
    entry = json.loads(source.read_bytes())["mcpServers"]["sidekick-work"]
    if target.is_symlink():
        raise ValueError("symlink")
    original = target.read_bytes() if target.exists() else None
    config = json.loads(original) if original is not None else {}
    if not isinstance(config, dict) or not isinstance(config.get("mcpServers", {}), dict) or not isinstance(entry, dict):
        raise ValueError("object expected")
except (OSError, ValueError, KeyError, TypeError):
    sys.exit(texts["invalid"])
servers = config.setdefault("mcpServers", {})
if servers.get("sidekick-work") == entry:
    print(texts["same"])
    sys.exit(0)
action = texts["replace"] if "sidekick-work" in servers else texts["add"]
print(texts["preview"].format(path=target, action=action))
# Show only the proposed Sidekick entry, never other connectors' credentials or the previous entry's env.
print(json.dumps({"mcpServers": {"sidekick-work": entry}}, ensure_ascii=False, indent=2))
print(texts["ask"], end="", file=sys.stderr, flush=True)
with os.fdopen(os.dup(3), encoding="utf-8") as answers:
    answer = answers.readline().strip().lower()
if answer not in ("j", "ja", "y", "yes"):
    print(texts["abort"])
    sys.exit(0)
temporary = None
try:
    current = target.read_bytes() if target.exists() else None
    if target.is_symlink() or current != original:
        sys.exit(texts["changed"])
    target.parent.mkdir(parents=True, exist_ok=True)
    if original is not None:
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        backup = target.with_name(target.name + ".bak." + stamp)
        with backup.open("xb") as handle:
            handle.write(original)
        print(texts["backup"].format(path=backup))
    servers["sidekick-work"] = entry
    fd, temporary = tempfile.mkstemp(prefix=".claude-config-", dir=target.parent)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(config, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, target)
except (OSError, ValueError):
    sys.exit(texts["failed"])
finally:
    if temporary is not None and os.path.exists(temporary):
        os.unlink(temporary)
print(texts["saved"].format(path=target))
PY
}

# Read-only diagnosis after a failed start. Logs are inspected in memory, never echoed (they may contain URLs).
# An absent/empty yoyo table must be confirmed over the local superuser socket; an unknown state is never empty.
diagnose_first_start() {
  local start_line="$1" migration_log postgres_log evidence table count volume command stop_command
  migration_log="$(compose logs --no-color --tail 80 migrate 2>/dev/null || true)"
  postgres_log="$(compose logs --no-color --tail 120 postgres 2>/dev/null || true)"
  # Here-strings, not pipes into grep -q: under pipefail grep exits at the first match, the writer can then die of
  # SIGPIPE, and the whole test reads as "no evidence" at random.
  evidence="$(printf '%s\n' "$migration_log"; sed -n "$((start_line + 1)),\$p" "$LOG")" || true
  if ! grep -Eiq '(password authentication failed|authentication failed|role .* does not exist).*sidekick_migrator|sidekick_migrator.*(password authentication failed|authentication failed|does not exist)' <<<"$evidence" \
      && ! grep -Eiq 'initdb\.d.*[Pp]ermission denied' <<<"$postgres_log"; then
    return 0
  fi
  table="$(db_scalar "select coalesce(to_regclass('public._yoyo_migration')::text, 'absent')")" || return 0
  case "$table" in
    absent) ;;
    _yoyo_migration|public._yoyo_migration)
      count="$(db_scalar 'select count(*) from public._yoyo_migration')" || return 0
      [ "$count" = 0 ] || return 0
      ;;
    *) return 0 ;;
  esac
  volume="$(docker volume ls -q --filter "label=com.docker.compose.project=$PROJECT" \
    --filter 'label=com.docker.compose.volume=pgdata' 2>/dev/null)" || return 0
  # Exactly one Docker volume name; never interpolate unchecked output into a suggested shell command.
  [[ "$volume" =~ ^[a-zA-Z0-9][a-zA-Z0-9_.-]*$ ]] || return 0
  printf -v command 'docker volume rm %q' "$volume"
  printf -v stop_command 'SIDEKICK_WORK_PROJECT=%q bash tools/work.sh stop' "$PROJECT"
  errf first_start_volume "$volume" "$stop_command" "$command"
}

cmd_start() {
  warn_strict_umask
  local build=0 wait_docker=0 no_cache=0 image arg i log_start
  local build_args=()
  for arg in "$@"; do
    case "$arg" in
      --build) build=1 ;;
      --no-cache) no_cache=1 ;;
      --wait-docker) wait_docker=1 ;;
      *) errf usage; exit 2 ;;
    esac
  done
  if [ "$no_cache" = 1 ]; then
    [ "$build" = 1 ] || { errf usage; exit 2; }
    build_args+=(--no-cache)
  fi
  need_docker
  ensure_work_env || exit 1
  ensure_secrets
  derive
  write_rooms_env
  if [ "$wait_docker" = 1 ]; then
    # Used by autostart: Docker may still be starting at login. Bounded wait, then give up.
    i=0
    until docker info >/dev/null 2>&1; do
      i=$((i + 1))
      if [ "$i" -gt 60 ]; then errf docker_wait; exit 1; fi
      sleep 5
    done
  fi
  render_generated
  echo "=== $(now) start ===" >>"$LOG"
  image="${SIDEKICK_WORK_API_IMAGE:-$(envval SIDEKICK_WORK_API_IMAGE)}"
  image="${image:-roadlake-sidekick:work}"
  if [ "$build" = 1 ] || ! docker image inspect "$image" >/dev/null 2>&1; then
    sayf building "$image"
    if ! compose build ${build_args[@]+"${build_args[@]}"} api >>"$LOG" 2>&1; then
      errf build_fail "$LOG"
      tail -n 20 "$LOG" >&2 || true
      exit 1
    fi
    write_build_info
  fi
  log_start="$(wc -l <"$LOG")"
  if ! compose up -d --wait --wait-timeout 420 >>"$LOG" 2>&1; then
    errf up_fail "$LOG"
    tail -n 20 "$LOG" >&2 || true
    diagnose_first_start "$log_start"
    exit 1
  fi
  # The gateway configuration is a mounted file that compose does not watch: restart the gateway when it changed.
  if ! cmp -s "$GEN/gateway.haproxy.cfg" "$GEN/.gateway.applied" 2>/dev/null; then
    compose restart gateway >>"$LOG" 2>&1 || { errf gw_fail "$LOG"; exit 1; }
    cp "$GEN/gateway.haproxy.cfg" "$GEN/.gateway.applied"
  fi
  say started
  desktop_setup
}

cmd_stop() {
  need_docker
  [ -f "$WORK_ENV" ] || cp "$WORK/work.env.example" "$WORK_ENV"
  derive lenient
  echo "=== $(now) stop ===" >>"$LOG"
  if [ "${1:-}" = "--purge" ]; then
    local answer
    read -rp "$(msg purge_q)" answer
    [ "$answer" = "$(msg purge_yes)" ] || { say aborted; exit 1; }
    compose down -v >>"$LOG" 2>&1 || { errf down_fail "$LOG"; exit 1; }
    rm -rf "$SECRETS" "$BACKUPS" "$GEN"
    autostart_remove
    say purged
  else
    compose down >>"$LOG" 2>&1 || { errf down_fail "$LOG"; exit 1; }
    say stopped
  fi
}

cmd_status() {
  need_docker
  [ -f "$WORK_ENV" ] || { errf no_work_env; exit 1; }
  derive
  local svc id state port api_id probe via direct_host out listed want hs_id line reached blocked commit="" cdate="" built="" updated=""
  for svc in postgres hindsight memory-worker automation-worker api gateway; do
    id="$(container_id "$svc")"
    if [ -z "$id" ]; then
      sayf st_not_running "$svc"
      continue
    fi
    state="$(docker inspect --format '{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{else}}-{{end}}' "$id" 2>/dev/null || msg st_unknown)"
    echo "$svc: $state"
  done
  if [ -f "$GEN/build-info.json" ]; then
    { read -r commit; read -r cdate; read -r built; read -r updated; } < <(python3 -c '
import json, sys
i = json.load(open(sys.argv[1], encoding="utf-8"))
print(i["commit"][:10]); print(i["commit_date"][:10]); print(i["built_at"]); print(i["updated_at"])
' "$GEN/build-info.json" 2>/dev/null) || true
    if [ -n "${commit:-}" ]; then sayf st_version "$commit" "$cdate" "$built" "$updated"; fi
  fi
  port="$(envval SIDEKICK_WORK_PORT)"; port="${port:-8765}"
  sayf st_noauth "$(curl -s -o /dev/null -m 10 -w '%{http_code}' -X POST -H 'Content-Type: application/json' -d '{}' "http://127.0.0.1:$port/mcp/" || true)"
  if [ -s "$SECRETS/claude_desktop_config.json" ]; then sayf st_desktop_ok "$SECRETS/claude_desktop_config.json"; else say st_desktop_missing; fi
  api_id="$(container_id api)"
  [ -n "$api_id" ] || { say st_api_down; exit 0; }
  # Egress proof, from inside the containers. Each probe must be refused: the public internet by name and by
  # address, a lookup of a name that certainly exists (an answer means DNS is a way out), and the model server directly (only
  # the gateway may talk to it).
  probe='
import socket, sys
def reach(host, port):
    try:
        socket.create_connection((host, int(port)), timeout=4).close()
        return sys.argv[3]
    except OSError:
        return sys.argv[4]
print("example.com:443", reach("example.com", 443))
print("1.1.1.1:443", reach("1.1.1.1", 443))
try:
    socket.getaddrinfo("example.com", 443)
    print("DNS lookup of example.com", sys.argv[3])
except OSError as error:
    print("DNS lookup of example.com", sys.argv[4], "(" + str(error.errno) + ")")
print(sys.argv[5], reach(sys.argv[1], sys.argv[2]))
'
  reached="$(msg st_reached)"; blocked="$(msg st_blocked)"
  direct_host="${SIDEKICK_WORK_UPSTREAM_ADDR%:*}"
  say st_probe_api
  compose exec -T api python -c "$probe" "$direct_host" "$SIDEKICK_WORK_MODEL_PORT" "$reached" "$blocked" "$(msg st_direct)" | sed 's/^/  /' || echo "  $(msg st_probe_fail)"
  hs_id="$(container_id hindsight)"
  if [ -n "$hs_id" ]; then
    say st_probe_hs
    compose exec -T hindsight /app/api/.venv/bin/python -c "$probe" "$direct_host" "$SIDEKICK_WORK_MODEL_PORT" "$reached" "$blocked" "$(msg st_direct)" | sed 's/^/  /' || echo "  $(msg st_probe_fail)"
  fi
  # Through the gateway: the model list (needs the key from the container's own environment, never printed),
  # and a path outside the base path, which the gateway must refuse. The script prints neutral lines
  # ("models ...", "models_error ...", "outside ...", "outside_reached", "outside_error ...") translated below.
  via='
import json, os, sys, urllib.error, urllib.request
base = sys.argv[1]
key = os.environ.get("WORK_MODEL_API_KEY", "")
headers = {"Authorization": "Bearer " + key} if key else {}
try:
    with urllib.request.urlopen(urllib.request.Request(base + "/models", headers=headers), timeout=10) as r:
        print("models", ",".join(m["id"] for m in json.load(r).get("data", [])))
except Exception as error:
    print("models_error", type(error).__name__, getattr(error, "code", ""))
try:
    root = base.rsplit("/", 1)[0] + "/not-the-base-path"
    urllib.request.urlopen(root, timeout=10)
    print("outside_reached")
except urllib.error.HTTPError as error:
    print("outside", error.code)
except Exception as error:
    print("outside_error", type(error).__name__)
'
  say st_via
  out="$(compose exec -T api python -c "$via" "http://$GATEWAY_NAME:$SIDEKICK_WORK_MODEL_PORT$SIDEKICK_WORK_MODEL_PATH" || true)"
  listed=""
  while IFS= read -r line; do
    case "$line" in
      "models "*) listed="${line#models }"; printf '  '; sayf st_models "$listed" ;;
      "models_error "*) printf '  '; sayf st_models_err "${line#models_error }" ;;
      "outside_reached") printf '  '; say st_outside_reached ;;
      "outside_error "*) printf '  '; sayf st_outside_err "${line#outside_error }" ;;
      "outside "*) printf '  '; sayf st_outside "${line#outside }" ;;
    esac
  done <<<"$out"
  want="$(envval SIDEKICK_WORK_MEMORY_MODEL)"
  if [ -n "$want" ]; then
    case ",$listed," in
      *",$want,"*) printf '  '; sayf st_model_ok "$want" ;;
      *) printf '  '; sayf st_model_missing "$want" ;;
    esac
  fi
}

# ---------------------------------------------------------------------------------------------------------
# Autostart. Linux: a systemd user unit that brings the stack up at login (containers also come back on their own
# when the Docker service starts, unless they were stopped with `stop`). macOS: a launchd LaunchAgent that waits
# for Docker Desktop. SIDEKICK_WORK_AUTOSTART_DIR redirects the unit file (tests) and skips systemctl/launchctl.
AUTOSTART_LABEL=local.sidekick.work

autostart_file() {
  if [ -n "${SIDEKICK_WORK_AUTOSTART_DIR:-}" ]; then
    if [ "$(uname -s)" = Darwin ]; then echo "$SIDEKICK_WORK_AUTOSTART_DIR/$AUTOSTART_LABEL.plist"; else echo "$SIDEKICK_WORK_AUTOSTART_DIR/sidekick-work.service"; fi
  elif [ "$(uname -s)" = Darwin ]; then
    echo "$HOME/Library/LaunchAgents/$AUTOSTART_LABEL.plist"
  else
    echo "${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/sidekick-work.service"
  fi
}

autostart_on() {
  local file; file="$(autostart_file)"
  mkdir -p "$(dirname "$file")"
  if [ "$(uname -s)" = Darwin ]; then
    cat >"$file" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$AUTOSTART_LABEL</string>
  <key>ProgramArguments</key>
  <array><string>/bin/bash</string><string>$REPO/tools/work.sh</string><string>start</string><string>--wait-docker</string></array>
  <key>RunAtLoad</key><true/>
  <key>StandardOutPath</key><string>$WORK/autostart.log</string>
  <key>StandardErrorPath</key><string>$WORK/autostart.log</string>
</dict>
</plist>
EOF
    if [ -z "${SIDEKICK_WORK_AUTOSTART_DIR:-}" ]; then
      launchctl bootout "gui/$(id -u)/$AUTOSTART_LABEL" >/dev/null 2>&1 || true
      launchctl bootstrap "gui/$(id -u)" "$file"
    fi
    sayf as_launchd "$file"
  else
    cat >"$file" <<EOF
[Unit]
Description=Sidekick Work (local Sidekick for the work laptop)
After=docker.service network-online.target
Wants=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/bin/bash $REPO/tools/work.sh start --wait-docker

[Install]
WantedBy=default.target
EOF
    if [ -z "${SIDEKICK_WORK_AUTOSTART_DIR:-}" ]; then
      systemctl --user daemon-reload
      systemctl --user enable sidekick-work.service >/dev/null
    fi
    sayf as_systemd "$file" "$USER"
  fi
}

autostart_remove() {
  local file; file="$(autostart_file)"
  if [ -z "${SIDEKICK_WORK_AUTOSTART_DIR:-}" ]; then
    if [ "$(uname -s)" = Darwin ]; then
      launchctl bootout "gui/$(id -u)/$AUTOSTART_LABEL" >/dev/null 2>&1 || true
    else
      systemctl --user disable sidekick-work.service >/dev/null 2>&1 || true
    fi
  fi
  rm -f "$file"
  if [ -z "${SIDEKICK_WORK_AUTOSTART_DIR:-}" ] && [ "$(uname -s)" != Darwin ]; then
    systemctl --user daemon-reload >/dev/null 2>&1 || true
  fi
  return 0
}

cmd_autostart() {
  case "${1:-}" in
    on) autostart_on ;;
    off) autostart_remove; say as_off ;;
    status) if [ -f "$(autostart_file)" ]; then sayf as_state_on "$(autostart_file)"; else say as_state_off; fi ;;
    *) errf as_usage; exit 2 ;;
  esac
}

# ---------------------------------------------------------------------------------------------------------
# Backup: the database (pg_dump) and Hindsight's memory. Hindsight keeps its data in an embedded Postgres in the
# volume hindsight_pg0 (deploy/selfhost/compose.yaml); a copy of live database files is not consistent, so
# Hindsight is stopped for the few seconds the volume is archived (tar, run from the pinned Hindsight image
# itself, offline) and started again. Both files get the same timestamp. If either fails, nothing is kept and
# the caller stops.

# Encryption of the backups: the mechanism of the encrypted database snapshots in deploy/selfhost/update.sh (Fernet,
# run in a one-off api container from the image that is already here; the code is deploy/selfhost/snapshot_crypto.py).
# The key is a file of its own, generated on the first backup, mode 600, and kept OUT of the backup directory
# (default deploy/work/secrets/backup.key; SIDEKICK_WORK_BACKUP_KEY_FILE moves it, for example to a mounted key store).
# It is a different key from SIDEKICK_BACKUP_ENCRYPTION_KEY of a self-hosted installation. Its content is read into a
# variable for one command and reaches the container through the environment (docker compose run -e NAME takes the
# value from this process), never through a command line, the log or the terminal. No plain dump or archive is
# written to disk: pg_dump and tar are piped straight into the encryption.
BACKUP_KEY_FILE="${SIDEKICK_WORK_BACKUP_KEY_FILE:-$SECRETS/backup.key}"
CRYPTO_SCRIPT="$SELFHOST/snapshot_crypto.py"

# stdin to stdout through the api image: $1 = encrypt|decrypt. Non-zero on any failure (no key, wrong key, damaged data).
backup_crypto() {
  local key
  key="$(tr -d '[:space:]' <"$BACKUP_KEY_FILE" 2>/dev/null)" || return 1
  [ -n "$key" ] || return 1
  SIDEKICK_BACKUP_ENCRYPTION_KEY="$key" compose run --rm -T --no-deps -e SIDEKICK_BACKUP_ENCRYPTION_KEY api \
    python -I -c "$(cat "$CRYPTO_SCRIPT")" "$1" 2>>"$LOG"
}

backup_files_exist() { ls "$BACKUPS"/*.enc >/dev/null 2>&1; }

# Makes a file, or a directory entry, durable: `sync PATH` (coreutils) flushes that one file or directory to disk,
# older or other implementations ignore the argument and flush everything. Used on a finished backup file before it is
# renamed into place and on the directory after the rename (and after pruning), so a power loss cannot leave a name
# that points at data that was never written, and cannot bring a pruned old backup back or lose the new name.
fsync_path() { sync "$1" 2>/dev/null || sync; }

# Fails closed (exit 1, nothing changed) unless a usable key file exists. A missing key is never replaced silently while
# encrypted backups exist: a new key would make them unreadable. $1 = generate: create the key when there is no backup.
require_backup_key() {
  local key tmp dir
  case "$BACKUP_KEY_FILE" in "$BACKUPS"/*) errf bk_key_inside "$BACKUP_KEY_FILE" "$BACKUPS"; exit 1 ;; esac
  if [ ! -e "$BACKUP_KEY_FILE" ]; then
    if [ "${1:-}" != generate ] || backup_files_exist; then errf bk_key_missing "$BACKUP_KEY_FILE" "$BACKUPS"; exit 1; fi
    dir="$(dirname "$BACKUP_KEY_FILE")"
    mkdir -p "$dir"
    tmp="$(mktemp "$dir/.tmp.XXXXXX")"
    # A Fernet key is 32 random bytes as URL-safe base64.
    openssl rand -base64 32 | tr '+/' '-_' | tr -d '\n' >"$tmp"
    printf '\n' >>"$tmp"
    chmod 600 "$tmp"
    fsync_path "$tmp"
    mv "$tmp" "$BACKUP_KEY_FILE"
    fsync_path "$dir"
    sayf bk_key_new "$BACKUP_KEY_FILE"
  fi
  key="$(tr -d '[:space:]' <"$BACKUP_KEY_FILE" 2>/dev/null || true)"
  [[ "$key" =~ ^[A-Za-z0-9_-]{43}=$ ]] || { errf bk_key_bad "$BACKUP_KEY_FILE"; exit 1; }
  chmod 600 "$BACKUP_KEY_FILE" 2>/dev/null || true
}

# The proof that a backup is usable: decrypt it again (Fernet authenticates the whole file, so a damaged or wrongly
# keyed file fails) and look at what is inside. Nothing is written to disk. pipefail makes a failing decryption fail the check.
verify_dump() { backup_crypto decrypt <"$1" | grep 'PostgreSQL database dump complete' >/dev/null; }
verify_archive() { backup_crypto decrypt <"$1" | tar -tz 2>>"$LOG" | grep . >/dev/null; }

# The volume compose created for hindsight_pg0 in this project, or nothing.
# ---------------------------------------------------------------------------------------------------------
# One lock for the commands that change the stack (setup, init, start, stop, backup, update, restore --apply), so that
# none of them can start Hindsight or the writers in the middle of another. status, autostart and the dry run of
# restore take no lock. flock on $LOCK_FILE where it exists (released by the kernel on any exit); otherwise (macOS
# has no flock by default) a mkdir lock in $LOCK_DIR holding "PID command", taken over only when that PID is gone.
LOCK_FILE="$WORK/.work.lock"
LOCK_DIR="$WORK/.work.lock.d"
LOCK_HELD=""     # flock or dir while this process holds the lock
LOCK_COMMAND=""  # the command that takes it, written next to the PID

lock_busy() { errf busy "${1:-?}" "$2"; exit 1; }

take_lock() { # $1 = the command; exits 1 with a message when another changing command holds the lock
  local holder pid stale_id moved
  if [ -z "${SIDEKICK_WORK_NO_FLOCK:-}" ] && command -v flock >/dev/null 2>&1; then
    exec 9>>"$LOCK_FILE"
    flock -n 9 || lock_busy "$(head -n 1 "$LOCK_FILE" 2>/dev/null || true)" "$LOCK_FILE"
    printf 'PID %s: %s\n' "$$" "$1" >"$LOCK_FILE"
    LOCK_HELD=flock
    return 0
  fi
  if ! mkdir "$LOCK_DIR" 2>/dev/null; then
    stale_id="$(ls -di "$LOCK_DIR" 2>/dev/null | cut -d' ' -f1)"  # read before the owner line, see the takeover below
    holder="$(head -n 1 "$LOCK_DIR/owner" 2>/dev/null || true)"
    # The holder writes its line right after mkdir; give a holder that has just started a moment to do so.
    if [ -z "$holder" ]; then sleep 1; holder="$(head -n 1 "$LOCK_DIR/owner" 2>/dev/null || true)"; fi
    pid="${holder#PID }"; pid="${pid%%:*}"
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then lock_busy "$holder" "$LOCK_DIR"; fi
    # The holder is gone (stale lock). Take it over so that a lock somebody else has just taken is never deleted:
    # rename is atomic and succeeds for one taker only; the renamed directory must still be the stale one we read
    # (same owner line and inode), otherwise it is another process's live lock and goes straight back.
    moved="$LOCK_DIR.stale.$$"
    rm -rf "$moved"
    mv "$LOCK_DIR" "$moved" 2>/dev/null || lock_busy "" "$LOCK_DIR"
    if [ "$(head -n 1 "$moved/owner" 2>/dev/null || true)" = "$holder" ] \
      && [ "$(ls -di "$moved" 2>/dev/null | cut -d' ' -f1)" = "$stale_id" ]; then
      rm -rf "$moved"
    else
      [ -e "$LOCK_DIR" ] || mv "$moved" "$LOCK_DIR" 2>/dev/null || true
      lock_busy "$(head -n 1 "$LOCK_DIR/owner" 2>/dev/null || true)" "$LOCK_DIR"
    fi
    mkdir "$LOCK_DIR" 2>/dev/null || lock_busy "" "$LOCK_DIR"
  fi
  printf 'PID %s: %s\n' "$$" "$1" >"$LOCK_DIR/owner"
  LOCK_HELD=dir
}

release_lock() { # the mkdir lock only, and only while it is still ours; flock is released when the process ends
  if [ "$LOCK_HELD" = dir ] && [ "$(head -n 1 "$LOCK_DIR/owner" 2>/dev/null || true)" = "PID $$: ${LOCK_COMMAND:-}" ]; then
    rm -rf "$LOCK_DIR"
  fi
  LOCK_HELD=""
}

# arm_traps HANDLER: HANDLER runs on every way out (an interrupt, a closed terminal, kill, an error), then the lock is
# released. disarm_traps goes back to releasing the lock only. INT, TERM and HUP become exits so the EXIT trap runs.
# The handler writes to the terminal (fds 7 and 8, saved by main): a signal can arrive inside a function whose
# output goes to the log, and the trap would otherwise inherit that redirection.
arm_traps() {
  # The handler name is read now, when the trap is armed: that is the point of arm_traps.
  # shellcheck disable=SC2064
  trap "$1 >&7 2>&8; release_lock" EXIT
  trap 'exit 130' INT
  trap 'exit 143' TERM
  trap 'exit 129' HUP
}
disarm_traps() { arm_traps :; }

hindsight_volume() {
  docker volume ls -q --filter "label=com.docker.compose.project=$PROJECT" \
    --filter "label=com.docker.compose.volume=hindsight_pg0" 2>/dev/null | head -n 1
}

# The pinned Hindsight image of this stack (its tar and sh are used offline on the volume), or nothing.
hindsight_image() {
  compose config --images 2>>"$LOG" | grep 'vectorize-io/hindsight' | head -n 1 || true
}

backup_database() {
  local out="$1"
  ( umask 077; : >"$out.part" ) && chmod 600 "$out.part" || return 1
  if ! compose exec -T postgres pg_dump -U postgres -d sidekick --no-owner 2>>"$LOG" | backup_crypto encrypt >"$out.part" \
      || [ ! -s "$out.part" ]; then
    rm -f "$out.part"
    return 1
  fi
  if ! verify_dump "$out.part"; then
    errf bk_verify_fail "$out" "$LOG"
    rm -f "$out.part"
    return 1
  fi
  # Verified, so now durable: flush the file, rename it into place, flush the directory entry.
  chmod 600 "$out.part"
  fsync_path "$out.part"
  mv "$out.part" "$out"
  fsync_path "$BACKUPS"
}

# Services that write to Postgres or feed Hindsight. They are paused for the whole backup (both copies), so the
# database dump and the Hindsight archive describe the same moment. Postgres and Hindsight stay up until their copy.
WRITERS=(api memory-worker automation-worker)
PAUSED_WRITERS=()      # the WRITERS that were running when the backup began; started again on every way out
HINDSIGHT_PAUSED=0
PARTIAL_BACKUP_FILES=""

# Ids of the containers of service $1 that are, or may become, active. Every status counts, not only "running": a
# writer in a restart loop is "restarting" between two attempts and Docker starts it again during the copies; a
# paused one is still alive; a created one starts by itself when it has a restart policy. Non-zero when compose or
# docker cannot tell (the caller fails closed). Same rule as live_containers() in deploy/selfhost/update.sh.
live_writer_containers() {
  local cids cid line policy
  cids="$(compose ps -a -q "$1" 2>>"$LOG")" || return 1
  for cid in $cids; do
    line="$(docker inspect -f '{{.State.Status}} {{.HostConfig.RestartPolicy.Name}}' "$cid" 2>>"$LOG")" || return 1
    case "$line" in
      running\ * | restarting\ * | paused\ *) echo "$cid" ;;
      created\ *)
        policy="${line#created }"
        if [ -n "$policy" ] && [ "$policy" != no ]; then echo "$cid"; fi
        ;;
    esac
  done
}

# [message key]; stops every writer that is or may become active, then checks that none is and none can start again
# by itself. Fails closed: non-zero (the caller aborts before changing anything, the trap starts the paused ones
# again) if compose or docker cannot tell which writers are active, if the stop fails, or if any writer is still
# active afterwards. Used by backup, update and restore.
pause_writers() {
  local svc listed
  PAUSED_WRITERS=()
  for svc in "${WRITERS[@]}"; do
    listed="$(live_writer_containers "$svc")" || { errf writers_unknown "${WRITERS[*]}" "$LOG"; return 1; }
    if [ -n "$listed" ]; then PAUSED_WRITERS+=("$svc"); fi
  done
  if [ "${#PAUSED_WRITERS[@]}" -gt 0 ]; then
    sayf "${1:-bk_writers_pause}" "${PAUSED_WRITERS[*]}"
    compose stop "${PAUSED_WRITERS[@]}" >>"$LOG" 2>&1 || return 1
  fi
  for svc in "${WRITERS[@]}"; do
    listed="$(live_writer_containers "$svc")" || { errf writers_unknown "${WRITERS[*]}" "$LOG"; return 1; }
    [ -z "$listed" ] || { errf writers_still "${WRITERS[*]}"; return 1; }
  done
}

resume_writers() { # starts the paused writers again (waits until healthy); idempotent, the list is emptied only on success
  [ "${#PAUSED_WRITERS[@]}" -gt 0 ] || return 0
  compose up -d --wait --wait-timeout 300 "${PAUSED_WRITERS[@]}" >>"$LOG" 2>&1 && PAUSED_WRITERS=()
}

# Starts Hindsight again (also the way out of a pause, see backup_memory).
resume_hindsight() {
  [ "$HINDSIGHT_PAUSED" = 1 ] || return 0
  # The gateway now depends on api: do not restart paused writers through Hindsight's dependencies.
  compose up -d --wait --wait-timeout 300 --no-deps hindsight >>"$LOG" 2>&1 && HINDSIGHT_PAUSED=0
}

# EXIT trap for the whole backup: an interrupt (Ctrl-C, a closed terminal, kill) or an unexpected error cannot
# leave the memory or the writers stopped, and no half-made backup files are kept.
abort_paused_backup() {
  local f
  trap - EXIT INT TERM HUP
  for f in $PARTIAL_BACKUP_FILES; do rm -f "$f"; done
  resume_hindsight || true
  resume_writers || true
}

# Archive the volume into $1 (a .tar.gz). Prints nothing when there is no volume yet; returns 1 on any failure,
# after Hindsight has been started again. The trap set by do_backup guarantees the restart on every other way out.
backup_memory() {
  local out="$1" vol image ok=1
  vol="$(hindsight_volume)"
  if [ -z "$vol" ]; then say bk_mem_none; return 0; fi
  image="$(hindsight_image)"
  [ -n "$image" ] || return 1
  say bk_mem_pause
  PARTIAL_BACKUP_FILES="$out.part $PARTIAL_BACKUP_FILES"
  # The encrypted archive is created private (0600) before a byte is written, whatever the umask.
  ( umask 077; : >"$out.part" ) && chmod 600 "$out.part" || { rm -f "$out.part"; return 1; }
  HINDSIGHT_PAUSED=1
  if ! compose stop hindsight >>"$LOG" 2>&1 \
      || ! docker run --rm --network none -v "$vol:/src:ro" --entrypoint tar "$image" -C /src -czf - . 2>>"$LOG" \
        | backup_crypto encrypt >"$out.part" \
      || [ ! -s "$out.part" ]; then
    rm -f "$out.part"
    ok=0
  fi
  resume_hindsight || ok=0
  # Hindsight is up again; only now the (slower) read-back of the encrypted archive.
  if [ "$ok" = 1 ] && ! verify_archive "$out.part"; then
    errf bk_verify_fail "$out" "$LOG"
    rm -f "$out.part"
    ok=0
  fi
  PARTIAL_BACKUP_FILES="${PARTIAL_BACKUP_FILES#"$out.part "}"
  [ "$ok" = 1 ] || return 1
  chmod 600 "$out.part"
  fsync_path "$out.part"
  mv "$out.part" "$out"
  fsync_path "$BACKUPS"
  sayf bk_mem_ok "$out"
}

# Keeps the newest $KEEP_BACKUPS of each kind (the time stamp in the name sorts by time, so the order does not depend on
# file times that a copy or a restore can change). Called only after a backup set was written, read back and
# renamed into place, and never deletes the files of that set (LAST_BACKUP_DB and LAST_BACKUP_MEM), whatever
# KEEP_BACKUPS is. Does nothing when the newest set is not there, so a failed backup never prunes older ones.
prune_backups() {
  [ -s "$LAST_BACKUP_DB" ] || return 0
  backup_prune_finished "$BACKUPS" 'sidekick-[0-9]{8}-[0-9]{6}\.sql\.enc' "$KEEP_BACKUPS" "$(basename "$LAST_BACKUP_DB")" >/dev/null || true
  backup_prune_finished "$BACKUPS" 'hindsight-[0-9]{8}-[0-9]{6}\.tar\.gz\.enc' "$KEEP_BACKUPS" "$(basename "$LAST_BACKUP_MEM")" >/dev/null || true
  fsync_path "$BACKUPS"
}

# Before a new backup (and before anything is paused or stopped): the backup directory must have room for the
# next set, judged by the newest finished set times a margin. Refuses with a clear error otherwise.
require_backup_space() {
  local baseline rc=0
  baseline=$(( $(backup_newest_size "$BACKUPS" 'sidekick-[0-9]{8}-[0-9]{6}\.sql\.enc') + $(backup_newest_size "$BACKUPS" 'hindsight-[0-9]{8}-[0-9]{6}\.tar\.gz\.enc') ))
  backup_check_space "$BACKUPS" "$baseline" || rc=$?
  case "$rc" in
    0) ;;
    1) errf bk_space "$BACKUPS" "$BACKUP_SPACE_FREE" "$BACKUP_SPACE_NEEDED"; exit 1 ;;
    *) errf bk_space_unknown "$BACKUPS"; exit 1 ;;
  esac
}

# Used by `backup`, `update` and `restore`. Prints where the files went; exits 1 (the caller must not go on) on any
# failure. Order: pause the writers, dump the database, archive Hindsight (paused inside), start both again. The trap
# starts everything again and removes half-made files on every way out. With --keep-paused (restore) nothing is
# pruned, the writers stay paused and the trap stays set: the caller takes both over. The files are in LAST_BACKUP_*.
LAST_BACKUP_TS=""
LAST_BACKUP_DB=""
LAST_BACKUP_MEM=""
BACKUP_TRAP=abort_paused_backup  # the EXIT handler of the backup; `update` sets its own, which also knows the image and the code
do_backup() {
  local ts db mem keep_paused=0
  if [ "${1:-}" = --keep-paused ]; then keep_paused=1; fi
  mkdir -p "$BACKUPS"
  chmod 700 "$BACKUPS"
  backup_valid_keep "$KEEP_BACKUPS" || { errf bk_keep_bad "$KEEP_BACKUPS"; exit 1; }
  require_backup_space  # fails closed before anything is paused or started
  require_backup_key generate  # fails closed before anything is paused or started
  if [ -z "$(container_id postgres)" ]; then
    compose up -d --wait postgres >>"$LOG" 2>&1 || { errf bk_db_start "$LOG"; exit 1; }
  fi
  ts="$(date +%Y%m%d-%H%M%S)"
  # Never write over an existing set (two backups within one second): wait for the next time stamp.
  while [ -e "$BACKUPS/sidekick-$ts.sql.enc" ] || [ -e "$BACKUPS/hindsight-$ts.tar.gz.enc" ]; do
    sleep 1
    ts="$(date +%Y%m%d-%H%M%S)"
  done
  db="$BACKUPS/sidekick-$ts.sql.enc"
  mem="$BACKUPS/hindsight-$ts.tar.gz.enc"
  arm_traps "$BACKUP_TRAP"
  pause_writers || { errf bk_fail "$LOG"; exit 1; }
  PARTIAL_BACKUP_FILES="$db.part"
  if ! backup_database "$db"; then errf bk_fail "$LOG"; exit 1; fi
  sayf bk_db_ok "$db"
  PARTIAL_BACKUP_FILES="$db"
  if ! backup_memory "$mem"; then
    errf bk_fail "$LOG"
    exit 1
  fi
  PARTIAL_BACKUP_FILES=""
  LAST_BACKUP_TS="$ts"; LAST_BACKUP_DB="$db"; LAST_BACKUP_MEM="$mem"
  if [ "$keep_paused" = 1 ]; then return 0; fi
  # The trap stays active until the writers are up: a TERM during the restart still ends in a second, harmless attempt.
  if ! resume_writers; then
    errf bk_writers_fail "${WRITERS[*]}" "$LOG"
    exit 1
  fi
  disarm_traps
  prune_backups
  sayf bk_keep "$KEEP_BACKUPS" "$BACKUPS"
}

cmd_backup() {
  need_docker
  ensure_work_env || exit 1
  ensure_secrets
  derive
  echo "=== $(now) backup ===" >>"$LOG"
  do_backup
}

# Run inside the api container; exit 0 = ready. The same code as READINESS_PY in deploy/selfhost/update.sh and as the
# selfhost api healthcheck (a test keeps them equal). 1) The running api process must answer HTTP within 3 s: 2xx, or
# the intended 404 (the public surface hides /health/* in github_oauth mode); any other status or a hung process fails.
# 2) If the image has the readiness module, the database must answer with the runtime role and the schema must be at
# the image's revision. The container merely being up is not enough.
# shellcheck disable=SC2016
READINESS_PY='import importlib.util, sys, urllib.error, urllib.request
try:
    urllib.request.urlopen("http://127.0.0.1:8000/health/live", timeout=3)
except urllib.error.HTTPError as error:
    if error.code != 404:
        sys.exit(1)
except Exception:
    sys.exit(1)
if importlib.util.find_spec("sidekick.shared.readiness") is None:
    sys.exit(0)
from sidekick.shared.readiness import main
main()'

wait_ready() { # 0 once the api passes the readiness check, 1 after the timeout
  local timeout="${SIDEKICK_WORK_READY_TIMEOUT:-180}" deadline
  deadline=$((SECONDS + timeout))
  sayf up_ready_wait "$timeout"
  while :; do
    if compose exec -T api python -c "$READINESS_PY" >>"$LOG" 2>&1; then return 0; fi
    [ "$SECONDS" -lt "$deadline" ] || return 1
    sleep "${SIDEKICK_WORK_READY_POLL:-3}"
  done
}

# The migration class of an update, as deploy/selfhost/update.sh decides it from the image label: the new code may only
# bring migrations the old code can still run against (expand-only) unless --allow-breaking-migration is given.
# This package builds its image from the checkout and has no label, so tools/check-release-migration-class.py
# compares the migrations since the commit that was installed ($1). Output goes to the log; returns the script's code.
check_migration_class() {
  local class=expand rc=0
  [ "$2" = 1 ] && class=breaking
  python3 "$REPO/tools/check-release-migration-class.py" --release-class "$class" --installed "$1" >>"$LOG" 2>&1 || rc=$?
  [ "$rc" -eq 0 ] && return 0
  tail -n 20 "$LOG" >&2 || true
  if [ "$rc" -eq 1 ]; then errf up_contract "$LOG"; else errf up_class_fail "$LOG"; fi
  return "$rc"
}

# State of a running `update`, read by its EXIT trap. UPDATE_PHASE: pre = nothing has been migrated (every way out puts the
# previous version back), migrating = the migration has begun or may have (every way out leaves the writers stopped).
UPDATE_PHASE=pre
PREV_IMAGE=""        # the image that ran before the update (its id); empty when there was none
PREV_IMAGE_TAG=""    # the tag that keeps it: repository:previous
CUR_IMAGE=""         # the tag the stack runs from, which `compose build` moves to the new image
UPDATE_BUILT=0       # the build ran, so CUR_IMAGE may point at the new image
RETAG_FAILED=0       # putting the previous image back under CUR_IMAGE failed, so a restart runs the new build
UPDATE_BEFORE=""     # the commit the checkout was on; the code goes back to it on every failure before the migration

# The image name the stack runs from and a tag that keeps what runs now, before the build moves the name on.
save_previous_image() {
  local name
  CUR_IMAGE="${SIDEKICK_WORK_API_IMAGE:-$(envval SIDEKICK_WORK_API_IMAGE)}"
  CUR_IMAGE="${CUR_IMAGE:-roadlake-sidekick:work}"
  PREV_IMAGE="$(docker image inspect -f '{{.Id}}' "$CUR_IMAGE" 2>/dev/null)" || PREV_IMAGE=""
  [ -n "$PREV_IMAGE" ] || return 0
  name="${CUR_IMAGE%@*}"
  case "${name##*/}" in *:*) name="${name%:*}" ;; esac
  PREV_IMAGE_TAG="$name:previous"
  if docker tag "$PREV_IMAGE" "$PREV_IMAGE_TAG" >>"$LOG" 2>&1; then
    sayf up_prev_saved "$PREV_IMAGE_TAG"
  else
    PREV_IMAGE=""; PREV_IMAGE_TAG=""
  fi
}

# EXIT trap of `update`. Before the migration: the code goes back to the commit it came from, the previous image is put
# back under its name (a build may have moved it) and the writers, if the backup had stopped them, start again from it.
# From the migration on, the writers stay stopped and nothing is restored: the person decides, with the backup, from the
# messages already printed.
abort_update() {
  local f stopped
  if [ "$UPDATE_PHASE" = pre ]; then
    if [ -n "$UPDATE_BEFORE" ] && [ "$(git -C "$REPO" rev-parse HEAD 2>/dev/null)" != "$UPDATE_BEFORE" ]; then
      # --keep fails rather than touch local changes; the message says how to move the code.
      git -C "$REPO" reset --keep "$UPDATE_BEFORE" >>"$LOG" 2>&1 || errf up_class_stuck "$REPO" "$UPDATE_BEFORE"
    fi
    if [ "$UPDATE_BUILT" = 1 ] && [ -n "$PREV_IMAGE" ]; then
      if ! docker tag "$PREV_IMAGE" "$CUR_IMAGE" >>"$LOG" 2>&1; then
        RETAG_FAILED=1
        errf up_retag_failed "$CUR_IMAGE" "$LOG" "$PREV_IMAGE_TAG"
      fi
    fi
    stopped="${#PAUSED_WRITERS[@]}"
    abort_paused_backup
    if [ "${#PAUSED_WRITERS[@]}" -gt 0 ]; then
      errf up_old_failed "$LOG"
    elif [ "$RETAG_FAILED" = 1 ]; then
      errf up_old_not_running "$CUR_IMAGE" "$PREV_IMAGE_TAG" "$PREV_IMAGE_TAG" "$CUR_IMAGE"
    elif [ "$stopped" -gt 0 ]; then
      sayf up_old_running "${PREV_IMAGE_TAG:-$CUR_IMAGE}"
    fi
    return 0
  fi
  trap - EXIT INT TERM HUP
  for f in $PARTIAL_BACKUP_FILES; do rm -f "$f"; done
  resume_hindsight || true
  compose stop "${WRITERS[@]}" >>"$LOG" 2>&1 || true
  PAUSED_WRITERS=()
}

# The messages after a failure from the migration on: the writers stay stopped (the trap does it), the backup is named,
# the way back for the code is given, and nothing is restored.
update_stays_stopped() { # before, after, branch
  errf up_stay_stopped "${WRITERS[*]}" "$LAST_BACKUP_DB" "$LAST_BACKUP_MEM" "$BACKUPS" "$LAST_BACKUP_TS" "${PREV_IMAGE_TAG:-none}"
  errf up_rollback "$1" "$2" "$REPO" "$1" "$BACKUPS" "$REPO" "$3"
}

# Update. Order: tag the previous image, git pull --ff-only, the migration class check (a refusal puts the code back on the
# commit it came from), pull/build. None of that touches data or stops anything, so a failure there only puts the code and
# the image name back. Then stop every writer and take the backup (they start again from the previous image if it fails),
# keep them stopped, migrate, start the api alone and wait until it is ready, then start the rest and check again.
# From the migration on a failure leaves the writers stopped, restores nothing automatically and prints where the backup
# is and how to go back (docs/operate/work-laptop/backup-and-update.md). Compare deploy/selfhost/update.sh: the same rule, written there for a
# pinned image.
cmd_update() {
  local allow_breaking=0
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --allow-breaking-migration) allow_breaking=1 ;;
      *) errf usage; exit 2 ;;
    esac
    shift
  done
  need_docker; need_tool git; need_tool python3
  git -C "$REPO" rev-parse --is-inside-work-tree >/dev/null 2>&1 || { errf up_no_git; exit 1; }
  ensure_work_env || exit 1
  ensure_secrets
  derive
  local before after branch
  echo "=== $(now) update ===" >>"$LOG"
  UPDATE_PHASE=pre
  BACKUP_TRAP=abort_update
  save_previous_image
  arm_traps abort_update
  before="$(git -C "$REPO" rev-parse HEAD)"
  UPDATE_BEFORE="$before"
  branch="$(git -C "$REPO" rev-parse --abbrev-ref HEAD 2>/dev/null || echo HEAD)"
  if ! git -C "$REPO" pull --ff-only >>"$LOG" 2>&1; then
    errf up_pull_fail "$LOG"
    exit 1
  fi
  after="$(git -C "$REPO" rev-parse HEAD)"
  # A refusal exits; the trap puts the code back on $before.
  if [ "$before" != "$after" ] && ! check_migration_class "$before" "$allow_breaking"; then exit 1; fi
  if [ "$before" = "$after" ]; then sayf up_same "${after:0:10}"; else sayf up_changed "${before:0:10}" "${after:0:10}"; fi
  write_rooms_env
  render_generated
  say up_building
  compose pull --ignore-buildable --quiet >>"$LOG" 2>&1 || errf up_offline
  UPDATE_BUILT=1
  if ! compose build api >>"$LOG" 2>&1; then
    errf up_build_fail "$LOG"
    tail -n 20 "$LOG" >&2 || true
    exit 1
  fi
  # Only now are the writers stopped, and they stay stopped until the new version is up and ready: nothing writes between
  # the backup and the migration. The running containers keep the previous image until they are recreated.
  do_backup --keep-paused
  arm_traps abort_update
  # The image built above migrates while nothing writes. yoyo is idempotent, so the start below, which reruns the
  # one-shot migrate service before the api starts, finds nothing left to do.
  UPDATE_PHASE=migrating
  if ! compose run --rm -T --no-deps migrate >>"$LOG" 2>&1; then
    errf up_migrate_fail "$LOG" "$BACKUPS"
    tail -n 20 "$LOG" >&2 || true
    update_stays_stopped "$before" "$after" "$branch"
    exit 1
  fi
  # The api alone first, because the readiness check runs in it; the memory worker and the automation worker start only
  # after it has passed (they are recreated by this, their image is new), and then the whole stack is checked again.
  if ! compose up -d --wait --wait-timeout 420 --force-recreate api >>"$LOG" 2>&1; then
    errf up_restart_fail "$LOG" "$BACKUPS"
    tail -n 20 "$LOG" >&2 || true
    update_stays_stopped "$before" "$after" "$branch"
    exit 1
  fi
  if ! wait_ready; then
    errf up_ready_fail "$LOG" "$BACKUPS"
    update_stays_stopped "$before" "$after" "$branch"
    exit 1
  fi
  if ! compose up -d --wait --wait-timeout 420 >>"$LOG" 2>&1; then
    errf up_restart_fail "$LOG" "$BACKUPS"
    tail -n 20 "$LOG" >&2 || true
    update_stays_stopped "$before" "$after" "$branch"
    exit 1
  fi
  # The gateway configuration is a mounted file that compose does not watch: restart the gateway when it changed.
  if ! cmp -s "$GEN/gateway.haproxy.cfg" "$GEN/.gateway.applied" 2>/dev/null; then
    compose restart gateway >>"$LOG" 2>&1 || { errf gw_fail "$LOG"; update_stays_stopped "$before" "$after" "$branch"; exit 1; }
  fi
  if ! wait_ready; then
    errf up_ready_fail "$LOG" "$BACKUPS"
    update_stays_stopped "$before" "$after" "$branch"
    exit 1
  fi
  PAUSED_WRITERS=()
  disarm_traps
  prune_backups
  cp "$GEN/gateway.haproxy.cfg" "$GEN/.gateway.applied"
  write_build_info "$before" updated
  desktop_setup
  sayf up_done "$GEN/build-info.json"
}

# ---------------------------------------------------------------------------------------------------------
# Restore: the database and Hindsight's memory from ONE backup set (the same time stamp), never one without the other,
# because Sidekick's database records which sources were sent to Hindsight and Hindsight holds the memories.
# Without --apply: checks the set and the target and prints the plan; reads only. With --apply, after the project
# name is typed: do_backup --keep-paused (the way back; the writers stay paused), the database sidekick is renamed (kept,
# not dropped) and the dump read into a fresh one with the grants postgres-init.sh gives, ownership repaired, Hindsight
# stopped and its volume replaced, the migration run. Until that point every failure or interrupt puts the previous
# database and memory back (abort_restore). Then Hindsight and the writers start and the api must become ready; from
# there nothing is rolled back automatically, because the services have run against the restored data.

# psql as the superuser inside the postgres container, stopping at the first error.
pg_admin() { compose exec -T postgres psql -U postgres -v ON_ERROR_STOP=1 -q "$@"; }

NO_OTHER_SESSIONS="SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = 'sidekick' AND pid <> pg_backend_pid()"
RESTORE_OLD_DB=""      # the name the previous database gets (set just before the rename); empty = nothing to undo
RESTORE_OLD_NAME=""    # the same name, kept for the messages
RESTORE_MEM_TOUCHED=0  # 1 while the memory volume may hold something other than what was there before
RESTORE_COMMITTED=0    # 1 once the restored data is final: from then on the trap only starts services again
RESTORE_SAFETY_DB=""
RESTORE_SAFETY_MEM=""

# Prints the time stamps that have both files in $BACKUPS, oldest first (the names sort by time).
list_backup_sets() {
  local f ts found=0
  for f in "$BACKUPS"/sidekick-*.sql.enc; do
    [ -e "$f" ] || continue
    ts="${f##*/sidekick-}"; ts="${ts%.sql.enc}"
    if [ -s "$BACKUPS/hindsight-$ts.tar.gz.enc" ]; then
      [ "$found" = 1 ] || sayf rs_sets "$BACKUPS"
      found=1
      printf '  %s\n' "$ts"
    fi
  done
  [ "$found" = 1 ] || sayf rs_no_sets "$BACKUPS"
}

# Both files present and whole, read with the key: decrypted again, the dump ends with pg_dump's end marker and the
# archive lists and holds at least one entry. A missing key stops here (fail closed), before anything is changed.
check_backup_set() {
  local db="$1" mem="$2"
  [ -s "$db" ] || { errf rs_missing "$db"; return 1; }
  [ -s "$mem" ] || { errf rs_missing "$mem"; return 1; }
  require_backup_key
  verify_dump "$db" || { errf rs_bad_dump "$db" "$BACKUP_KEY_FILE"; return 1; }
  verify_archive "$mem" || { errf rs_bad_archive "$mem" "$BACKUP_KEY_FILE"; return 1; }
}

# Renames sidekick to $2 and reads the encrypted dump $1 into a fresh sidekick (decrypted on the way, never to disk). Returns 1 on any failure (the trap undoes it).
restore_database() {
  local dump="$1" old="$2"
  pg_admin -d postgres -c "$NO_OTHER_SESSIONS" >>"$LOG" 2>&1 || return 1
  # Recorded before the rename: a signal between the rename and the next line must still find the way back.
  # rollback_database asks Postgres which of the two names exist, so it is right whether the rename ran or not.
  RESTORE_OLD_DB="$old"
  pg_admin -d postgres -c "ALTER DATABASE sidekick RENAME TO $old" >>"$LOG" 2>&1 || return 1
  pg_admin -d postgres -c "CREATE DATABASE sidekick" \
    -c "GRANT CONNECT ON DATABASE sidekick TO sidekick_migrator, sidekick_app" \
    -c "GRANT CREATE ON DATABASE sidekick TO sidekick_owner" >>"$LOG" 2>&1 || return 1
  pg_admin -d sidekick -c "GRANT CREATE, USAGE ON SCHEMA public TO sidekick_migrator" >>"$LOG" 2>&1 || return 1
  # VERBOSITY=sqlstate: psql prints only the error code. Its normal messages quote the failing row ("Failing row
  # contains", COPY context lines, the rejected value), and the last lines of the log are shown on failure.
  backup_crypto decrypt <"$dump" | pg_admin -v VERBOSITY=sqlstate -d sidekick --single-transaction >>"$LOG" 2>&1 || return 1
  # The dump leaves out owners; without this the migrator could not change the tables in a later update.
  pg_admin -d sidekick <"$SELFHOST/restore-ownership.sql" >>"$LOG" 2>&1 || return 1
}

# Empties the Hindsight volume and unpacks the encrypted archive $1 into it (decrypted on the way, never to disk), offline,
# with the pinned image. Hindsight must be stopped.
unpack_memory() {
  local archive="$1" vol image
  vol="$(hindsight_volume)"
  image="$(hindsight_image)"
  [ -n "$vol" ] && [ -n "$image" ] || return 1
  backup_crypto decrypt <"$archive" \
    | docker run --rm -i --network none -v "$vol:/dst" --entrypoint sh "$image" \
      -c 'find /dst -mindepth 1 -delete && tar -C /dst -xzf -' >>"$LOG" 2>&1
}

# Idempotent, decided by what exists: the old name present means the rename ran (drop the new sidekick, rename back);
# only sidekick present means the rename never ran or was undone already (nothing to do); neither, or no answer from
# Postgres, is a failure (the trap then starts nothing).
rollback_database() {
  [ -n "$RESTORE_OLD_DB" ] || return 0
  local names
  names="$(pg_admin -d postgres -tAc "SELECT datname FROM pg_database WHERE datname IN ('sidekick', '$RESTORE_OLD_DB')" 2>>"$LOG")" || return 1
  if printf '%s\n' "$names" | grep -qx "$RESTORE_OLD_DB"; then
    pg_admin -d postgres -c "$NO_OTHER_SESSIONS" -c "DROP DATABASE IF EXISTS sidekick" \
      -c "ALTER DATABASE $RESTORE_OLD_DB RENAME TO sidekick" >>"$LOG" 2>&1 || return 1
  elif ! printf '%s\n' "$names" | grep -qx sidekick; then
    return 1
  fi
  RESTORE_OLD_DB=""
}

rollback_memory() {
  [ "$RESTORE_MEM_TOUCHED" = 1 ] || return 0
  unpack_memory "$RESTORE_SAFETY_MEM" && RESTORE_MEM_TOUCHED=0
}

# EXIT trap of restore --apply. Before the commit point: put the previous memory and database back (Hindsight is still
# stopped), then start Hindsight and the writers again. After it: only start them again. If putting back fails, nothing
# is started (the memory-worker would start Hindsight on a volume in an unknown state); the message says what is where.
abort_restore() {
  local f undo=0 ok=1
  trap - EXIT INT TERM HUP
  for f in $PARTIAL_BACKUP_FILES; do rm -f "$f"; done
  if [ "$RESTORE_COMMITTED" = 0 ]; then
    if [ -n "$RESTORE_OLD_DB" ] || [ "$RESTORE_MEM_TOUCHED" = 1 ]; then undo=1; fi
    rollback_memory || ok=0
    rollback_database || ok=0
    if [ "$ok" = 0 ]; then
      errf rs_rollback_fail "$LOG" "$RESTORE_OLD_NAME" "$RESTORE_SAFETY_DB" "$RESTORE_SAFETY_MEM"
      return
    fi
    if [ "$undo" = 1 ]; then errf rs_rolled_back "$RESTORE_OLD_NAME" "$RESTORE_SAFETY_MEM"; fi
  fi
  resume_hindsight || true
  resume_writers || true
}

# The restored database has its own owner user jobb (on another machine a different UUID): point Claude Desktop at it.
sync_owner_id() {
  local id tmp
  id="$(pg_admin -d sidekick -tAc "select id from sidekick.users where username = 'jobb'" 2>>"$LOG" | tr -d '[:space:]' || true)"
  if printf '%s' "$id" | grep -Eqi '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'; then
    tmp="$(mktemp "$SECRETS/.tmp.XXXXXX")"
    printf '%s\n' "$id" >"$tmp"
    chmod 600 "$tmp"
    mv "$tmp" "$SECRETS/user-id"
  else
    say rs_owner_none
    rm -f "$SECRETS/user-id"
  fi
}

cmd_restore() {
  local apply=0 arg="" dir ts base db mem answer
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --apply) apply=1 ;;
      -*) errf rs_usage; exit 2 ;;
      *) [ -z "$arg" ] || { errf rs_usage; exit 2; }; arg="$1" ;;
    esac
    shift
  done
  need_docker
  ensure_work_env || exit 1
  ensure_secrets
  derive
  if [ -z "$arg" ]; then errf rs_usage; list_backup_sets >&2; exit 2; fi
  case "$arg" in
    */*|*.sql.enc|*.tar.gz.enc)
      base="${arg##*/}"
      dir="$(dirname "$arg")"
      ts="${base#sidekick-}"; ts="${ts#hindsight-}"; ts="${ts%.sql.enc}"; ts="${ts%.tar.gz.enc}"
      ;;
    *) dir="$BACKUPS"; ts="$arg" ;;
  esac
  [[ "$ts" =~ ^[0-9]{8}-[0-9]{6}$ ]] || { errf rs_bad_name "$arg"; exit 2; }
  db="$dir/sidekick-$ts.sql.enc"
  mem="$dir/hindsight-$ts.tar.gz.enc"
  check_backup_set "$db" "$mem" || exit 1
  [ -f "$SELFHOST/restore-ownership.sql" ] || { errf rs_no_ownership "$SELFHOST/restore-ownership.sql"; exit 1; }
  [ -n "$(hindsight_volume)" ] || { errf rs_no_volume "$PROJECT"; exit 1; }
  sayf rs_plan "$db" "$mem" "$PROJECT" "$BACKUPS"
  if [ "$apply" = 0 ]; then say rs_dry; return 0; fi

  printf "$(msg rs_confirm_q)" "$PROJECT" >&2
  IFS= read -r answer || answer=""
  [ "$answer" = "$PROJECT" ] || { say aborted; exit 1; }
  echo "=== $(now) restore $ts ===" >>"$LOG"

  # 1-2. The way back, taken while the writers are paused; they stay paused and the backup trap stays set.
  do_backup --keep-paused
  RESTORE_SAFETY_DB="$LAST_BACKUP_DB"
  RESTORE_SAFETY_MEM="$LAST_BACKUP_MEM"
  RESTORE_OLD_NAME="sidekick_before_restore_${LAST_BACKUP_TS/-/_}"
  arm_traps abort_restore
  [ -s "$RESTORE_SAFETY_MEM" ] || { errf bk_fail "$LOG"; exit 1; }
  sayf rs_safety "$RESTORE_SAFETY_DB" "$RESTORE_SAFETY_MEM"

  # 3. The database.
  sayf rs_db "$RESTORE_OLD_NAME"
  restore_database "$db" "$RESTORE_OLD_NAME" || { errf rs_fail "$(msg rs_step_db)" "$LOG"; exit 1; }
  # 4. The memory.
  say rs_mem
  HINDSIGHT_PAUSED=1
  compose stop hindsight >>"$LOG" 2>&1 || { errf rs_fail "$(msg rs_step_mem)" "$LOG"; exit 1; }
  RESTORE_MEM_TOUCHED=1
  unpack_memory "$mem" || { errf rs_fail "$(msg rs_step_mem)" "$LOG"; exit 1; }
  # 5. A set from older code is brought up to the schema of this image (yoyo is idempotent).
  say rs_migrating
  compose run --rm -T --no-deps migrate >>"$LOG" 2>&1 || { errf rs_fail "$(msg rs_step_migrate)" "$LOG"; exit 1; }

  # 6. Commit point: the restored data is final; the trap now only starts the services again.
  RESTORE_COMMITTED=1
  if ! resume_hindsight || ! resume_writers; then
    errf rs_start_fail "$LOG" "$RESTORE_OLD_NAME" "$RESTORE_SAFETY_DB" "$RESTORE_SAFETY_MEM"
    exit 1
  fi
  if ! wait_ready; then
    errf rs_ready_fail "$LOG" "$RESTORE_OLD_NAME" "$RESTORE_SAFETY_DB" "$RESTORE_SAFETY_MEM"
    exit 1
  fi
  disarm_traps
  sync_owner_id
  desktop_setup
  sayf rs_done "$ts" "$RESTORE_OLD_NAME" "$PROJECT" "$RESTORE_OLD_NAME"
}

# ---------------------------------------------------------------------------------------------------------
cmd_setup() {
  local lang_default ans url key mem allow rooms models parsed test_key keep_key port t missing
  lang_default="$L"
  printf '%s [%s]: ' "$(msg lang_q)" "$lang_default" >&2
  IFS= read -r ans || ans=""
  case "${ans:-$lang_default}" in sv*|SV*) L=sv ;; *) L=en ;; esac
  warn_strict_umask
  echo
  say title
  say intro
  echo
  missing=""
  for t in docker openssl python3 curl; do command -v "$t" >/dev/null 2>&1 || missing="$missing $t"; done
  if [ -n "$missing" ]; then errf need "${missing# }"; exit 1; fi
  if ! docker compose version >/dev/null 2>&1; then errf compose_old; exit 1; fi

  mkdir -p "$SECRETS"; chmod 700 "$SECRETS"
  if [ ! -f "$WORK_ENV" ]; then cp "$WORK/work.env.example" "$WORK_ENV"; chmod 600 "$WORK_ENV"; fi
  if ! secrets_exist; then generate_secrets; apply_model_key ""; fi

  # 1. Model server address and key, tested with GET /models.
  url="$(envval SIDEKICK_WORK_MODEL_BASE_URL)"
  case "$url" in *"<"*) url="" ;; esac
  keep_key="$(stored_model_key)"
  models=""
  while :; do
    ask url url_q "$url"
    if ! parsed="$(parse_base_url "$url" 2>&1)"; then
      errf url_bad "$parsed"
      url=""
      continue
    fi
    printf '%s: ' "$(msg key_q)" >&2
    key=""
    IFS= read -rs key || key=""
    echo >&2
    case "$key" in
      '') test_key="$keep_key" ;;
      -) test_key="" ;;
      *) test_key="$key" ;;
    esac
    errf testing "$url"
    if models="$(list_models "$url" "$test_key")"; then
      sayf test_ok "$(printf '%s\n' "$models" | grep -c . || true)"
      break
    fi
    errf test_fail
    models=""
    confirm retry_q n || break
  done
  set_env SIDEKICK_WORK_MODEL_BASE_URL "$url"
  case "$key" in
    '') ;;
    -) apply_model_key "" ;;
    *) apply_model_key "$key" ;;
  esac

  # 2. The memory model (Hindsight's; Sidekick itself calls no model), chosen from the server's list.
  mem="$(envval SIDEKICK_WORK_MEMORY_MODEL)"; case "$mem" in *"<"*) mem="" ;; esac
  if [ -n "$models" ]; then
    say models_head
    printf '%s\n' "$models" | awk '{ printf "  %d) %s\n", NR, $0 }'
    # shellcheck disable=SC2086
    set -- $models
    pick_model mem mem_q "${mem:-$1}" "$@"
  else
    ask mem mem_q "$mem"
  fi
  set_env SIDEKICK_WORK_MEMORY_MODEL "$mem"

  # 3. Allowlist of further addresses.
  say allow_note
  port="$(parse_base_url "$url" 2>/dev/null | sed -n 3p)"
  while :; do
    ask allow allow_q "$(envval SIDEKICK_WORK_ALLOW)"
    if [ -z "$allow" ]; then break; fi
    if parsed="$(parse_allowlist "$allow" "${port:-0}" 2>&1)"; then break; fi
    errf allow_bad "$parsed"
  done
  if [ -n "$allow" ]; then set_env SIDEKICK_WORK_ALLOW "$allow"; else unset_env SIDEKICK_WORK_ALLOW; fi

  # 4. Rooms. The proposal for a work machine is every room except shopping; Enter takes the value offered in
  # brackets (an existing work.env value wins) and "-" switches every room on.
  say rooms_note
  ask rooms rooms_q "$(envval SIDEKICK_ENABLED_ROOMS)" "$DEFAULT_ROOMS"
  if [ -z "$rooms" ]; then rooms="$DEFAULT_ROOMS"; fi
  if [ "$rooms" = "-" ]; then unset_env SIDEKICK_ENABLED_ROOMS; else set_env SIDEKICK_ENABLED_ROOMS "$rooms"; fi

  # 5. The apps' language is its own question (the guide's display language may differ). Swedish is the proposal
  # unless work.env already holds a value.
  while :; do
    ask applang applang_q "$(envval SIDEKICK_WORK_LOCALE)" sv
    case "$applang" in sv|en) break ;; esac
    errf applang_bad
  done
  set_env SIDEKICK_WORK_LOCALE "$applang"
  say wrote
  sayf summary "$applang" "$rooms"
  echo

  # 6. Autostart, then start (which also creates the owner and writes the Claude Desktop configuration).
  if confirm auto_q n; then
    cmd_autostart on
  else
    cmd_autostart off >/dev/null
  fi
  if confirm start_q y; then cmd_start; fi
  echo
  say "done"
  say mobile
}

main() {
  local command="${1:-}"
  if [ "$#" -gt 0 ]; then shift; fi
  init_lang
  exec 7>&1 8>&2
  case "$command" in
    setup|init|start|stop|backup|update) LOCK_COMMAND="$command" ;;
    restore) case " $* " in *" --apply "*) LOCK_COMMAND="restore --apply" ;; esac ;;
  esac
  if [ -n "${LOCK_COMMAND:-}" ]; then
    take_lock "$LOCK_COMMAND"
    disarm_traps
  fi
  case "$command" in
    setup) cmd_setup "$@" ;;
    init) cmd_init "$@" ;;
    start) cmd_start "$@" ;;
    claude-config) cmd_claude_config "$@" ;;
    stop) cmd_stop "$@" ;;
    status) cmd_status "$@" ;;
    backup) cmd_backup "$@" ;;
    autostart) cmd_autostart "$@" ;;
    update) cmd_update "$@" ;;
    restore) cmd_restore "$@" ;;
    *)
      errf usage
      exit 2
      ;;
  esac
}

main "$@"
exit $?
