import { fillLabel } from "../agenda-undo";
import type { WorkLabels } from "../../shared/labels";
import { agendaLabelsFor } from "../agenda-labels";

/**
 * A search with no hit (designsystem §3 "Tomt"): the `noMatch` line and the `clearSearch` text button,
 * which empties the search. Shared by the agenda and the Status tab; the button shows when `onClear` is given.
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
  return (
    <div className="work-agenda-nomatch">
      <p role="status">{fillLabel(a.noMatch, { q: query.trim() })}</p>
      {onClear && (
        <button type="button" className="work-agenda-clear" onClick={onClear}>
          {a.clearSearch}
        </button>
      )}
    </div>
  );
}
