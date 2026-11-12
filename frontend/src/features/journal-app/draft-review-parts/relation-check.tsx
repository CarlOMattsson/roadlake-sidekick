import { Segmented } from "../../mcp-apps/ui/segmented";
import type { JournalLabels } from "../labels";
import {
  decisionOptions,
  decisionStatus,
  pairValue,
  type Option,
} from "./decisions";

/**
 * One link candidate in the relation fieldsets. An AI suggestion gets the Godkänn/Avslå pair only:
 * the pair already is the choice, so a checkbox next to it would be a second control for the same
 * value. A candidate the AI did not suggest has no pair, so its checkbox stays the only control.
 */
export function RelationCheck({
  option,
  checked,
  declined,
  disabled,
  onChange,
  onDeclinedChange,
  labels: t,
}: {
  option: Option;
  checked: boolean;
  declined: boolean;
  disabled: boolean;
  onChange: (on: boolean) => void;
  onDeclinedChange: (declined: boolean) => void;
  labels: JournalLabels;
}) {
  const decision = pairValue(checked && option.known, declined);
  return (
    <div
      className={
        option.suggested ? "journal-check journal-check-flat" : "journal-check"
      }
    >
      {option.suggested ? (
        <>
          <p className="journal-choice">
            {option.label}
            {" · "}
            <span className="journal-tag">{t.suggestedByAi}</span>
          </p>
          <Segmented
            label={t.decisionFor(option.label)}
            options={decisionOptions(t)}
            value={decision}
            onChange={(next) => {
              onDeclinedChange(next === "decline");
              onChange(next === "approve");
            }}
            disabled={disabled || !option.known}
          />
          <p className="journal-muted">{decisionStatus(decision, t)}</p>
        </>
      ) : (
        <label>
          <input
            type="checkbox"
            checked={checked && option.known}
            disabled={disabled || !option.known}
            onChange={(event) => onChange(event.target.checked)}
          />
          <span>{option.label}</span>
        </label>
      )}
      {!option.suggested && checked && option.known && (
        <p className="journal-muted">
          <span className="journal-tag">{t.chosenByUser}</span>
        </p>
      )}
      {!option.known && <p className="journal-muted">{t.unknownItem}</p>}
      {option.context && <p className="journal-muted">{option.context}</p>}
      {option.rationale && <p className="journal-muted">{option.rationale}</p>}
    </div>
  );
}
