"""Where a running process took its configuration from: names only, never values."""

import os
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path

from sidekick.shared.config.settings import Settings


@dataclass(frozen=True, slots=True)
class ConfigurationSources:
    """Where a running process actually took its configuration from.

    Two groups, because they mean different things. `disagreeing_with_the_file` is a live
    contradiction: the environment and the file both name a setting and they do not match,
    which makes the process act on a value that `.env` no longer
    selects. `environment_only` is not a contradiction at all. It names variables set in the
    process environment that the file does not mention: how CI and a
    container started with `env_file` legitimately configure the application. It does mean the
    file is not a complete record of this run. A declared setting named in neither place is
    simply unset, and its default applies; it is not listed.

    `dotenv_file_found` says whether the file itself was there to read, which is the case
    that matters most: a missing file makes every variable look environment-only. `None`
    means the comparison was made without a file, as in the test suite.

    Names only. Neither field ever holds a value.
    """

    disagreeing_with_the_file: tuple[str, ...] = ()
    environment_only: tuple[str, ...] = ()
    dotenv_file_found: bool | None = None

    @property
    def has_disagreement(self) -> bool:
        return bool(self.disagreeing_with_the_file)


def declared_variable_names() -> frozenset[str]:
    """Every environment variable name that can affect this application.

    `extra="forbid"` makes this exhaustive: an undeclared prefixed variable stops startup
    rather than being read, so anything outside this set is somebody else's variable.
    """

    prefix = Settings.model_config.get("env_prefix") or ""
    return frozenset(f"{prefix}{name}".upper() for name in Settings.model_fields)


def dotenv_variables(path: Path) -> dict[str, str]:
    """Read a dotenv file for comparison only. This configures nothing.

    `pydantic-settings` remains the one loader. This reads the same file again solely to
    answer which variables the process took from its environment instead, and it is
    deliberately simpler than the loader: `KEY=value` lines, comments and blanks ignored,
    one matching pair of surrounding quotes stripped, no export syntax, no interpolation,
    no multi-line values. Where that simplicity disagrees with the loader the only
    possible error is reporting a difference that does not exist, which is a visible false
    alarm rather than a hidden truth.
    """

    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    values: dict[str, str] = {}
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name, _, raw = stripped.partition("=")
        value = raw.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        values[name.strip().upper()] = value
    return values


def configuration_sources(
    *,
    environ: Mapping[str, str],
    dotenv: Mapping[str, str],
    declared: frozenset[str] | None = None,
) -> ConfigurationSources:
    """Compare the process environment with the file, and keep only names.

    Values are read here to decide whether they differ and are then discarded. Nothing in
    the returned value can be logged into a secret.
    """

    names = declared if declared is not None else declared_variable_names()
    disagreeing: list[str] = []
    environment_only: list[str] = []
    for name in sorted(names):
        if name not in environ:
            continue
        if name not in dotenv:
            environment_only.append(name)
        elif environ[name] != dotenv[name]:
            disagreeing.append(name)
    return ConfigurationSources(tuple(disagreeing), tuple(environment_only))


def describe_configuration_sources(
    environ: Mapping[str, str] | None = None,
) -> ConfigurationSources:
    """The comparison for this process, against the dotenv file `Settings` is configured with.

    With `env_file=None`, which is what the test suite sets, there is no file to disagree
    with and every supplied variable would be reported as absent from it. The suite also
    removes ambient application variables, so the honest result there is empty either way.
    """

    env_file = Settings.model_config.get("env_file")
    if env_file is None:
        return ConfigurationSources()
    # Relative like the loader's own path, so it resolves against the same working directory.
    path = Path(str(env_file))
    sources = configuration_sources(
        environ=environ if environ is not None else os.environ,
        dotenv=dotenv_variables(path),
    )
    return replace(sources, dotenv_file_found=path.is_file())
