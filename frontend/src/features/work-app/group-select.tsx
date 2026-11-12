import {
  placeValue,
  placeFromValue,
  type GroupChoicesState,
  type TaskPlace,
} from "./group-choices";
import type { GroupSelectLabels } from "./group-select-labels";
import { ErrorNotice } from "../mcp-apps/ui/states";
import "./group-select.css";

/**
 * The place picker: a native select (the phone draws its own list, with touch and screen reader built in), with
 * "Ingen plats" first and one group per Domain: the Domain alone, then its open Projects, then its Processes marked
 * "(process)". The value is the Task's place; `onChange` gives the chosen place, null for none. While the places are
 * read it says so; a failed read is the shared row error with a retry. The caller labels it (`label` is the accessible name).
 */
export function GroupSelect({
  id,
  label,
  value,
  choices,
  labels: t,
  disabled = false,
  onChange,
}: {
  id?: string;
  /** The accessible name: "Plats för Måla taket". */
  label: string;
  value: TaskPlace | null;
  choices: GroupChoicesState & { retry: () => void };
  labels: GroupSelectLabels;
  disabled?: boolean;
  onChange: (place: TaskPlace | null) => void;
}) {
  if (choices.phase === "error")
    return (
      // The family's error notice in its row variant: the sentence, and "Försök igen" as a text button.
      <ErrorNotice
        locale={t.locale}
        placement="row"
        message={t.failed}
        onRetry={choices.retry}
      />
    );
  if (choices.phase !== "ready")
    return (
      <p role="status" className="work-group-select-state">
        {t.loading}
      </p>
    );
  return (
    <select
      id={id}
      className="work-group-select"
      aria-label={label}
      value={placeValue(value)}
      disabled={disabled}
      onChange={(event) => onChange(placeFromValue(event.target.value))}
    >
      <option value="">{t.none}</option>
      {choices.domains.map((domain) => (
        <optgroup key={domain.id} label={domain.title}>
          <option value={placeValue({ kind: "domain", id: domain.id })}>
            {t.domainOnly(domain.title)}
          </option>
          {domain.groups.map((group) => (
            <option
              key={group.id}
              value={placeValue({ kind: group.kind, id: group.id })}
            >
              {group.kind === "process"
                ? t.processOption(group.title)
                : group.title}
            </option>
          ))}
        </optgroup>
      ))}
    </select>
  );
}
