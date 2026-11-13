"""Command line of workctl: what ``work.sh`` calls. One sub-command per moved piece of logic.

Exit codes: 0 success, 1 the input was rejected (the reason is on stderr, one line), 2 a usage error
(argparse). Secrets are read from stdin, never from arguments, and never printed.
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys
from pathlib import Path

from . import (
    addresses,
    autostart,
    backupkey,
    derive,
    desktopconfig,
    diagnose,
    generated,
    messages,
    modelserver,
    owner,
    prompts,
    restore,
    secretfiles,
    status,
    workenv,
)

# Exit code of ``first-start-table``: the table exists, so ask for its row count.
COUNT_NEEDED = 10


def _fail(message: str) -> int:
    print(message, file=sys.stderr)
    return 1


def _cmd_base_url(args: argparse.Namespace) -> int:
    try:
        parsed = addresses.parse_base_url(args.url, args.lang)
    except addresses.AddressError as error:
        return _fail(str(error))
    print("\n".join(parsed.lines()))
    return 0


def _cmd_allowlist(args: argparse.Namespace) -> int:
    try:
        entries = addresses.parse_allowlist(args.allow, args.model_port, args.lang)
    except addresses.AddressError as error:
        return _fail(str(error))
    for host, port in entries:
        print(host, port)
    return 0


def _cmd_autostart(args: argparse.Namespace) -> int:
    managed = not os.environ.get("SIDEKICK_WORK_AUTOSTART_DIR")
    file = autostart.unit_file(
        args.platform,
        os.environ.get("SIDEKICK_WORK_AUTOSTART_DIR", ""),
        Path.home(),
        os.environ.get("XDG_CONFIG_HOME", ""),
    )
    try:
        if args.action == "on":
            autostart.enable(file, args.platform, args.script, args.log, managed)
            if args.platform == "Darwin":
                print(messages.fill(args.lang, "as_launchd", file))
            else:
                print(messages.fill(args.lang, "as_systemd", file, getpass.getuser()))
        elif args.action == "off":
            autostart.disable(file, args.platform, managed)
            print(messages.text(args.lang, "as_off"))
        elif file.is_file():
            print(messages.fill(args.lang, "as_state_on", file))
        else:
            print(messages.text(args.lang, "as_state_off"))
    except autostart.AutostartError as error:
        return _fail(str(error))
    return 0


def _cmd_generate_secrets(args: argparse.Namespace) -> int:
    try:
        secretfiles.generate_secrets(args.secrets_dir, args.hindsight_example, args.gateway)
    except secretfiles.SecretsExist as error:
        return _fail(f"a secrets file already exists: {error}")
    return 0


def _cmd_model_key_apply(args: argparse.Namespace) -> int:
    key = sys.stdin.read().rstrip("\n")
    secretfiles.apply_model_key(args.secrets_dir, key)
    return 0


def _cmd_model_key_show(args: argparse.Namespace) -> int:
    key = secretfiles.stored_model_key(args.secrets_dir)
    if key:
        print(key)
    return 0


def _cmd_rooms_env(args: argparse.Namespace) -> int:
    secretfiles.write_rooms_env(args.secrets_dir, workenv.env_value(args.env_file, secretfiles.ROOMS_NAME))
    return 0


def _cmd_render_gateway(args: argparse.Namespace) -> int:
    entries = generated.parse_allow_lines(args.allow)
    generated.write_gateway_files(args.template, args.out_dir, entries)
    return 0


def _cmd_text(args: argparse.Namespace) -> int:
    # Bytes, so the output does not depend on the locale of the terminal; no trailing newline.
    sys.stdout.buffer.write(messages.text(args.lang, args.key).encode("utf-8"))
    return 0


def _cmd_env_value(args: argparse.Namespace) -> int:
    print(workenv.env_value(args.env_file, args.key))
    return 0


def _cmd_env_set(args: argparse.Namespace) -> int:
    try:
        workenv.set_value(args.env_file, args.key, args.value)
    except ValueError as error:
        return _fail(str(error))
    return 0


def _cmd_env_unset(args: argparse.Namespace) -> int:
    workenv.unset_value(args.env_file, args.key)
    return 0


def _cmd_memory_wanted(args: argparse.Namespace) -> int:
    return 0 if workenv.memory_wanted(args.env_file) else 1


def _cmd_derive(args: argparse.Namespace) -> int:
    try:
        derived = derive.derive(args.env_file, args.gen_dir, args.lang, args.lenient)
    except derive.DeriveError as error:
        return _fail(str(error))
    print("\n".join(derived.lines()))
    return 0


def _cmd_status_version(args: argparse.Namespace) -> int:
    line = status.version_line(args.lang, args.build_info)
    if line:
        print(line)
    return 0


def _cmd_status_via(args: argparse.Namespace) -> int:
    for line in status.via_report(args.lang, sys.stdin.read(), args.wanted_model):
        print(line)
    return 0


def _cmd_build_info(args: argparse.Namespace) -> int:
    generated.write_build_info(
        args.path, args.commit, args.commit_date, args.now, args.previous, args.updated == "updated"
    )
    return 0


def _cmd_desktop_config(args: argparse.Namespace) -> int:
    desktopconfig.write_desktop_config(args.out, args.docker, args.container, args.owner)
    return 0


def _cmd_claude_config(args: argparse.Namespace) -> int:
    return desktopconfig.merge_into_claude_config(
        args.source, args.target, args.lang, sys.stdin.readline, sys.stdout, sys.stderr
    )


def _cmd_models_list(args: argparse.Namespace) -> int:
    try:
        ids = modelserver.fetch_model_ids(args.base_url, sys.stdin.read().rstrip("\n"))
    except ValueError:
        return 1
    print("\n".join(ids))
    return 0


def _cmd_backup_key(args: argparse.Namespace) -> int:
    try:
        created = backupkey.ensure_key(args.key_file, args.backups_dir, args.generate)
    except backupkey.KeyProblem as problem:
        return _fail(messages.render(args.lang, problem.key, *problem.values))
    if created:
        print(messages.render(args.lang, "bk_key_new", args.key_file))
    return 0


def _cmd_first_start_evidence(_args: argparse.Namespace) -> int:
    # stdin: the evidence, a NUL byte, the postgres log.
    evidence, _, postgres_log = sys.stdin.buffer.read().decode("utf-8", errors="replace").partition("\0")
    return 0 if diagnose.has_failure_evidence(evidence, postgres_log) else 1


def _cmd_first_start_table(args: argparse.Namespace) -> int:
    if diagnose.count_needed(args.table):
        return COUNT_NEEDED
    return 0 if diagnose.nothing_applied(args.table, "") else 1


def _cmd_first_start_hint(args: argparse.Namespace) -> int:
    hint = diagnose.volume_hint(args.lang, args.project, args.volume, args.table, args.count)
    if hint:
        print(hint, file=sys.stderr)
    return 0 if hint else 1


def _cmd_is_uuid(args: argparse.Namespace) -> int:
    return 0 if owner.is_uuid(args.value) else 1


def _cmd_ask(args: argparse.Namespace) -> int:
    if args.raw:
        prompt = messages.render(args.lang, args.key, *args.values)
    else:
        prompt = prompts.question(messages.text(args.lang, args.key), args.default)
    answer = prompts.ask(prompt, args.default, secret=args.secret, only_on_terminal=args.only_on_terminal)
    # Bytes, so the answer is returned as it was typed whatever the locale; no trailing newline.
    sys.stdout.buffer.write(answer.encode("utf-8", errors="surrogateescape"))
    return 0


def _cmd_confirm(args: argparse.Namespace) -> int:
    prompt = prompts.question(messages.text(args.lang, args.key))
    return 0 if prompts.confirm(prompt, args.default) else 1


def _cmd_pick(args: argparse.Namespace) -> int:
    print(prompts.pick_choice(args.answer, args.choices))
    return 0


def _cmd_backup_sets(args: argparse.Namespace) -> int:
    stamps = restore.complete_sets(args.dir, args.memory == "on")
    if not stamps:
        print(messages.fill(args.lang, "rs_no_sets", args.dir))
        return 0
    print(messages.fill(args.lang, "rs_sets", args.dir))
    for stamp in stamps:
        print(f"  {stamp}")
    return 0


def _cmd_restore_ref(args: argparse.Namespace) -> int:
    ref = restore.parse_reference(args.reference, args.backups)
    if ref is None:
        print(messages.render(args.lang, "rs_bad_name", args.reference), file=sys.stderr)
        return 2
    print(ref.directory)
    print(ref.timestamp)
    return 0


def _cmd_rollback_action(args: argparse.Namespace) -> int:
    print(restore.rollback_action(sys.stdin.read().split(), args.old))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="workctl", description="Logic behind tools/work.sh.")
    commands = parser.add_subparsers(dest="command", required=True)

    def add(name: str, handler: object, help_text: str) -> argparse.ArgumentParser:
        sub = commands.add_parser(name, help=help_text)
        sub.set_defaults(handler=handler)
        return sub

    sub = add("base-url", _cmd_base_url, "split the model server URL (scheme, host, port, path, is_ip)")
    sub.add_argument("--lang", choices=("sv", "en"), default="sv")
    sub.add_argument("url")

    sub = add("allowlist", _cmd_allowlist, "validate host:port,host:port; print 'host port' lines")
    sub.add_argument("--lang", choices=("sv", "en"), default="sv")
    sub.add_argument("--model-port", type=int, required=True)
    sub.add_argument("allow")

    sub = add("autostart", _cmd_autostart, "switch the start at login on or off, or show its state")
    sub.add_argument("--lang", choices=("sv", "en"), default="sv")
    sub.add_argument("--platform", required=True, help="uname -s: Darwin means launchd, anything else systemd")
    sub.add_argument("--script", required=True)
    sub.add_argument("--log", required=True)
    sub.add_argument("action", choices=("on", "off", "status"))

    sub = add("generate-secrets", _cmd_generate_secrets, "create db.env, sidekick.env, hindsight.env")
    sub.add_argument("--secrets-dir", type=Path, required=True)
    sub.add_argument("--hindsight-example", type=Path, required=True)
    sub.add_argument("--gateway", required=True)

    sub = add(
        "model-key-apply",
        _cmd_model_key_apply,
        "store the model key read from stdin (empty = none)",
    )
    sub.add_argument("--secrets-dir", type=Path, required=True)

    sub = add("model-key-show", _cmd_model_key_show, "print the stored model key (empty = none)")
    sub.add_argument("--secrets-dir", type=Path, required=True)

    sub = add("rooms-env", _cmd_rooms_env, "write secrets/rooms.env from work.env (removed when no rooms are set)")
    sub.add_argument("--env-file", type=Path, required=True)
    sub.add_argument("--secrets-dir", type=Path, required=True)

    sub = add("render-gateway", _cmd_render_gateway, "write gateway.haproxy.cfg and allow.compose.yaml")
    sub.add_argument("--template", type=Path, required=True)
    sub.add_argument("--out-dir", type=Path, required=True)
    sub.add_argument("--allow", default="", help="'host port' lines from the allowlist command")

    sub = add("text", _cmd_text, "print one message of work.sh (the key itself when there is none)")
    sub.add_argument("--lang", choices=("sv", "en"), default="sv")
    sub.add_argument("key")

    sub = add("env-value", _cmd_env_value, "print one value of work.env (last assignment wins, quotes stripped)")
    sub.add_argument("--env-file", type=Path, required=True)
    sub.add_argument("key")

    sub = add("env-set", _cmd_env_set, "set KEY=value in work.env (replaces the first KEY or # KEY line, else appends)")
    sub.add_argument("--env-file", type=Path, required=True)
    sub.add_argument("key")
    sub.add_argument("value")

    sub = add("env-unset", _cmd_env_unset, "comment out the active KEY lines of work.env")
    sub.add_argument("--env-file", type=Path, required=True)
    sub.add_argument("key")

    sub = add("memory-wanted", _cmd_memory_wanted, "exit 0 when work.env turns the memory on, 1 when off")
    sub.add_argument("--env-file", type=Path, required=True)

    sub = add("derive", _cmd_derive, "print MEMORY, the NAME=value exports and the allowlist from work.env")
    sub.add_argument("--env-file", type=Path, required=True)
    sub.add_argument("--gen-dir", type=Path, required=True)
    sub.add_argument("--lang", choices=("sv", "en"), default="sv")
    sub.add_argument("--lenient", action="store_true", help="an unusable work.env is not an error")

    sub = add("status-version", _cmd_status_version, "print the version line of build-info.json, if any")
    sub.add_argument("--lang", choices=("sv", "en"), default="sv")
    sub.add_argument("--build-info", type=Path, required=True)

    sub = add("status-via", _cmd_status_via, "translate the gateway probe's output (stdin)")
    sub.add_argument("--lang", choices=("sv", "en"), default="sv")
    sub.add_argument("--wanted-model", default="", help="warn when this model id is not among the listed ones")

    sub = add("build-info", _cmd_build_info, "write build-info.json")
    sub.add_argument("--path", type=Path, required=True)
    sub.add_argument("--commit", required=True)
    sub.add_argument("--commit-date", required=True)
    sub.add_argument("--now", required=True)
    sub.add_argument("--previous", default="")
    sub.add_argument("--updated", default="")

    sub = add("desktop-config", _cmd_desktop_config, "write the Claude Desktop entry file (mode 600)")
    sub.add_argument("--out", type=Path, required=True)
    sub.add_argument("--docker", required=True, help="absolute path of the docker binary")
    sub.add_argument("--container", required=True)
    sub.add_argument("--owner", required=True)

    sub = add(
        "claude-config", _cmd_claude_config, "preview and, after a yes on stdin, merge the entry into Claude Desktop"
    )
    sub.add_argument("--lang", choices=("sv", "en"), default="sv")
    sub.add_argument("--source", type=Path, required=True)
    sub.add_argument("--target", type=Path, required=True)

    add(
        "first-start-evidence",
        _cmd_first_start_evidence,
        "exit 0 when the logs (stdin: evidence NUL postgres) show a role failure",
    )

    sub = add(
        "first-start-table",
        _cmd_first_start_table,
        "exit 0 when the yoyo table is absent, 10 to ask for its count, 1 otherwise",
    )
    sub.add_argument("--table", required=True)

    sub = add(
        "first-start-hint",
        _cmd_first_start_hint,
        "print the failed-first-start hint on stderr; exit 1 when none applies",
    )
    sub.add_argument("--lang", choices=("sv", "en"), default="sv")
    sub.add_argument("--project", required=True)
    sub.add_argument("--volume", required=True)
    sub.add_argument("--table", required=True)
    sub.add_argument("--count", default="")

    sub = add("is-uuid", _cmd_is_uuid, "exit 0 when the value is a well-formed UUID")
    sub.add_argument("value")

    sub = add(
        "ask", _cmd_ask, "ask a question of the message table on stderr; print the answer, else the default, on stdout"
    )
    sub.add_argument("--lang", choices=("sv", "en"), default="sv")
    sub.add_argument("--key", required=True)
    sub.add_argument("--default", default="")
    sub.add_argument("--secret", action="store_true", help="no echo while the answer is typed")
    sub.add_argument("--raw", action="store_true", help="the message is the whole prompt (no colon, no default shown)")
    sub.add_argument("--only-on-terminal", action="store_true", help="show the prompt only when stdin is a terminal")
    sub.add_argument("values", nargs="*", help="fill the message's %%s (with --raw)")

    sub = add(
        "confirm", _cmd_confirm, "ask a yes/no question; exit 0 for a yes (j, y, ja, yes), an empty answer is --default"
    )
    sub.add_argument("--lang", choices=("sv", "en"), default="sv")
    sub.add_argument("--key", required=True)
    sub.add_argument("--default", choices=("y", "n"), required=True)

    sub = add("pick", _cmd_pick, "print the numbered choice the answer names, else the answer itself")
    sub.add_argument("--answer", required=True)
    sub.add_argument("choices", nargs="*")

    sub = add("backup-sets", _cmd_backup_sets, "list the complete backup sets of a directory")
    sub.add_argument("--lang", choices=("sv", "en"), default="sv")
    sub.add_argument("--dir", type=Path, required=True)
    sub.add_argument("--memory", choices=("on", "off"), required=True)

    sub = add(
        "restore-ref", _cmd_restore_ref, "print the directory and time stamp a restore argument names; exit 2 if none"
    )
    sub.add_argument("--lang", choices=("sv", "en"), default="sv")
    sub.add_argument("--backups", required=True, help="the directory a bare time stamp refers to")
    sub.add_argument("reference")

    sub = add(
        "rollback-action", _cmd_rollback_action, "print keep, rename-back or fail for the database names on stdin"
    )
    sub.add_argument("--old", required=True)

    sub = add(
        "models-list",
        _cmd_models_list,
        "print the model ids the server lists (API key on stdin); exit 1 when it cannot be asked",
    )
    sub.add_argument("--base-url", required=True)

    sub = add(
        "backup-key", _cmd_backup_key, "check the backup key file; create it with --generate when no backup exists"
    )
    sub.add_argument("--lang", choices=("sv", "en"), default="sv")
    sub.add_argument("--key-file", type=Path, required=True)
    sub.add_argument("--backups-dir", type=Path, required=True)
    sub.add_argument("--generate", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.handler(args))
