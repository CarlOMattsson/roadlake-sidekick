import { fillLabel } from "../agenda-undo";
import type { WorkLabels } from "../../shared/labels";

/**
 * A search with no hit (designsystem §3 "Tomt"): "Inga uppgifter matchar ”{q}”." and the text button "Rensa
 * sökningen", which empties the search. Shared by the agenda and the Status tab; the button shows when `onClear` is given.
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
  return (
    <div className="work-agenda-nomatch">
      <p role="status">{fillLabel(t.agendaNoMatch, { q: query.trim() })}</p>
      {onClear && (
        <button type="button" className="work-agenda-clear" onClick={onClear}>
          {t.agendaClearSearch}
        </button>
      )}
    </div>
  );
}
