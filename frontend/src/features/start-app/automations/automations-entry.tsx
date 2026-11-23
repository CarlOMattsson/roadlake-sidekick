import { useCallback } from "react";

import type { RoomTarget } from "../../mcp-apps/room-types";
import { Row } from "../../mcp-apps/ui/row";
import { useRead } from "../../mcp-apps/ui/use-read";
import type { AutomationLabels } from "./labels";
import { waitsForApproval } from "./model";
import type { AutomationTransport } from "./transport";
import "./automations.css";

/** The target of the automations' list. */
export function automationsTarget(t: AutomationLabels): RoomTarget {
  return { room: "start", view: "automations", label: t.title };
}

/**
 * The inbox's way to the automations: one row, "Automationer" over "1 väntar på ditt godkännande" (or how many there
 * are), above the suggestions. It reads the list for itself and draws nothing until there is at least one automation,
 * nor when the read fails: the inbox's ⋯ still leads there.
 */
export function AutomationsEntry({
  api,
  t,
  refreshKey,
  onOpen,
}: {
  api: AutomationTransport;
  t: AutomationLabels;
  refreshKey?: number;
  onOpen: (target: RoomTarget) => void;
}) {
  const read = useCallback(() => api.list(), [api]);
  const [state] = useRead(read, refreshKey);
  if (state.phase !== "ready" || state.value.items.length === 0) return null;
  const items = state.value.items;
  const waiting = items.filter((item) => waitsForApproval(item)).length;
  return (
    <ul className="start-automations-entry" aria-label={t.title}>
      <Row
        primary={t.entry}
        secondary={
          <span data-waiting={waiting > 0 ? "true" : undefined}>
            {waiting > 0 ? t.entryWaiting(waiting) : t.entryCount(items.length)}
          </span>
        }
        navigates
        onOpen={() => onOpen(automationsTarget(t))}
      />
    </ul>
  );
}
