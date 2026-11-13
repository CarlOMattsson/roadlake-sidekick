"""Names that work.sh derives from the stack: the previous image tag and the database a restore sets aside."""

from __future__ import annotations


def previous_image_tag(image: str) -> str:
    """The tag that keeps the image that runs now: ``repository:previous``. A digest and a tag are dropped; a port
    in the registry's name (``host:5000/app``) is not a tag."""
    name = image.rsplit("@", 1)[0]
    if ":" in name.rsplit("/", 1)[-1]:
        name = name.rsplit(":", 1)[0]
    return f"{name}:previous"


def old_database_name(stamp: str) -> str:
    """The name the database gets when a restore sets it aside: ``sidekick_before_restore_<date>_<time>``."""
    return "sidekick_before_restore_" + stamp.replace("-", "_", 1)
