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
    autostart,
    backupfiles,
    backupflow,
    derive,
    desktopconfig,
    desktopsetup,
    firststart,
    generated,
    invocation,
    messages,
    prompts,
    restoreflow,
    secretfiles,
    setupguide,
    stackfiles,
    status,
    updateflow,
    updatestate,
    workenv,
)
from .stack import Stack, Stop

# Exit code of ``backup-space``: the free size or a setting could not be judged.
BACKUP_SPACE_UNKNOWN = 2


def _fail(message: str) -> int:
    print(message, file=sys.stderr)
    return 1


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


def _cmd_rooms_env(args: argparse.Namespace) -> int:
    secretfiles.write_rooms_env(args.secrets_dir, workenv.env_value(args.env_file, secretfiles.ROOMS_NAME))
    return 0


def _stack(args: argparse.Namespace) -> Stack:
    return Stack(args.repo, project=args.project, lang=args.lang, memory=args.memory == "1")


def _cmd_render_generated(args: argparse.Namespace) -> int:
    stackfiles.render_generated(_stack(args), generated.parse_allow_lines(args.allow))
    return 0


def _cmd_backup(args: argparse.Namespace) -> int:
    return backupflow.run_backup(_stack(args))


def _cmd_update(args: argparse.Namespace) -> int:
    allow = generated.parse_allow_lines(args.allow)
    return updateflow.run_update(_stack(args), args.allow_breaking_migration, allow)


def _cmd_restore(args: argparse.Namespace) -> int:
    return restoreflow.run_restore(_stack(args), args.reference, args.apply)


def _cmd_desktop_setup(args: argparse.Namespace) -> int:
    desktopsetup.desktop_setup(_stack(args))
    return 0


def _cmd_diagnose_first_start(args: argparse.Namespace) -> int:
    firststart.print_hint(_stack(args), args.log_start)
    return 0


def _cmd_text(args: argparse.Namespace) -> int:
    # Bytes, so the output does not depend on the locale of the terminal; no trailing newline.
    sys.stdout.buffer.write(messages.text(args.lang, args.key).encode("utf-8"))
    return 0


def _cmd_env_value(args: argparse.Namespace) -> int:
    print(workenv.env_value(args.env_file, args.key))
    return 0


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
    if args.if_missing:
        stackfiles.ensure_build_info(_stack(args))
    else:
        stackfiles.write_build_info(_stack(args), args.previous, args.updated)
    return 0


def _cmd_claude_config(args: argparse.Namespace) -> int:
    target = desktopconfig.claude_config_target(
        args.platform, os.environ.get("SIDEKICK_WORK_CLAUDE_CONFIG", ""), Path.home()
    )
    return desktopconfig.merge_into_claude_config(
        args.source, target, args.lang, sys.stdin.readline, sys.stdout, sys.stderr
    )


def _cmd_backup_keep_valid(args: argparse.Namespace) -> int:
    return 0 if backupfiles.valid_keep(args.value) else 1


def _cmd_backup_space(args: argparse.Namespace) -> int:
    check = backupfiles.check_space(args.dir, os.environ, args.pattern)
    print(check.needed, check.free)
    return {backupfiles.ENOUGH: 0, backupfiles.TOO_LITTLE: 1}.get(check.outcome, BACKUP_SPACE_UNKNOWN)


def _cmd_backup_prune(args: argparse.Namespace) -> int:
    if not backupfiles.valid_keep(args.keep):
        return 1
    print(backupfiles.prune(args.dir, int(args.keep), args.pattern, args.protected))
    return 0


def _cmd_journal_add(args: argparse.Namespace) -> int:
    updatestate.add_journal_entry(args.file, args.state, args.detail)
    return 0


def _cmd_release_write(args: argparse.Namespace) -> int:
    updatestate.write_release(args.file, args.image, args.previous)
    return 0


def _cmd_release_restore(args: argparse.Namespace) -> int:
    updatestate.restore_release(args.file, args.pinned, args.image)
    return 0


def _cmd_lock_owner(args: argparse.Namespace) -> int:
    print(updatestate.lock_owner(args.file))
    return 0


def _cmd_journal_state(args: argparse.Namespace) -> int:
    try:
        state = updatestate.last_journal_state(args.file)
    except OSError:
        return _fail("the update journal cannot be read")
    if state is not None:
        print(state)
    return 0


def _cmd_release_pin(args: argparse.Namespace) -> int:
    try:
        value = updatestate.release_value(args.file, args.key)
    except OSError:
        return _fail("the release pointer cannot be read")
    if value is not None:
        print(value)
    return 0


def _cmd_snapshot_name(_args: argparse.Namespace) -> int:
    print(updatestate.snapshot_name(updatestate.utc_now()))
    return 0


def _cmd_snapshot_pattern(_args: argparse.Namespace) -> int:
    print(updatestate.SNAPSHOT_PATTERN)
    return 0


