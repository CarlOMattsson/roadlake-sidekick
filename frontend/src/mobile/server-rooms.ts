/**
 * The rooms the server shows, for the phone. `SIDEKICK_ENABLED_ROOMS` is the server's setting and the only place it is
 * configured: the phone reads `enabled_rooms` from the pairing (the stored copy first, so a phone without network
 * still draws the right rooms) and again from the server at the start and on every return to the foreground. The
 * rooms are declared the way the backend declares them in the app document (enabled-rooms.ts), so the strip, the room
 * picker and every link and menu entry that leads to a room read one answer. A server that does not say (older) leaves
 * every room on, as the app shows them without this.
 *
 * The owner's time zone travels the same way (`timezone` of the same answers, kept in the pairing) and is declared as the
 * backend declares it in the app document (app-timezone.ts), so every date the phone draws is in the owner's zone and not
 * in Stockholm's default or the phone's own. A change of zone starts the shell again, like a change of rooms.
 *
 * Kontroll (`control`) is never on in the phone: the companion API has no trash, history or memory routes, so its
 * views could only fail. Every link to it disappears, and the shell sends the license entry to Inställningar instead.
 */
import { useEffect, useState } from "react";

import { declareOwnerTimeZone } from "@/features/mcp-apps/app-timezone";
import { declareEnabledRooms } from "@/features/mcp-apps/enabled-rooms";
import { ROOM_IDS } from "@/features/mcp-apps/router";
import type { SidekickNativePlugin } from "./sidekick-native";

export type ServerRoomsNative = Pick<
  SidekickNativePlugin,
  "status" | "deviceStatus"
>;

const ALL_ROOMS = "all";

/** The room the companion API does not serve; the phone's settings stand in its place. */
const PHONE_WITHOUT: (typeof ROOM_IDS)[number] = "control";

/** The rooms the phone draws: the server's list, or every room when it did not say, without Kontroll. */
function phoneRooms(rooms: readonly string[] | undefined): string[] {
  return (rooms ?? ROOM_IDS).filter((room) => room !== PHONE_WITHOUT);
}

/**
 * `key` is undefined until the stored copy has been read (it is local and quick), then names the rooms: it changes
 * when they do, so a caller that keys the shell on it starts again in Arbete when a room it had open goes away.
 * Without `native` (a host that cannot ask) every room stays on and the key is there at once.
 */
export function useServerRooms(
  native: ServerRoomsNative | undefined,
  refreshKey: number,
): string | undefined {
  const [key, setKey] = useState<string | undefined>(
    native ? undefined : ALL_ROOMS,
  );

  useEffect(() => {
    if (!native) return;
    let live = true;
    // The meta is written before the state changes, so the shell that renders next reads the new rooms.
    const apply = (
      rooms: readonly string[] | undefined,
      zone: string | undefined,
    ) => {
      const shown = phoneRooms(rooms);
      declareEnabledRooms(shown);
      declareOwnerTimeZone(zone);
      const roomsKey = rooms === undefined ? ALL_ROOMS : shown.join(",");
      setKey(zone === undefined ? roomsKey : `${roomsKey}|${zone}`);
    };
    void (async () => {
      const stored = await native.status().then(
        (status) => status,
        () => undefined,
      );
      if (!live) return;
      apply(stored?.enabledRooms, stored?.ownerTimeZone);
      const device = await native.deviceStatus().catch(() => undefined);
      if (live && device?.paired) {
        apply(device.enabledRooms, device.ownerTimeZone);
      }
    })();
    return () => {
      live = false;
    };
  }, [native, refreshKey]);

  // The declaration belongs to this pairing: it goes with the app.
  useEffect(
    () => () => {
      declareEnabledRooms(undefined);
      declareOwnerTimeZone(undefined);
    },
    [],
  );

  return key;
}
