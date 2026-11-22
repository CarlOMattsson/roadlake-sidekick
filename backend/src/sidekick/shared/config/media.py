"""Where journal photo files are kept."""

from pathlib import Path

from pydantic import Field

from sidekick.shared.config.base import SettingsGroup


class MediaSettings(SettingsGroup):
    media_directory: Path = Field(
        default=Path(".sidekick/media"),
        description="Directory that holds the files of journal photos, named by their content; "
        "keep it on the same volume as the instance's other data.",
    )