def _cmd_ask(args: argparse.Namespace) -> int:
    prompt = messages.render(args.lang, args.key, *args.values)
    answer = prompts.ask(prompt, secret=args.secret, only_on_terminal=args.only_on_terminal)
    # Bytes, so the answer is returned as it was typed whatever the locale; no trailing newline.
    sys.stdout.buffer.write(answer.encode("utf-8", errors="surrogateescape"))
    return 0


def _cmd_confirm(args: argparse.Namespace) -> int:
    prompt = prompts.question(messages.text(args.lang, args.key))
    return 0 if prompts.confirm(prompt, args.default) else 1


def _cmd_parse_args(args: argparse.Namespace) -> int:
    try:
        options = invocation.parse_options(args.command_name, args.arguments)
    except invocation.UsageError as error:
        print(messages.render(args.lang, error.key), file=sys.stderr)
        return 2
    print("\n".join(options.lines()))
    return 0


def _cmd_lock_command(args: argparse.Namespace) -> int:
    print(invocation.lock_command(args.command_name, args.arguments))
    return 0


def _cmd_api_image(args: argparse.Namespace) -> int:
    print(invocation.api_image(args.env_file))
    return 0


def _cmd_setup_language(args: argparse.Namespace) -> int:
    sys.stdout.write(setupguide.ask_language(args.lang))
    return 0


