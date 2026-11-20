import { useContext } from "react";
import { buttonClass } from "../../../mcp-apps/ui/button";
import { RoomMessageContext } from "../../../mcp-apps/ui/room-context";
import { EmptyState } from "../../../mcp-apps/ui/states";
import { fillLabel } from "../agenda-undo";
import type { WorkLabels } from "../../shared/labels";
import { agendaLabelsFor } from "../agenda-labels";

/**
 * A search with no hit (designsystem §3 "Tomt"): the family's empty state with the `noMatch` sentence, what to say to
 * Claude to create the Task (`noMatchAsk`, sent where the host offers messages), and the `clearSearch` button, which
 * empties the search. Shared by the agenda and the Status tab; the button shows when `onClear` is given.
 */
export function SearchNoMatch({
  query,
  labels: t,
  onClear,
}: {
  query: string;
  labels: WorkLabels;
  onClear?: () => void;
}) {
  const a = agendaLabelsFor(t.dateLocale);
  const send = useContext(RoomMessageContext);
  const q = query.trim();
  const example = fillLabel(a.noMatchAsk, { q });
  return (
    <div role="status">
      <EmptyState
        title={fillLabel(a.noMatch, { q })}
        ask={
          q
            ? {
                locale: t.dateLocale,
                example,
                onSend: send ? () => void send(example) : undefined,
              }
            : undefined
        }
      >
        {onClear && (
          <button
            type="button"
            className={buttonClass("quiet")}
            onClick={onClear}
          >
            {a.clearSearch}
          </button>
        )}
      </EmptyState>
    </div>
  );
}
