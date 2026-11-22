import { useEffect, useState, useSyncExternalStore } from "react";

import type { RoomId } from "@/features/mcp-apps/router";
import type { SidekickShellLabels } from "@/features/mcp-apps/sidekick-shell-labels";
import {
  createShortcutRegistry,
  type ShortcutHelpGroup,
} from "@/features/mcp-apps/ui/shortcut-registry";
import { useShortcuts } from "@/features/mcp-apps/ui/shortcuts";

/**
 * The keys of every room (desktop spec 2.6) and their help: `?` opens the help, `g 1`–`g 4` the rooms with a cell of
 * their own in the strip's order, `g 5` the Mer menu. Mer keeps `g 5` however many rooms come before it. In capture,
 * so `g` and then `1` reach the shell before a room's own `1` (Agenda's status). Fullscreen with local navigation
 * only (`on`). The help lists the shell's keys first, then what the rooms on top registered (useRoomShortcuts), one
 * heading per name.
 */
export function useShellKeys({
  on,
  labels,
  stripRooms,
  openMore,
  choose,
}: {
  on: boolean;
  labels: SidekickShellLabels;
  /** The rooms with a cell of their own, in order. */
  stripRooms: readonly RoomId[];
  /** Opens Mer; undefined while the strip draws no Mer cell. */
  openMore: (() => void) | undefined;
  choose: (room: RoomId) => void;
}) {
  const [registry] = useState(createShortcutRegistry);
  const [helpOpen, setHelpOpen] = useState(false);
  const groups = useSyncExternalStore(registry.subscribe, registry.groups);
  const charKeys = useSyncExternalStore(registry.subscribe, registry.charKeys);

  const roomKeys = stripRooms.slice(0, 4);
  const globalKeys: Record<string, () => void> = {
    "?": () => setHelpOpen(true),
  };
  roomKeys.forEach((room, index) => {
    globalKeys[`g ${index + 1}`] = () => choose(room);
  });
  if (openMore) globalKeys["g 5"] = openMore;
  useShortcuts(globalKeys, { enabled: on && !helpOpen, capture: true });
  const roomNames = roomKeys.map((room) => labels.rooms[room]).join("|");
  const moreKey = openMore !== undefined;
  useEffect(() => {
    if (!on) {
      registry.set("shell", undefined);
      return;
    }
    const names = roomNames.split("|");
    registry.set("shell", {
      id: "shell",
      title: labels.shortcuts.everywhere,
      entries: [
        { keys: ["?"], label: labels.shortcuts.help },
        ...names.map((name, index) => ({
          keys: [`g ${index + 1}`],
          label: labels.shortcuts.goTo(name),
        })),
        ...(moreKey
          ? [{ keys: ["g 5"], label: labels.shortcuts.openMore }]
          : []),
        { keys: ["Escape"], label: labels.shortcuts.escape },
      ],
    });
  }, [on, roomNames, moreKey, labels, registry]);

  return {
    registry,
    helpOpen,
    setHelpOpen,
    charKeys,
    groups: mergeByTitle(groups),
  };
}

/**
 * The help's groups with one heading per name: a room's head and its list register their keys apart, under the
 * room's name, and read as one group. The shell's own group comes first.
 */
function mergeByTitle(
  groups: readonly ShortcutHelpGroup[],
): ShortcutHelpGroup[] {
  const byTitle = new Map<string, ShortcutHelpGroup>();
  const ordered = [
    ...groups.filter((group) => group.id === "shell"),
    ...groups.filter((group) => group.id !== "shell"),
  ];
  for (const group of ordered) {
    const seen = byTitle.get(group.title);
    byTitle.set(
      group.title,
      seen
        ? { ...seen, entries: [...seen.entries, ...group.entries] }
        : { ...group },
    );
  }
  return [...byTitle.values()];
}