def _cmd_setup_guide(args: argparse.Namespace) -> int:
    try:
        setupguide.run_guide(args.lang, args.env_file, args.secrets_dir, args.default_rooms)
    except ValueError as error:
        return _fail(str(error))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="workctl", description="Logic behind tools/work.sh.")
    commands = parser.add_subparsers(dest="command", required=True)

    def add(name: str, handler: object, help_text: str) -> argparse.ArgumentParser:
        sub = commands.add_parser(name, help=help_text)
        sub.set_defaults(handler=handler)
        return sub

    def stack_options(sub: argparse.ArgumentParser) -> None:
        sub.add_argument("--repo", type=Path, required=True, help="the checkout")
        sub.add_argument("--project", default="sidekick-work", help="the compose project")
        sub.add_argument("--lang", choices=("sv", "en"), default="sv")
        sub.add_argument("--memory", choices=("0", "1"), default="1", help="1 when Hindsight's memory is on")

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

    sub = add("rooms-env", _cmd_rooms_env, "write secrets/rooms.env from work.env (removed when no rooms are set)")
    sub.add_argument("--env-file", type=Path, required=True)
    sub.add_argument("--secrets-dir", type=Path, required=True)

    sub = add(
        "render-generated",
        _cmd_render_generated,
        "write gateway.haproxy.cfg, allow.compose.yaml and (when missing) build-info.json",
    )
    stack_options(sub)
    sub.add_argument("--allow", default="", help="'host port' lines from the allowlist command")

    sub = add("text", _cmd_text, "print one message of work.sh (the key itself when there is none)")
    sub.add_argument("--lang", choices=("sv", "en"), default="sv")
    sub.add_argument("key")

    sub = add("env-value", _cmd_env_value, "print one value of work.env (last assignment wins, quotes stripped)")
    sub.add_argument("--env-file", type=Path, required=True)
    sub.add_argument("key")

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

    sub = add("build-info", _cmd_build_info, "write build-info.json for the commit this checkout is on")
    stack_options(sub)
    sub.add_argument("--if-missing", action="store_true", help="write it only when there is none")
    sub.add_argument("--previous", default="", help="the commit the checkout was on before an update")
    sub.add_argument("--updated", action="store_true", help="record the time as the time of the update")

    sub = add(
        "backup",
        _cmd_backup,
        "pause the writers, take an encrypted copy of the database and of Hindsight's memory, prune old copies",
    )
    stack_options(sub)

    sub = add(
        "restore",
        _cmd_restore,
        "check one backup set and show the plan; with --apply replace the database and Hindsight's memory by it",
    )
    stack_options(sub)
    sub.add_argument("--reference", default="", help="a time stamp, or the path of either file of a set")
    sub.add_argument("--apply", action="store_true", help="really replace (asks for the project name first)")

    sub = add(
        "update",
        _cmd_update,
        "pull the code, build, back up, migrate and restart; on a failure say where the backup is and how to go back",
    )
    stack_options(sub)
    sub.add_argument("--allow", default="", help="'host port' lines from the allowlist command")
    sub.add_argument("--allow-breaking-migration", action="store_true", help="accept migrations that need a restore")

    sub = add(
        "desktop-setup",
        _cmd_desktop_setup,
        "check the image, make sure the owner user exists and write the Claude Desktop entry file",
    )
    stack_options(sub)

    sub = add(
        "claude-config", _cmd_claude_config, "preview and, after a yes on stdin, merge the entry into Claude Desktop"
    )
    sub.add_argument("--lang", choices=("sv", "en"), default="sv")
    sub.add_argument("--source", type=Path, required=True)
    sub.add_argument("--platform", required=True, help="uname -s: Darwin keeps the file elsewhere than Linux")

    sub = add(
        "diagnose-first-start",
        _cmd_diagnose_first_start,
        "print on stderr what a failed first start left behind, when it provably is an unmigrated database",
    )
    stack_options(sub)
    sub.add_argument("--log-start", type=int, required=True, help="the number of lines the log had at the start")

    sub = add("ask", _cmd_ask, "ask a question of the message table on stderr; print the answer on stdout")
    sub.add_argument("--lang", choices=("sv", "en"), default="sv")
    sub.add_argument("--key", required=True)
    sub.add_argument("--secret", action="store_true", help="no echo while the answer is typed")
    sub.add_argument("--only-on-terminal", action="store_true", help="show the prompt only when stdin is a terminal")
    sub.add_argument("values", nargs="*", help="fill the message's %%s")

    sub = add(
        "confirm", _cmd_confirm, "ask a yes/no question; exit 0 for a yes (j, y, ja, yes), an empty answer is --default"
    )
    sub.add_argument("--lang", choices=("sv", "en"), default="sv")
    sub.add_argument("--key", required=True)
    sub.add_argument("--default", choices=("y", "n"), required=True)

    sub = add(
        "parse-args",
        _cmd_parse_args,
        "print the options of start, update or restore as NAME=value lines; exit 2 with the usage text when refused",
    )
    sub.add_argument("--lang", choices=("sv", "en"), default="sv")
    sub.add_argument("command_name", choices=sorted(invocation.PARSERS))
    sub.add_argument("arguments", nargs="*")

    sub = add("lock-command", _cmd_lock_command, "print the name a command takes the lock under, or nothing")
    sub.add_argument("command_name")
    sub.add_argument("arguments", nargs="*")

    sub = add("api-image", _cmd_api_image, "print the image the stack runs from")
    sub.add_argument("--env-file", type=Path, required=True)

    sub = add("setup-language", _cmd_setup_language, "ask the guide's language; print sv or en")
    sub.add_argument("--lang", choices=("sv", "en"), default="sv", help="the current language, offered as the answer")

    sub = add(
        "setup-guide",
        _cmd_setup_guide,
        "ask the questions of setup (memory, model server, allowlist, rooms, app language) and write the answers",
    )
    sub.add_argument("--lang", choices=("sv", "en"), default="sv")
    sub.add_argument("--env-file", type=Path, required=True)
    sub.add_argument("--secrets-dir", type=Path, required=True)
    sub.add_argument("--default-rooms", required=True)

    sub = add("backup-keep-valid", _cmd_backup_keep_valid, "exit 0 when the value is a whole number of at least 1")
    sub.add_argument("value")

    sub = add(
        "backup-space",
        _cmd_backup_space,
        "print the bytes needed and free for a new backup; exit 0 enough, 1 too little, 2 cannot be judged",
    )
    sub.add_argument("--dir", type=Path, required=True)
    sub.add_argument("--pattern", action="append", required=True, help="finished-name regex; repeat for each kind")

    sub = add(
        "backup-prune",
        _cmd_backup_prune,
        "remove the finished backup files beyond the newest --keep; print how many; exit 1 for a bad --keep",
    )
    sub.add_argument("--dir", type=Path, required=True)
    sub.add_argument("--keep", required=True)
    sub.add_argument("--pattern", required=True, help="finished-name regex")
    sub.add_argument("--protected", required=True, help="file name just written, never removed (may be empty)")

    sub = add(
        "journal-add", _cmd_journal_add, "add one line (UTC time, state, detail) to the update journal, atomically"
    )
    sub.add_argument("--file", type=Path, required=True)
    sub.add_argument("state")
    sub.add_argument("detail", nargs="?", default="")

    sub = add("release-write", _cmd_release_write, "write the release pointer (new and previous api image), atomically")
    sub.add_argument("--file", type=Path, required=True)
    sub.add_argument("--image", required=True)
    sub.add_argument("--previous", required=True)

    sub = add(
        "release-restore",
        _cmd_release_restore,
        "after a rollback: pin the earlier image again, or remove the pointer when none was pinned",
    )
    sub.add_argument("--file", type=Path, required=True)
    sub.add_argument("--pinned", default="", help="the image that was pinned before the update (may be empty)")
    sub.add_argument("--image", required=True, help="the image of the failed update")

    sub = add("lock-owner", _cmd_lock_owner, "print the pid recorded in the update lock's pid file, or nothing")
    sub.add_argument("--file", type=Path, required=True)

    sub = add(
        "journal-state",
        _cmd_journal_state,
        "print the state (second field) of the last line of the update journal, or nothing without a journal",
    )
    sub.add_argument("--file", type=Path, required=True)

    sub = add(
        "release-pin", _cmd_release_pin, "print the value of KEY in the release pointer, or nothing when it is absent"
    )
    sub.add_argument("--file", type=Path, required=True)
    sub.add_argument("key")

    add("snapshot-name", _cmd_snapshot_name, "print the finished name of a snapshot taken now")
    add("snapshot-pattern", _cmd_snapshot_pattern, "print the regex that matches finished snapshot names")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.handler(args))
    except Stop as stop:
        return stop.code
