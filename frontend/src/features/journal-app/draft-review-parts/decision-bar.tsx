import type { RefObject } from "react";
import type { JournalLabels } from "../labels";
import type { Confirm } from "./use-draft-confirm";
import type { WriteState } from "./use-draft-writes";

/** Save and reject for the whole draft (hidden while a confirmation is open), with the failures of those two writes. */
export function DecisionBar({
  confirm,
  disabled,
  editing,
  write,
  onFinalize,
  onReject,
  finalizeRef,
  rejectRef,
  labels: t,
}: {
  confirm: Confirm;
  disabled: boolean;
  editing: boolean;
  write: WriteState;
  onFinalize: () => void;
  onReject: () => void;
  finalizeRef: RefObject<HTMLButtonElement | null>;
  rejectRef: RefObject<HTMLButtonElement | null>;
  labels: JournalLabels;
}) {
  return (
    <>
      {confirm === undefined && (
        <div className="journal-actions journal-decision-bar">
          <button
            type="button"
            className="sk-btn--primary"
            ref={finalizeRef}
            disabled={disabled}
            onClick={onFinalize}
          >
            {t.finalize}
          </button>
          <button
            type="button"
            ref={rejectRef}
            disabled={disabled}
            onClick={onReject}
          >
            {t.reject}
          </button>
        </div>
      )}
      {confirm === undefined && editing && (
        <p className="journal-muted">{t.finishEditFirst}</p>
      )}
      {write.kind === "failed" && write.action === "finalize" && (
        <p role="alert">{t.saveFailed}</p>
      )}
      {write.kind === "failed" && write.action === "reject" && (
        <p role="alert">{t.saveFailed}</p>
      )}
    </>
  );
}
