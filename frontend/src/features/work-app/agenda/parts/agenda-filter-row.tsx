import type { WorkLabels } from "../../shared/labels";
import { agendaLabelsFor } from "../agenda-labels";

/** The agenda's own filter row, drawn when the fullscreen shell keeps no filter text of its own: the filter and "Refresh". */
export function AgendaFilterRow({
  labels: t,
  query,
  onQuery,
  disabled,
  onRefresh,
}: {
  labels: WorkLabels;
  query: string;
  onQuery: (query: string) => void;
  disabled: boolean;
  onRefresh: () => void;
}) {
  const filter = agendaLabelsFor(t.dateLocale).filter;
  return (
    <div className="work-agenda-toolbar">
      <label className="work-agenda-filter">
        <span>{filter}</span>
        <input
          type="search"
          aria-label={filter}
          value={query}
          onChange={(event) => onQuery(event.target.value)}
        />
      </label>
      <button
        type="button"
        className="work-agenda-refresh"
        aria-label={t.refresh}
        disabled={disabled}
        onClick={onRefresh}
      >
        {t.refresh}
      </button>
    </div>
  );
}
