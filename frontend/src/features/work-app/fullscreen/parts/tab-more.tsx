import type { ReactNode } from "react";

import { roomEnabled } from "../../../mcp-apps/enabled-rooms";
import type {
  HostSettingsEntry,
  RoomTarget,
} from "../../../mcp-apps/room-types";
import { controlEntry } from "../../../mcp-apps/ui/control-entry";
import { AgendaMore } from "../../agenda/agenda-toolbar";
import type { WorkLabels } from "../../shared/labels";

/**
 * One tab's "⋯" menu. Its last entry is the host's own settings when it has them (the phone's settings), else
 * Control, which a routing host offers when the Control room is on and the host can list the trash.
 */
export function TabMore({
  labels,
  hidden,
  open,
  onOpenChange,
  onRefresh,
  hostSettings,
  onRoute,
  supportsTool,
  locale,
  children,
}: {
  labels: WorkLabels;
  hidden: boolean;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onRefresh: () => void;
  hostSettings: HostSettingsEntry | undefined;
  onRoute: ((target: RoomTarget) => void) | undefined;
  supportsTool: ((name: string) => boolean) | undefined;
  locale: string;
  children: ReactNode;
}) {
  const control =
    onRoute && roomEnabled("control") && supportsTool?.("list_trash") !== false
      ? controlEntry(locale === "en" ? "en" : "sv")
      : undefined;
  return (
    <AgendaMore
      labels={labels}
      hidden={hidden}
      open={open}
      onOpenChange={onOpenChange}
      onRefresh={onRefresh}
      control={
        hostSettings ??
        (control && {
          label: control.label,
          onOpen: () => onRoute?.(control.target),
        })
      }
    >
      {children}
    </AgendaMore>
  );
}
