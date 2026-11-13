"""How ``work.sh`` was called: the options of a command, the name under which it takes the lock, and the image it runs
from. The shell acts on the answers; a call the command does not accept is a usage error (exit code 2)."""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import NamedTuple

from . import workenv

API_IMAGE_NAME = "SIDEKICK_WORK_API_IMAGE"
DEFAULT_API_IMAGE = "roadlake-sidekick:work"
USAGE = "usage"
RESTORE_USAGE = "rs_usage"
LOCKING_COMMANDS = ("setup", "init", "start", "stop", "backup", "update")


class UsageError(ValueError):
    """The call is not one the command accepts; ``key`` names the usage message of the message table."""

    def __init__(self, key: str) -> None:
        super().__init__(key)
        self.key = key


class Options(NamedTuple):
    """Name and value of every option the command knows, in the order the shell reads them."""

    values: tuple[tuple[str, str], ...]

    def lines(self) -> list[str]:
        return [f"{name}={value}" for name, value in self.values]


def _flag(args: Sequence[str], name: str) -> str:
    return "1" if name in args else "0"


def start_options(args: Sequence[str]) -> Options:
    """``start [--build [--no-cache]] [--wait-docker]``; ``--no-cache`` needs ``--build``."""
    known = ("--build", "--no-cache", "--wait-docker")
    if any(arg not in known for arg in args) or ("--no-cache" in args and "--build" not in args):
        raise UsageError(USAGE)
    return Options(
        (
            ("BUILD", _flag(args, "--build")),
            ("NO_CACHE", _flag(args, "--no-cache")),
            ("WAIT_DOCKER", _flag(args, "--wait-docker")),
        )
    )


def update_options(args: Sequence[str]) -> Options:
    """``update [--allow-breaking-migration]``."""
    if any(arg != "--allow-breaking-migration" for arg in args):
        raise UsageError(USAGE)
    return Options((("ALLOW_BREAKING", _flag(args, "--allow-breaking-migration")),))


def restore_options(args: Sequence[str]) -> Options:
    """``restore [SET] [--apply]``: at most one reference, and it must not look like an option."""
    reference = ""
    for arg in args:
        if arg == "--apply":
            continue
        if arg.startswith("-") or reference:
            raise UsageError(RESTORE_USAGE)
        reference = arg
    return Options((("APPLY", _flag(args, "--apply")), ("REFERENCE", reference)))


PARSERS = {"start": start_options, "update": update_options, "restore": restore_options}


def parse_options(command: str, args: Sequence[str]) -> Options:
    return PARSERS[command](args)


def lock_command(command: str, args: Sequence[str]) -> str:
    """The name written next to the PID of the lock for a command that changes the stack, else nothing: the commands
    that only read (status, autostart, claude-config) and the dry run of restore take no lock."""
    if command in LOCKING_COMMANDS:
        return command
    if command == "restore" and "--apply" in args:
        return "restore --apply"
    return ""


def api_image(env_file: Path, environ: Mapping[str, str] = os.environ) -> str:
    """The image the stack runs from: the environment of the call, else work.env, else the default."""
    return environ.get(API_IMAGE_NAME) or workenv.env_value(env_file, API_IMAGE_NAME) or DEFAULT_API_IMAGE
