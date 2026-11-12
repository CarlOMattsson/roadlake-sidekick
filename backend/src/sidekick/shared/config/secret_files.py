"""Secrets read from files: `SIDEKICK_<NAME>_FILE` holds the value of `SIDEKICK_<NAME>`.

A secret given as an environment variable is visible to every process of the container and to
`docker inspect`. A file (a Docker secret, or any read-only mount) is not. This one mechanism
serves every secret setting; which settings are secret is read from the field declarations, so a
new secret field gets the `_FILE` variant without further code.
"""

import os
from typing import Any

from pydantic import SecretStr
from pydantic.fields import FieldInfo
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsError

FILE_SUFFIX = "_FILE"
# A secret is a few hundred bytes at most; the cap keeps a variable that points at something
# unbounded (a device, a large file) from being read whole.
MAX_SECRET_FILE_BYTES = 64 * 1024


def is_secret_field(field: FieldInfo) -> bool:
    """A field is secret when its value is a `SecretStr`, or is kept out of `repr` and logs."""

    members = getattr(field.annotation, "__args__", None) or (field.annotation,)
    return SecretStr in members or field.repr is False


def _variable_name(settings_cls: type[BaseSettings], field_name: str) -> str:
    return f"{settings_cls.model_config.get('env_prefix') or ''}{field_name}".upper()


def secret_file_variable_names(settings_cls: type[BaseSettings]) -> frozenset[str]:
    """The `<NAME>_FILE` variable of every secret field of the settings class."""

    return frozenset(
        _variable_name(settings_cls, name) + FILE_SUFFIX
        for name, field in settings_cls.model_fields.items()
        if is_secret_field(field)
    )


def _read_secret_file(variable: str, path: str) -> str:
    """The content without its trailing line break. Errors name the variable, never a value."""

    try:
        with open(path, "rb") as handle:
            data = handle.read(MAX_SECRET_FILE_BYTES + 1)
        text = data.decode("utf-8")
    except OSError as error:
        raise SettingsError(
            f"{variable} names a file that cannot be read: {error.strerror}"
        ) from None
    except UnicodeDecodeError:
        raise SettingsError(f"{variable} names a file that is not UTF-8 text") from None
    if len(data) > MAX_SECRET_FILE_BYTES:
        raise SettingsError(f"{variable} names a file over {MAX_SECRET_FILE_BYTES} bytes")
    text = text.rstrip("\r\n")
    if not text.strip():
        raise SettingsError(f"{variable} names an empty file")
    return text


def _environment_values(variable: str) -> list[str]:
    """Values of the variable under any spelling of its case, as the environment source reads it."""

    return [value for name, value in os.environ.items() if name.upper() == variable]


class SecretFilesSource(PydanticBaseSettingsSource):
    """Settings source for `<NAME>_FILE` variables; it outranks the plain environment variable.

    An empty `<NAME>_FILE` counts as not set, the way an empty `<NAME>` does, so a Compose file can
    pass the variable on unconditionally; a file that is empty is an error, never an unset secret.
    Only the process environment is read, not the dotenv file. A non-empty `<NAME>` together with
    `<NAME>_FILE` is a configuration error, whatever the case of the names: two places would
    otherwise disagree about which value is the secret.
    """

    def get_field_value(self, field: FieldInfo, field_name: str) -> tuple[Any, str, bool]:
        variable = _variable_name(self.settings_cls, field_name)
        paths = [path for path in _environment_values(variable + FILE_SUFFIX) if path]
        if not paths or not is_secret_field(field):
            return None, field_name, False
        if any(value.strip() for value in _environment_values(variable)):
            raise SettingsError(
                f"{variable} and {variable}{FILE_SUFFIX} are both set; set only one"
            )
        return _read_secret_file(variable + FILE_SUFFIX, paths[0]), field_name, False

    def __call__(self) -> dict[str, Any]:
        values: dict[str, Any] = {}
        for name, field in self.settings_cls.model_fields.items():
            value, key, _ = self.get_field_value(field, name)
            if value is not None:
                values[key] = value
        return values
