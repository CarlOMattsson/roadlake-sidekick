"""The rooms an instance shows (`SIDEKICK_ENABLED_ROOMS`) and the scopes a room stands for.

A room is one of the app's places: Work (`work`), Journal (`journal`), Shopping (`shopping`),
Contacts (`contacts`) and Control (`control`). An instance can leave rooms out, for example a
work machine that shows Work only. A room that is left out takes its MCP tools, its navigation
and its companion routes with it; its data stays where it is.
"""

from collections.abc import Collection, Iterable
from typing import Final, Literal

type Room = Literal["work", "journal", "shopping", "contacts", "control"]

# In the order the app lists them. `work` is the room every instance has.
ROOMS: Final[tuple[Room, ...]] = ("work", "journal", "shopping", "contacts", "control")
REQUIRED_ROOM: Final[Room] = "work"
DEFAULT_ENABLED_ROOMS: Final = ",".join(ROOMS)

# The read and write scopes of the rooms that hold records of their own. A disabled room's scopes
# are taken off the actor of the MCP surface, so the tools that look across rooms (search, the
# day's brief, memory recall) leave that room out, as they do for a session that never held it.
# `work` and `control` own no scope that another room's data hangs on.
ROOM_SCOPES: Final[dict[Room, frozenset[str]]] = {
    "journal": frozenset({"journal:read", "journal:write"}),
    "shopping": frozenset({"shopping:read", "shopping:write"}),
    "contacts": frozenset({"contacts:read", "contacts:write"}),
}


def parse_enabled_rooms(value: str) -> frozenset[Room]:
    """Parse the comma list. Blank means every room; unknown names and a missing `work` fail."""

    names = [name.strip().lower() for name in value.split(",") if name.strip()]
    if not names:
        return frozenset(ROOMS)
    unknown = sorted({name for name in names if name not in ROOMS})
    if unknown:
        raise ValueError(
            f"SIDEKICK_ENABLED_ROOMS names an unknown room ({', '.join(unknown)}); "
            f"valid rooms are {', '.join(ROOMS)}"
        )
    if REQUIRED_ROOM not in names:
        raise ValueError(f"SIDEKICK_ENABLED_ROOMS must keep the {REQUIRED_ROOM} room switched on")
    return frozenset(room for room in ROOMS if room in names)


def disabled_scopes(enabled: Collection[str]) -> frozenset[str]:
    """The scopes of every room that is switched off."""

    return frozenset(
        scope for room, scopes in ROOM_SCOPES.items() if room not in enabled for scope in scopes
    )


def ordered(rooms: Iterable[str]) -> tuple[str, ...]:
    """The rooms in the app's order, as the app document declares them."""

    present = set(rooms)
    return tuple(room for room in ROOMS if room in present)
