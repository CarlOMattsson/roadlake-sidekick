"""Validated runtime configuration: the `Settings` class composed from its groups."""

from sidekick.shared.config.backup import BackupSettings
from sidekick.shared.config.database import DatabaseSettings
from sidekick.shared.config.instance import InstanceSettings
from sidekick.shared.config.license import LicenseSettings
from sidekick.shared.config.memory import MemorySettings
from sidekick.shared.config.oauth import OAuthSettings
from sidekick.shared.config.push import PushSettings
from sidekick.shared.config.request_limits import RequestLimitSettings
from sidekick.shared.config.signing import SigningSettings


class Settings(
    LicenseSettings,
    InstanceSettings,
    RequestLimitSettings,
    PushSettings,
    MemorySettings,
    OAuthSettings,
    BackupSettings,
    SigningSettings,
    DatabaseSettings,
):
    """Sidekick settings with fail-closed production validation.

    The fields and their checks live in the group classes of this package. The groups share one
    `SettingsGroup` configuration, so every field keeps its flat `SIDEKICK_<NAME>` variable and
    its `settings.<name>` access. Pydantic collects fields and validators from the base classes
    before this class, so the checks run in the order `EnvironmentSettings` (undeclared
    variables), database, signing secrets, backup, OAuth, memory, push.
    """
